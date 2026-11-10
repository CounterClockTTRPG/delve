"""The backup run and its schedule (cloud storage plan Task 7): every module, campaign and setting whose bundle changed
goes to the backup store, latest copy only, as `<install id>/<kind>s/<id>.<ext>`, and `<install id>/index.json` lists
everything the store holds for this install (a campaign's entry with its `module_id` and `setting_id`, for restore).

An item is unchanged when its bundle hashes to what `backup_items` recorded at its last backup and the store's index
lists it at that hash, so a new backup store gets everything. An item is recorded only once its put succeeded: one
that failed keeps its old record (or none) and goes up at the next run (Review Focus 3). A run with failures says
`partial` (or `failed`, when nothing went up) and lists each failure in Delve's words, never as a success, and never
with a credential: a store's failure is its `StoreError` words, anything else a fixed sentence.

An item deleted here stays in the index, `on_install: false`; nothing is pruned. When the old index can't be read
(other than not being there yet), the run stops before uploading, since a new index would lose those items.

Packing runs in a worker thread and the store is awaited, so a run never holds up a beat or a conversion. One run at a
time: `start` answers None while one runs (Back up now's 409). `schedule_loop` starts a run when one is `due`: the
owner's time today (local time, default 04:00) has passed and the last run started before it, which also runs a
backup missed while Delve was down at the next start. A run that failed as a whole is tried again at the next
scheduled time, or by Back up now, never at the next tick.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from delve.cloud import connections
from delve.cloud.bundles import EXTENSIONS, Packed, pack
from delve.cloud.store import Missing, ObjectStore, StoreError
from delve.storage.interfaces import SNAPSHOT_KINDS, BackupItem, SnapshotKind

if TYPE_CHECKING:
    from delve.storage.interfaces import Storage

log = logging.getLogger(__name__)

SCHEDULE_KEY = "backup"
"""Where `storage.settings` keeps the backup's `time` and its `last_run`."""
DEFAULT_TIME = "04:00"
TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
TICK = 60
"""Seconds between the schedule's checks."""

CANT_PACK = "Delve couldn't pack it."
NOT_TAKEN = "The store didn't take it."
UNFINISHED = "Delve couldn't finish the backup."
INDEX = "index.json"
INDEX_TITLE = "The backup's list"

Status = Literal["ok", "partial", "failed"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


@dataclass
class RunResult:
    """One run: when, the titles it uploaded, how many were unchanged, and each failure `{kind, item_id, title,
    error}` (an index that couldn't be written or read is `kind: "index"`)."""

    started_at: str
    finished_at: str
    uploaded: list[str] = field(default_factory=list)
    unchanged: int = 0
    failed: list[dict[str, str]] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if not self.failed:
            return "ok"
        return "partial" if self.uploaded else "failed"

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "status": self.status}


def object_name(install_id: str, kind: SnapshotKind, item_id: str) -> str:
    return f"{install_id}/{kind}s/{item_id}.{EXTENSIONS[kind]}"


async def run_backup(
    storage: Storage,
    store: ObjectStore,
    install_id: str,
    *,
    now: Callable[[], datetime] = _utc_now,
    name: str | None = None,
) -> RunResult:
    """Back up what changed to `store` and store the result as the last run. `name` is the install's name in the
    index (the machine's, by default). A run that breaks off, by an exception or cancelled, is stored too, with
    `UNFINISHED` as a failure, so it never shows an earlier run's `ok`; a cancellation is raised again."""
    result = RunResult(started_at=_iso(now()), finished_at="")
    try:
        await _run(storage, store, install_id, now, name, result)
    except BaseException as error:
        if isinstance(error, Exception):
            log.exception("the backup run broke off")
        result.failed.append(_failure("index", INDEX, INDEX_TITLE, UNFINISHED))
        _finish(storage, result, now)
        if not isinstance(error, Exception):
            raise
        return result
    return _finish(storage, result, now)


