"""The seat identity (plan 4 Task 1, spec §11): seat tokens, and the dependencies that give a campaign's routes the
caller's seat at that table.

A seat token is random, sent in the `delve_seat` cookie, and stored only as its SHA-256 hex digest. It gives rights
in its own campaign only, and none once the seat has left. The owner has a seat at every table: their owner seat. An
account (players and tavern Task C3) has its live seat at each table it joined, and none elsewhere.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from starlette.requests import HTTPConnection

from delve.domain.campaigns import Seat
from delve.play import seats
from delve.storage import Storage
from delve.web.auth import NEEDS_LOGIN, SEAT_COOKIE, identify

__all__ = [
    "NO_SEAT",
    "SEAT_COOKIE",
    "ActorSeat",
    "HostSeat",
    "TableSeat",
    "actor_seat",
    "connection_seat",
    "host_seat",
    "new_seat_token",
    "seat_lookup",
    "table_seat",
    "token_hash",
]

ANOTHER_TABLE = "This seat is for another table."
LEFT = "You have left this table."
NO_SEAT = "You have no seat at this table."


def new_seat_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def seat_lookup(storage: Storage) -> Callable[[str], Seat | None]:
    """The identity's lookup: the seat whose token this is, if any."""
    return lambda token: storage.seats.by_token_hash(token_hash(token))


def table_seat(request: Request, campaign_id: str) -> Seat:
    """The caller's seat at the campaign's table: the owner's owner seat, an account's live seat there, or the seat of
    the token when it is of this campaign and hasn't left. 403 otherwise; 404 for the owner or an account at an
    unknown campaign."""
    return connection_seat(request, campaign_id)


def connection_seat(connection: HTTPConnection, campaign_id: str) -> Seat:
    """`table_seat` for any connection, a WebSocket's handshake too (table voice and fixes Task V1.2): the same seat,
    or the same `HTTPException` (401 for nobody known)."""
    principal = identify(connection)
    if principal is None:
        raise HTTPException(status_code=401, detail=NEEDS_LOGIN)
    storage = connection.app.state.storage
    if principal.owner:
        if storage.campaigns.get(campaign_id) is None:
            raise HTTPException(status_code=404, detail="No such campaign.")
        try:
            return seats.owner_seat(storage, campaign_id)
        except KeyError:  # deleted since, before its owner seat was made
            raise HTTPException(status_code=404, detail="No such campaign.") from None
    if principal.account is not None:
        if storage.campaigns.get(campaign_id) is None:
            raise HTTPException(status_code=404, detail="No such campaign.")
        seat = storage.seats.for_account(principal.account.id, campaign_id)
        if seat is None:
            raise HTTPException(status_code=403, detail=NO_SEAT)
        return seat
    if principal.seat is None:
        raise HTTPException(status_code=403, detail=NO_SEAT)
    if principal.seat.campaign_id != campaign_id:
        raise HTTPException(status_code=403, detail=ANOTHER_TABLE)
    if principal.seat.left_at is not None:
        raise HTTPException(status_code=403, detail=LEFT)
    return principal.seat


TableSeat = Annotated[Seat, Depends(table_seat)]


def host_seat(seat: TableSeat) -> Seat:
    """The caller's seat, when it runs the table: the host or a co-host."""
    if seat.role not in seats.TABLE_RIGHTS:
        raise HTTPException(status_code=403, detail=seats.ONLY_THE_HOST)
    return seat


def actor_seat(seat: TableSeat) -> Seat:
    """The caller's seat, when it acts: anyone but an observer."""
    if seat.role == "observer":
        raise HTTPException(status_code=403, detail=seats.OBSERVERS)
    return seat


HostSeat = Annotated[Seat, Depends(host_seat)]
ActorSeat = Annotated[Seat, Depends(actor_seat)]
