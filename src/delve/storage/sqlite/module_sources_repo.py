"""Module sources: the working copy's in `module_sources`, and each revision's in `module_revisions.source`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, func, select, update
from sqlalchemy.dialects.sqlite import insert

from delve.modules.source import ModuleSource
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import module_revisions, module_sources


def working_source(connection: Connection, module_id: str) -> dict[str, Any] | None:
    return connection.execute(
        select(module_sources.c.source).where(module_sources.c.module_id == module_id)
    ).scalar()


def revision_source(connection: Connection, module_id: str, number: int) -> dict[str, Any] | None:
    return connection.execute(
        select(module_revisions.c.source).where(
            module_revisions.c.module_id == module_id, module_revisions.c.number == number
        )
    ).scalar()


class SqliteModuleSourceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, module_id: str) -> ModuleSource | None:
        with self._db.connect() as connection:
            raw = working_source(connection, module_id)
        return None if raw is None else ModuleSource.from_json(raw)

    def updated_at(self, module_id: str) -> str | None:
        with self._db.connect() as connection:
            return connection.execute(
                select(module_sources.c.updated_at).where(module_sources.c.module_id == module_id)
            ).scalar_one_or_none()

    def put(self, module_id: str, source: ModuleSource) -> None:
        now = datetime.now(UTC).isoformat()
        raw = source.to_json()
        with self._db.begin() as connection:
            upsert = insert(module_sources).values(module_id=module_id, source=raw, updated_at=now)
            connection.execute(
                upsert.on_conflict_do_update(
                    index_elements=[module_sources.c.module_id], set_={"source": raw, "updated_at": now}
                )
            )

    def revision(self, module_id: str, number: int) -> ModuleSource | None:
        with self._db.connect() as connection:
            raw = revision_source(connection, module_id, number)
        return None if raw is None else ModuleSource.from_json(raw)

    def pin_legacy(self, module_id: str, source: ModuleSource) -> None:
        # A JSON column holds SQL NULL, or JSON null when a None was written: json_type tells both.
        no_source = func.coalesce(func.json_type(module_revisions.c.source), "null") == "null"
        with self._db.begin() as connection:
            connection.execute(
                update(module_revisions)
                .where(module_revisions.c.module_id == module_id, no_source)
                .values(source=source.to_json())
            )
