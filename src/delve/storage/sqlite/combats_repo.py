"""Fights, as the raw JSON of the `Combat` state machine; at most one live per campaign."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import campaigns, combats


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteCombatRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def live(self, campaign_id: str) -> tuple[str, dict[str, Any]] | None:
        query = select(combats.c.id, combats.c.state).where(
            combats.c.campaign_id == campaign_id, combats.c.phase != "ended"
        )
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else (row.id, row.state)

    def create(self, campaign_id: str, phase: str, raw: dict[str, Any]) -> str:
        id = new_id("cbt")
        now = _now()
        row = {"id": id, "campaign_id": campaign_id, "phase": phase, "state": raw, "created_at": now, "updated_at": now}
        with self._db.begin() as connection:
            if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
                raise KeyError(campaign_id)
            if phase != "ended" and self.live(campaign_id) is not None:
                raise ValueError(f"campaign {campaign_id} already has a live fight")
            try:
                connection.execute(combats.insert().values(row))
            except IntegrityError:
                raise ValueError(f"campaign {campaign_id} already has a live fight") from None
        return id

    def save(self, id: str, phase: str, raw: dict[str, Any]) -> None:
        update = combats.update().where(combats.c.id == id).values(phase=phase, state=raw, updated_at=_now())
        with self._db.begin() as connection:
            if connection.execute(update).rowcount == 0:
                raise KeyError(id)

    def get(self, id: str) -> dict[str, Any] | None:
        with self._db.connect() as connection:
            return connection.execute(select(combats.c.state).where(combats.c.id == id)).scalar()
