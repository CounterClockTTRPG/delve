"""Blobs: the bytes on disk at `<root>/<aa>/<sha256>`, written atomically; a row per blob and per module link.

Nothing deletes a blob but `prune` (DEL-36), which takes those no row names any more. A blob is named in many places,
a column (`modules.banner_blob`, `accounts.avatar_sha`), a JSON field (a world picture's tiles, a module source's
attachments) or a module revision's source, and more come with new features; so a blob counts as named when any text
of any row of any table but `blobs` holds its sha, as a snapshot finds a module's blobs. A false match only keeps a
file. `prune` holds the write lock from its last look until the files are gone, and `put` touches the file before it
adds the row and looks for it again after, so a blob put again while a prune runs is never left without its file.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Connection, delete, select
from sqlalchemy.dialects.sqlite import insert

from delve.storage.interfaces import UnusedBlob, UnusedBlobs
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.tables import blobs, conversions, module_blobs, modules

SHA256 = re.compile(r"[0-9a-f]{64}")
NAMED = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
"""A sha in a row's text: 64 hex digits, not part of a longer run."""
CHUNK = 1 << 20
"""Bytes `put_file` reads at a time."""
LIVE_JOBS = ("queued", "running", "paused")
"""A job in these may have put blobs it names only when it ends (a conversion's pictures come before its module)."""
DELETE_CHUNK = 500
TEMP_PREFIX = ".tmp-"
TEMP_AGE = timedelta(hours=1)
"""A temporary file goes only this much older than the grace period, whatever it is: a write may be under way."""


class SqliteBlobStore:
    def __init__(self, db: Database, root: Path) -> None:
        self._db = db
        self._root = root

    def put(self, data: bytes, mime: str) -> str:
        sha = hashlib.sha256(data).hexdigest()
        path = self._path(sha)
        if not _touch(path):
            _write_atomically(path, data)
        self._insert(sha, mime, len(data))
        if not path.is_file():  # a prune took it between the two
            _write_atomically(path, data)
        return sha

    def put_file(self, source: Path, mime: str) -> str:
        """`put` for the file at `source`, streamed: hashed while it is copied to a temporary file in the store, which
        is then renamed into place (or dropped, when the blob is already there)."""
        sha, size = self._place(source)
        self._insert(sha, mime, size)
        if not self._path(sha).is_file():  # a prune took it between the two
            self._place(source)
        return sha

    def _place(self, source: Path) -> tuple[str, int]:
        """Copy `source` into the store under its sha, or touch the file there already; its sha and size."""
        self._root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        fd, tmp = tempfile.mkstemp(dir=self._root, prefix=TEMP_PREFIX)
        try:
            with os.fdopen(fd, "wb") as file, source.open("rb") as reading:
                while chunk := reading.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    file.write(chunk)
                file.flush()
                os.fsync(file.fileno())
            sha = digest.hexdigest()
            path = self._path(sha)
            if _touch(path):
                Path(tmp).unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return sha, size

    def get(self, sha: str) -> bytes | None:
        if not self.exists(sha):
            return None
        try:
            return self._path(sha).read_bytes()
        except FileNotFoundError:
            return None

    def exists(self, sha: str) -> bool:
        if not SHA256.fullmatch(sha):
            return False
        with self._db.connect() as connection:
            return connection.execute(select(blobs.c.sha256).where(blobs.c.sha256 == sha)).first() is not None

    def link(self, module_id: str, role: str, sha: str) -> None:
        with self._db.begin() as connection:
            if connection.execute(select(modules.c.id).where(modules.c.id == module_id)).first() is None:
                raise KeyError(module_id)
            if connection.execute(select(blobs.c.sha256).where(blobs.c.sha256 == sha)).first() is None:
                raise KeyError(sha)
            row = {"module_id": module_id, "role": role, "sha256": sha}
            connection.execute(insert(module_blobs).values(row).on_conflict_do_nothing())

    def links(self, module_id: str) -> list[tuple[str, str]]:
        query = (
            select(module_blobs.c.role, module_blobs.c.sha256)
            .where(module_blobs.c.module_id == module_id)
            .order_by(module_blobs.c.role, module_blobs.c.sha256)
        )
        with self._db.connect() as connection:
            return [(role, sha) for role, sha in connection.execute(query)]

    def unused(self, grace: timedelta) -> UnusedBlobs:
        with self._db.engine.connect() as connection:
            return self._unused(connection, grace)

    def prune(self, grace: timedelta) -> UnusedBlobs:
        """The look again under `BEGIN IMMEDIATE`: no one adds a row naming a blob, nor puts one, until its files are
        gone and the rows' delete commits. Temporary files older than `grace` that a crashed write left go too."""
        with self._db.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                found = self._unused(connection, grace)
                shas = [blob.sha for blob in found.blobs]
                for start in range(0, len(shas), DELETE_CHUNK):
                    connection.execute(delete(blobs).where(blobs.c.sha256.in_(shas[start : start + DELETE_CHUNK])))
                for sha in shas:
                    self._path(sha).unlink(missing_ok=True)
                for temp in self._temporaries(_cutoff(connection, grace) - TEMP_AGE):
                    temp.unlink(missing_ok=True)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return found

    def _unused(self, connection: Connection, grace: timedelta) -> UnusedBlobs:
        cutoff = _cutoff(connection, grace)
        named = _named(connection)
        rows = {sha: (mime, size, created) for sha, mime, size, created in connection.execute(select(blobs))}
        files = {path.name: path for path in self._files()}
        gone: list[UnusedBlob] = []
        kept = 0
        for sha in (rows.keys() | files.keys()) - named:
            row = rows.get(sha)
            stat = _stat(files.get(sha))
            times = [datetime.fromtimestamp(stat.st_mtime, UTC)] if stat is not None else []
            if row is not None:
                times.append(datetime.fromisoformat(row[2]))
            if any(time >= cutoff for time in times):
                kept += 1
                continue
            if row is not None:
                gone.append(UnusedBlob(sha, row[1], row[0], row[2]))
            elif stat is not None:
                gone.append(UnusedBlob(sha, stat.st_size, None, None))
        gone.sort(key=lambda blob: (-blob.size, blob.sha))
        return UnusedBlobs(gone, kept)

    def _files(self) -> Iterator[Path]:
        if self._root.is_dir():
            yield from (path for path in self._root.glob("??/*") if SHA256.fullmatch(path.name))

    def _temporaries(self, cutoff: datetime) -> Iterator[Path]:
        if not self._root.is_dir():
            return
        for path in [*self._root.glob(f"{TEMP_PREFIX}*"), *self._root.glob(f"??/{TEMP_PREFIX}*")]:
            stat = _stat(path)
            if stat is not None and datetime.fromtimestamp(stat.st_mtime, UTC) < cutoff:
                yield path

    def _insert(self, sha: str, mime: str, size: int) -> None:
        row = {"sha256": sha, "mime": mime, "size": size, "created_at": datetime.now(UTC).isoformat()}
        with self._db.begin() as connection:
            connection.execute(insert(blobs).values(row).on_conflict_do_nothing())

    def _path(self, sha: str) -> Path:
        return self._root / sha[:2] / sha


