"""Histories and carries: a campaign's history, one row with both texts, gone with its campaign (`ON DELETE
CASCADE`); and the carries, each kept when its old campaign is deleted (`ON DELETE SET NULL`) and gone with its new
one."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import Connection, select
from sqlalchemy.exc import IntegrityError

from delve.domain.histories import Carry, History
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.play_repos import _now, _require_campaign
from delve.storage.sqlite.tables import campaign_carries, campaign_histories


def _history(row: Any) -> History:
    return History.from_dict({**row._mapping, "edited": bool(row.edited)})


def _carry(row: Any) -> Carry:
    return Carry.from_dict(dict(row._mapping))


class SqliteHistoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _get(self, connection: Connection, campaign_id: str) -> History | None:
        query = select(campaign_histories).where(campaign_histories.c.campaign_id == campaign_id)
        row = connection.execute(query).first()
        return None if row is None else _history(row)

    def get(self, campaign_id: str) -> History | None:
        with self._db.connect() as connection:
            return self._get(connection, campaign_id)

    def put(self, history: History) -> History:
        now = _now()
        with self._db.begin() as connection:
            _require_campaign(connection, history.campaign_id)
            before = self._get(connection, history.campaign_id)
            made = replace(history, created_at=now if before is None else before.created_at, updated_at=now)
            if before is None:
                connection.execute(campaign_histories.insert().values(made.to_dict()))
            else:
                where = campaign_histories.c.campaign_id == history.campaign_id
                connection.execute(campaign_histories.update().where(where).values(made.to_dict()))
            stored = self._get(connection, history.campaign_id)
        assert stored is not None
        return stored

    def writing(self) -> list[History]:
        query = select(campaign_histories).where(campaign_histories.c.status == "writing")
        with self._db.connect() as connection:
            return [_history(row) for row in connection.execute(query.order_by(campaign_histories.c.created_at))]


class SqliteCarryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _list(self, *where: Any) -> list[Carry]:
        query = select(campaign_carries).where(*where).order_by(campaign_carries.c.id)
        with self._db.connect() as connection:
            return [_carry(row) for row in connection.execute(query)]

    def add(self, from_campaign_id: str, to_campaign_id: str, character_ids: Sequence[str]) -> Carry:
        values = {
            "from_campaign_id": from_campaign_id,
            "to_campaign_id": to_campaign_id,
            "character_ids": list(character_ids),
            "carried_at": _now(),
        }
        try:
            with self._db.begin() as connection:
                _require_campaign(connection, from_campaign_id)
                _require_campaign(connection, to_campaign_id)
                id = connection.execute(campaign_carries.insert().values(values)).inserted_primary_key[0]
                row = connection.execute(select(campaign_carries).where(campaign_carries.c.id == id)).first()
        except IntegrityError:
            raise ValueError("a party was already carried into that campaign") from None
        return _carry(row)

    def origin(self, to_campaign_id: str) -> Carry | None:
        found = self._list(campaign_carries.c.to_campaign_id == to_campaign_id)
        return found[0] if found else None

    def onward(self, from_campaign_id: str) -> list[Carry]:
        return self._list(campaign_carries.c.from_campaign_id == from_campaign_id)

    def all(self) -> list[Carry]:
        return self._list()
