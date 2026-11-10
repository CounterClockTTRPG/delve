"""A fight's rounds as the initiative timeline shows them (table voice and fixes Task 0): one row per fight and round,
put when its initiative is rolled and again when it is resolved, and released to the table once."""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from delve.domain.campaigns import CombatRound
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import combat_rounds, combats


def _from(row) -> CombatRound:
    return CombatRound(**{**row._mapping, "slots": tuple(row.slots)})


class SqliteCombatRoundRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def put(self, row: CombatRound) -> CombatRound:
        values = {**asdict(row), "slots": list(row.slots)}
        values.pop("released_at")
        upsert = insert(combat_rounds).values(values)
        upsert = upsert.on_conflict_do_update(
            index_elements=[combat_rounds.c.combat_id, combat_rounds.c.round],
            set_={k: upsert.excluded[k] for k in values if k not in ("combat_id", "round")},
        )
        with self._db.begin() as connection:
            if connection.execute(select(combats.c.id).where(combats.c.id == row.combat_id)).first() is None:
                raise KeyError(row.combat_id)
            connection.execute(upsert)
            stored = connection.execute(self._one(row.combat_id, row.round)).first()
        return _from(stored)

    @staticmethod
    def _one(combat_id: str, round: int):
        return select(combat_rounds).where(combat_rounds.c.combat_id == combat_id, combat_rounds.c.round == round)

    def get(self, combat_id: str, round: int) -> CombatRound | None:
        with self._db.connect() as connection:
            row = connection.execute(self._one(combat_id, round)).first()
        return None if row is None else _from(row)

    def latest(self, combat_id: str) -> CombatRound | None:
        query = (
            select(combat_rounds)
            .where(combat_rounds.c.combat_id == combat_id)
            .order_by(combat_rounds.c.round.desc())
            .limit(1)
        )
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else _from(row)

    def list(self, combat_id: str) -> list[CombatRound]:
        query = select(combat_rounds).where(combat_rounds.c.combat_id == combat_id).order_by(combat_rounds.c.round)
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def release(self, combat_id: str, round: int, at: str) -> bool:
        update = (
            combat_rounds.update()
            .where(
                combat_rounds.c.combat_id == combat_id,
                combat_rounds.c.round == round,
                combat_rounds.c.released_at.is_(None),
            )
            .values(released_at=at)
        )
        with self._db.begin() as connection:
            return connection.execute(update).rowcount == 1

    def unreleased(self, campaign_id: str) -> list[CombatRound]:
        query = (
            select(combat_rounds)
            .where(
                combat_rounds.c.campaign_id == campaign_id,
                combat_rounds.c.resolved_at.is_not(None),
                combat_rounds.c.released_at.is_(None),
            )
            .order_by(combat_rounds.c.resolved_at, combat_rounds.c.round)
        )
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]
