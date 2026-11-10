"""The shared module library (cloud storage plan Task 9): modules published to a store that friends' installs browse,
download from and publish to, by right.

Every version of an entry is two new objects, `<entry key>/v<N>/module.dscn` and then its `entry.json`, written with
`create`, which never overwrites. Two installs publishing the same entry at once can't both have `v<N>`: the second
gets `Exists`, reads the versions again and takes the next number. A version is listed once its `entry.json` is there,
so one still uploading is not. There is no shared index, which would need the overwrite right for every publish.

Deleting a version first creates its tombstone, `<entry key>/v<N>/deleted`, also with `create`, and never removes it:
a tombstoned version is never listed, and as the numbering counts it, its number is never used again, so an install
that downloaded it is offered the next version published.

Rights (`read` < `publish` < `manage`): `read` browses and downloads; `publish` adds entries, and versions to entries
this install published; `manage` also adds versions to any entry, and deletes entries and versions. A module
downloaded from another install's entry is published as a new entry of its own.

`list_entries` shows each entry's newest version. An `entry.json` that doesn't parse, or is of a newer format than
this Delve reads, or is larger than `ENTRY_LIMIT`, is left out with a warning naming its key, so one bad entry never
fails the whole tab; the probe's
objects (`.delve-probe/`, which a create-only credential can't delete) aren't entries. A `module.dscn` is read within
`MODULE_LIMIT`, and one the listing says is larger isn't fetched at all.

A module's hash (`module_hash`) is over its `.dscn` export, so an unchanged module hashes the same: a publish of one is
`UpToDate`, and a downloaded copy whose hash differs from the one recorded at download was edited here (`edited`).

Updates (Task 10): `check_updates` finds the downloaded modules whose entry has a newer version; the app keeps them on
`app.state.stores.updates`, checked at start, at each day's backup time and whenever the library is read. `update`
makes the newest version a new revision of the same module, so a campaign stays on the revision it pinned and a new
one gets the new content; with `keep_copy` the module as it is here is first kept as a module of its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import secrets
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from delve.cloud import backup
from delve.cloud.store import (
    ENTRY_LIMIT,
    MODULE_LIMIT,
    PROBE_PREFIX,
    TOO_LARGE,
    Exists,
    Missing,
    ObjectStore,
    Right,
    StoreError,
)
from delve.maps.geo import pictures
from delve.maps.geo.tiles import PictureRefused
from delve.modules.dscn import MANIFEST, check
from delve.modules.exporter import export_module
from delve.modules.importer import import_bundle

if TYPE_CHECKING:
    from delve.domain.modules import Module
    from delve.modules.dscn import Bundle
    from delve.modules.importer import ImportResult
    from delve.storage.interfaces import Storage

log = logging.getLogger(__name__)

ENTRY_FORMAT = 1
MODULE_FILE = "module.dscn"
ENTRY_FILE = "entry.json"
TOMBSTONE = "deleted"
KEY_PREFIX = "lib_"
KEY = re.compile(r"lib_[0-9a-f]{12}")
_VERSION = re.compile(r"(lib_[0-9a-f]{12})/v([1-9][0-9]{0,8})/(.+)")

READ_ONLY = "This library lets Delve read only, so it can't publish to it."
NOT_YOURS = "Another install published this entry; only the library's managers can add a version to it."
MANAGERS_ONLY = "Only the library's managers can delete from it."
MY_VERSION = "{title} (my version)"
MODULE_TOO_LARGE = "The library's copy of this module is larger than Delve takes."


class UpToDate(Exception):
    """The module is the same as its entry's newest version: there is nothing new to publish."""


class Unreadable(ValueError):
    """An `entry.json` this Delve can't read: it doesn't parse, is of a newer format, or isn't its version's."""


class Unpublishable(Exception):
    """The module's export doesn't validate, so no install could import it from the library."""


class NotFromLibrary(Exception):
    """The module wasn't downloaded from the library, so there is nothing to update it from."""


