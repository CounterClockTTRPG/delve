"""Joining a table with a link (spec §7.2, §11): the host's invite, and the join link anyone may open.

The link holds the campaign's join token; a new invite replaces it, and the old link stops working. Every invite asks
for an account (players and tavern Task C5, decision 2): a logged-in account joins as itself, and someone without one
makes one on the join page, which logs them in. Joining gives the account a seat there, a player or an observer, and
an account has one live seat per table: joining again answers the seat it has. A full table (DEL-204) seats no new
player, and the link shows the table's description, its places and its house rules. Seat tokens made before accounts keep
working (`delve_seat`), and `POST …/seats/keep` hands such a seat to an account. Join requests are limited per
address (`guard.client_address`), so a join token can't be guessed. Each change publishes the event `seats`.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import Counter, defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.responses import JSONResponse

from delve.domain.campaigns import Campaign
from delve.domain.settings import LANGUAGES as INTERFACE_LANGUAGES
from delve.play import accounts, join_requests, profiles, schedule, seats
from delve.play.context import PlayError
from delve.web import guard
from delve.web.auth import Principal
from delve.web.routes.accounts import logged_in, text_field
from delve.web.routes.join_requests import request_json, requests_changed
from delve.web.routes.listing import house_rules_json
from delve.web.routes.seats import seat_json, seats_changed
from delve.web.seats import HostSeat

router = APIRouter()

LANGUAGES = list(INTERFACE_LANGUAGES)
"""The languages the interface speaks; a seat may read the story in any other, in English around it."""
LANGUAGE = re.compile(r"[a-z]{2,3}")
"""A BCP-47 primary language tag."""
NAME_LENGTH = 40
ROLES = ("player", "observer")
JOINS_PER_MINUTE = 10
WINDOW_S = 60.0
ACCOUNTS_PER_INVITE = 25
"""At most this many accounts are made through one join link (audit-auth finding 8); a new invite counts again. The
count is kept while Delve runs."""
NO_SUCH_LINK = "This join link doesn't work: ask the host for a new one."
TOO_MANY = "Too many tries to join: wait a minute."
TOO_MANY_ACCOUNTS = f"This join link has made {ACCOUNTS_PER_INVITE} accounts already: ask the host for a new one."
NEEDS_ACCOUNT = "Log in or make an account to join."
OWNER_IS_SEATED = "The owner has a seat at every table already."

clock = time.monotonic
_counting = threading.Lock()


def _limit(request: Request) -> None:
    """429 for an address that made `JOINS_PER_MINUTE` join requests in the last minute."""
    hits: defaultdict[str, deque[float]] | None = getattr(request.app.state, "join_requests", None)
    if hits is None:
        hits = request.app.state.join_requests = defaultdict(deque)
    address = guard.client_address(request)
    now = clock()
    recent = hits[address]
    while recent and recent[0] <= now - WINDOW_S:
        recent.popleft()
    if len(recent) >= JOINS_PER_MINUTE:
        raise HTTPException(status_code=429, detail=TOO_MANY)
    recent.append(now)


@contextmanager
def _an_account_made_through(request: Request, join_token: str) -> Iterator[None]:
    """Count an account made through the join link, from before it is made (so parallel requests can't pass the
    cap), and give the count back when it isn't made; 429 past `ACCOUNTS_PER_INVITE`."""
    made: Counter[str] | None = getattr(request.app.state, "invite_accounts", None)
    if made is None:
        made = request.app.state.invite_accounts = Counter()
    key = hashlib.sha256(join_token.encode()).hexdigest()
    with _counting:
        if made[key] >= ACCOUNTS_PER_INVITE:
            raise HTTPException(status_code=429, detail=TOO_MANY_ACCOUNTS)
        made[key] += 1
    try:
        yield
    except BaseException:
        with _counting:
            made[key] -= 1
        raise


def _campaign_of(request: Request, join_token: str) -> Campaign:
    _limit(request)
    campaign = request.app.state.storage.campaigns.by_join_token(join_token)
    if campaign is None:
        raise HTTPException(status_code=404, detail=NO_SUCH_LINK)
    return campaign


