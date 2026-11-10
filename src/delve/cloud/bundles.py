"""Bundles (cloud storage plan Task 6): a module (`.dmod`, with all its revisions), a campaign (`.dcmp`) or a setting
(`.dset`) as one zip, for the backup store.

A bundle holds `manifest.json`, the item's rows as `rows/<table>.json` (a `Snapshot` of `storage.snapshots`) and the
bytes of the blobs they reference as `blobs/<sha>`. Its entries are written in sorted order with a fixed timestamp,
the rows deflated and the blobs, mostly compressed pictures already, stored. Its `hash` is that of every entry but the
manifest's `created_at`, so an item that didn't change packs to the same hash and the backup can skip it.

A bundle holds the database rows of the item and nothing else: never Preferences, Connections, accounts or a store's
credential, which live in other tables or in files of the data dir that no snapshot reads.

Unpacking refuses, with `BundleRefused` and words for the owner, a bundle from a newer format, one without a manifest
or with damaged rows, a blob whose bytes don't hash to its name, and one that unpacks to more than `MAX_ENTRY` an
entry or `MAX_TOTAL` in all, before it reads it. `unpack_into` restores the item in one
transaction: when `storage.snapshots.restore` refuses, the rows roll back, and the blob files it put stay until a
prune (`delve blobs prune`, DEL-36) deletes them, files without their row.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from delve import __version__
from delve.storage.interfaces import SNAPSHOT_KINDS, Snapshot, SnapshotKind, SnapshotRefused

if TYPE_CHECKING:
    from delve.storage.interfaces import Storage

EXTENSIONS: dict[SnapshotKind, str] = {"module": "dmod", "campaign": "dcmp", "setting": "dset"}
FORMAT = 1
"""The bundle format this Delve writes and the newest it reads."""

MANIFEST = "manifest.json"
ROWS = "rows/"
BLOBS = "blobs/"
STAMP = (1980, 1, 1, 0, 0, 0)
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_TOTAL = 1 << 30
"""The most a bundle may unpack to, all its entries together: 1 GiB."""
MAX_ENTRY = 256 << 20
"""The most one entry may unpack to: 256 MiB."""
TOO_LARGE = "This copy is too large to restore."


class BundleRefused(SnapshotRefused):
    """A bundle Delve won't unpack. Its message is for the owner."""


@dataclass(frozen=True)
class Manifest:
    """What a bundle is: its format, the item, the Delve and migration head that packed it, and for a campaign the
    module revision it plays and its setting."""

    format: int
    kind: SnapshotKind
    item_id: str
    title: str
    head: str
    delve_version: str
    created_at: str
    module_id: str | None = None
    revision: int | None = None
    setting: str | None = None

    def to_json(self) -> dict[str, Any]:
        raw = asdict(self)
        if self.kind != "campaign":
            for key in ("module_id", "revision", "setting"):
                del raw[key]
        return raw


@dataclass(frozen=True)
class Packed:
    data: bytes
    hash: str
    title: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def pack(storage: Storage, kind: SnapshotKind, item_id: str) -> Packed:
    """The item as a bundle; `KeyError` when it isn't here. It reads one moment of the database, its blobs included."""
    with storage.reading():
        return _pack(storage, kind, item_id)


def _pack(storage: Storage, kind: SnapshotKind, item_id: str) -> Packed:
    snapshot = storage.snapshots.dump(kind, item_id)
    title = storage.snapshots.title(kind, item_id)
    campaign = snapshot.rows["campaigns"][0] if kind == "campaign" else {}
    manifest = Manifest(
        format=FORMAT,
        kind=kind,
        item_id=item_id,
        title=title,
        head=snapshot.head,
        delve_version=__version__,
        created_at=_now(),
        module_id=campaign.get("module_id"),
        revision=campaign.get("revision"),
        setting=campaign.get("setting") or None,
    )
    files = {f"{ROWS}{table}.json": _json(rows) for table, rows in snapshot.rows.items()}
    for sha in snapshot.blobs:
        data = storage.blobs.get(sha)
        if data is None:
            raise KeyError(sha)
        files[f"{BLOBS}{sha}"] = data
    hashed = {**files, MANIFEST: _json({k: v for k, v in manifest.to_json().items() if k != "created_at"})}
    files[MANIFEST] = _json(manifest.to_json())

    digest = hashlib.sha256()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in sorted(files):
            digest.update(_json(name) + hashlib.sha256(hashed[name]).digest())
            info = zipfile.ZipInfo(name, date_time=STAMP)
            info.compress_type = zipfile.ZIP_STORED if name.startswith(BLOBS) else zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return Packed(data=buffer.getvalue(), hash=digest.hexdigest(), title=title)