@dataclass(frozen=True)
class Entry:
    """One version of a library entry, as its `entry.json` says. `created_at` is the entry's first version's time and
    `updated_at` this version's; `hash` is the module's (`module_hash`); `publisher` the install id that wrote it."""

    key: str
    version: int
    title: str
    summary: str
    author: str
    created_at: str
    updated_at: str
    size: int
    hash: str
    publisher: str
    format: int


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def object_name(key: str, version: int, file: str) -> str:
    return f"{key}/v{version}/{file}"


def module_hash(storage: Storage, module_id: str) -> str:
    """The sha256 over the module's `.dscn` export's entries, sorted by name. The manifest's scenario `id` is left
    out: a module made in Delve has none, and its export makes a fresh one each time.

    An export reads every picture and parses every map: seconds for a big module, on every module list (DEL-163). So
    each module's hash is kept for the state it was made from: when the module's row and its source were last
    written, and its banner, which changes without the row's time. What else an export holds can't change without
    those (pictures are named by the sha256 of their bytes, and a map's includes come from Delve's own library)."""
    module = storage.modules.get(module_id)
    if module is None:
        raise KeyError(module_id)
    banner = module.banner
    state = (
        module_id,
        module.updated_at,
        storage.module_sources.updated_at(module_id),
        (banner.blob, banner.mime, banner.source) if banner is not None else None,
    )
    known = _HASHES.get(state)
    if known is None:
        known = _hash(export_module(storage, module_id))
        if len(_HASHES) >= _HASHES_KEPT:
            _HASHES.clear()
        _HASHES[state] = known
    return known


# A module's state (see `module_hash`) → its export's hash; dropped whole when it fills.
_HASHES: dict[tuple[Any, ...], str] = {}
_HASHES_KEPT = 512


def _hash(bundle: Bundle) -> str:
    manifest = {key: value for key, value in bundle.manifest.items() if key != "id"}
    entries = {MANIFEST: json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode(), **bundle.files}
    digest = hashlib.sha256()
    for name, data in sorted(entries.items()):
        digest.update(f"{name}\0{hashlib.sha256(data).hexdigest()}\n".encode())
    return digest.hexdigest()


def _export(storage: Storage, module_id: str) -> tuple[bytes, str]:
    """The module's `.dscn` zip and its hash; `Unpublishable` when the export doesn't validate."""
    bundle = export_module(storage, module_id)
    errors = [str(d) for d in check(bundle).diagnostics if d.severity == "error"]
    if errors:
        raise Unpublishable("The module's export doesn't validate: " + "; ".join(errors))
    return bundle.to_zip(), _hash(bundle)


async def _versions(store: ObjectStore, key: str) -> dict[int, dict[str, int]]:
    """Each version of the entry with the files it has so far, and their sizes as the listing gives them."""
    versions: dict[int, dict[str, int]] = {}
    for listed in await store.list(f"{key}/"):
        match = _VERSION.fullmatch(listed.name)
        if match is not None and match[1] == key:
            versions.setdefault(int(match[2]), {})[match[3]] = listed.size
    return versions


