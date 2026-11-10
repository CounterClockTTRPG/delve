"""Connections for the repositories, joining the open transaction when there is one.

`Database.transaction()` opens one SQLite transaction; every repository write inside it (in the same thread or task)
joins it, and an exception rolls all of it back. A `transaction()` inside another joins the outer one. Outside a
transaction, `begin()` commits on its own, as before.

A transaction begins with `BEGIN IMMEDIATE`, taking the write lock before its first read. pysqlite would begin only
before the first write, so a transaction that reads, checks and then writes (a free seat, a party's carrying, a name
not yet taken) could read what another was about to change, and then lose to it or overwrite it. Taken up front, a
second transaction waits (the engine's busy timeout) until the first commits and then reads what it wrote. So nothing
slow may run inside one: no model call, no painting, no `await`. `reading()` is for reads that must see one moment
(a bundle's packing) without stopping every writer meanwhile: a deferred BEGIN, which WAL keeps to the moment of its
first read.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Connection, Engine


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._current: ContextVar[Connection | None] = ContextVar(f"delve_tx_{id(self)}", default=None)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._open("BEGIN IMMEDIATE"):
            yield

    @contextmanager
    def reading(self) -> Iterator[None]:
        """A transaction whose reads all see one moment, taking no lock: writers go on meanwhile, unseen. A write
        inside it may fail on a stale snapshot, so it is for reading only; inside a `transaction()`, it joins that."""
        with self._open("BEGIN"):
            yield

    @contextmanager
    def _open(self, begin: str) -> Iterator[None]:
        if self._current.get() is not None:
            yield
            return
        with self.engine.begin() as connection:
            # SQLAlchemy's begin is a no-op for pysqlite; this is the BEGIN, and pysqlite, seeing a transaction open,
            # adds none of its own before the first write. The block's end commits or rolls it back as usual.
            connection.exec_driver_sql(begin)
            token = self._current.set(connection)
            try:
                yield
            finally:
                self._current.reset(token)

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        """A connection to write with: the open transaction's, or a new one that commits when the block ends."""
        current = self._current.get()
        if current is not None:
            yield current
            return
        with self.engine.begin() as connection:
            yield connection

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        """A connection to read with, which sees the open transaction's writes."""
        current = self._current.get()
        if current is not None:
            yield current
            return
        with self.engine.connect() as connection:
            yield connection


def like_pattern(words: str) -> str:
    """A LIKE pattern (with `ESCAPE '\\'`) for text that contains `words`, its `%`, `_` and `\\` taken as they are.
    LIKE ignores case for ASCII letters only."""
    escaped = words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