async def _run(
    storage: Storage,
    store: ObjectStore,
    install_id: str,
    now: Callable[[], datetime],
    name: str | None,
    result: RunResult,
) -> None:
    try:
        old = await _read_index(store, install_id)
    except StoreError as error:
        result.failed.append(_failure("index", INDEX, INDEX_TITLE, str(error)))
        return
    listed = {(item["kind"], item["item_id"]): item for item in old}

    here = {(kind, item_id) for kind in SNAPSHOT_KINDS for item_id in storage.snapshots.item_ids(kind)}
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for kind, item_id in sorted(here, key=lambda key: (SNAPSHOT_KINDS.index(key[0]), key[1])):
        entry = await _back_up(storage, store, install_id, kind, item_id, listed.get((kind, item_id)), now, result)
        if entry is not None:
            entries[(kind, item_id)] = entry
    for key, item in listed.items():
        if key not in entries:
            entries[key] = {**item, "on_install": False}
    index = {
        "install_id": install_id,
        "name": name if name is not None else socket.gethostname(),
        "updated_at": _iso(now()),
        "items": [entries[key] for key in sorted(entries)],
    }
    try:
        await store.put(f"{install_id}/{INDEX}", json.dumps(index, ensure_ascii=False, indent=1).encode())
    except Exception as error:  # noqa: BLE001 — a failure is listed, in Delve's words
        result.failed.append(_failure("index", INDEX, INDEX_TITLE, _words(error)))


async def _back_up(
    storage: Storage,
    store: ObjectStore,
    install_id: str,
    kind: SnapshotKind,
    item_id: str,
    listed: dict[str, Any] | None,
    now: Callable[[], datetime],
    result: RunResult,
) -> dict[str, Any] | None:
    """Back up one item; answer its index entry, or None when the store has no copy of it. When it fails, the entry is
    the old index's: what the store still holds of it, if anything."""
    recorded = storage.backup_items.get(kind, item_id)
    try:
        packed: Packed = await asyncio.to_thread(pack, storage, kind, item_id)
    except Exception:
        if not _on_install(storage, kind, item_id):
            return None  # deleted while the run went on: the old index's entry stays, as no longer here
        log.warning("couldn't pack %s %s for the backup", kind, item_id, exc_info=True)
        result.failed.append(_failure(kind, item_id, _title(storage, kind, item_id), CANT_PACK))
        return _kept(listed)

    if recorded is not None and recorded.hash == packed.hash and listed is not None and listed["hash"] == packed.hash:
        result.unchanged += 1
        return _entry(storage, kind, item_id, packed.title, recorded)
    try:
        await store.put(object_name(install_id, kind, item_id), packed.data)
    except Exception as error:  # noqa: BLE001 — a failure is listed, in Delve's words
        result.failed.append(_failure(kind, item_id, packed.title, _words(error)))
        return _kept(listed)
    item = BackupItem(kind, item_id, packed.hash, len(packed.data), _iso(now()))
    storage.backup_items.put(item)
    result.uploaded.append(packed.title)
    return _entry(storage, kind, item_id, packed.title, item)


async def _read_index(store: ObjectStore, install_id: str) -> list[dict[str, Any]]:
    """The old index's items; none when it isn't there yet or is damaged."""
    try:
        raw = json.loads(await store.get(f"{install_id}/{INDEX}"))
    except Missing:
        return []
    except ValueError:
        log.warning("the backup's index of %s is damaged; it is written anew", install_id)
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return []
    return [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("kind") in SNAPSHOT_KINDS
        and isinstance(item.get("item_id"), str)
        and isinstance(item.get("hash"), str)
    ]


def _entry(storage: Storage, kind: str, item_id: str, title: str, item: BackupItem) -> dict[str, Any]:
    """The item's index entry; a campaign's names its module and setting, so the Restore list can bring them along."""
    entry = {
        "kind": kind,
        "item_id": item_id,
        "title": title,
        "hash": item.hash,
        "size": item.size,
        "backed_up_at": item.backed_up_at,
        "on_install": True,
    }
    if kind == "campaign":
        campaign = storage.campaigns.get(item_id)
        entry["module_id"] = campaign.module_id if campaign is not None else None
        entry["setting_id"] = (campaign.setting or None) if campaign is not None else None
    return entry


