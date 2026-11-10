"""Map states, per campaign and map name, as the raw JSON `delve.maps.state.to_json` gives."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert

from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import campaigns, map_states


class SqliteMapStateRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, campaign_id: str, map_name: str) -> dict[str, Any] | None:
        query = select(map_states.c.state).where(
            map_states.c.campaign_id == campaign_id, map_states.c.map_name == map_name
        )
        with self._db.connect() as connection:
            return connection.execute(query).scalar()

    def put(self, campaign_id: str, map_name: str, raw: dict[str, Any]) -> None:
        row = {
            "campaign_id": campaign_id,
            "map_name": map_name,
            "state": raw,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        upsert = insert(map_states).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[map_states.c.campaign_id, map_states.c.map_name],
            set_={"state": upsert.excluded.state, "updated_at": upsert.excluded.updated_at},
        )
        with self._db.begin() as connection:
            if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
                raise KeyError(campaign_id)
            connection.execute(upsert)

    def list(self, campaign_id: str) -> dict[str, dict[str, Any]]:
        query = select(map_states.c.map_name, map_states.c.state).where(map_states.c.campaign_id == campaign_id)
        with self._db.connect() as connection:
            return {name: state for name, state in connection.execute(query.order_by(text("rowid")))}
