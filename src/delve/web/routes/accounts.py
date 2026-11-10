"""Logging in and out (players and tavern Task C4): the login session's cookie, the throttle, the browsers an account
is logged in on, changing its password, the one-time links that set or reset one, an account's tables, and the first
owner account (the human's ruling of 2026-10-24).

The session's token goes only into the `delve_session` cookie: `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure`
when the browser came over HTTPS (`guard.came_over_https`). A failed login counts against the folded username and
the address (`guard.client_address`), from before the password is checked; past `PER_USERNAME_AND_ADDRESS` failures
of a username from one address in `WINDOW_S`, that username waits `WAIT_S` there; past `PER_USERNAME` from all of
them, everywhere, except for a browser with a device cookie for that account (`delve_device`, `delve.web.devices`),
which waits past `PER_DEVICE` of its own instead; past `PER_ADDRESS` of any usernames, that address waits. A login sets
the device cookie with the session's, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` the same way, for a year; logging
out keeps it, as it says which browser this is, not who is logged in. Every refusal of a login is the same 401,
so no answer says whether a username exists. No answer holds a password, a token or a hash; a body's fields are read
by hand, so a refusal never echoes them.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from starlette.responses import JSONResponse, Response

from delve.domain.accounts import PASSWORD_MAX, Account
from delve.play import accounts, banners, logins, profiles, schedule, seats
from delve.play.context import PlayError
from delve.play.passwords import PasswordsBusy
from delve.play.seats import NotAllowed
from delve.web import devices, guard
from delve.web.auth import DEVICE_COOKIE, SESSION_COOKIE, Principal, current_principal, device_cookie, session_token
from delve.web.refusals import refusal
from delve.web.routes.voice import table_changed

router = APIRouter()

WRONG = "Wrong username or password."
TOO_MANY = "Too many tries: wait 15 minutes."
NOT_AN_ACCOUNT = "Log in to an account first."
NO_LINK = "This link doesn't work: ask for a new one."
NOT_HERE = "Make the owner account on the machine Delve runs on."
OWNER_EXISTS = "There is an owner account already: log in with it."
NOT_TEXT = "Send the fields as text."
USERNAME_FIELD_MAX = 64
"""A login's username past this many characters, or its password past `PASSWORD_MAX`, is refused before the throttle
and scrypt (Clara's final audit, finding 4): no account has one, and it would only cost memory and time."""
COOKIE_MAX_AGE = 365 * 24 * 60 * 60
"""The cookie lives a year; the server ends the session `logins.SESSION_DAYS` after its last use."""


class LoginThrottle:
    """Failed logins per folded username from one address, per username from anywhere, and per address. One outsider
    can't lock the owner out: their failures make the username wait at their own address only, until `PER_USERNAME`
    from all addresses together (audit-auth finding 7). Many outsiders still could: ten addresses with five tries each
    made any username wait everywhere for 15 minutes, the owner's too (DEL-154, audit finding 8). So an attempt that
    presents a device cookie for the account it logs in to (`delve.web.devices`: a browser that logged in to it
    before) neither counts against the username from anywhere nor waits for it; it counts against that device
    instead, which waits past `PER_DEVICE` failures, from any address. Only the account's password gets a browser such
    a cookie, so a stranger guessing passwords is held as before: `PER_USERNAME_AND_ADDRESS` per address,
    `PER_USERNAME` everywhere, `PER_ADDRESS` for any usernames; and the device's attempts keep the per-address limits.
    An attempt counts as failed from before its password is checked (`reserve`), and is taken back when it succeeds,
    so parallel attempts can't get past the limit while their checks run (audit-auth finding 4). `clock` is patched
    in tests."""

    PER_USERNAME_AND_ADDRESS = 5
    PER_USERNAME = 50
    PER_DEVICE = 5
    PER_ADDRESS = 20
    WINDOW_S = 15 * 60
    WAIT_S = 15 * 60

    def __init__(self) -> None:
        self.clock: Callable[[], float] = time.monotonic
        self._failures: defaultdict[str, deque[float]] = defaultdict(deque)
        self._waits: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(username: str, address: str, device: str | None) -> tuple[tuple[str, int], ...]:
        """The counts an attempt goes into, with their limits: the username at the address, the username everywhere
        or the device, and the address. A success starts the first two again."""
        user = username.strip().casefold()
        return (
            (f"user-at:{user}@{address}", LoginThrottle.PER_USERNAME_AND_ADDRESS),
            (f"device:{device}", LoginThrottle.PER_DEVICE) if device else (f"user:{user}", LoginThrottle.PER_USERNAME),
            (f"address:{address}", LoginThrottle.PER_ADDRESS),
        )

    def reserve(self, username: str, address: str, device: str | None = None) -> float:
        """429 while any of its counts waits; otherwise count the attempt as failed already, and answer its time for
        `succeeded`. `device` is the nonce of a valid device cookie for the username's account (`known_device`)."""
        with self._lock:
            now = self.clock()
            keys = self._keys(username, address, device)
            for key, _ in keys:
                until = self._waits.get(key)
                if until is not None and now < until:
                    raise HTTPException(status_code=429, detail=TOO_MANY)
                self._waits.pop(key, None)
            for key, limit in keys:
                recent = self._failures[key]
                while recent and recent[0] <= now - self.WINDOW_S:
                    recent.popleft()
                recent.append(now)
                if len(recent) >= limit:
                    self._waits[key] = now + self.WAIT_S
            return now

    def take_back(self, username: str, address: str, at: float, device: str | None = None) -> None:
        """The attempt reserved `at` didn't fail: it no longer counts."""
        with self._lock:
            for key, limit in self._keys(username, address, device):
                recent = self._failures.get(key)
                if recent is None or at not in recent:
                    continue
                recent.remove(at)
                if self._waits.get(key) == at + self.WAIT_S and len(recent) < limit:
                    del self._waits[key]
                if not recent:
                    del self._failures[key]

    def succeeded(self, username: str, address: str, at: float, device: str | None = None) -> None:
        """The attempt reserved `at` let the caller in: it no longer counts, and the username's count at that address
        starts again, and the device's. The username's count from everywhere doesn't: strangers made it."""
        self.take_back(username, address, at, device)
        with self._lock:
            pair, everywhere, _ = self._keys(username, address, device)
            for key, _ in (pair, everywhere) if device else (pair,):
                self._failures.pop(key, None)
                self._waits.pop(key, None)


def throttle(request: Request) -> LoginThrottle:
    found = getattr(request.app.state, "login_throttle", None)
    if found is None:
        found = request.app.state.login_throttle = LoginThrottle()
    return found


def text_field(body: dict[str, Any], name: str, *, optional: bool = False) -> str | None:
    """A text field of the body; 422 for a missing one (unless `optional`) or one that isn't text, never echoing it."""
    value = body.get(name)
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=NOT_TEXT)
    return value


