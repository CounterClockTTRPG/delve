"""Module text: the working copy's in `module_texts`, each revision's in `module_revisions.text`, and the full-text
index of each revision's sections in the FTS5 table `module_text_index`.

The index is ttrpg2's `module_lookup` (`tools/module_ref.py`) on stored text: one row per paragraph, or per numbered
key entry, tagged with its section's anchor and heading path. A revision is indexed when it is snapshotted, so a
search answers from the text that revision pinned. Search words are quoted and ANDed, and a section filter is a
`LIKE` on the heading path with its wildcards escaped, so a query is never FTS or `LIKE` syntax.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, select, text
from sqlalchemy.dialects.sqlite import insert

from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import module_revisions, module_texts

PATH_SEPARATOR = " › "
_KEY_ENTRY = re.compile(r"^\d+[a-z]?\.\s")


def working_text(connection: Connection, module_id: str) -> dict[str, Any] | None:
    return connection.execute(select(module_texts.c.text).where(module_texts.c.module_id == module_id)).scalar()


def revision_text(connection: Connection, module_id: str, number: int) -> dict[str, Any] | None:
    return connection.execute(
        select(module_revisions.c.text).where(
            module_revisions.c.module_id == module_id, module_revisions.c.number == number
        )
    ).scalar()


def index_revision(connection: Connection, module_id: str, number: int, raw: dict[str, Any] | None) -> None:
    """Index the sections of a revision's text, once."""
    connection.execute(
        text("DELETE FROM module_text_index WHERE module_id = :module_id AND revision = :revision"),
        {"module_id": module_id, "revision": number},
    )
    rows = [
        {"module_id": module_id, "revision": number, **row} for row in _rows(raw.get("sections", []) if raw else [])
    ]
    if rows:
        connection.execute(
            text(
                "INSERT INTO module_text_index (module_id, revision, anchor, position, heading_path, body)"
                " VALUES (:module_id, :revision, :anchor, :position, :heading_path, :body)"
            ),
            rows,
        )


def drop_index(connection: Connection, module_id: str) -> None:
    connection.execute(text("DELETE FROM module_text_index WHERE module_id = :module_id"), {"module_id": module_id})


def _rows(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in sections:
        path = PATH_SEPARATOR.join(section.get("heading_path", []))
        for chunk in _chunks(f"{section.get('read_aloud') or ''}\n\n{section.get('markdown') or ''}"):
            rows.append({"anchor": section["anchor"], "position": len(rows), "heading_path": path, "body": chunk})
    return rows


def _chunks(markdown: str) -> list[str]:
    """Paragraphs, and numbered key entries with their wrapped lines, each on one line (ttrpg2's `_chunks`)."""
    out: list[str] = []
    buf: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if (not line or _KEY_ENTRY.match(line)) and buf:
            out.append(" ".join(buf))
            buf.clear()
        if line:
            buf.append(line)
    if buf:
        out.append(" ".join(buf))
    return out


_COMMON = frozenset(
    {
        *("a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "he", "her", "his", "how"),
        *("in", "is", "it", "its", "of", "on", "or", "she", "that", "the", "their", "them", "they", "this", "to"),
        *("was", "what", "when", "where", "which", "who", "why", "will", "with"),
    }
)
"""Words an any-word search leaves out: every paragraph has them."""


def _fts_query(query: str, any_word: bool = False) -> str:
    """Each word as a quoted term, ANDed (or ORed, without the commonest words, for `any_word`): the DM's words are
    never FTS syntax."""
    words = re.findall(r"[\w'-]+", query)
    if any_word:
        words = [w for w in words if w.casefold() not in _COMMON]
    return (" OR " if any_word else " ").join('"' + word.replace('"', "") + '"' for word in words)


def _like_pattern(section: str) -> str:
    escaped = section.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SqliteModuleTextRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, module_id: str) -> dict[str, Any] | None:
        with self._db.connect() as connection:
            return working_text(connection, module_id)

    def put(self, module_id: str, raw: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._db.begin() as connection:
            upsert = insert(module_texts).values(module_id=module_id, text=raw, updated_at=now)
            connection.execute(
                upsert.on_conflict_do_update(
                    index_elements=[module_texts.c.module_id],
                    set_={
                        "text": raw,
                        "updated_at": now,
                    },
                )
            )

    def revision(self, module_id: str, number: int) -> dict[str, Any] | None:
        with self._db.connect() as connection:
            return revision_text(connection, module_id, number)

    def search(
        self, module_id: str, revision: int, query: str, limit: int = 5, *, section: str = "", any_word: bool = False
    ) -> list[dict[str, Any]]:
        terms = _fts_query(query, any_word)
        if not terms:
            return []
        sql = (
            "SELECT anchor, heading_path, body FROM module_text_index"
            " WHERE module_text_index MATCH :terms AND module_id = :module_id AND revision = :revision"
        )
        values: dict[str, Any] = {"terms": terms, "module_id": module_id, "revision": revision, "limit": max(1, limit)}
        if section:
            sql += " AND heading_path LIKE :section ESCAPE '\\'"
            values["section"] = _like_pattern(section)
        sql += " ORDER BY rank, position LIMIT :limit"
        with self._db.connect() as connection:
            rows = connection.execute(text(sql), values).all()
        return [
            {"anchor": anchor, "heading_path": path.split(PATH_SEPARATOR), "snippet": body}
            for anchor, path, body in rows
        ]
