"""Finding a table and asking to join it (DEL-204 part B): the public tables, the requests to join them, the short
thread on each, and the hosts' answer.

Public tables are listed for logged-in accounts only (`AccountCaller`), the owner's account too: never for a seat
token, the owner token alone or anyone not logged in. An account asks to join a public table with a note; until a host
or a co-host accepts or declines, the account and the table's hosts talk on the request (`delve.play.join_requests`).
Accepting gives the account a `player` seat, as the join link would.

The table's description and the request's messages are for people only: the DM never reads them, so they go into no
prompt. Each change publishes `join_requests` to the table's host and co-hosts, with the `campaign_id`; an accept
publishes `seats` too. The account that asked has no seat there, so it hears no event: its page reads its requests
again.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from delve.domain.campaigns import JoinRequest
from delve.play import join_requests, profiles, schedule, seats
from delve.play.context import PlayError
from delve.storage import Storage
from delve.web.auth import Principal, current_principal
from delve.web.refusals import refusal
from delve.web.routes.accounts import AccountCaller, text_field
from delve.web.routes.campaigns import now_of
from delve.web.routes.listing import house_rules_json
from delve.web.routes.seats import seat_json, seats_changed
from delve.web.seats import HostSeat, table_seat

router = APIRouter()

NO_SUCH_TABLE = "No such table."
NOT_YOURS = "This request is between its player and the table's hosts."
HOSTS = ("host", "cohost")


def _now(request: Request):
    return request.app.state.clock.now()


def requests_changed(request: Request, campaign_id: str) -> None:
    """Tell the table's host and co-hosts that its requests changed."""
    request.app.state.events.publish(
        "join_requests", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id, roles=HOSTS
    )


def request_json(storage: Storage, found: JoinRequest) -> dict[str, Any]:
    """The request as its player and the table's hosts read it, with the account that asked and its profile summary."""
    account = storage.accounts.get(found.account_id)
    return {
        "id": found.id,
        "campaign_id": found.campaign_id,
        "status": found.status,
        "messages": [dict(m) for m in found.messages],
        "created_at": found.created_at,
        "decided_at": found.decided_at,
        "seat_id": found.seat_id,
        "role": found.role,
        "account": {
            "id": found.account_id,
            "display_name": account.profile.display_name if account is not None else "",
            "profile": profiles.summary(account) if account is not None else None,
        },
    }


def _last_played(storage: Storage, campaign_id: str) -> str | None:
    newest = storage.story.list(campaign_id, limit=1)
    return newest[-1].at if newest else None


def _host_json(storage: Storage, campaign_id: str) -> dict[str, Any] | None:
    """The table's host: its account's profile summary (the owner's, for the owner's seat), or the seat's name without
    an account."""
    host = next((s for s in storage.seats.list(campaign_id) if s.role == "host" and s.left_at is None), None)
    if host is None:
        return None
    account = seats.shown_account(storage, host)
    if account is None:
        return {"display_name": host.name, "profile": None}
    return {"display_name": account.profile.display_name, "profile": profiles.summary(account)}


