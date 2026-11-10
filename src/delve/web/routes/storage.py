"""Storage (cloud storage plan Task 4): the backup store, the shared module library and the backup time. The owner's
alone (`Owner`): an organiser gets 403, since the backup store holds the whole install and the library's credential
is the owner's.

A credential comes in and goes into the data dir's files (`delve.cloud.connections`); it never comes back out. A
store's view says `set` and where it is (the container URL, or the endpoint and bucket), never the SAS's query string
or the secret key. A refused body is answered without echoing it (bodies are read raw, as Connections reads them), and
a store's failure is answered in Delve's own words (`StoreError`).

Saving a store probes it first: a backup store needs to write, overwrite and delete (`manage`), and a library needs at
least to list. Only saving and Test probe; the library's right they find is recorded in its file for the next start.
Each change publishes `preferences`, as Connections' changes do. The backup store and the library are never one store
(`connections.same_place`): saving one where the other is, or a folder inside the other's, is 422, before any probe.

`GET /api/storage` answers:

    {"backup": StoreView | null, "library": StoreView | null,
     "schedule": {"time": "HH:MM", "last_run": … | null}, "install_id": "ins_…"}

    StoreView = {"provider": "azure" | "s3" | "local", "label": str, "secret": "set" | "unset",
                 "right": "read" | "publish" | "manage" | null, "expires": ISO time | null,
                 "choice": "publish" | "manage" | null}

`right` is the library's right as saving or Test last probed it (null when the store didn't answer) and `manage` for the
backup store, which is saved only with it; `expires` is an Azure SAS's `se=`; `choice` is the owner's cap on an S3
library's write key. `last_run` is what the backup run records under `storage.settings["backup"]["last_run"]`
(plan Task 7), null before the first run:

    {"started_at": ISO time, "finished_at": ISO time, "uploaded": [title, …], "unchanged": int,
     "failed": [{"kind", "item_id", "title", "error"}, …], "status": "ok" | "partial" | "failed"}

and `running` says a run is going. `POST /api/storage/backup` (Back up now) starts one in the background and answers
202 at once, so it never holds up play; 409 while one runs, or when no backup store is set. Its end publishes
`preferences`, as a change does.

Files nothing uses (DEL-36): `GET /api/storage/unused` says what a prune would delete now, and
`POST /api/storage/unused/delete` deletes it, looking afresh, and says what went (`blobs.unused`, `blobs.prune`), both

    {"count": int, "size": int, "kept": int, "kinds": [{"mime": str | null, "count": int, "size": int}, …]}

`kinds` by size, largest first (`mime` null for files without their row); `kept` are those nothing names yet but too new
to go, a day's or a running job's. The delete publishes `preferences`.

Restore (plan Task 8) reads the backup store; 409 without one, 502 with the store's words when it fails:

- `GET /api/storage/backups` → `[{"install_id", "name", "updated_at"}, …]`, the installs it holds, the latest first;
- `GET /api/storage/backups/{install_id}` → `[{"kind", "item_id", "title", "hash", "size", "backed_up_at",
  "on_install", "exists_here"}, …]`, a campaign's also with `"module_id"` and `"setting_id"` (null for none); 404
  when the install has no index;
- `POST /api/storage/restore` `{"install_id", "items": [{"kind", "item_id"}, …], "replace": bool}` →
  `[{"kind", "item_id", "ok", "warnings", "error", "added"?}, …]` in the order restored; `error` is `"exists"` for
  an item here that `replace` didn't confirm. Each restored module publishes `modules`, campaign `campaigns` and
  setting `settings`, with its `id`.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from delve.cloud import backup, connections, restore
from delve.cloud.azure import sas_expiry
from delve.cloud.connections import StoreConfig, StoreKind, Stores
from delve.cloud.store import Gap, Missing, ObjectStore, Right, StoreError, probe_gap
from delve.images import thumbs
from delve.storage.interfaces import SNAPSHOT_KINDS, UnusedBlobs
from delve.web.auth import Owner
from delve.web.routes.connections import _changed, _object

router = APIRouter()

DEFAULT_TIME = backup.DEFAULT_TIME
SCHEDULE_KEY = backup.SCHEDULE_KEY
_TIME = backup.TIME
_INSTALL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ITEM_ID = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}")
UNUSED_GRACE = timedelta(days=1)
"""A blob put within this long stays, though nothing names it yet: what put it may name it in a moment."""
CONFIG_FIELDS = frozenset({"sas_url", "endpoint", "bucket", "access_key_id", "secret_access_key", "root", "right"})

NOT_FOR_BACKUPS = "This credential can't write and delete, so backups can't use it."
# Why a backup store's credential falls short, by what the probe was refused first, and for an Azure SAS the
# permission to add when it is made again.
BACKUP_GAPS: dict[Gap, str] = {
    "container": "The container isn't there: check its name in the URL, after the host, or create it in the storage.",
    "list": "This credential can't list the store, so backups can't use it.",
    "create": "This credential can read but not create, so backups can't use it.",
    "write": "This credential can create but not overwrite, so backups can't use it.",
    "delete": "This credential can create and overwrite but not delete, so backups can't use it.",
}
AZURE_GAPS: dict[Gap, str] = {
    "container": "In the Azure portal: the storage account's Data storage, Containers.",
    "list": "Make the SAS again with List (l).",
    "create": "Make the SAS again with Create (c), Write (w) and Delete (d).",
    "write": "Make the SAS again with Write (w) and Delete (d).",
    "delete": "Make the SAS again with Delete (d).",
}
CANT_LIST = "This credential can't list the library, so Delve can't use it."
SAME_STORE = "The backup store and the library must be different stores."
RIGHT_WORDS: dict[Right, str] = {
    "read": "Delve can read the library.",
    "publish": "Delve can read the library and publish to it.",
    "manage": "Delve can read the library, publish to it and manage it.",
}


@router.get("/api/storage")
def get_storage(request: Request, principal: Owner) -> dict:
    data_dir = request.app.state.config.data_dir
    return {
        "backup": _view(request, "backup"),
        "library": _view(request, "library"),
        "schedule": _schedule(request),
        "install_id": connections.install_id(data_dir),
    }


@router.put("/api/storage/schedule")
def put_schedule(request: Request, principal: Owner, raw: Annotated[Any, Body()] = None) -> dict:
    """`{"time": "HH:MM"}`, local time, stored in `storage.settings` under `backup`."""
    body = _object(raw, required={"time"})
    if not isinstance(body["time"], str) or not _TIME.fullmatch(body["time"]):
        raise HTTPException(status_code=422, detail="The time is HH:MM, such as 04:00.")
    request.app.state.storage.settings.update({"time": body["time"]}, within=SCHEDULE_KEY)
    _changed(request)
    return _schedule(request)


@router.post("/api/storage/backup")
async def back_up_now(request: Request, principal: Owner) -> JSONResponse:
    """Back up now: 202 with the schedule, the run going on behind; 409 while one runs or without a backup store."""
    state = request.app.state
    if state.stores.backup is None:
        raise HTTPException(status_code=409, detail="No backup store is set.")
    if await state.backups.start(state.storage, state.stores, state.config.data_dir) is None:
        raise HTTPException(status_code=409, detail="A backup is already running.")
    _changed(request)
    return JSONResponse(_schedule(request), status_code=202)


@router.get("/api/storage/unused")
async def get_unused(request: Request, principal: Owner) -> dict:
    storage = request.app.state.storage
    return _unused(await run_in_threadpool(storage.blobs.unused, UNUSED_GRACE))


@router.post("/api/storage/unused/delete")
async def delete_unused(request: Request, principal: Owner) -> dict:
    state = request.app.state
    gone = await run_in_threadpool(state.storage.blobs.prune, UNUSED_GRACE)
    await run_in_threadpool(thumbs.forget, state.config.data_dir, [blob.sha for blob in gone.blobs])
    _changed(request)
    return _unused(gone)


@router.get("/api/storage/backups")
async def get_backups(request: Request, principal: Owner) -> list[dict]:
    store = _backup_store(request)
    try:
        return await restore.backed_up_installs(store)
    except StoreError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None


@router.get("/api/storage/backups/{install_id}")
async def get_backup(request: Request, principal: Owner, install_id: str) -> list[dict]:
    store = _backup_store(request)
    if not _INSTALL_ID.fullmatch(install_id):
        raise HTTPException(status_code=404, detail="No backup of that install.")
    try:
        return await restore.backup_index(request.app.state.storage, store, install_id)
    except Missing:
        raise HTTPException(status_code=404, detail="No backup of that install.") from None
    except StoreError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None


@router.post("/api/storage/restore")
async def post_restore(request: Request, principal: Owner, raw: Annotated[Any, Body()] = None) -> list[dict]:
    """Restore the chosen items; an item here is restored over only with `replace`. Per item, its result."""
    body = _object(raw, required={"install_id", "items"}, optional={"replace"})
    install_id, items, replace = body["install_id"], body["items"], body.get("replace", False)
    if not isinstance(install_id, str) or not _INSTALL_ID.fullmatch(install_id):
        raise HTTPException(status_code=422, detail="Name the install to restore from.")
    if not isinstance(replace, bool):
        raise HTTPException(status_code=422, detail="replace is true or false.")
    if not isinstance(items, list) or not items or not all(_item(item) for item in items):
        raise HTTPException(status_code=422, detail="Choose the items to restore, each a kind and an id.")
    store = _backup_store(request)
    chosen = [(item["kind"], item["item_id"]) for item in items]
    results = await restore.restore_items(request.app.state.storage, store, install_id, chosen, replace=replace)
    events = request.app.state.events
    for result in results:
        if result["ok"]:
            events.publish(f"{result['kind']}s", {"id": result["item_id"]})
    return results


@router.put("/api/storage/{kind}")
async def put_store(request: Request, principal: Owner, kind: str, raw: Annotated[Any, Body()] = None):
    """The store's config; an absent secret keeps the stored one. Probed before it is saved: 422 with the reason when
    Delve can't use it, and nothing is stored."""
    kind = _kind(kind)
    body = _object(raw, required={"provider"}, optional=CONFIG_FIELDS)
    data_dir = request.app.state.config.data_dir
    try:
        config = connections.check_config(connections.kept_secret(data_dir, kind, StoreConfig(**body)))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=_words(error)) from None
    other = connections.load_store(data_dir, "library" if kind == "backup" else "backup")
    if other is not None and connections.same_place(config, other):
        raise HTTPException(status_code=422, detail=SAME_STORE)
    stores: Stores = request.app.state.stores
    store = stores.open(config)
    try:
        right, gap = await _right(store, kind, config)
        if kind == "backup" and right != "manage":
            raise HTTPException(status_code=422, detail=_short_of(config, gap))
        if right is None:
            raise HTTPException(status_code=422, detail=CANT_LIST)
        connections.save_store(data_dir, kind, config, keep_secret=False)
        if kind == "library":
            connections.record_right(data_dir, right)
    except StoreError as error:
        await store.aclose()
        raise HTTPException(status_code=422, detail=str(error)) from None
    except BaseException:
        await store.aclose()
        raise
    await stores.reload(kind, opened=store)
    _changed(request)
    return _view(request, kind)