def known_device(request: Request, username: str) -> str | None:
    """The nonce of the request's device cookie when it is a valid one for the account `username` names, else None
    (`delve.web.devices`)."""
    value = device_cookie(request)
    if value is None:
        return None
    try:
        account = request.app.state.storage.accounts.by_username(accounts.username_of(username))
    except PlayError:
        return None
    account_id = account.id if account is not None else None
    return devices.device_of(request.app.state.device_secret, value, account_id, _now(request).timestamp())


def account_json(account: Account) -> dict[str, Any]:
    """The account as `/api/me` and the login routes answer it."""
    return {
        "id": account.id,
        "username": account.username,
        "display_name": account.profile.display_name,
        "language": account.profile.language,
        "organiser": account.organiser,
        "owner": account.owner,
    }


def _now(request: Request):
    return request.app.state.clock.now()


def logged_in(request: Request, account: Account, status_code: int = 200, **extra: Any) -> JSONResponse:
    """The answer that logs the browser in to `account`: a new login session in the `delve_session` cookie, and a new
    device cookie for the account in `delve_device` (DEL-154)."""
    response = JSONResponse({**extra, "account": account_json(account)}, status_code=status_code)
    return log_in_on(request, account, response)


def log_in_on(request: Request, account: Account, response: Response) -> Response:
    """`response` with the cookies that log the browser in to `account` (`logged_in`): a redirect does it too
    (`delve.web.routes.oidc`)."""
    user_agent = request.headers.get("user-agent", "")
    now = _now(request)
    token = logins.start(request.app.state.storage, account.id, user_agent, guard.client_address(request), now)
    device = devices.new_device_cookie(request.app.state.device_secret, account.id, now.timestamp())
    for name, value in ((SESSION_COOKIE, token), (DEVICE_COOKIE, device)):
        response.set_cookie(
            name,
            value,
            max_age=COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            samesite="lax",
            secure=guard.came_over_https(request),
        )
    return response


def _logged_out(response: Response) -> Response:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return response