@router.get("/api/tables")
def public_tables(request: Request, principal: AccountCaller) -> list[dict]:
    """The public tables that aren't complete, the most recently played first (a table never played after them,
    oldest first): each with its name, module, ruleset and setting (ids and titles), description, places, whether it
    is full, its house rules, its schedule and next sessions (`schedule.next_sessions`), its host and the `people` at it
    (`profiles.people`); whether the account is `seated` there, and its newest `request` there."""
    storage = request.app.state.storage
    registries = request.app.state.registries
    ruleset_titles = {caps.id: caps.title for caps in registries.rulesets.capabilities()}
    setting_titles = {caps.id: caps.title for caps in registries.settings_.capabilities()}
    account = principal.account
    newest: dict[str, JoinRequest] = {}
    for found in storage.join_requests.of_account(account.id):  # newest first
        newest.setdefault(found.campaign_id, found)
    now = now_of(request)
    tables = []
    for campaign in storage.campaigns.list():
        if not seats.is_listed(campaign):
            continue
        module = storage.modules.get(campaign.module_id)
        mine = newest.get(campaign.id)
        tables.append(
            {
                "campaign_id": campaign.id,
                "name": campaign.name,
                "module_title": module.title if module is not None else "",
                "ruleset": campaign.ruleset,
                "ruleset_title": ruleset_titles.get(campaign.ruleset, campaign.ruleset),
                "setting": campaign.setting,
                "setting_title": setting_titles.get(campaign.setting, campaign.setting) if campaign.setting else None,
                "description": campaign.description,
                "slots": campaign.slots,
                "observers": campaign.observers,
                "taken": seats.taken(storage, campaign.id),
                "full": seats.is_full(storage, campaign),
                "house_rules": house_rules_json(storage, campaign.id),
                "schedule": campaign.schedule,
                "next_sessions": schedule.next_sessions(campaign.schedule, now),
                "host": _host_json(storage, campaign.id),
                "people": profiles.people(storage, campaign.id),
                "seated": join_requests.is_seated(storage, campaign.id, account),
                "request": None if mine is None else {"id": mine.id, "status": mine.status},
                "last_played_at": _last_played(storage, campaign.id),
            }
        )
    played = sorted((t for t in tables if t["last_played_at"]), key=lambda t: t["last_played_at"], reverse=True)
    return [
        {k: v for k, v in t.items() if k != "last_played_at"}
        for t in played + [t for t in tables if not t["last_played_at"]]
    ]


@router.post("/api/tables/{campaign_id}/requests", status_code=201)
def ask_to_join(
    request: Request, principal: AccountCaller, campaign_id: str, body: Annotated[dict[str, Any], Body()]
) -> dict:
    """Ask to join a public table with a note (at most 1000 characters; it may be empty), as a `player` or, with
    `"role": "observer"`, to watch (DEL-215): 201 with the request. 404 for a table that isn't listed, 409 when the
    account is seated there or asked already, a player's table is full, or the table takes no observers."""
    storage = request.app.state.storage
    campaign = storage.campaigns.get(campaign_id)
    if not seats.is_listed(campaign):
        raise HTTPException(status_code=404, detail=NO_SUCH_TABLE)
    note = text_field(body, "note", optional=True) or ""
    role = body.get("role", "player")
    if role not in ("player", "observer"):
        raise HTTPException(status_code=422, detail="Ask to join as a player or an observer.")
    try:
        asked = join_requests.ask(storage, campaign, principal.account, note, _now(request), role)
    except PlayError as refused:
        raise refusal(refused) from None
    requests_changed(request, campaign_id)
    return {"request": request_json(storage, asked)}


@router.get("/api/account/requests")
def my_requests(request: Request, principal: AccountCaller) -> list[dict]:
    """The account's requests to join, newest first, each with its table's name and module."""
    storage = request.app.state.storage
    answer = []
    for found in storage.join_requests.of_account(principal.account.id):
        campaign = storage.campaigns.get(found.campaign_id)
        if campaign is None:
            continue
        module = storage.modules.get(campaign.module_id)
        table = {"id": campaign.id, "name": campaign.name, "module_title": module.title if module is not None else ""}
        answer.append({**request_json(storage, found), "campaign": table})
    return answer


def _request(request: Request, request_id: str) -> JoinRequest:
    found = request.app.state.storage.join_requests.get(request_id)
    if found is None:
        raise HTTPException(status_code=404, detail=join_requests.NO_SUCH_REQUEST)
    return found


def _speaker(request: Request, principal: Principal, found: JoinRequest) -> tuple[join_requests.Sender, str]:
    """Who talks on the request: its account, as `player` under its display name, or a host or co-host of its table,
    as `host` under the seat's name. 403 for anyone else."""
    if principal.account is not None and principal.account.id == found.account_id:
        return "player", principal.account.profile.display_name
    try:
        seat = table_seat(request, found.campaign_id)
    except HTTPException:
        raise HTTPException(status_code=403, detail=NOT_YOURS) from None
    if seat.role not in seats.TABLE_RIGHTS:
        raise HTTPException(status_code=403, detail=NOT_YOURS)
    return "host", seat.name