def _parse(raw: bytes, key: str, version: int) -> Entry:
    """The entry its `entry.json` says; a `ValueError` (`Unreadable`, or the JSON's own) when this Delve can't read
    it."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise Unreadable("not an object")
    if not isinstance(data.get("format"), int) or data["format"] > ENTRY_FORMAT:
        raise Unreadable("a newer format")
    values = {}
    for field in fields(Entry):
        value = data.get(field.name)
        wanted = int if field.name in ("version", "size", "format") else str
        if not isinstance(value, wanted) or isinstance(value, bool):
            raise Unreadable(f"no {field.name}")
        values[field.name] = value
    entry = Entry(**values)
    if (entry.key, entry.version) != (key, version):
        raise Unreadable("another version's")
    return entry


async def _newest(store: ObjectStore, key: str, versions: dict[int, dict[str, int]]) -> Entry | None:
    """The entry's newest version that has its `entry.json` and no tombstone; `ValueError` when that one can't be read,
    or is larger than `ENTRY_LIMIT`."""
    listed = [version for version, files in versions.items() if ENTRY_FILE in files and TOMBSTONE not in files]
    if not listed:
        return None
    version = max(listed)
    if versions[version][ENTRY_FILE] > ENTRY_LIMIT:
        raise Unreadable("too large")
    try:
        raw = await store.get(object_name(key, version, ENTRY_FILE), limit=ENTRY_LIMIT)
    except StoreError as error:
        if str(error) == TOO_LARGE:  # the listing said less than the object is
            raise Unreadable("too large") from None
        raise
    return _parse(raw, key, version)


async def _module(store: ObjectStore, entry: Entry, versions: dict[int, dict[str, int]]) -> bytes:
    """The version's `module.dscn`, read within `MODULE_LIMIT`; `StoreError` for a larger one, which isn't fetched at
    all when the listing says so."""
    if versions[entry.version].get(MODULE_FILE, 0) > MODULE_LIMIT:
        raise StoreError(MODULE_TOO_LARGE)
    try:
        return await store.get(object_name(entry.key, entry.version, MODULE_FILE), limit=MODULE_LIMIT)
    except StoreError as error:
        if str(error) == TOO_LARGE:
            raise StoreError(MODULE_TOO_LARGE) from None
        raise


async def list_entries(store: ObjectStore) -> tuple[list[Entry], list[str]]:
    """Each entry's newest version, newest `updated_at` first, and a warning for each entry left out."""
    keys: dict[str, dict[int, dict[str, int]]] = {}
    for listed in await store.list():
        if listed.name.startswith(PROBE_PREFIX):
            continue  # a Test with a create-only credential can't remove its probe object
        match = _VERSION.fullmatch(listed.name)
        if match is not None:
            keys.setdefault(match[1], {}).setdefault(int(match[2]), {})[match[3]] = listed.size
    entries, warnings = [], []
    for key in sorted(keys):
        try:
            entry = await _newest(store, key, keys[key])
        except Missing:
            continue  # deleted while being listed
        except ValueError:
            log.warning("the library's entry %s can't be read", key)
            warnings.append(f"The library's entry {key} can't be read by this Delve, so it isn't listed.")
            continue
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda entry: entry.updated_at, reverse=True)
    return entries, warnings


async def publish(
    storage: Storage,
    store: ObjectStore,
    right: Right | None,
    module_id: str,
    *,
    author: str,
    install: str,
    now: Callable[[], datetime] = _utc_now,
) -> Entry:
    """Publish the module as its entry's next version, or as a new entry. `PermissionError` for the read right, or for
    a version on another install's entry without `manage`; `UpToDate` when the newest version has the same hash;
    `KeyError` for an unknown module; `Exists` when another publish took the next number twice."""
    if right not in ("publish", "manage"):
        raise PermissionError(READ_ONLY)
    module = storage.modules.get(module_id)
    if module is None:
        raise KeyError(module_id)
    data, digest = await asyncio.to_thread(_export, storage, module_id)

    key, versions, newest = module.library_key, {}, None
    if key is not None and KEY.fullmatch(key):
        versions = await _versions(store, key)
        try:
            newest = await _newest(store, key, versions)
        except ValueError:
            newest = None
    if newest is None or (module.library_origin == "downloaded" and newest.publisher != install):
        key, versions, newest = KEY_PREFIX + secrets.token_hex(6), {}, None
    elif newest.publisher != install and right != "manage":
        raise PermissionError(NOT_YOURS)
    elif newest.hash == digest:
        raise UpToDate("The library's newest version is the same as this module.")

    at = _iso(now())
    version = max(versions, default=0) + 1
    for attempt in range(2):
        entry = Entry(
            key=key,
            version=version,
            title=module.title,
            summary=_summary(module),
            author=newest.author if newest is not None else author,
            created_at=newest.created_at if newest is not None else at,
            updated_at=at,
            size=len(data),
            hash=digest,
            publisher=install,
            format=ENTRY_FORMAT,
        )
        try:
            await store.create(object_name(key, version, MODULE_FILE), data)
        except Exists:
            if attempt:
                raise
            # Another install took this number: read the versions again and take the next one.
            version = max(max(await _versions(store, key), default=0), version) + 1
            continue
        try:
            await store.create(object_name(key, version, ENTRY_FILE), _entry_json(entry))
        except BaseException:
            with contextlib.suppress(StoreError):
                await store.delete(object_name(key, version, MODULE_FILE))
            raise
        break
    storage.modules.set_library(
        module_id, key=key, version=version, hash=digest, origin="published", author=entry.author
    )
    return entry