def _caller(request: Request) -> Principal | None:
    """Whoever asks, without refusing anyone: the join link is open to all."""
    return request.app.state.identity.resolve(request)


@router.get("/api/join/{join_token}")
def join_link(request: Request, join_token: str) -> dict:
    """The table the link is for, before joining; no login needed: its name, its host's name, its module's title, its
    description, its places for players and how many are taken, whether it is `full` (`seats.is_full`), its house
    rules, and its next sessions (`schedule.next_sessions`). `you` is the logged-in account, with its seat there if
    it has one and its profile summary, as a seat shows it (`seat_json`)."""
    campaign = _campaign_of(request, join_token)
    storage = request.app.state.storage
    module = storage.modules.get(campaign.module_id)
    principal = _caller(request)
    account = principal.account if principal is not None else None
    you = None
    if account is not None:
        seat = storage.seats.for_account(account.id, campaign.id)
        you = {
            "account_id": account.id,
            "display_name": account.profile.display_name,
            "seat_id": seat.id if seat is not None else None,
            "profile": profiles.summary(account),
        }
    owner = seats.owner_seat(storage, campaign.id)
    shown = seats.shown_account(storage, owner) if owner is not None else None
    return {
        "campaign": {
            "name": campaign.name,
            # Who invites: the host's name as the table shows it (DEL-264).
            "host": (shown.profile.display_name if shown is not None else owner.name) if owner is not None else None,
            "module_title": module.title if module else "",
            "description": campaign.description,
            "slots": campaign.slots,
            "observers": campaign.observers,
            "taken": seats.taken(storage, campaign.id),
            "full": seats.is_full(storage, campaign),
            "house_rules": house_rules_json(storage, campaign.id),
            "next_sessions": schedule.next_sessions(campaign.schedule, request.app.state.clock.now()),
        },
        "languages": LANGUAGES,
        "you": you,
    }


def _name(raw: str) -> str:
    name = raw.strip()
    if not 1 <= len(name) <= NAME_LENGTH:
        raise HTTPException(status_code=422, detail=f"A name has 1 to {NAME_LENGTH} characters.")
    return name


def _language(raw: str) -> str:
    language = raw.strip().lower()
    if not LANGUAGE.fullmatch(language):
        raise HTTPException(status_code=422, detail="A language is a code of 2 or 3 letters, such as en or nl.")
    return language


def _role(body: dict[str, Any]) -> str:
    role = body.get("role")
    if role not in ROLES:
        raise HTTPException(status_code=422, detail="Join as a player or an observer.")
    return role


def _watching(campaign: Campaign, role: str) -> str:
    """How the link takes an observer (DEL-215): `seat` at once, `ask` a host first, or refused, 409, at a table that
    takes none. A player is always `seat`."""
    if role != "observer" or campaign.observers == "anyone":
        return "seat"
    if campaign.observers == "nobody":
        raise HTTPException(status_code=409, detail=join_requests.NO_OBSERVERS)
    return "ask"


def _ask_to_watch(request: Request, campaign: Campaign, account) -> dict[str, Any]:
    """The account asks to watch, from the link: the request, which a host answers; the seat it has, when it has
    one already."""
    storage = request.app.state.storage
    seat = storage.seats.for_account(account.id, campaign.id)
    if seat is not None:
        return {"seat": seat_json(storage, seat, None), "campaign_id": campaign.id}
    try:
        asked = join_requests.ask(storage, campaign, account, "", request.app.state.clock.now(), "observer")
    except PlayError as refused:
        raise HTTPException(status_code=409, detail=refused.message) from None
    requests_changed(request, campaign.id)
    return {"join_request": request_json(storage, asked), "campaign_id": campaign.id}