def _named(connection: Connection) -> set[str]:
    """Every sha that any text of any row of any table but `blobs` holds: a column, a JSON field, a module's source."""
    found: set[str] = set()
    tables = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'table'").scalars().all()
    for table in tables:
        if table == blobs.name or table.startswith("sqlite_"):
            continue
        quoted = table.replace('"', '""')
        for row in connection.exec_driver_sql(f'SELECT * FROM "{quoted}"'):
            for value in row:
                if isinstance(value, bytes):
                    value = value.decode("latin-1")
                if isinstance(value, str) and len(value) >= 64:
                    found.update(NAMED.findall(value))
    return found


def _cutoff(connection: Connection, grace: timedelta) -> datetime:
    """Blobs from this time on stay: those of the last `grace`, and since the oldest job still going started."""
    cutoff = datetime.now(UTC) - grace
    oldest = connection.execute(
        select(conversions.c.created_at).where(conversions.c.status.in_(LIVE_JOBS)).order_by(conversions.c.created_at)
    ).first()
    return cutoff if oldest is None else min(cutoff, datetime.fromisoformat(oldest[0]))


def _stat(path: Path | None) -> os.stat_result | None:
    if path is None:
        return None
    try:
        return path.stat()
    except FileNotFoundError:
        return None


def _touch(path: Path) -> bool:
    """Mark the blob's file as just put, so a prune lets it be; False when there is no file."""
    try:
        os.utime(path)
    except FileNotFoundError:
        return False
    return True


def _write_atomically(path: Path, data: bytes) -> None:
    """Write to a temporary file beside `path` and rename it into place, so `path` is whole or absent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
