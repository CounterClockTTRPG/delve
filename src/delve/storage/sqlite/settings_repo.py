"""Preferences (stored as `settings`): the whole dict, stored as JSON in one row."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import settings

APP_KEY = "app"


class SqliteSettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def load(self) -> dict[str, Any]:
        with self._db.connect() as connection:
            value = connection.execute(select(settings.c.value).where(settings.c.key == APP_KEY)).scalar()
        return value if isinstance(value, dict) else {}

    def save(self, raw: dict[str, Any]) -> None:
        row = {"key": APP_KEY, "value": raw, "updated_at": datetime.now(UTC).isoformat()}
        upsert = insert(settings).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[settings.c.key],
            set_={"value": upsert.excluded.value, "updated_at": upsert.excluded.updated_at},
        )
        with self._db.begin() as connection:
            connection.execute(upsert)

    def update(self, patch: dict[str, Any], *, within: str | None = None) -> dict[str, Any]:
        with self._db.transaction():
            stored = self.load()
            if within is None:
                updated = {**stored, **patch}
            else:
                kept = stored.get(within)
                updated = {**stored, within: {**(kept if isinstance(kept, dict) else {}), **patch}}
            self.save(updated)
        return updated
