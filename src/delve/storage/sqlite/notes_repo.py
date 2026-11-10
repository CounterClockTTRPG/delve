"""The DM's notes and the campaign's sessions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import Connection, select, text

from delve.domain import new_id
from delve.domain.campaigns import Note, NoteKind, Session
from delve.storage.sqlite.db import Database, like_pattern
from delve.storage.sqlite.tables import campaigns, notes, sessions


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require_campaign(connection: Connection, campaign_id: str) -> None:
    if connection.execute(select(campaigns.c.id).where(campaigns.c.id == campaign_id)).first() is None:
        raise KeyError(campaign_id)


def _note_from(row) -> Note:
    return Note(
        id=row.id,
        campaign_id=row.campaign_id,
        kind=row.kind,
        text=row.text,
        tags=tuple(row.tags),
        related_to=row.related_to,
        revealed=bool(row.revealed),
        map_name=row.map_name,
        node=row.node,
        session=row.session,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqliteNoteRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self,
        campaign_id: str,
        kind: NoteKind,
        text: str,
        *,
        tags: Iterable[str] = (),
        related_to: str = "",
        map_name: str | None = None,
        node: str | None = None,
        session: int = 1,
    ) -> Note:
        now = _now()
        note = Note(
            new_id("note"),
            campaign_id,
            kind,
            text,
            tuple(tags),
            related_to,
            False,
            map_name,
            node,
            session,
            now,
            now,
        )
        row = {**note.__dict__, "tags": list(note.tags)}
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            connection.execute(notes.insert().values(row))
        return note

    def get(self, id: str) -> Note | None:
        with self._db.connect() as connection:
            row = connection.execute(select(notes).where(notes.c.id == id)).first()
        return None if row is None else _note_from(row)

    def list(
        self, campaign_id: str, *, kind: NoteKind | None = None, map_name: str | None = None, node: str | None = None
    ) -> list[Note]:
        query = select(notes).where(notes.c.campaign_id == campaign_id)
        if kind is not None:
            query = query.where(notes.c.kind == kind)
        if map_name is not None:
            query = query.where(notes.c.map_name == map_name)
        if node is not None:
            query = query.where(notes.c.node == node)
        with self._db.connect() as connection:
            return [_note_from(row) for row in connection.execute(query.order_by(text("rowid")))]

    def search(self, campaign_id: str, words: str, limit: int) -> list[Note]:
        holds = notes.c.text.like(like_pattern(words), escape="\\")
        query = select(notes).where(notes.c.campaign_id == campaign_id, holds)
        with self._db.connect() as connection:
            return [_note_from(row) for row in connection.execute(query.order_by(text("rowid DESC")).limit(limit))]

    def save(self, note: Note) -> Note:
        saved = replace(note, updated_at=_now())
        values = {
            "text": saved.text,
            "tags": list(saved.tags),
            "related_to": saved.related_to,
            "revealed": saved.revealed,
            "updated_at": saved.updated_at,
        }
        with self._db.begin() as connection:
            done = connection.execute(notes.update().where(notes.c.id == note.id).values(values))
            if done.rowcount == 0:
                raise KeyError(note.id)
            row = connection.execute(select(notes).where(notes.c.id == note.id)).first()
        return _note_from(row)


def _session_from(row) -> Session:
    return Session(
        campaign_id=row.campaign_id,
        number=row.number,
        title=row.title,
        started_at=row.started_at,
        ended_at=row.ended_at,
        recap_md=row.recap_md,
    )


class SqliteSessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def start(self, campaign_id: str, number: int, title: str) -> Session:
        session = Session(campaign_id, number, title, _now())
        with self._db.begin() as connection:
            _require_campaign(connection, campaign_id)
            connection.execute(sessions.insert().values(session.__dict__))
        return session

    def get(self, campaign_id: str, number: int) -> Session | None:
        query = select(sessions).where(sessions.c.campaign_id == campaign_id, sessions.c.number == number)
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else _session_from(row)

    def list(self, campaign_id: str) -> list[Session]:
        query = select(sessions).where(sessions.c.campaign_id == campaign_id).order_by(sessions.c.number)
        with self._db.connect() as connection:
            return [_session_from(row) for row in connection.execute(query)]

    def end(self, campaign_id: str, number: int, recap_md: str) -> Session:
        where = (sessions.c.campaign_id == campaign_id, sessions.c.number == number)
        with self._db.begin() as connection:
            done = connection.execute(sessions.update().where(*where).values(ended_at=_now(), recap_md=recap_md))
            if done.rowcount == 0:
                raise KeyError((campaign_id, number))
            row = connection.execute(select(sessions).where(*where)).first()
        return _session_from(row)
