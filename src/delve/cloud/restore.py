"""Restore (cloud storage plan Task 8): the installs a backup store holds, what each one's index lists, and the owner's
choice of its items brought back under their own ids.

Every install writes `<install id>/index.json`, so a new machine (a new id) finds and restores the old one's backups
in the same store. An item of the index says whether it `exists_here`; a campaign's also names its module and setting
(`module_id`, `setting_id`), so the list can tick them along with it.

`restore_items` restores modules, then settings, then campaigns, each in its own transaction (`restore_unpacked`), so
one that is refused leaves the others restored. Each copy is fetched and unpacked once. A campaign whose module isn't here brings it from the same backup, and its
setting when the index has one, marked `added: true`; one whose module is here without the revision it plays is
refused with words that say to tick the module and replace it. An item that is here already is left alone unless `replace`:
its answer is `error: "exists"`, for the owner to confirm. A copy whose manifest names another item is refused. Every other failure is answered in Delve's words, never
with a credential: a store's `StoreError` words, a bundle's `SnapshotRefused` words, or a fixed sentence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from delve.cloud.backup import INDEX, object_name
from delve.cloud.bundles import Manifest, Unpacked, restore_unpacked, unpack
from delve.cloud.store import Missing, ObjectStore, StoreError
from delve.storage.interfaces import SNAPSHOT_KINDS, SnapshotKind, SnapshotRefused

if TYPE_CHECKING:
    from delve.storage.interfaces import Storage

log = logging.getLogger(__name__)

EXISTS = "exists"
NO_COPY = "This backup has no copy of it."
CANT_RESTORE = "Delve couldn't restore it."
ANOTHER_ITEM = "This copy is of another item."
LACKS_REVISION = "{title} here doesn't have the revision this campaign plays. Tick the module and replace it."
ORDER: tuple[SnapshotKind, ...] = ("module", "setting", "campaign")


async def backed_up_installs(store: ObjectStore) -> list[dict[str, Any]]:
    """Each install with an index in the store, `{install_id, name, updated_at}`, the latest first. An index that
    can't be read is left out."""
    installs = []
    for listed in await store.list():
        install_id, _, rest = listed.name.partition("/")
        if rest != INDEX:
            continue
        index = await _index(store, install_id)
        if index is None:
            continue
        name, updated_at = index.get("name"), index.get("updated_at")
        installs.append({
            "install_id": install_id,
            "name": name if isinstance(name, str) else install_id,
            "updated_at": updated_at if isinstance(updated_at, str) else listed.modified,
        })
    return sorted(installs, key=lambda install: install["updated_at"], reverse=True)


async def backup_index(storage: Storage, store: ObjectStore, install_id: str) -> list[dict[str, Any]]:
    """The items of the install's index, each with `exists_here`, and a campaign's with its `module_id` and
    `setting_id` (null when it has none, or when the index is older than they are). `Missing` when there's no index."""
    index = await _index(store, install_id)
    if index is None:
        raise Missing("This backup has no list of its items.")
    here = {kind: set(storage.snapshots.item_ids(kind)) for kind in SNAPSHOT_KINDS}
    items = []
    for item in _items(index):
        entry = {**item, "exists_here": item["item_id"] in here[item["kind"]]}
        if item["kind"] == "campaign":
            entry["module_id"] = item.get("module_id")
            entry["setting_id"] = item.get("setting_id")
        items.append(entry)
    return items


