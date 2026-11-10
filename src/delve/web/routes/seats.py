"""The seats at a campaign's table (spec §7.2, §11): who sits there, the host's controls over roles, the characters
each seat plays, leaving and removing a seat (DEL-204), and who the caller is (`/api/me`).

Every seat at the table reads the seats. The host, or a co-host, gives roles and gives characters to seats; only the
install's owner makes a seat an organiser. An account keeps a seat its browser joined with a seat token before
accounts (players and tavern Task C5). Each change publishes the event `seats` with the `campaign_id`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.responses import JSONResponse, Response

from delve.domain.campaigns import Seat, SeatRole
from delve.play import profiles, seats
from delve.play.accounts import has_owner_account
from delve.play.context import PlayError
from delve.storage import Storage
from delve.web import guard
from delve.web.auth import Principal, current_principal, seat_token
from delve.web.refusals import refusal
from delve.web.routes.accounts import AccountCaller, account_json
from delve.web.routes.characters import player_character_json, sheet_context
from delve.web.routes.play import recheck_beat
from delve.web.routes.voice import table_changed
from delve.web.seats import SEAT_COOKIE, ActorSeat, HostSeat, TableSeat, token_hash

router = APIRouter()

ONLY_THE_OWNER = "Only the owner of this Delve makes organisers."
OWNER_ORGANISES = "The owner is always an organiser."
ACCOUNTS_ORGANISE = "Give an account organiser rights on the Players page."
SEATED_ALREADY = "You have a seat at this table already."
NO_SEAT_TO_KEEP = "There is no seat of this browser to keep at this table."


def seats_changed(request: Request, campaign_id: str) -> None:
    request.app.state.events.publish("seats", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id)
    # A seat that left, or plays nothing any more, no longer holds the open beat up.
    recheck_beat(request, campaign_id)
    # A seat that left is out of voice at once, and an observer's voice is listen-only from now.
    table_changed(request.app, campaign_id)


def present_seats(request: Request, campaign_id: str) -> set[str] | None:
    """The ids of the seats present at the table, from the event stream's presence; None while the stream doesn't
    keep it (then a seat that hasn't left counts as present)."""
    present = getattr(request.app.state.events, "present", None)
    return None if present is None else set(present(campaign_id))


def seat_json(storage: Storage, seat: Seat, present: set[str] | None) -> dict[str, Any]:
    """The seat as the table sees it: no token, and no owner mark. `profile` is its account's summary (players and
    tavern Task D3), null for a seat without an account; the owner's seat shows the owner's account."""
    account = seats.shown_account(storage, seat)
    return {
        "id": seat.id,
        "name": seat.name,
        "language": seat.language,
        "role": seat.role,
        "organiser": seat.organiser,
        "present": seat.left_at is None if present is None else seat.id in present,
        "characters": sorted(seats.controls(storage, seat.id)),
        "profile": None if account is None else profiles.summary(account),
    }


@router.get("/api/campaigns/{campaign_id}/seats")
def list_seats(request: Request, seat: TableSeat, campaign_id: str) -> list[dict]:
    """The seats at the table, oldest first; a seat that left isn't listed. The asking seat is present: it is at the
    page (DEL-260: its own arrival is announced as its stream opens, often before the page listens, so it read Away)."""
    storage = request.app.state.storage
    present = present_seats(request, campaign_id)
    if present is not None:
        present = present | {seat.id}
    return [seat_json(storage, s, present) for s in storage.seats.list(campaign_id) if s.left_at is None]


class SeatIn(BaseModel):
    role: SeatRole | None = None
    organiser: bool | None = None


@router.put("/api/campaigns/{campaign_id}/seats/{seat_id}")
def change_seat(
    request: Request,
    seat: TableSeat,
    principal: Annotated[Principal, Depends(current_principal)],
    campaign_id: str,
    seat_id: str,
    body: SeatIn,
) -> dict:
    """Give the seat a role (the host or a co-host; 409 when the table would have no host), or the organiser rights
    (the owner only, 403 otherwise). Both change together or not at all."""
    storage = request.app.state.storage
    target = storage.seats.get(seat_id)
    if target is None or target.campaign_id != campaign_id or target.left_at is not None:
        raise HTTPException(status_code=404, detail="No such seat at this table.")
    if body.organiser is not None:
        if not principal.owner:
            raise HTTPException(status_code=403, detail=ONLY_THE_OWNER)
        if target.owner and not body.organiser:
            raise HTTPException(status_code=422, detail=OWNER_ORGANISES)
        if target.account_id is not None:
            raise HTTPException(status_code=422, detail=ACCOUNTS_ORGANISE)
    try:
        with storage.transaction():
            if body.role is not None:
                target = seats.set_role(storage, campaign_id, seat_id, body.role, by=seat)
            if body.organiser is not None and body.organiser != target.organiser:
                target = storage.seats.save(replace(target, organiser=body.organiser))
    except PlayError as refused:
        raise refusal(refused) from None
    seats_changed(request, campaign_id)
    return seat_json(storage, target, present_seats(request, campaign_id))


class ClaimIn(BaseModel):
    seat: str | None = None
    """The seat to give the character to: the host's (or a co-host's) choice. Left out: the caller's own seat."""


@router.post("/api/campaigns/{campaign_id}/characters/{character_id}/claim")
def claim(request: Request, seat: ActorSeat, campaign_id: str, character_id: str, body: ClaimIn) -> dict:
    """Play a free PC; the host gives any PC to any seat. 409 when another seat plays it. Answers the character as
    a seat reads it (`GET …/characters`)."""
    storage = request.app.state.storage
    try:
        character = seats.claim(storage, character_id, seat, for_seat=body.seat)
    except PlayError as refused:
        raise refusal(refused) from None
    seats_changed(request, campaign_id)
    return player_character_json(character, sheet_context(request, campaign_id), request.app.state.storage)


@router.post("/api/campaigns/{campaign_id}/characters/{character_id}/release")
def release(request: Request, seat: TableSeat, campaign_id: str, character_id: str) -> dict:
    """Let nobody play the character: its own player, or the host, may. Answers the character as a seat reads it."""
    storage = request.app.state.storage
    try:
        character = seats.release(storage, character_id, seat)
    except PlayError as refused:
        raise refusal(refused) from None
    seats_changed(request, campaign_id)
    return player_character_json(character, sheet_context(request, campaign_id), request.app.state.storage)


@router.post("/api/campaigns/{campaign_id}/leave", status_code=204)
def leave(request: Request, seat: TableSeat, campaign_id: str) -> Response:
    """Leave the table: the seat's characters are free, and its cookie is cleared. 409 for the host, who hands the
    role over first."""
    try:
        seats.leave(request.app.state.storage, seat)
    except PlayError as refused:
        raise refusal(refused) from None
    seats_changed(request, campaign_id)
    response = Response(status_code=204)
    response.delete_cookie(SEAT_COOKIE, path="/", httponly=True, samesite="strict")
    return response


@router.post("/api/campaigns/{campaign_id}/seats/{seat_id}/remove")
def remove_seat(request: Request, seat: HostSeat, campaign_id: str, seat_id: str) -> dict:
    """The host, or a co-host, removes the seat from the table, as Leave would (`seats.remove`): its characters are
    free. 404 for a seat not at this table or gone already, 409 for the host's seat and the caller's own, 403 for a
    co-host removing a co-host. The account may come back through the join link; a new invite stops that."""
    storage = request.app.state.storage
    try:
        removed = seats.remove(storage, campaign_id, seat_id, by=seat)
    except PlayError as refused:
        raise refusal(refused) from None
    seats_changed(request, campaign_id)
    return {"seat": seat_json(storage, removed, None)}  # gone: not present, whatever the stream still holds


def keepable_seat(request: Request, principal: Principal, campaign_id: str) -> Seat | None:
    """The seat this browser's old seat token holds at the campaign, when the account may keep it: live, of that
    campaign, of no account, not the owner's, and the account has no seat there."""
    account = principal.account
    token = seat_token(request)
    if account is None or account.owner or token is None:
        return None
    storage = request.app.state.storage
    seat = storage.seats.by_token_hash(token_hash(token))
    if seat is None or seat.campaign_id != campaign_id or seat.left_at is not None:
        return None
    if seat.account_id is not None or seat.owner or storage.seats.for_account(account.id, campaign_id) is not None:
        return None
    return seat


@router.post("/api/campaigns/{campaign_id}/seats/keep")
def keep_seat(request: Request, principal: AccountCaller, campaign_id: str) -> Response:
    """Keep this seat: the seat this browser joined with before accounts becomes the account's, its old seat token
    stops working everywhere, and this browser's cookie of it is cleared. 409 when the account has a seat there, 404 when there is no such seat."""
    storage = request.app.state.storage
    if principal.account.owner:
        raise HTTPException(status_code=409, detail=SEATED_ALREADY)
    if storage.campaigns.get(campaign_id) is not None and storage.seats.for_account(principal.account.id, campaign_id):
        raise HTTPException(status_code=409, detail=SEATED_ALREADY)
    seat = keepable_seat(request, principal, campaign_id)
    if seat is None:
        raise HTTPException(status_code=404, detail=NO_SEAT_TO_KEEP)
    try:
        kept = storage.seats.save(replace(seat, account_id=principal.account.id))
    except ValueError:  # seated meanwhile
        raise HTTPException(status_code=409, detail=SEATED_ALREADY) from None
    seats_changed(request, campaign_id)
    response = JSONResponse(seat_json(storage, kept, present_seats(request, campaign_id)))
    response.delete_cookie(SEAT_COOKIE, path="/", httponly=True, samesite="strict")
    return response


@router.get("/api/me")
def me(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    campaign: Annotated[str | None, Query(max_length=64)] = None,
) -> dict:
    """Who the caller is: the owner, an account, or a seat at one table, with that table's campaign name (a seat may
    not read the campaign itself). With `campaign`, the owner's seat is their owner seat at that table (none at an
    unknown one), which the play screen needs to know its own, and an account's is its live seat there. From this
    machine, `owner_account_exists` says whether the login page should offer to make the first owner account."""
    storage = request.app.state.storage
    seat = principal.seat
    if campaign is not None and storage.campaigns.get(campaign) is not None:
        if principal.owner:
            seat = seats.owner_seat(storage, campaign)
        elif principal.account is not None:
            seat = storage.seats.for_account(principal.account.id, campaign)
    table = storage.campaigns.get(seat.campaign_id) if seat is not None else None
    answer = {
        "principal": {"id": principal.id, "roles": sorted(principal.roles)},
        "account": None if principal.account is None else account_json(principal.account),
        "seat": None
        if seat is None
        else {
            "id": seat.id,
            "campaign_id": seat.campaign_id,
            "campaign_name": table.name if table is not None else "",
            "name": seat.name,
            "language": seat.language,
            "role": seat.role,
            "organiser": seat.organiser,
        },
    }
    keepable = keepable_seat(request, principal, campaign) if campaign is not None else None
    answer["keepable_seat"] = None if keepable is None else {"id": keepable.id, "name": keepable.name}
    if guard.is_this_machine(request):
        answer["owner_account_exists"] = has_owner_account(storage)
    return answer
