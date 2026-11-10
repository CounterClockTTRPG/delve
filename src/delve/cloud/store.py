"""The object store seam (cloud storage plan Task 1): what Delve needs of a cloud store, and a local folder that plays one.

An `ObjectStore` lists, reads, creates (never over an existing object), overwrites and deletes objects by name. Its
errors are Delve's own words: a `StoreError` never carries a credential or a provider's answer, and `label` says where
the store is without one.

`probe` reads a credential's right from what it can do, as the spec's table does: list only is `read`, list and create
is `publish`, and list, create, overwrite and delete is `manage`. Its probe object, `.delve-probe/<random>`, is removed
on every path that made it.

`get(name, limit=…)` refuses an object larger than `limit` bytes without reading the rest of it: a library entry is
read within `ENTRY_LIMIT` and a module within `MODULE_LIMIT`, as a store it doesn't own may hold anything.

`LocalStore` is a folder. It backs the tests, and plays each right: `read_only` refuses every write, and `create_only`
refuses an overwrite (it still deletes, so the probe can clean up after itself).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import tempfile
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

Right = Literal["read", "publish", "manage"]
RIGHTS: tuple[Right, ...] = ("read", "publish", "manage")
Gap = Literal["container", "list", "create", "write", "delete"]
"""What a credential was refused when `probe_gap` tried it, in the order it tries them; `container` is a container or
bucket that isn't there at all."""

PROBE_PREFIX = ".delve-probe/"
_TMP_PREFIX = ".delve-tmp-"

ENTRY_LIMIT = 64 * 1024  # a library entry's `entry.json`
MODULE_LIMIT = 64 * 1024 * 1024  # a module's `.dscn`, as the import takes
TOO_LARGE = "It is larger than Delve takes."


class StoreError(Exception):
    """A store's failure, in Delve's own words: never a credential, never the provider's answer."""


class Exists(StoreError):
    """A create over an object that is already there."""


class Missing(StoreError):
    """A get or delete of an object that isn't there."""


class Refused(StoreError):
    """The store refused the credential (401 or 403)."""


@dataclass(frozen=True)
class Listed:
    name: str
    size: int
    modified: str


class ObjectStore(Protocol):
    label: str

    async def list(self, prefix: str = "") -> list[Listed]: ...

    async def get(self, name: str, *, limit: int | None = None) -> bytes: ...

    async def create(self, name: str, data: bytes) -> None: ...

    async def put(self, name: str, data: bytes) -> None: ...

    async def delete(self, name: str) -> None: ...

    async def aclose(self) -> None: ...


async def read_within(chunks: AsyncIterable[bytes], limit: int | None) -> bytes:
    """The bytes of `chunks`, read no further than past `limit`: then `StoreError`."""
    data = bytearray()
    async for chunk in chunks:
        data += chunk
        if limit is not None and len(data) > limit:
            raise StoreError(TOO_LARGE)
    return bytes(data)


async def probe(store: ObjectStore) -> Right | None:
    """The right `store`'s credential gives, or None when it can't even list. An error other than a refusal is raised,
    after the probe object is removed."""
    return (await probe_gap(store))[0]


async def probe_gap(store: ObjectStore) -> tuple[Right | None, Gap | None]:
    """`probe`'s right, with the first thing the credential was refused (`list`, `create`, `write`, `delete`; or
    `container`, when the container or bucket isn't there), or None when it may do all of them: what a backup store's
    refusal names."""
    try:
        await store.list(PROBE_PREFIX)
    except Refused:
        return None, "list"
    except Missing:
        return None, "container"
    name = PROBE_PREFIX + secrets.token_hex(8)
    try:
        await store.create(name, b"delve probe")
    except Refused:
        return "read", "create"
    right: Right = "publish"
    gap: Gap | None = "write"
    try:
        await store.put(name, b"delve probe, overwritten")
        gap = "delete"
        await store.delete(name)
        right, gap = "manage", None
    except Refused:
        pass
    finally:
        if right != "manage":
            with contextlib.suppress(StoreError):
                await store.delete(name)
    return right, gap


class LocalStore:
    """A folder as an object store. The folder must exist; names are `/`-separated paths inside it."""

    def __init__(self, root: Path, *, read_only: bool = False, create_only: bool = False) -> None:
        self.root = Path(root)
        self.read_only = read_only
        self.create_only = create_only
        self.label = str(self.root)

    def __repr__(self) -> str:
        return f"LocalStore({self.label!r})"

    def _path(self, name: str) -> Path:
        parts = name.split("/")
        if not name or name.startswith("/") or "\\" in name or any(part in ("", ".", "..") for part in parts):
            raise StoreError("That object name isn't allowed.")
        if not self.root.is_dir():
            raise Missing("The folder isn't there.")
        return self.root.joinpath(*parts)

    def _writable(self) -> None:
        if self.read_only:
            raise Refused("The store refused the write.")

    # The folder is read and written in a thread (DEL-172): the store is used from the event loop, and a backup's
    # objects are megabytes.

    async def list(self, prefix: str = "") -> list[Listed]:
        return await asyncio.to_thread(self._list, prefix)

    async def get(self, name: str, *, limit: int | None = None) -> bytes:
        return await asyncio.to_thread(self._get, name, limit)

    async def create(self, name: str, data: bytes) -> None:
        await asyncio.to_thread(self._create, name, data)

    async def put(self, name: str, data: bytes) -> None:
        await asyncio.to_thread(self._put, name, data)

    async def delete(self, name: str) -> None:
        await asyncio.to_thread(self._delete, name)

    def _list(self, prefix: str) -> list[Listed]:
        if not self.root.is_dir():
            raise Missing("The folder isn't there.")
        listed = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.name.startswith(_TMP_PREFIX):
                continue
            name = path.relative_to(self.root).as_posix()
            if name.startswith(prefix):
                stat = path.stat()
                modified = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="seconds")
                listed.append(Listed(name, stat.st_size, modified))
        return sorted(listed, key=lambda item: item.name)

    def _get(self, name: str, limit: int | None) -> bytes:
        path = self._path(name)
        try:
            if limit is not None and path.stat().st_size > limit:
                raise StoreError(TOO_LARGE)
            return path.read_bytes()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            raise Missing("That object isn't there.") from None

    def _create(self, name: str, data: bytes) -> None:
        path = self._path(name)
        self._writable()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise Exists("That object is already there.") from None
        with os.fdopen(fd, "wb") as file:
            file.write(data)

    def _put(self, name: str, data: bytes) -> None:
        path = self._path(name)
        self._writable()
        if self.create_only and path.exists():
            raise Refused("The store refused the overwrite.")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=_TMP_PREFIX, dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise

    def _delete(self, name: str) -> None:
        path = self._path(name)
        self._writable()
        try:
            path.unlink()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            raise Missing("That object isn't there.") from None
        # Remove the folders the object leaves empty, as a cloud store has none.
        parent = path.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    async def aclose(self) -> None:
        return None