async def download(storage: Storage, store: ObjectStore, key: str) -> Module:
    """A new local module from the entry's newest version, remembering the entry, the version, and the hash of what
    was downloaded. `Missing` when the library has no such entry; the import's own errors (`ScenarioError`,
    `ImportRefused`) when its `module.dscn` can't be imported."""
    if not KEY.fullmatch(key):
        raise Missing("The library has no such entry.")
    versions = await _versions(store, key)
    try:
        entry = await _newest(store, key, versions)
    except ValueError:
        raise Missing("The library's entry can't be read by this Delve.") from None
    if entry is None:
        raise Missing("The library has no such entry.")
    data = await _module(store, entry, versions)
    return await asyncio.to_thread(_import, storage, data, entry)


def _import(storage: Storage, data: bytes, entry: Entry) -> Module:
    module_id = _import_bundle(storage, data, entry.key).module.id
    digest = module_hash(storage, module_id)
    return storage.modules.set_library(
        module_id, key=entry.key, version=entry.version, hash=digest, origin="downloaded", author=entry.author
    )


def _import_bundle(storage: Storage, data: bytes, key: str | None) -> ImportResult:
    """A new module from the `.dscn` zip, with its world maps' pictures stored."""
    result = import_bundle(storage, data)
    for sha, mime in result.pictures:
        try:
            pictures.store_blob(storage, sha, mime)
        except (PictureRefused, LookupError):
            log.warning("a world map's picture of library entry %s can't be used", key)
    return result


def edited(storage: Storage, module: Module) -> bool:
    """Whether the module changed here since it was downloaded or published: its hash isn't the recorded one. A module
    that can't be exported any more was changed too."""
    try:
        return module_hash(storage, module.id) != module.library_hash
    except LookupError:
        return True


async def check_updates(storage: Storage, store: ObjectStore) -> dict[str, int]:
    """`{module id: newest version}` for each downloaded module whose entry has a newer version than it is at. An
    entry that is gone or can't be read is no update; `StoreError` when the library doesn't answer."""
    found = {}
    for module in _downloaded(storage.modules.list()):
        try:
            entry = await _newest(store, module.library_key, await _versions(store, module.library_key))
        except (Missing, ValueError):
            continue
        if entry is not None and entry.version > (module.library_version or 0):
            found[module.id] = entry.version
    return found


def newer_versions(modules: Iterable[Module], entries: Iterable[Entry]) -> dict[str, int]:
    """`check_updates` from a listing already read."""
    newest = {entry.key: entry.version for entry in entries}
    return {
        module.id: newest[module.library_key]
        for module in _downloaded(modules)
        if newest.get(module.library_key, 0) > (module.library_version or 0)
    }


def _downloaded(modules: Iterable[Module]) -> list[Module]:
    return [m for m in modules if m.library_origin == "downloaded" and m.library_key and KEY.fullmatch(m.library_key)]


def set_updates(state: Any, updates: dict[str, int]) -> None:
    """Keep the updates on `state.stores`, publishing `modules` for each module whose update changed."""
    stores = state.stores
    old, stores.updates = stores.updates, updates
    for module_id in sorted(old.keys() | updates.keys()):
        if old.get(module_id) != updates.get(module_id):
            state.events.publish("modules", {"id": module_id})


async def refresh_updates(state: Any) -> None:
    """Check the library for updates and keep them; without a library there are none. A library that doesn't answer
    keeps the updates as they were."""
    store = state.stores.library
    if store is None:
        set_updates(state, {})
        return
    try:
        updates = await check_updates(state.storage, store)
    except StoreError as error:
        log.warning("the library's updates couldn't be checked: %s", error)
        return
    if state.stores.library is store:  # not replaced while it was read
        set_updates(state, updates)