@router.delete("/api/storage/{kind}")
async def delete_store(request: Request, principal: Owner, kind: str) -> None:
    kind = _kind(kind)
    connections.save_store(request.app.state.config.data_dir, kind, None, keep_secret=False)
    await request.app.state.stores.reload(kind)
    _changed(request)


@router.post("/api/storage/{kind}/test")
async def check_store(request: Request, principal: Owner, kind: str) -> dict:
    """Probe the saved store: `{"ok", "right", "message"}`. A library's right found here becomes its right, and is
    recorded for the next start."""
    kind = _kind(kind)
    stores: Stores = request.app.state.stores
    config = connections.load_store(request.app.state.config.data_dir, kind)
    store = stores.backup if kind == "backup" else stores.library
    if config is None or store is None:
        return {"ok": False, "right": None, "message": "No backup store is set." if kind == "backup" else
                "No library is set."}
    try:
        right, gap = await _right(store, kind, config)
    except StoreError as error:
        right, message = None, str(error)
    else:
        message = _message(kind, right, _short_of(config, gap))
    if kind == "library" and store is stores.library:
        connections.record_right(request.app.state.config.data_dir, right)
        stores.library_right = right
    ok = right == "manage" if kind == "backup" else right is not None
    return {"ok": ok, "right": right, "message": message}