@router.post("/api/login")
def login(request: Request, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    """Log in: 200 with the account and the session cookie; 401 for every refusal, 403 for the right password of a
    sign-up that waits for approval (unless `join_token` is a live join link, which approves it), 429 while the
    username or the address waits (checked before the password is), 503 when no password check is free in time."""
    username, password = text_field(body, "username"), text_field(body, "password")
    if len(username) > USERNAME_FIELD_MAX or len(password) > PASSWORD_MAX:
        raise HTTPException(status_code=401, detail=WRONG)
    limits, address = throttle(request), guard.client_address(request)
    device = known_device(request, username)
    at = limits.reserve(username, address, device)
    try:
        account = accounts.authenticate(request.app.state.storage, username, password)
    except PasswordsBusy:
        limits.take_back(username, address, at, device)  # nothing was checked
        raise
    except accounts.AccountPending as waiting:
        limits.take_back(username, address, at, device)  # the password was right
        account = _let_in_by_invite(request, body, username)
        if account is None:
            raise refusal(waiting, 403) from None
    if account is None:
        raise HTTPException(status_code=401, detail=WRONG)
    limits.succeeded(username, address, at, device)
    return logged_in(request, account)


def _let_in_by_invite(request: Request, body: dict[str, Any], username: str) -> Account | None:
    """A pending sign-up that logs in on a table's join page (`join_token`, a live join link) is approved: the host
    who shared the link vouched for whoever has it (DEL-156). None without such a link."""
    join_token = body.get("join_token")
    storage = request.app.state.storage
    if not isinstance(join_token, str) or storage.campaigns.by_join_token(join_token) is None:
        return None
    account = storage.accounts.by_username(accounts.username_of(username))
    approved = accounts.approve(storage, account.id)
    request.app.state.events.publish("accounts", {"id": approved.id}, scope="organisers")
    return approved


@router.post("/api/logout", status_code=204)
def logout(request: Request) -> Response:
    """Log this browser out, and clear its cookie; 204 without a session too."""
    token = session_token(request)
    if token:
        logins.end(request.app.state.storage, token)
        table_changed(request.app)  # this browser's voice goes with its login
    return _logged_out(Response(status_code=204))


def account_caller(request: Request) -> Principal:
    """A dependency: the caller, when it is an account (403 for the owner token, this machine and seat tokens)."""
    principal = current_principal(request)
    if principal.account is None:
        raise HTTPException(status_code=403, detail=NOT_AN_ACCOUNT)
    return principal


AccountCaller = Annotated[Principal, Depends(account_caller)]


def _current_login(request: Request, principal: Principal) -> str | None:
    login = request.app.state.storage.login_sessions.by_token_hash(principal.login_hash or "")
    return None if login is None else login.id


@router.get("/api/account/sessions")
def list_sessions(request: Request, principal: AccountCaller) -> list[dict]:
    """The browsers the account is logged in on, the most recently used first."""
    current = _current_login(request, principal)
    return [
        {"id": s.id, "device": s.device, "last_used_at": s.last_used_at, "current": s.id == current}
        for s in request.app.state.storage.login_sessions.list(principal.account.id)
    ]


@router.delete("/api/account/sessions/{login_id}", status_code=204)
def end_session(request: Request, principal: AccountCaller, login_id: str) -> Response:
    """Log one of the account's browsers out; 404 for one that isn't the account's."""
    storage = request.app.state.storage
    if not any(s.id == login_id for s in storage.login_sessions.list(principal.account.id)):
        raise HTTPException(status_code=404, detail="No such login.")
    storage.login_sessions.end(login_id)
    table_changed(request.app)
    response = Response(status_code=204)
    return _logged_out(response) if login_id == _current_login(request, principal) else response


@router.post("/api/account/sessions/end-all", status_code=204)
def end_all_sessions(request: Request, principal: AccountCaller) -> Response:
    """Log out everywhere: every browser of the account, this one included."""
    request.app.state.storage.login_sessions.end_all(principal.account.id)
    table_changed(request.app)
    return _logged_out(Response(status_code=204))


@router.put("/api/account/password", status_code=204)
def change_password(request: Request, principal: AccountCaller, body: Annotated[dict[str, Any], Body()]) -> Response:
    """Change the password; the account's other browsers are logged out. 403 for a wrong current password, which
    counts as a failed login; 422 for a new one that isn't allowed."""
    old, new = text_field(body, "old"), text_field(body, "new")
    limits, address = throttle(request), guard.client_address(request)
    username = principal.account.username
    device = known_device(request, username)
    at = limits.reserve(username, address, device)
    try:
        logins.change_password(
            request.app.state.storage,
            principal.account.id,
            old,
            new,
            keep=_current_login(request, principal) or "",
        )
    except NotAllowed as refused:
        raise refusal(refused) from None
    except PasswordsBusy:
        limits.take_back(username, address, at, device)  # nothing was checked
        raise
    except PlayError as refused:
        limits.take_back(username, address, at, device)  # the current password was right
        raise refusal(refused) from None
    limits.take_back(username, address, at, device)
    table_changed(request.app)  # the other browsers' voice goes with their logins
    return Response(status_code=204)


@router.get("/api/account-links/{token}")
def account_link(request: Request, token: str) -> dict:
    """Whose password a one-time link sets or resets; 404 for one that is unknown, used or expired."""
    found = accounts.link_for(request.app.state.storage, token, _now(request))
    if found is None:
        raise HTTPException(status_code=404, detail=NO_LINK)
    account, link = found
    return {"username": account.username, "kind": link.kind}


@router.post("/api/account-links/{token}")
def use_account_link(request: Request, token: str, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    """Set the password through a one-time link: 200, logged in, every older login of the account ended. 404 for a
    link that doesn't work, 422 for a password that isn't allowed."""
    password = text_field(body, "password")
    storage = request.app.state.storage
    if accounts.link_for(storage, token, _now(request)) is None:
        raise HTTPException(status_code=404, detail=NO_LINK)
    try:
        accounts.check_new_password(password)
    except PlayError as refused:
        raise refusal(refused) from None
    try:
        account = logins.use_link(storage, token, password, _now(request))
    except PlayError:
        raise HTTPException(status_code=404, detail=NO_LINK) from None  # used by another request meanwhile
    return logged_in(request, account)


@router.get("/api/account/tables")
def my_tables(request: Request, principal: AccountCaller) -> list[dict]:
    """The tables the account has a live seat at, the most recently played first and complete ones last, each with its
    campaign's `status`, its places (`slots`, `taken`), the `people` at it (`profiles.people`) and its next sessions
    (`schedule.next_sessions`). An owner account is seated at every table by its owner's seat, which has no account
    (`seats.shown_account`)."""
    storage = request.app.state.storage
    now = _now(request)
    tables = []
    live = storage.seats.of_account(principal.account.id)
    if principal.account.owner:
        taken = {seat.campaign_id for seat in live}
        owned = (storage.seats.owner_seat(c.id) for c in storage.campaigns.list() if c.id not in taken)
        live += [seat for seat in owned if seat is not None and seat.account_id is None]
    for seat in live:
        campaign = storage.campaigns.get(seat.campaign_id)
        if campaign is None:
            continue
        module = storage.modules.get(campaign.module_id)
        newest = storage.story.list(campaign.id, limit=1)
        state = storage.campaign_states.get(campaign.id)
        banner = banners.shown(storage, campaign.id)
        tables.append(
            {
                "campaign_id": campaign.id,
                "name": campaign.name,
                "module_title": module.title if module is not None else "",
                "status": campaign.status,
                "role": seat.role,
                "slots": campaign.slots,
                "taken": seats.taken(storage, campaign.id),
                "people": profiles.people(storage, campaign.id),
                "seat_id": seat.id,
                "last_played_at": newest[-1].at if newest else None,
                "session_number": state.session if state is not None else 1,
                "banner": banner is not None,
                "next_sessions": schedule.next_sessions(campaign.schedule, now),
            }
        )
    # Newest play first; a table never played after, oldest seat first (`of_account`'s order); complete ones last.
    played = sorted((t for t in tables if t["last_played_at"]), key=lambda t: t["last_played_at"], reverse=True)
    ordered = played + [t for t in tables if not t["last_played_at"]]
    return sorted(ordered, key=lambda t: t["status"] == "complete")


@router.post("/api/accounts/first-owner", status_code=201)
def first_owner(request: Request, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    """The install's first owner account, made from this machine while there is none: 201, logged in. 403 from
    anywhere else, or once an owner account exists."""
    username, password = text_field(body, "username"), text_field(body, "password")
    display_name = text_field(body, "display_name", optional=True)
    if not guard.is_this_machine(request):
        raise HTTPException(status_code=403, detail=NOT_HERE)
    storage = request.app.state.storage
    if accounts.has_owner_account(storage):
        raise HTTPException(status_code=403, detail=OWNER_EXISTS)
    try:
        account = accounts.create_first_owner(storage, username, password, display_name=display_name or None)
    except accounts.AccountConflict as refused:
        status = 403 if refused.message == OWNER_EXISTS else 409
        raise refusal(refused, status) from None
    except PlayError as refused:
        raise refusal(refused) from None
    return logged_in(request, account, 201)