@router.post("/api/join/{join_token}", status_code=201)
def join(request: Request, join_token: str, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    """Take a seat at the table as the logged-in account: 201 with the new seat, or 200 with the one it has there.
    An observer at a table whose watchers a host lets in asks instead: 202 with the request (DEL-215). 401 for anyone
    who isn't an account, 409 for a new player at a full table or an observer at a table that takes none."""
    campaign = _campaign_of(request, join_token)
    principal = _caller(request)
    if principal is None or principal.account is None:
        raise HTTPException(status_code=401, detail=NEEDS_ACCOUNT)
    if principal.owner:
        raise HTTPException(status_code=409, detail=OWNER_IS_SEATED)
    role = _role(body)
    if _watching(campaign, role) == "ask":
        answer = _ask_to_watch(request, campaign, principal.account)
        return JSONResponse(answer, status_code=200 if "seat" in answer else 202)
    name = text_field(body, "name", optional=True)
    storage = request.app.state.storage
    try:
        seat, made = seats.seat_account(
            storage, campaign, principal.account, role, _name(name) if name is not None else None
        )
    except seats.TableFull as refused:
        raise HTTPException(status_code=409, detail=refused.message) from None
    if made:
        seats_changed(request, campaign.id)
    return JSONResponse(
        {"seat": seat_json(storage, seat, None), "campaign_id": campaign.id}, status_code=201 if made else 200
    )


@router.post("/api/join/{join_token}/account", status_code=201)
def join_with_a_new_account(request: Request, join_token: str, body: Annotated[dict[str, Any], Body()]) -> JSONResponse:
    """Make an account through the invite and take a seat with it: 201 with the seat and the account, logged in; an
    observer at a table whose watchers a host lets in gets the account and a request to watch, 202 (DEL-215).
    409 for a username that is taken, or for a player at a full table, before the account is made; 429 once the link
    made `ACCOUNTS_PER_INVITE`. The account and the seat are made together or not at all."""
    campaign = _campaign_of(request, join_token)
    username, password = text_field(body, "username"), text_field(body, "password")
    display_name = _name(text_field(body, "display_name"))
    language = _language(text_field(body, "language"))
    role = _role(body)
    watching = _watching(campaign, role)
    storage = request.app.state.storage
    try:
        seats.make_room_for(storage, campaign, role)
        with _an_account_made_through(request, join_token), storage.transaction():
            account = accounts.create_account(storage, username, password, display_name=display_name, language=language)
            if watching == "seat":
                seat, _ = seats.seat_account(storage, campaign, account, role)
    except (accounts.AccountConflict, seats.TableFull) as refused:
        raise HTTPException(status_code=409, detail=refused.message) from None
    except PlayError as refused:
        raise HTTPException(status_code=422, detail=refused.message) from None
    if watching == "ask":
        # The account is made and logged in; the host lets it watch (DEL-215).
        return logged_in(request, account, 202, **_ask_to_watch(request, campaign, account))
    seats_changed(request, campaign.id)
    return logged_in(request, account, 201, seat=seat_json(storage, seat, None), campaign_id=campaign.id)


def link_origin(request: Request) -> str:
    """Where a link Delve hands out should point: from this machine, the first LAN address, which the other devices
    can reach (the request's own host without one); otherwise, through a proxy too, the request's own host, over
    https when the browser came over it (`guard.came_over_https`, audit-auth finding 6)."""
    base = request.base_url
    if guard.came_over_https(request):
        base = base.replace(scheme="https")
    origin = str(base).rstrip("/")
    if guard.is_this_machine(request):
        port = request.url.port or request.app.state.config.port
        origin = next(iter(guard.lan_origins(port)), origin)
    return origin


def invite_json(request: Request, campaign: Campaign) -> dict:
    """The join link, at `link_origin`."""
    return {"url": f"{link_origin(request)}/join/{campaign.join_token}", "join_token": campaign.join_token}


@router.get("/api/campaigns/{campaign_id}/invite")
def invite(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    return invite_json(request, request.app.state.storage.campaigns.get(campaign_id))


@router.post("/api/campaigns/{campaign_id}/invite")
def new_invite(request: Request, seat: HostSeat, campaign_id: str) -> dict:
    """A new join link: the old one stops working."""
    campaign = request.app.state.storage.campaigns.new_join_token(campaign_id)
    seats_changed(request, campaign_id)
    return invite_json(request, campaign)
