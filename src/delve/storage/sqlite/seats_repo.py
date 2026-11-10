"""The seats at a campaign's table, and the seat that plays each character."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.domain.campaigns import Seat, SeatRole
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import campaigns, characters, seats

COLUMNS = (
    seats.c.id,
    seats.c.campaign_id,
    seats.c.name,
    seats.c.language,
    seats.c.role,
    seats.c.organiser,
    seats.c.owner,
    seats.c.joined_at,
    seats.c.left_at,
    seats.c.account_id,
)


def _from(row) -> Seat:
    return Seat(**{**row._mapping, "organiser": bool(row.organiser), "owner": bool(row.owner)})


class SqliteSeatRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        campaign_id: str,
        name: str,
        language: str,
        role: SeatRole,
        *,
        organiser: bool = False,
        owner: bool = False,
        token_hash: str | None = None,
        account_id: str | None = None,
    ) -> Seat:
        seat = Seat(
            new_id("seat"),
            campaign_id,
            name,
            language,
            role,
            organiser,
            owner,
            datetime.now(UTC).isoformat(),
            None,
            account_id,
        )
        try:
            with self._db.begin() as connection:
                if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
                    raise KeyError(campaign_id)
                connection.execute(seats.insert().values(**asdict(seat), token_hash=token_hash))
        except IntegrityError:
            raise ValueError(
                "the campaign has an owner's seat, the token is in use, or the account has a seat there"
            ) from None
        return seat

    def get(self, id: str) -> Seat | None:
        return self._one(seats.c.id == id)

    def by_token_hash(self, token_hash: str) -> Seat | None:
        return self._one(seats.c.token_hash == token_hash)

    def owner_seat(self, campaign_id: str) -> Seat | None:
        return self._one(seats.c.campaign_id == campaign_id, seats.c.owner.is_(True))

    def for_account(self, account_id: str, campaign_id: str) -> Seat | None:
        return self._one(
            seats.c.account_id == account_id, seats.c.campaign_id == campaign_id, seats.c.left_at.is_(None)
        )

    def of_account(self, account_id: str) -> list[Seat]:
        live = (seats.c.account_id == account_id, seats.c.left_at.is_(None))
        query = select(*COLUMNS).where(*live).order_by(text("rowid"))
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def _one(self, *where) -> Seat | None:
        with self._db.connect() as connection:
            row = connection.execute(select(*COLUMNS).where(*where)).first()
        return None if row is None else _from(row)

    def list(self, campaign_id: str) -> list[Seat]:
        query = select(*COLUMNS).where(seats.c.campaign_id == campaign_id).order_by(text("rowid"))
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def by_campaign(self) -> dict[str, list[Seat]]:
        query = select(*COLUMNS).order_by(text("rowid"))
        found: dict[str, list[Seat]] = {}
        with self._db.connect() as connection:
            for row in connection.execute(query):
                seat = _from(row)
                found.setdefault(seat.campaign_id, []).append(seat)
        return found

    def save(self, seat: Seat) -> Seat:
        values = {
            "name": seat.name,
            "language": seat.language,
            "role": seat.role,
            "organiser": seat.organiser,
            "joined_at": seat.joined_at,
            "left_at": seat.left_at,
            "account_id": seat.account_id,
        }
        if seat.account_id is not None:
            values["token_hash"] = None  # an account's seat is reached by logging in, never by a token
        try:
            with self._db.begin() as connection:
                if connection.execute(update(seats).where(seats.c.id == seat.id).values(values)).rowcount == 0:
                    raise KeyError(seat.id)
        except IntegrityError:
            raise ValueError("the account has a live seat at the campaign") from None
        return seat

    def set_controller(self, character_id: str, seat_id: str | None) -> None:
        with self._db.begin() as connection:
            campaign_id = connection.execute(
                select(characters.c.campaign_id).where(characters.c.id == character_id)
            ).scalar()
            if campaign_id is None:
                raise KeyError(character_id)
            if seat_id is not None:
                seat_campaign = connection.execute(select(seats.c.campaign_id).where(seats.c.id == seat_id)).scalar()
                if seat_campaign != campaign_id:
                    raise KeyError(seat_id)
            connection.execute(update(characters).where(characters.c.id == character_id).values(controller_id=seat_id))

    def controlled(self, seat_id: str) -> list[str]:
        query = select(characters.c.id).where(characters.c.controller_id == seat_id).order_by(text("rowid"))
        with self._db.connect() as connection:
            return list(connection.execute(query).scalars())