def _kept(listed: dict[str, Any] | None) -> dict[str, Any] | None:
    return {**listed, "on_install": True} if listed is not None else None


def _failure(kind: str, item_id: str, title: str, error: str) -> dict[str, str]:
    return {"kind": kind, "item_id": item_id, "title": title, "error": error}


def _words(error: Exception) -> str:
    """A store's own words (a `StoreError` never holds a credential); for anything else, a fixed sentence."""
    if isinstance(error, StoreError):
        return str(error)
    log.warning("the backup store failed: %s", type(error).__name__)
    return NOT_TAKEN


def _on_install(storage: Storage, kind: SnapshotKind, item_id: str) -> bool:
    return item_id in storage.snapshots.item_ids(kind)


def _title(storage: Storage, kind: SnapshotKind, item_id: str) -> str:
    try:
        return storage.snapshots.title(kind, item_id)
    except KeyError:
        return item_id


def _finish(storage: Storage, result: RunResult, now: Callable[[], datetime]) -> RunResult:
    result.finished_at = _iso(now())
    storage.settings.update({"last_run": result.to_json()}, within=SCHEDULE_KEY)
    if result.failed:
        log.warning("backup %s: %d failed, %d uploaded", result.status, len(result.failed), len(result.uploaded))
    return result


# ----- the schedule -----


def due(schedule_time: str, last_run_at: str | None, now: datetime) -> bool:
    """True when today's `schedule_time` (HH:MM, local time) has passed and the last run started before it; a naive
    `now` is local time."""
    local = now.astimezone()
    hour, minute = (int(part) for part in schedule_time.split(":"))
    scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local < scheduled:
        return False
    if last_run_at is None:
        return True
    try:
        last = datetime.fromisoformat(last_run_at)
    except ValueError:
        return True
    return last.astimezone() < scheduled


def schedule(storage: Storage) -> dict[str, Any]:
    """The stored `{time, last_run}`, the time `DEFAULT_TIME` when none is set."""
    stored = storage.settings.load().get(SCHEDULE_KEY)
    stored = stored if isinstance(stored, dict) else {}
    time = stored.get("time")
    last_run = stored.get("last_run")
    return {
        "time": time if isinstance(time, str) and TIME.fullmatch(time) else DEFAULT_TIME,
        "last_run": last_run if isinstance(last_run, dict) else None,
    }


class Backups:
    """The one backup run at a time (on `app.state.backups`), shared by the schedule and Back up now."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.task: asyncio.Task[RunResult | None] | None = None
        self.on_finish: Callable[[RunResult], None] | None = None

    @property
    def running(self) -> bool:
        return self.lock.locked()

    async def start(self, storage: Storage, stores: connections.Stores, data_dir) -> asyncio.Task | None:
        """Start a run in the background; None while one runs, or when no backup store is set."""
        store = stores.backup
        if store is None or self.lock.locked():
            return None
        await self.lock.acquire()  # free, so this takes it at once: no second run can start in between
        self.task = asyncio.create_task(self._run(storage, store, connections.install_id(data_dir)))
        return self.task

    async def _run(self, storage: Storage, store: ObjectStore, install_id: str) -> RunResult | None:
        try:
            result = await run_backup(storage, store, install_id)
        except Exception:
            log.exception("the backup run failed")
            return None
        finally:
            self.lock.release()
        if self.on_finish is not None:
            self.on_finish(result)
        return result

    async def stop(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


async def schedule_loop(app: Any, *, tick: float = TICK, now: Callable[[], datetime] = _utc_now) -> None:
    """Start a backup whenever one is due, checking at once and then every `tick` seconds, until cancelled."""
    state = app.state
    tried: str | None = None  # when this loop last started one, should its last run not have been stored
    while True:
        try:
            current = schedule(state.storage)
            last = current["last_run"]
            at = now()
            if (
                state.stores.backup is not None
                and due(current["time"], last and last.get("started_at"), at)
                and due(current["time"], tried, at)
            ):
                tried = _iso(at)
                await state.backups.start(state.storage, state.stores, state.config.data_dir)
        except Exception:
            log.exception("the backup schedule's check failed")
        await asyncio.sleep(tick)
