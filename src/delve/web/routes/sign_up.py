"""Sign-up with approval (DEL-156): anyone may ask for a player's account, while the owner or an organiser has opened
sign-up (`SETTING`, off until then); the account waits for one of them to approve it on the Players page
(`delve.web.routes.players`). A pending account can't log in (`accounts.AccountPending`).

Each address asks at most `PER_ADDRESS` times in `WINDOW_S` (the attempts that get as far as the username, made or
taken), and at most `accounts.PENDING_MAX` sign-ups wait at once, so a stranger can neither fill the Players page nor
probe usernames at will. The counts are in memory, as the login throttle's are: a restart forgets them.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, StrictBool
from starlette.responses import JSONResponse

from delve.mail import addresses
from delve.mail.settings import mail_enabled
from delve.play import accounts
from delve.play.context import PlayError
from delve.web import guard
from delve.web.auth import Organiser
from delve.web.routes.accounts import text_field
from delve.web.routes.join import LANGUAGE

router = APIRouter()

SETTING = "sign_up_open"
"""The stored settings' key of the switch: True while anyone may ask for an account."""
CLOSED = "Sign-up is closed: ask the owner for an invite."
PER_ADDRESS = 3
WINDOW_S = 60 * 60


def is_open(request: Request) -> bool:
    return request.app.state.storage.settings.load().get(SETTING) is True


class SignUpThrottle:
    """What each address asked for in the last `window_s` (`WINDOW_S` unless given), at most `per_address` times:
    sign-ups here, requests for a new password (`delve.web.routes.password_help`) and a table's messages by email
    (`delve.web.routes.mail`, a day's). `clock` is patched in tests."""

    def __init__(
        self, per_address: int = PER_ADDRESS, refusal: str = "You've asked for accounts often", window_s: int = WINDOW_S
    ) -> None:
        self.per_address = per_address
        self.window_s = window_s
        self.refusal = refusal
        self.clock: Callable[[], float] = time.monotonic
        self._asked: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def take(self, address: str) -> None:
        """Count one for the address; 429, uncounted, with how long to wait, while it has asked `per_address` times."""
        wait = self._count(address)
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail=f"{self.refusal}: try again in {math.ceil(wait / 60)} minutes.",
                headers={"Retry-After": str(wait)},
            )

    def allows(self, key: str) -> bool:
        """Count one for `key` and answer True; False, uncounted, while it has asked `per_address` times."""
        return self._count(key) is None

    def _count(self, key: str) -> int | None:
        """Count one for `key` and answer None; while it has asked `per_address` times, the seconds left, uncounted."""
        with self._lock:
            now = self.clock()
            asked = self._asked[key]
            while asked and asked[0] <= now - self.window_s:
                asked.popleft()
            if len(asked) >= self.per_address:
                return max(1, math.ceil(asked[0] + self.window_s - now))
            asked.append(now)
            return None


def throttle(request: Request) -> SignUpThrottle:
    found = getattr(request.app.state, "sign_up_throttle", None)
    if found is None:
        found = request.app.state.sign_up_throttle = SignUpThrottle()
    return found


@router.get("/api/sign-up")
def sign_up_state(request: Request) -> dict[str, bool]:
    """Whether anyone may ask for an account now; open to all, as the login page asks before anyone logs in."""
    return {"open": is_open(request)}


class SignUpSwitch(BaseModel):
    open: StrictBool


@router.put("/api/sign-up")
def switch_sign_up(request: Request, principal: Organiser, body: SignUpSwitch) -> dict[str, bool]:
    """Open or close sign-up (the owner or an organiser). The rest of the stored settings stays as it is."""
    request.app.state.storage.settings.update({SETTING: body.open})
    request.app.state.events.publish("accounts", {"sign_up_open": body.open}, scope="organisers")
    return {"open": body.open}


@router.post("/api/sign-up", status_code=201)
def ask_for_an_account(request: Request, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    """Ask for a player's account: 201 once it waits for approval, nobody logged in. 403 while sign-up is closed, 409
    for a username taken, 422 for a field that won't do, 429 for an address that asked often or when
    `accounts.PENDING_MAX` sign-ups wait already."""
    if not is_open(request):
        raise HTTPException(status_code=403, detail=CLOSED)
    username, password = text_field(body, "username"), text_field(body, "password")
    display_name = text_field(body, "display_name", optional=True)
    note = text_field(body, "note", optional=True) or ""
    language = (text_field(body, "language", optional=True) or "en").strip().lower()
    if not LANGUAGE.fullmatch(language):
        raise HTTPException(status_code=422, detail="A language is a code of 2 or 3 letters, such as en or nl.")
    raw_address = text_field(body, "email", optional=True)
    try:
        accounts.username_of(username)
        accounts.check_new_password(password)
        address = addresses.normalise(raw_address) if raw_address and raw_address.strip() else None
    except PlayError as refused:
        raise HTTPException(status_code=422, detail=refused.message) from None
    throttle(request).take(guard.client_address(request))
    storage = request.app.state.storage
    try:
        account = accounts.request_account(
            storage, username, password, display_name=display_name, language=language, note=note
        )
    except accounts.AccountConflict as refused:
        raise HTTPException(status_code=409, detail=refused.message) from None
    except accounts.SignUpsFull as refused:
        raise HTTPException(status_code=429, detail=refused.message) from None
    except PlayError as refused:
        raise HTTPException(status_code=422, detail=refused.message) from None
    data_dir = request.app.state.config.data_dir
    if address is not None and mail_enabled(data_dir):  # with mail off the field is ignored
        addresses.ask_to_confirm(storage, data_dir, account, address, request.app.state.clock.now())
    request.app.state.events.publish("accounts", {"id": account.id}, scope="organisers")
    return JSONResponse({"username": account.username, "pending": True}, status_code=201)