async def _right(store: ObjectStore, kind: StoreKind, config: StoreConfig) -> tuple[Right | None, Gap | None]:
    """The credential's right, and for a backup store what it was refused first (`probe_gap`)."""
    if kind == "library":
        return await connections.library_right(store, config), None
    return await probe_gap(store)


def _backup_store(request: Request) -> ObjectStore:
    store = request.app.state.stores.backup
    if store is None:
        raise HTTPException(status_code=409, detail="No backup store is set.")
    return store


def _item(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and set(item) == {"kind", "item_id"}
        and item["kind"] in SNAPSHOT_KINDS
        and isinstance(item["item_id"], str)
        and _ITEM_ID.fullmatch(item["item_id"]) is not None
    )


def _kind(kind: str) -> StoreKind:
    if kind not in connections.KINDS:
        raise HTTPException(status_code=404, detail="unknown store")
    return cast(StoreKind, kind)


def _short_of(config: StoreConfig, gap: Gap | None) -> str:
    """Why a backup store's credential falls short: what it was refused, and on Azure the permission to add."""
    if gap is None:
        return NOT_FOR_BACKUPS
    hint = AZURE_GAPS[gap] if config.provider == "azure" else ""
    return f"{BACKUP_GAPS[gap]} {hint}".strip()


def _message(kind: StoreKind, right: Right | None, short_of: str = NOT_FOR_BACKUPS) -> str:
    if kind == "backup":
        return "Delve can back up to this store." if right == "manage" else short_of
    return RIGHT_WORDS[right] if right is not None else CANT_LIST


