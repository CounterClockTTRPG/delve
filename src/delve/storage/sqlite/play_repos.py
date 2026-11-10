"""The campaign state, the dice log and the event log."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, exists, func, literal_column, select, text
from sqlalchemy.dialects.sqlite import insert

from delve.dice import Roll, RollKey
from delve.domain.campaigns import CampaignState, Event
from delve.storage.sqlite.db import Database, like_pattern
from delve.storage.sqlite.tables import campaign_state, campaigns, events, rolls


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require_campaign(connection: Connection, campaign_id: str) -> None:
    if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
        raise KeyError(campaign_id)


def _campaign_exists(connection: Connection, campaign_id: str) -> bool:
    return connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is not None


class SqliteCampaignStateRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, campaign_id: str) -> CampaignState | None:
        with self._db.connect() as connection:
            row = connection.execute(select(campaign_state).where(campaign_state.c.campaign_id == campaign_id)).first()
            if row is None:
                return CampaignState(campaign_id) if _campaign_exists(connection, campaign_id) else None
        raw = {k: getattr(row, k) for k in ("day", "hour", "minute", "session", "coin", "loot")}
        raw |= {k: getattr(row, k) for k in ("start_date", "weather", "world", "journey") if getattr(row, k) is not None}
        return CampaignState.from_dict({"campaign_id": campaign_id, **raw})

    def put(self, state: CampaignState) -> None:
        row = {**state.to_dict(), "updated_at": _now()}
        upsert = insert(campaign_state).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[campaign_state.c.campaign_id],
            set_={k: getattr(upsert.excluded, k) for k in row if k != "campaign_id"},
        )
        with self._db.begin() as connection:
            _require_campaign(connection, state.campaign_id)
            connection.execute(upsert)


def _key(key: RollKey) -> str:
    return json.dumps([key.beat, key.actor, key.purpose, key.target, key.combat_round])


def _roll_from(row) -> Roll:
    return Roll(
        id=row.id,
        key=RollKey(
            beat=row.beat, actor=row.actor, purpose=row.purpose, target=row.target, combat_round=row.combat_round
        ),
        notation=row.notation,
        faces=tuple(row.faces),
        kept=tuple(row.kept),
        modifier=row.modifier,
        total=row.total,
        at=row.at,
    )


class SqliteRollRepository:
    """The dice log; implements `delve.dice.RollLog`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def find(self, campaign_id: str, key: RollKey) -> Roll | None:
        query = select(rolls).where(rolls.c.campaign_id == campaign_id, rolls.c.key == _key(key))
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else _roll_from(row)

    def record(self, campaign_id: str, roll: Roll) -> None:
        row = {
            "id": roll.id,
            "campaign_id": campaign_id,
            "key": _key(roll.key),
            "beat": roll.key.beat,
            "actor": roll.key.actor,
            "purpose": roll.key.purpose,
            "target": roll.key.target,
            "combat_round": roll.key.combat_round,
            "notation": roll.notation,
            "faces": list(roll.faces),
            "kept": list(roll.kept),
            "modifier": roll.modifier,
            "total": roll.total,
            "at": roll.at,
        }
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            connection.execute(rolls.insert().values(row))

    def list(self, campaign_id: str, beat: str | None = None) -> list[Roll]:
        """The campaign's rolls, oldest first; only one beat's with `beat`."""
        query = select(rolls).where(rolls.c.campaign_id == campaign_id)
        if beat is not None:
            query = query.where(rolls.c.beat == beat)
        with self._db.connect() as connection:
            return [_roll_from(row) for row in connection.execute(query.order_by(text("rowid")))]

    def get_many(self, campaign_id: str, ids: Iterable[str]) -> dict[str, Roll]:
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return {}
        query = select(rolls).where(rolls.c.campaign_id == campaign_id, rolls.c.id.in_(wanted))
        with self._db.connect() as connection:
            return {row.id: _roll_from(row) for row in connection.execute(query)}


def _event_from(row) -> Event:
    return Event(
        id=row.id,
        campaign_id=row.campaign_id,
        session=row.session,
        beat=row.beat,
        type=row.type,
        data=row.data,
        at=row.at,
    )


class SqliteEventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, campaign_id: str, type: str, data: dict[str, Any], *, session: int, beat: str) -> Event:
        row = {"campaign_id": campaign_id, "session": session, "beat": beat, "type": type, "data": data, "at": _now()}
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            id = connection.execute(events.insert().values(row)).inserted_primary_key[0]
        return Event(id=id, **row)

    def list(
        self,
        campaign_id: str,
        *,
        after: int | None = None,
        types: Iterable[str] | None = None,
        limit: int | None = None,
        beat: str | None = None,
    ) -> list[Event]:
        query = select(events).where(events.c.campaign_id == campaign_id)
        if after is not None:
            query = query.where(events.c.id > after)
        if beat is not None:
            query = query.where(events.c.beat == beat)
        if types is not None:
            query = query.where(events.c.type.in_(list(types)))
        with self._db.connect() as connection:
            return [_event_from(row) for row in connection.execute(query.order_by(events.c.id).limit(limit))]

    def recent(self, campaign_id: str, n: int) -> list[Event]:
        query = select(events).where(events.c.campaign_id == campaign_id).order_by(events.c.id.desc()).limit(n)
        with self._db.connect() as connection:
            return [_event_from(row) for row in reversed(connection.execute(query).all())]

    def search(self, campaign_id: str, words: str, limit: int) -> list[Event]:
        values = func.json_each(events.c.data).table_valued("value", "type")
        holds = exists(
            select(literal_column("1"))
            .select_from(values)
            .where(values.c.type == "text", values.c.value.like(like_pattern(words), escape="\\"))
        )
        query = select(events).where(events.c.campaign_id == campaign_id, holds)
        with self._db.connect() as connection:
            return [_event_from(row) for row in connection.execute(query.order_by(events.c.id.desc()).limit(limit))]
