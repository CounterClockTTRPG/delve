"""Conversions: a row per job that makes a module from a PDF or a request, or works on a module that exists (its
`target`), with its progress. At most one runs; the others wait `queued`, oldest first, while the queue's switch
(`QUEUE_KEY` in `settings`) isn't paused (thorough conversion, owner addition 2026-10-23)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.domain.conversions import Conversion, ConversionKind, ConversionMode, ConversionStatus
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import conversions, settings

QUEUE_KEY = "conversion-queue"
"""The `settings` row of the conversion queue's switch, `{"paused": bool}`; not one of the app's settings."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _from(row) -> Conversion:
    return Conversion(**{**row._mapping, "warnings": list(row.warnings), "closed": list(row.closed or [])})


class SqliteConversionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        kind: ConversionKind,
        title: str,
        mode: ConversionMode,
        *,
        target: dict[str, Any] | None = None,
        status: ConversionStatus = "running",
        comments: str = "",
    ) -> Conversion:
        if status not in ("running", "queued"):
            raise ValueError(f"A conversion starts running or queued, not {status!r}.")
        now = _now()
        conversion = Conversion(
            new_id("cnv"),
            kind,
            title,
            mode,
            status=status,
            created_at=now,
            updated_at=now,
            target=target,
            comments=comments,
        )
        try:
            with self._db.begin() as connection:
                connection.execute(conversions.insert().values(asdict(conversion)))
        except IntegrityError:
            raise ValueError("a conversion is already running") from None
        return conversion

    def get(self, id: str) -> Conversion | None:
        with self._db.connect() as connection:
            row = connection.execute(select(conversions).where(conversions.c.id == id)).first()
        return None if row is None else _from(row)

    def list(self, limit: int = 20) -> list[Conversion]:
        query = select(conversions).order_by(conversions.c.created_at.desc(), text("rowid DESC")).limit(limit)
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def for_module(self, module_id: str) -> list[Conversion]:
        named = or_(
            conversions.c.module_id == module_id,
            func.json_extract(conversions.c.target, "$.module_id") == module_id,
        )
        query = select(conversions).where(named).order_by(conversions.c.created_at.desc(), text("rowid DESC"))
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def running(self) -> Conversion | None:
        with self._db.connect() as connection:
            row = connection.execute(select(conversions).where(conversions.c.status == "running")).first()
        return None if row is None else _from(row)

    def paused(self) -> list[Conversion]:
        query = select(conversions).where(conversions.c.status == "paused")
        query = query.order_by(conversions.c.created_at, text("rowid"))
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def queued(self) -> list[Conversion]:
        query = select(conversions).where(conversions.c.status == "queued")
        query = query.order_by(conversions.c.created_at, text("rowid"))
        with self._db.connect() as connection:
            return [_from(row) for row in connection.execute(query)]

    def queue_paused(self) -> bool:
        with self._db.connect() as connection:
            value = connection.execute(select(settings.c.value).where(settings.c.key == QUEUE_KEY)).scalar()
        return isinstance(value, dict) and value.get("paused") is True

    def set_queue_paused(self, paused: bool) -> None:
        row = {"key": QUEUE_KEY, "value": {"paused": paused}, "updated_at": _now()}
        upsert = insert(settings).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[settings.c.key],
            set_={"value": upsert.excluded.value, "updated_at": upsert.excluded.updated_at},
        )
        with self._db.begin() as connection:
            connection.execute(upsert)

    def save(self, conversion: Conversion) -> Conversion:
        saved = replace(conversion, updated_at=_now())
        # `closed` is the organisers', written only by `set_closed`: a job saving its progress never reopens it.
        values = {k: v for k, v in asdict(saved).items() if k not in ("id", "created_at", "closed")}
        with self._db.begin() as connection:
            if (
                connection.execute(conversions.update().where(conversions.c.id == saved.id).values(values)).rowcount
                == 0
            ):
                raise KeyError(saved.id)
            closed = connection.execute(select(conversions.c.closed).where(conversions.c.id == saved.id)).scalar()
        return replace(saved, closed=list(closed or []))

    def set_closed(self, id: str, closed: Sequence[str]) -> Conversion:
        keys = list(dict.fromkeys(closed))
        with self._db.begin() as connection:
            if connection.execute(conversions.update().where(conversions.c.id == id).values(closed=keys)).rowcount == 0:
                raise KeyError(id)
            row = connection.execute(select(conversions).where(conversions.c.id == id)).first()
        return _from(row)
