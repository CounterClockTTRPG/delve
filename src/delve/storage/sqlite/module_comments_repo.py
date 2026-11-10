"""Fix-it comments on a module (table voice and fixes Task 0), oldest first, with their status and the job that acts
on them; they go with their module."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from delve.domain import new_id
from delve.domain.modules import COMMENT_STATUSES, CommentStatus, ModuleComment
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import module_comments, modules


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _from(row) -> ModuleComment:
    return ModuleComment(**row._mapping)


class SqliteModuleCommentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, module_id: str, text: str, *, anchor: dict[str, Any] | None = None, author: str = ""
    ) -> ModuleComment:
        now = _now()
        comment = ModuleComment(
            new_id("mcm"), module_id, text, anchor=anchor, author=author, created_at=now, updated_at=now
        )
        with self._db.begin() as connection:
            if connection.execute(select(modules.c.id).where(modules.c.id == module_id)).first() is None:
                raise KeyError(module_id)
            connection.execute(module_comments.insert().values(asdict(comment)))
        return comment

    def get(self, id: str) -> ModuleComment | None:
        with self._db.connect() as connection:
            row = connection.execute(select(module_comments).where(module_comments.c.id == id)).first()
        return None if row is None else _from(row)

    def _list(self, *where) -> list[ModuleComment]:
        query = select(module_comments).where(*where).order_by(module_comments.c.created_at, text("rowid"))
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def list(self, module_id: str) -> list[ModuleComment]:
        return self._list(module_comments.c.module_id == module_id)

    def with_status(self, module_id: str, *statuses: CommentStatus) -> list[ModuleComment]:
        return self._list(module_comments.c.module_id == module_id, module_comments.c.status.in_(statuses))

    def for_conversion(self, conversion_id: str) -> list[ModuleComment]:
        return self._list(module_comments.c.conversion_id == conversion_id)

    def save(self, comment: ModuleComment) -> ModuleComment:
        if comment.status not in COMMENT_STATUSES:
            raise ValueError(f"A comment's status is one of {', '.join(COMMENT_STATUSES)}, not {comment.status!r}.")
        saved = replace(comment, updated_at=_now())
        values = {k: v for k, v in asdict(saved).items() if k not in ("id", "module_id", "created_at")}
        update = module_comments.update().where(
            module_comments.c.id == saved.id, module_comments.c.module_id == saved.module_id
        )
        with self._db.begin() as connection:
            if connection.execute(update.values(values)).rowcount == 0:
                raise KeyError(saved.id)
        return saved