@router.post("/api/requests/{request_id}/messages", status_code=201)
def talk(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    request_id: str,
    body: Annotated[dict[str, Any], Body()],
) -> dict:
    """Add a message to a pending request's thread, as its player or a host of its table: 201 with the request. 403
    for anyone else, 409 once it is decided or holds 50 messages, 422 for an empty or too long text."""
    found = _request(request, request_id)
    sender, name = _speaker(request, principal, found)
    text = text_field(body, "text")
    storage = request.app.state.storage
    try:
        said = join_requests.say(storage, found.id, sender, name, text, _now(request))
    except PlayError as refused:
        raise refusal(refused) from None
    requests_changed(request, found.campaign_id)
    return {"request": request_json(storage, said)}


@router.post("/api/requests/{request_id}/withdraw")
def withdraw(
    request: Request, principal: AccountCaller, request_id: str, body: Annotated[dict[str, Any], Body()]
) -> dict:
    """The account takes its pending request back: 200 with the request. 403 for another account's, 409 once it is
    decided."""
    found = _request(request, request_id)
    if found.account_id != principal.account.id:
        raise HTTPException(status_code=403, detail=NOT_YOURS)
    storage = request.app.state.storage
    try:
        withdrawn = join_requests.withdraw(storage, found.id, _now(request))
    except PlayError as refused:
        raise refusal(refused) from None
    requests_changed(request, found.campaign_id)
    return {"request": request_json(storage, withdrawn)}


@router.get("/api/campaigns/{campaign_id}/requests")
def table_requests(request: Request, seat: HostSeat, campaign_id: str) -> list[dict]:
    """The table's requests, for its host and co-hosts: the pending ones, oldest first, then those decided in the last
    14 days, the most recently decided first."""
    storage = request.app.state.storage
    return [request_json(storage, r) for r in join_requests.for_host(storage, campaign_id, _now(request))]


def _table_request(request: Request, campaign_id: str, request_id: str) -> JoinRequest:
    found = _request(request, request_id)
    if found.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail=join_requests.NO_SUCH_REQUEST)
    return found


@router.post("/api/campaigns/{campaign_id}/requests/{request_id}/accept")
def accept(
    request: Request, seat: HostSeat, campaign_id: str, request_id: str, body: Annotated[dict[str, Any], Body()]
) -> dict:
    """The host, or a co-host, accepts the pending request: the account gets a `player` seat (or keeps the live seat
    it has there), and the request is `accepted` with it. 200 with the request and the seat; 409 once it is decided,
    or for a new player at a full table."""
    found = _table_request(request, campaign_id, request_id)
    storage = request.app.state.storage
    try:
        accepted, given, made = join_requests.accept(storage, found.id, _now(request))
    except PlayError as refused:
        raise refusal(refused) from None
    if made:
        seats_changed(request, campaign_id)
    requests_changed(request, campaign_id)
    return {"request": request_json(storage, accepted), "seat": seat_json(storage, given, None)}


@router.post("/api/campaigns/{campaign_id}/requests/{request_id}/decline")
def decline(
    request: Request, seat: HostSeat, campaign_id: str, request_id: str, body: Annotated[dict[str, Any], Body()]
) -> dict:
    """The host, or a co-host, declines the pending request; a `reason` that isn't empty goes into the thread first,
    under the seat's name. 200 with the request; 409 once it is decided, 422 for a reason past 1000 characters."""
    found = _table_request(request, campaign_id, request_id)
    reason = text_field(body, "reason", optional=True) or ""
    storage = request.app.state.storage
    try:
        declined = join_requests.decline(storage, found.id, seat.name, reason, _now(request))
    except PlayError as refused:
        raise refusal(refused) from None
    requests_changed(request, campaign_id)
    return {"request": request_json(storage, declined)}