async def updates_loop(app: Any, *, tick: float = backup.TICK, now: Callable[[], datetime] = _utc_now) -> None:
    """Check for updates at once, then each day once the backup's time has passed, until cancelled."""
    last: str | None = None
    while True:
        try:
            if last is None or backup.due(backup.schedule(app.state.storage)["time"], last, now()):
                last = _iso(now())
                await refresh_updates(app.state)
        except Exception:
            log.exception("the library's update check failed")
        await asyncio.sleep(tick)


async def update(storage: Storage, store: ObjectStore, module_id: str, *, keep_copy: bool) -> Module:
    """Make the entry's newest version a new revision of the module, which campaigns don't follow: each stays on its
    pinned revision. With `keep_copy`, the module as it is here is first kept as a module of its own, titled "<title>
    (my version)". `KeyError` for an unknown module, `NotFromLibrary` for one not downloaded, `UpToDate` when it is at
    the newest version, `Missing` when the entry is gone, and the import's own errors (`ScenarioError`,
    `ImportRefused`) when the version can't be imported; then nothing changed."""
    module = storage.modules.get(module_id)
    if module is None:
        raise KeyError(module_id)
    if not _downloaded([module]):
        raise NotFromLibrary("This module didn't come from the library.")
    key = module.library_key
    versions = await _versions(store, key)
    try:
        entry = await _newest(store, key, versions)
    except ValueError:
        raise Missing("The library's entry can't be read by this Delve.") from None
    if entry is None:
        raise Missing("The library has no such entry.")
    if entry.version <= (module.library_version or 0):
        raise UpToDate("The module is at the library's newest version.")
    data = await _module(store, entry, versions)
    return await asyncio.to_thread(_update, storage, module, data, entry, keep_copy)


def _update(storage: Storage, module: Module, data: bytes, entry: Entry, keep_copy: bool) -> Module:
    made: list[str] = []
    try:
        if keep_copy:
            copy = _import_bundle(storage, export_module(storage, module.id).to_zip(), None).module
            made.append(copy.id)
            storage.modules.rename(copy.id, MY_VERSION.format(title=module.title))
        scratch = _import_bundle(storage, data, entry.key).module
        made.append(scratch.id)
        with storage.transaction():
            storage.modules.take_working_copy(module.id, scratch.id)
            storage.modules.delete(scratch.id)
            storage.revisions.snapshot(module.id)
            digest = module_hash(storage, module.id)
            return storage.modules.set_library(
                module.id, key=entry.key, version=entry.version, hash=digest, origin="downloaded", author=entry.author
            )
    except BaseException:
        for made_id in made:
            with contextlib.suppress(KeyError):
                storage.modules.delete(made_id)
        raise


async def delete_entry(store: ObjectStore, right: Right | None, key: str, version: int | None) -> None:
    """Delete one version of the entry, or with None every version: each gets its tombstone, then loses its files.
    `manage` only (`PermissionError`); `Missing` when there is nothing to delete."""
    if right != "manage":
        raise PermissionError(MANAGERS_ONLY)
    if not KEY.fullmatch(key):
        raise Missing("The library has no such entry.")
    versions = await _versions(store, key)
    if version is not None:
        versions = {version: versions[version]} if version in versions else {}
    doomed = {number: files for number, files in versions.items() if set(files) - {TOMBSTONE}}
    if not doomed:
        raise Missing("The library has no such entry." if version is None else "The library has no such version.")
    for number, files in sorted(doomed.items()):
        # The tombstone first, so a version half deleted is no longer listed, and its number never used again.
        with contextlib.suppress(Exists):
            await store.create(object_name(key, number, TOMBSTONE), b"")
        for file in sorted(set(files) - {TOMBSTONE}, key=lambda file: file != ENTRY_FILE):
            with contextlib.suppress(Missing):
                await store.delete(object_name(key, number, file))


def _summary(module: Module) -> str:
    summary = module.metadata.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


def _entry_json(entry: Entry) -> bytes:
    return (json.dumps(asdict(entry), indent=1, ensure_ascii=False) + "\n").encode()