async def restore_items(
    storage: Storage,
    store: ObjectStore,
    install_id: str,
    items: list[tuple[SnapshotKind, str]],
    *,
    replace: bool,
) -> list[dict[str, Any]]:
    """Restore the items from the install's backup, with what their campaigns need; one result per item, in the order
    they were restored: `{kind, item_id, ok, warnings, error}`, and `added: true` on one a campaign brought along."""
    asked = list(dict.fromkeys(items))
    here = {kind: set(storage.snapshots.item_ids(kind)) for kind in SNAPSHOT_KINDS}
    try:
        listed = {(item["kind"], item["item_id"]) for item in _items(await _index(store, install_id) or {})}
    except StoreError:
        listed = set()

    copies: dict[tuple[str, str], Unpacked | SnapshotRefused | str] = {}

    async def fetch(kind: SnapshotKind, item_id: str) -> Unpacked | SnapshotRefused | str:
        """The item's bundle unpacked, once and in a thread (DEL-171: it was unpacked three times, on the loop); the
        refusal of a bundle Delve won't take; or the words of why it can't be had."""
        key = (kind, item_id)
        if key not in copies:
            try:
                data = await store.get(object_name(install_id, kind, item_id))
                copies[key] = await asyncio.to_thread(unpack, data)
            except Missing:
                copies[key] = NO_COPY
            except StoreError as error:
                copies[key] = str(error)
            except SnapshotRefused as error:
                copies[key] = error
            except Exception as error:  # noqa: BLE001 — a failure is answered, in Delve's words
                log.warning("the backup store failed: %s", type(error).__name__)
                copies[key] = CANT_RESTORE
        return copies[key]

    added: list[tuple[SnapshotKind, str]] = []
    for kind, item_id in asked:
        if kind != "campaign" or (item_id in here["campaign"] and not replace):
            continue
        got = await fetch(kind, item_id)
        if not isinstance(got, tuple):
            continue
        manifest = got[0]
        if (manifest.kind, manifest.item_id) != (kind, item_id):
            continue
        needs: list[tuple[SnapshotKind, str | None]] = [("module", manifest.module_id), ("setting", manifest.setting)]
        for need_kind, need_id in needs:
            if not need_id or need_id in here[need_kind] or (need_kind, need_id) in asked + added:
                continue
            if need_kind == "setting" and (need_kind, need_id) not in listed:
                continue  # a setting with nothing of its own on that install: there's nothing to bring
            added.append((need_kind, need_id))

    results = []
    for key in sorted(asked + added, key=lambda key: ORDER.index(key[0])):
        kind, item_id = key
        result: dict[str, Any] = {"kind": kind, "item_id": item_id, "ok": False, "warnings": [], "error": None}
        if item_id in here[kind] and not replace:
            result["error"] = EXISTS
        else:
            got = await fetch(kind, item_id)
            if not isinstance(got, tuple):
                result["error"] = str(got)
            elif _of_another_item(got[0], kind, item_id):
                result["error"] = ANOTHER_ITEM
            elif kind == "campaign" and (lacking := _lacking_revision(storage, got[0])) is not None:
                result["error"] = lacking
            else:
                try:
                    result["warnings"] = await asyncio.to_thread(restore_unpacked, storage, got, replace=replace)
                    result["ok"] = True
                except SnapshotRefused as error:
                    result["error"] = str(error)
                except Exception:
                    log.warning("couldn't restore %s %s", kind, item_id, exc_info=True)
                    result["error"] = CANT_RESTORE
        if key in added:
            result["added"] = True
        results.append(result)
    return results


def _of_another_item(manifest: Manifest, kind: SnapshotKind, item_id: str) -> bool:
    """Whether the copy's manifest names another item than the one asked for: a store may be written by anyone."""
    return (manifest.kind, manifest.item_id) != (kind, item_id)


def _lacking_revision(storage: Storage, manifest: Manifest) -> str | None:
    """When the campaign's module is here without the revision it plays, the words that say to replace it."""
    if manifest.module_id is None or manifest.revision is None:
        return None
    module = storage.modules.get(manifest.module_id)
    if module is None or storage.revisions.get(module.id, manifest.revision) is not None:
        return None
    return LACKS_REVISION.format(title=module.title)


async def _index(store: ObjectStore, install_id: str) -> dict[str, Any] | None:
    """The install's index; None when it isn't there or is damaged."""
    try:
        raw = json.loads(await store.get(f"{install_id}/{INDEX}"))
    except Missing:
        return None
    except ValueError:
        log.warning("the backup's index of %s is damaged", install_id)
        return None
    return raw if isinstance(raw, dict) else None


def _items(index: dict[str, Any]) -> list[dict[str, Any]]:
    items = index.get("items")
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict) and item.get("kind") in SNAPSHOT_KINDS and isinstance(item.get("item_id"), str)
    ]