def _view(request: Request, kind: StoreKind) -> dict[str, Any] | None:
    stores: Stores = request.app.state.stores
    store = stores.backup if kind == "backup" else stores.library
    config = connections.load_store(request.app.state.config.data_dir, kind)
    if store is None or config is None:
        return None
    return {
        "provider": config.provider,
        "label": store.label,
        "secret": "set" if config.secret else "unset",
        "right": "manage" if kind == "backup" else stores.library_right,
        "expires": sas_expiry(config.sas_url) if config.provider == "azure" else None,
        "choice": (config.right or connections.DEFAULT_S3_RIGHT) if config.provider == "s3" else None,
    }


def _schedule(request: Request) -> dict[str, Any]:
    state = request.app.state
    return {**backup.schedule(state.storage), "running": state.backups.running}


def _words(error: Exception) -> str:
    """A refusal's reason: `check_config`'s own words, or, for a body `StoreConfig` can't take, a fixed one."""
    return str(error) if isinstance(error, ValueError) else "Send the store's fields as text."


def _unused(found: UnusedBlobs) -> dict:
    kinds: dict[str | None, dict[str, Any]] = {}
    for blob in found.blobs:
        kind = kinds.setdefault(blob.mime, {"mime": blob.mime, "count": 0, "size": 0})
        kind["count"] += 1
        kind["size"] += blob.size
    listed = sorted(kinds.values(), key=lambda kind: (-kind["size"], kind["mime"] or ""))
    return {"count": len(found.blobs), "size": found.size, "kept": found.kept, "kinds": listed}
