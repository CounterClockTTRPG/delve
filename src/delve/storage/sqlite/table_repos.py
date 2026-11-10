"""Beats, the story, the DM log, the DM's resumable conversation per campaign, the campaign's play settings, and the
table's session state."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError

from delve.domain import new_id
from delve.domain.campaigns import (
    Beat,
    DmLogEntry,
    StoryEntry,
    StoryKind,
    TableSession,
    Translation,
    TranslationStatus,
)
from delve.storage.sqlite.db import Database, like_pattern
from delve.storage.sqlite.play_repos import _require_campaign
from delve.storage.sqlite.tables import beats, dm_log, dm_sessions, play_settings, story, table_sessions, translations

CURRENT = ("open", "running")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _beat_from(row) -> Beat:
    return Beat(
        id=row.id,
        campaign_id=row.campaign_id,
        number=row.number,
        status=row.status,
        submissions=tuple(row.submissions),
        opened_at=row.opened_at,
        closed_at=row.closed_at,
    )


class SqliteBeatRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def open(self, campaign_id: str, submissions: list[dict[str, Any]], status: str = "open") -> Beat:
        row = {
            "id": new_id("beat"),
            "campaign_id": campaign_id,
            "status": status,
            "submissions": list(submissions),
            "opened_at": _now(),
            "closed_at": None,
        }
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            if self.current(campaign_id) is not None:
                raise ValueError(f"campaign {campaign_id} already has a current beat")
            last = connection.execute(select(func.max(beats.c.number)).where(beats.c.campaign_id == campaign_id))
            row["number"] = (last.scalar() or 0) + 1
            try:
                connection.execute(beats.insert().values(row))
            except IntegrityError:
                raise ValueError(f"campaign {campaign_id} already has a current beat") from None
        return Beat(**{**row, "submissions": tuple(row["submissions"])})

    def get(self, id: str) -> Beat | None:
        with self._db.connect() as connection:
            row = connection.execute(select(beats).where(beats.c.id == id)).first()
        return None if row is None else _beat_from(row)

    def current(self, campaign_id: str) -> Beat | None:
        query = select(beats).where(beats.c.campaign_id == campaign_id, beats.c.status.in_(CURRENT))
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else _beat_from(row)

    def latest(self, campaign_id: str) -> Beat | None:
        query = select(beats).where(beats.c.campaign_id == campaign_id).order_by(beats.c.number.desc()).limit(1)
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else _beat_from(row)

    def save(self, beat: Beat) -> Beat:
        values = {
            "status": beat.status,
            "submissions": list(beat.submissions),
            "opened_at": beat.opened_at,
            "closed_at": beat.closed_at,
        }
        with self._db.begin() as connection:
            if connection.execute(beats.update().where(beats.c.id == beat.id).values(values)).rowcount == 0:
                raise KeyError(beat.id)
        return beat


def _entry_from(row) -> StoryEntry:
    return StoryEntry(
        id=row.id,
        campaign_id=row.campaign_id,
        beat_id=row.beat_id,
        seq=row.seq,
        kind=row.kind,
        payload=row.payload,
        at=row.at,
        audience=row.audience,
    )


class SqliteStoryRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(
        self,
        campaign_id: str,
        beat_id: str | None,
        kind: StoryKind,
        payload: dict[str, Any],
        audience: dict[str, list[str]] | None = None,
    ) -> StoryEntry:
        return self.put(StoryEntry(new_id("sty"), campaign_id, beat_id, 0, kind, payload, audience=audience))

    def put(self, entry: StoryEntry) -> StoryEntry:
        with self._db.begin() as connection:
            existing = connection.execute(select(story).where(story.c.id == entry.id)).first()
            if existing is not None:
                connection.execute(story.update().where(story.c.id == entry.id).values(payload=entry.payload))
                return replace(_entry_from(existing), payload=entry.payload)
            _require_campaign(connection, entry.campaign_id)
            last = connection.execute(select(func.max(story.c.seq)).where(story.c.campaign_id == entry.campaign_id))
            row = {
                "id": entry.id,
                "campaign_id": entry.campaign_id,
                "beat_id": entry.beat_id,
                "seq": (last.scalar() or 0) + 1,
                "kind": entry.kind,
                "payload": entry.payload,
                "at": _now(),
                "audience": entry.audience,
            }
            connection.execute(story.insert().values(row))
        return StoryEntry(**row)

    def get(self, id: str) -> StoryEntry | None:
        with self._db.connect() as connection:
            row = connection.execute(select(story).where(story.c.id == id)).first()
        return _entry_from(row) if row is not None else None

    def list(
        self,
        campaign_id: str,
        *,
        before_seq: int | None = None,
        limit: int | None = None,
        kind: StoryKind | None = None,
    ) -> list[StoryEntry]:
        query = select(story).where(story.c.campaign_id == campaign_id)
        if kind is not None:
            query = query.where(story.c.kind == kind)
        if before_seq is not None:
            query = query.where(story.c.seq < before_seq)
        with self._db.connect() as connection:
            rows = connection.execute(query.order_by(story.c.seq.desc()).limit(limit)).all()
        return [_entry_from(row) for row in reversed(rows)]

    def search(self, campaign_id: str, words: str, limit: int) -> list[StoryEntry]:
        said = func.json_extract(story.c.payload, "$.text")
        query = select(story).where(
            story.c.campaign_id == campaign_id,
            func.json_type(story.c.payload, "$.text") == "text",
            said.like(like_pattern(words), escape="\\"),
        )
        with self._db.connect() as connection:
            return [_entry_from(row) for row in connection.execute(query.order_by(story.c.seq.desc()).limit(limit))]


class SqliteTranslationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def put(
        self, entry_id: str, language: str, text: str, status: TranslationStatus, *, answer: str | None = None
    ) -> Translation:
        row = {
            "entry_id": entry_id,
            "language": language,
            "text": text,
            "status": status,
            "updated_at": _now(),
            "answer": answer,
        }
        upsert = insert(translations).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[translations.c.entry_id, translations.c.language],
            set_={key: getattr(upsert.excluded, key) for key in ("text", "status", "updated_at", "answer")},
        )
        with self._db.begin() as connection:
            connection.execute(upsert)
        return Translation(**row)

    def for_entries(self, entry_ids: Iterable[str], language: str) -> dict[str, Translation]:
        ids = list(entry_ids)
        if not ids:
            return {}
        query = select(translations).where(translations.c.entry_id.in_(ids), translations.c.language == language)
        with self._db.connect() as connection:
            rows = connection.execute(query).all()
        return {
            row.entry_id: Translation(row.entry_id, row.language, row.text, row.status, row.updated_at, row.answer)
            for row in rows
        }

    def fail_unfinished(self) -> int:
        update = translations.update().where(translations.c.status == "translating")
        with self._db.begin() as connection:
            return connection.execute(update.values(status="failed", updated_at=_now())).rowcount


class SqliteDmLogRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def append(self, campaign_id: str, beat_id: str | None, raw: dict[str, Any]) -> DmLogEntry:
        row = {"campaign_id": campaign_id, "beat_id": beat_id, "raw": raw, "at": _now()}
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            connection.execute(dm_log.insert().values(row))
        return DmLogEntry(campaign_id, beat_id, raw, row["at"])

    def list(self, campaign_id: str, beat_id: str | None = None) -> list[DmLogEntry]:
        query = select(dm_log).where(dm_log.c.campaign_id == campaign_id)
        if beat_id is not None:
            query = query.where(dm_log.c.beat_id == beat_id)
        with self._db.connect() as connection:
            rows = connection.execute(query.order_by(dm_log.c.id)).all()
        return [DmLogEntry(row.campaign_id, row.beat_id, row.raw, row.at) for row in rows]

    def costs(self, campaign_id: str) -> list[dict[str, Any]]:
        """Summed in SQL (DEL-172): the campaign page read the whole log to sum it, 38 KB a beat."""
        kind = func.json_extract(dm_log.c.raw, "$.type")

        def number(path: str) -> Any:
            value = func.json_extract(dm_log.c.raw, path)
            return case((func.typeof(value).in_(("integer", "real")), value), else_=None)

        is_ask = kind == "ask"
        usage = kind == "usage"
        query = (
            select(
                func.min(dm_log.c.id).label("first"),
                # SQLite answers a bare column of an aggregate query with min() from the row of that minimum.
                dm_log.c.at,
                func.max(is_ask).label("ask"),
                func.coalesce(dm_log.c.beat_id, "").label("beat"),
                func.sum(case((kind == "tool_call", 1), else_=0)).label("tools"),
                func.sum(
                    case((usage, func.coalesce(number("$.input_tokens"), 0)),
                         (is_ask, func.coalesce(number("$.usage.input_tokens"), 0)), else_=0)
                ).label("input"),
                func.sum(
                    case((usage, func.coalesce(number("$.output_tokens"), 0)),
                         (is_ask, func.coalesce(number("$.usage.output_tokens"), 0)), else_=0)
                ).label("output"),
                func.sum(case((usage, number("$.cost_usd")), (is_ask, number("$.usage.cost_usd")), else_=None)).label(
                    "cost"
                ),
            )
            .where(dm_log.c.campaign_id == campaign_id)
            .group_by(case((is_ask, func.printf("ask-%d", dm_log.c.id)), else_=func.coalesce(dm_log.c.beat_id, "")))
            .order_by("first")
        )
        with self._db.connect() as connection:
            rows = connection.execute(query).all()
        return [
            {
                "beat": f"ask-{row.first}" if row.ask else row.beat,
                "at": row.at,
                "ask": bool(row.ask),
                "tools": int(row.tools or 0),
                "input": int(row.input or 0),
                "output": int(row.output or 0),
                "cost": row.cost,
            }
            for row in rows
        ]


class SqliteDmSessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        with self._db.connect() as connection:
            row = connection.execute(select(dm_sessions).where(dm_sessions.c.campaign_id == campaign_id)).first()
        if row is None:
            return None
        return {
            "provider": row.provider,
            "session_id": row.session_id,
            "context_tokens": row.context_tokens,
            "updated_at": row.updated_at,
        }

    def set(self, campaign_id: str, provider: str, session_id: str | None, context_tokens: int) -> None:
        row = {
            "campaign_id": campaign_id,
            "provider": provider,
            "session_id": session_id,
            "context_tokens": int(context_tokens),
            "updated_at": _now(),
        }
        upsert = insert(dm_sessions).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[dm_sessions.c.campaign_id],
            set_={k: getattr(upsert.excluded, k) for k in row if k != "campaign_id"},
        )
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            connection.execute(upsert)

    def clear(self, campaign_id: str) -> None:
        with self._db.begin() as connection:
            connection.execute(dm_sessions.delete().where(dm_sessions.c.campaign_id == campaign_id))


class SqlitePlaySettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, campaign_id: str) -> dict[str, Any] | None:
        with self._db.connect() as connection:
            row = connection.execute(select(play_settings.c.raw).where(play_settings.c.campaign_id == campaign_id))
            raw = row.scalar()
        return dict(raw) if raw is not None else None

    def put(self, campaign_id: str, raw: dict[str, Any]) -> None:
        row = {"campaign_id": campaign_id, "raw": dict(raw), "updated_at": _now()}
        upsert = insert(play_settings).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[play_settings.c.campaign_id],
            set_={"raw": upsert.excluded.raw, "updated_at": upsert.excluded.updated_at},
        )
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            connection.execute(upsert)


class SqliteTableSessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, campaign_id: str) -> TableSession | None:
        with self._db.connect() as connection:
            row = connection.execute(select(table_sessions).where(table_sessions.c.campaign_id == campaign_id)).first()
        if row is None:
            return None
        return TableSession(
            campaign_id=row.campaign_id,
            state=row.state,
            since=row.since,
            absent=dict(row.absent),
            hands={seat_id: dict(hand) for seat_id, hand in row.hands.items()},
            break_at=row.break_at,
            away={seat_id: dict(away) for seat_id, away in (row.away or {}).items()},
        )

    def put(self, session: TableSession) -> None:
        row = {
            "campaign_id": session.campaign_id,
            "state": session.state,
            "since": session.since,
            "absent": dict(session.absent),
            "hands": {seat_id: dict(hand) for seat_id, hand in session.hands.items()},
            "break_at": session.break_at,
            "away": {seat_id: dict(away) for seat_id, away in session.away.items()},
            "updated_at": _now(),
        }
        upsert = insert(table_sessions).values(row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[table_sessions.c.campaign_id],
            set_={key: upsert.excluded[key] for key in row if key != "campaign_id"},
        )
        with self._db.begin() as connection:
            _require_campaign(connection, session.campaign_id)
            connection.execute(upsert)
