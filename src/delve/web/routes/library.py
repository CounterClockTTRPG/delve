"""The library (cloud storage plan Task 9): browse, download, publish and delete, for organisers (`Organiser`). The
library's store and its right are the owner's to set (Storage); here they are only used, and each answer is in
Delve's own words, never a credential. Every route answers 409 when no library store is set up, and 502 with the
store's words when it fails.

- `GET /api/library` → `{"right": "read" | "publish" | "manage" | null, "entries": [Entry + {"local": {"module_id",
  "origin", "version"} | null}, …], "warnings": [str, …]}`, the newest updated first. `local` is the module here
  that came from or went to the entry. An entry this Delve can't read is left out, with a warning.
- `POST /api/library/download` `{"key"}` → the new module, as `GET /api/modules/{id}` answers it; 404 for an entry
  the library hasn't.
- `POST /api/modules/{id}/publish` `{"author"?}` → the entry: the module's next version, or a new entry. The author
  is the account's display name (or the seat's name, else the module's library author, else "Delve", never the
  machine's name) unless the body names one; an entry keeps the author of its first version. 403 for the read
  right, or for a version on another install's entry without `manage`; 409 when it is up to date with the library,
  or when another publish took the next number twice.
- `DELETE /api/library/{key}?version=N` → 204; every version without `version`. 403 without `manage`. Each deleted
  version keeps its tombstone, so its number is never published again; deleting it again is 404.
- `POST /api/modules/{id}/library-update` `{"keep_copy": bool}` → the module, at the entry's newest version as a new
  revision; its campaigns stay on the revisions they pinned. `keep_copy` first keeps the module as it is here as a
  module of its own, "<title> (my version)". 409 for a module not downloaded from the library, or one at the newest
  version; 404 when the library hasn't the entry any more.

Downloading, publishing and updating publish `modules` with the module's id, and so does a change in the library's
updates, which reading the library checks again (`library.set_updates`).
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from starlette.responses import Response

from delve.cloud import connections, library
from delve.cloud.connections import Stores
from delve.cloud.store import Exists, Missing, ObjectStore, StoreError
from delve.modules.dscn import ScenarioError
from delve.modules.importer import ImportRefused
from delve.web.auth import Organiser, Principal
from delve.web.routes.connections import _object
from delve.web.routes.modules import changed, get_module, module_json, updates_of

router = APIRouter()

NO_LIBRARY = "No library store is set up."
NO_AUTHOR = "Delve"
AUTHOR_LIMIT = 100


@router.get("/api/library")
async def get_library(request: Request, principal: Organiser) -> dict[str, Any]:
    stores, store = await _library(request)
    try:
        entries, warnings = await library.list_entries(store)
    except StoreError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    modules = request.app.state.storage.modules.list()
    library.set_updates(request.app.state, library.newer_versions(modules, entries))
    local: dict[str, dict[str, Any]] = {}
    for module in modules:
        if module.library_key is not None and module.library_key not in local:
            local[module.library_key] = {
                "module_id": module.id, "origin": module.library_origin, "version": module.library_version
            }
    return {
        "right": stores.library_right,
        "entries": [{**dataclasses.asdict(entry), "local": local.get(entry.key)} for entry in entries],
        "warnings": warnings,
    }


@router.post("/api/library/download")
async def post_download(request: Request, principal: Organiser, raw: Annotated[Any, Body()] = None) -> dict:
    body = _object(raw, required={"key"})
    if not isinstance(body["key"], str):
        raise HTTPException(status_code=422, detail="Name the entry to download.")
    _, store = await _library(request)
    storage = request.app.state.storage
    try:
        module = await library.download(storage, store, body["key"])
    except Missing as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (ScenarioError, ImportRefused):
        raise HTTPException(status_code=502, detail="The library's copy of this module can't be imported.") from None
    except StoreError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    changed(request, module.id)
    return module_json(module, storage, updates=updates_of(request))


@router.post("/api/modules/{module_id}/publish")
async def post_publish(
    request: Request, principal: Organiser, module_id: str, raw: Annotated[Any, Body()] = None
) -> dict:
    body = _object(raw if raw is not None else {}, required=set(), optional={"author"})
    module = get_module(request, module_id)
    author = body.get("author")
    if author is not None and (not isinstance(author, str) or not author.strip() or len(author) > AUTHOR_LIMIT):
        raise HTTPException(status_code=422, detail=f"The author is a name of at most {AUTHOR_LIMIT} characters.")
    stores, store = await _library(request)
    install = connections.install_id(request.app.state.config.data_dir)
    try:
        entry = await library.publish(
            request.app.state.storage,
            store,
            stores.library_right,
            module_id,
            author=author.strip() if author else _author(principal, module.library_author),
            install=install,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except library.UpToDate:
        raise HTTPException(status_code=409, detail="This module is up to date with the library.") from None
    except library.Unpublishable as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except Exists:
        raise HTTPException(status_code=409, detail="Someone else is publishing this entry; try again.") from None
    except (KeyError, LookupError):
        raise HTTPException(status_code=409, detail="The module can't be exported, so it can't be published.") from None
    except StoreError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    changed(request, module_id)
    return dataclasses.asdict(entry)


@router.post("/api/modules/{module_id}/library-update")
async def post_library_update(
    request: Request, principal: Organiser, module_id: str, raw: Annotated[Any, Body()] = None
) -> dict:
    body = _object(raw, required={"keep_copy"})
    if not isinstance(body["keep_copy"], bool):
        raise HTTPException(status_code=422, detail="Say whether to keep a copy: true or false.")
    _, store = await _library(request)
    get_module(request, module_id)
    storage = request.app.state.storage
    try:
        module = await library.update(storage, store, module_id, keep_copy=body["keep_copy"])
    except library.NotFromLibrary as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except library.UpToDate:
        raise HTTPException(status_code=409, detail="This module is at the library's newest version.") from None
    except Missing as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (ScenarioError, ImportRefused):
        raise HTTPException(status_code=502, detail="The library's copy of this module can't be imported.") from None
    except StoreError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    updates = request.app.state.stores.updates
    library.set_updates(request.app.state, {key: value for key, value in updates.items() if key != module_id})
    changed(request, module_id)
    return module_json(module, storage, updates=updates_of(request))


@router.delete("/api/library/{key}", status_code=204)
async def delete_library_entry(request: Request, principal: Organiser, key: str, version: int | None = None) -> Response:
    stores, store = await _library(request)
    try:
        await library.delete_entry(store, stores.library_right, key, version)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except Missing as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except StoreError as error:
        raise HTTPException(status_code=502, detail=str(error)) from None
    return Response(status_code=204)


async def _library(request: Request) -> tuple[Stores, ObjectStore]:
    """The stores and the library; 409 without one."""
    stores: Stores = request.app.state.stores
    if stores.library is None:
        raise HTTPException(status_code=409, detail=NO_LIBRARY)
    return stores, stores.library


def _author(principal: Principal, kept: str | None) -> str:
    """Who publishes: the account's display name, the seat's name, the module's author so far, or "Delve". Never the
    machine's name, which would tell every reader of the library what this computer is called."""
    if principal.account is not None and principal.account.profile.display_name.strip():
        return principal.account.profile.display_name.strip()
    if principal.seat is not None and principal.seat.name.strip():
        return principal.seat.name.strip()
    return kept or NO_AUTHOR