Unpacked = tuple[Manifest, Snapshot, dict[str, tuple[bytes, str]]]
"""A bundle unpacked: its manifest, its item as a snapshot, and its blobs' bytes and mime by sha."""


def unpack(data: bytes) -> Unpacked:
    """The bundle's manifest, its item as a snapshot, and its blobs' bytes and mime by sha."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            listed = [info for info in archive.infolist() if not info.is_dir()]
            if any(info.file_size > MAX_ENTRY for info in listed) or sum(i.file_size for i in listed) > MAX_TOTAL:
                raise BundleRefused(TOO_LARGE)
            files = {info.filename: _read(archive, info) for info in listed}
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError) as error:
        raise BundleRefused("This copy isn't a Delve bundle.") from error
    if MANIFEST not in files:
        raise BundleRefused("This copy has no manifest.")
    manifest = _manifest(files[MANIFEST])
    rows: dict[str, list[dict[str, Any]]] = {}
    for name, content in files.items():
        if name.startswith(ROWS) and name.endswith(".json"):
            table = name.removeprefix(ROWS).removesuffix(".json")
            try:
                listed = json.loads(content)
            except ValueError as error:
                raise BundleRefused("This copy is damaged.") from error
            if not isinstance(listed, list) or not all(isinstance(row, dict) for row in listed):
                raise BundleRefused("This copy is damaged.")
            rows[table] = listed
    mimes = {row.get("sha256"): row.get("mime") for row in rows.get("blobs", [])}
    blobs: dict[str, tuple[bytes, str]] = {}
    for name, content in files.items():
        if not name.startswith(BLOBS):
            continue
        sha = name.removeprefix(BLOBS)
        if not SHA256.fullmatch(sha) or hashlib.sha256(content).hexdigest() != sha:
            raise BundleRefused("A picture in this copy is damaged.")
        mime = mimes.get(sha)
        if isinstance(mime, str):
            blobs[sha] = (content, mime)
    snapshot = Snapshot(
        kind=manifest.kind,
        item_id=manifest.item_id,
        head=manifest.head,
        rows=rows,
        blobs=frozenset(sha for sha in mimes if isinstance(sha, str)),
    )
    return manifest, snapshot, blobs


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """The entry's bytes, read no further than its declared size allows, so a size that lies can't fill memory."""
    with archive.open(info) as entry:
        content = entry.read(min(info.file_size, MAX_ENTRY) + 1)
    if len(content) > info.file_size:
        raise BundleRefused(TOO_LARGE)
    return content


def _manifest(content: bytes) -> Manifest:
    try:
        raw = json.loads(content)
    except ValueError as error:
        raise BundleRefused("This copy's manifest is damaged.") from error
    if not isinstance(raw, dict):
        raise BundleRefused("This copy's manifest is damaged.")
    format = raw.get("format")
    if isinstance(format, int) and not isinstance(format, bool) and format > FORMAT:
        raise BundleRefused("A newer Delve made this copy. Upgrade Delve to restore it.")
    if format != FORMAT or raw.get("kind") not in SNAPSHOT_KINDS:
        raise BundleRefused("This copy's manifest is damaged.")
    for key in ("item_id", "title", "head", "delve_version", "created_at"):
        if not isinstance(raw.get(key), str):
            raise BundleRefused("This copy's manifest is damaged.")
    return Manifest(
        format=format,
        kind=raw["kind"],
        item_id=raw["item_id"],
        title=raw["title"],
        head=raw["head"],
        delve_version=raw["delve_version"],
        created_at=raw["created_at"],
        module_id=raw.get("module_id"),
        revision=raw.get("revision"),
        setting=raw.get("setting"),
    )


def unpack_into(storage: Storage, data: bytes, *, replace: bool) -> list[str]:
    """Restore the bundle's item and answer its warnings: its blobs go into the blob store, then its rows, all in one
    transaction. `BundleRefused` (a `SnapshotRefused`) for a bundle Delve won't take; `SnapshotRefused` for one the
    database won't."""
    return restore_unpacked(storage, unpack(data), replace=replace)


def restore_unpacked(storage: Storage, unpacked: Unpacked, *, replace: bool) -> list[str]:
    """`unpack_into` for a bundle unpacked already: a restore reads its manifest first, and unpacks it once
    (DEL-171)."""
    _, snapshot, blobs = unpacked
    with storage.transaction():
        for content, mime in blobs.values():
            storage.blobs.put(content, mime)
        return storage.snapshots.restore(snapshot, replace=replace)
