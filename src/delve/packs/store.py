"""A pack's own data store: its snapshots checked against their sums and loaded into one SQLite file."""

from __future__ import annotations

import gzip
import hashlib
import os
import sqlite3
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

SUMS = "SHA256SUMS"
DEFAULT_TOKENIZER = "porter unicode61"


class SnapshotCorrupt(RuntimeError):
    """A snapshot is missing, or doesn't match `SHA256SUMS`."""


def sums_sha(data_dir: Path) -> str:
    """The sha256 of `SHA256SUMS`: one value that names the whole snapshot set."""
    return hashlib.sha256((data_dir / SUMS).read_bytes()).hexdigest()


def verify(data_dir: Path, names: Sequence[str]) -> str:
    """Check each of `names` against `SHA256SUMS` and return the set's sha. Raises `SnapshotCorrupt`."""
    try:
        sums = (data_dir / SUMS).read_text()
    except FileNotFoundError:
        raise SnapshotCorrupt(f"{data_dir / SUMS} is missing") from None
    expected = {}
    for line in sums.splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            expected[name.strip()] = digest
    for name in names:
        path = data_dir / name
        if name not in expected:
            raise SnapshotCorrupt(f"{name} is not listed in {SUMS}")
        if not path.is_file():
            raise SnapshotCorrupt(f"{name} is missing from {data_dir}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
            raise SnapshotCorrupt(f"{name} doesn't match its checksum in {SUMS}")
    return sums_sha(data_dir)


def load_snapshots(
    data_dir: Path,
    db: Path,
    sql: Sequence[str],
    json_tables: Mapping[str, str],
    fts: Mapping[str, tuple[str, ...]] = {},
    *,
    tokenizers: Mapping[str, str] = {},
    finish: Callable[[sqlite3.Connection, str], None] | None = None,
) -> str:
    """Build `db` from the snapshots in `data_dir` and return the checksum file's sha.

    Every file in `sql` and `json_tables` must match `SHA256SUMS`. The `sql` files (gzipped) are run in order, each
    `json_tables` file (gzipped, name -> table) becomes the one row of its table, and `fts` (table -> columns) gets an
    external-content FTS5 index `<table>_fts`, tokenized as `tokenizers` says (default `porter unicode61`). `finish`,
    if given, is called with the connection and the sha after the indexes are made and before the file is put in place.

    The database is written to a temp file next to `db` and renamed into place, so an interrupted or failed build
    leaves the old `db` (or none), never half of one.
    """
    sha = verify(data_dir, (*sql, *json_tables))
    db.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{db.name}.", suffix=".building", dir=db.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        conn = sqlite3.connect(tmp)
        try:
            for name in sql:
                with gzip.open(data_dir / name, "rt", encoding="utf-8") as script:
                    conn.executescript(f"BEGIN;\n{script.read()}\nCOMMIT;")
            for name, table in json_tables.items():
                with gzip.open(data_dir / name, "rt", encoding="utf-8") as snapshot:
                    data = snapshot.read()
                with conn:
                    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)")
                    conn.execute(f"INSERT INTO {table} (id, data) VALUES (1, ?)", (data,))
            # VACUUM may renumber the rowids of a table without an INTEGER PRIMARY KEY, which an external-content
            # index reads its text by, so the indexes come after it.
            conn.execute("VACUUM")
            with conn:
                for table, columns in fts.items():
                    tokenize = tokenizers.get(table, DEFAULT_TOKENIZER)
                    conn.execute(
                        f"CREATE VIRTUAL TABLE {table}_fts USING fts5({', '.join(columns)},"
                        f" content='{table}', content_rowid='rowid', tokenize='{tokenize}')"
                    )
                    conn.execute(f"INSERT INTO {table}_fts ({table}_fts) VALUES ('rebuild')")
            if finish is not None:
                finish(conn, sha)
        finally:
            conn.close()
        os.replace(tmp, db)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return sha


def open_pack_db(db: Path) -> sqlite3.Connection:
    """The pack's database, read-only and usable from any thread."""
    return sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
