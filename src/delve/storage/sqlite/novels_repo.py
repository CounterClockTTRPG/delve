"""Novels: one row per novel of a campaign or a module, its chapters as JSON, saved as they are written. A novel goes
with its source (`ON DELETE CASCADE`)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import Connection, select, text

from delve.domain import new_id
from delve.domain.novels import Novel
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.play_repos import _now, _require_campaign
from delve.storage.sqlite.tables import modules, novels

_NEWEST_FIRST = (novels.c.created_at.desc(), text("rowid DESC"))


def _novel(row: Any) -> Novel:
    return Novel.from_dict(dict(row._mapping))


def _require_source(connection: Connection, novel: Novel) -> None:
    if (novel.campaign_id is None) == (novel.module_id is None):
        raise ValueError("a novel is of a campaign or of a module, exactly one")
    if novel.campaign_id is not None:
        _require_campaign(connection, novel.campaign_id)
    elif connection.execute(select(modules.c.id).where(modules.c.id == novel.module_id)).first() is None:
        raise KeyError(novel.module_id)


class SqliteNovelRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def _get(self, connection: Connection, id: str) -> Novel | None:
        row = connection.execute(select(novels).where(novels.c.id == id)).first()
        return None if row is None else _novel(row)

    def _list(self, *where: Any) -> list[Novel]:
        with self._db.connect() as connection:
            return [_novel(row) for row in connection.execute(select(novels).where(*where).order_by(*_NEWEST_FIRST))]

    def create(self, novel: Novel) -> Novel:
        now = _now()
        made = replace(novel, id=novel.id or new_id("nov"), created_at=now, updated_at=now)
        with self._db.begin() as connection:
            _require_source(connection, made)
            connection.execute(novels.insert().values(made.to_dict()))
        return made

    def get(self, id: str) -> Novel | None:
        with self._db.connect() as connection:
            return self._get(connection, id)

    def save(self, novel: Novel) -> Novel:
        values = {k: v for k, v in novel.to_dict().items() if k not in ("id", "created_at")}
        with self._db.begin() as connection:
            _require_source(connection, novel)
            query = novels.update().where(novels.c.id == novel.id).values({**values, "updated_at": _now()})
            if connection.execute(query).rowcount == 0:
                raise KeyError(novel.id)
            stored = self._get(connection, novel.id)
        assert stored is not None
        return stored

    def for_campaign(self, campaign_id: str) -> list[Novel]:
        return self._list(novels.c.campaign_id == campaign_id)

    def for_module(self, module_id: str) -> list[Novel]:
        return self._list(novels.c.module_id == module_id)

    def delete(self, id: str) -> bool:
        with self._db.begin() as connection:
            return connection.execute(novels.delete().where(novels.c.id == id)).rowcount > 0

    def writing(self) -> list[Novel]:
        return self._list(novels.c.status == "writing")
