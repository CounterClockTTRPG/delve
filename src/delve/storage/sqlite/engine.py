"""The SQLite engine: WAL journal with `synchronous=NORMAL`, foreign keys and a 5 s busy timeout on every connection."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def create_sqlite_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        # Safe in WAL: a commit can be lost to a power cut, never corrupt the database; one fsync per checkpoint,
        # not per commit, for the DM's streamed replies (DEL-165).
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        # A writer waits for another's lock (a beat's background task, a conversion) instead of failing at once.
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine
