"""The install's packs in the web (DEL-366): the rulesets and settings installed, each to download as the
`.delvepack` it was installed from; and for the owner alone, installing one from a `.delvepack` file, removing one, and
restarting Delve to use what changed. A pack holds Python code that runs on this machine when it is installed and
whenever Delve starts, so only the owner installs or removes one (the owner's decision); organisers download.

Delve uses the packs it loaded when it started. An installed or removed pack takes effect once it restarts:
`restart.needed` says so, and `POST /api/restart` restarts it when systemd runs it with its socket
(`restart.possible`, `delve.web.app.run`), after saying what is under way (beats the DM is answering, a running
conversion), which a restart breaks off.

A setting's additions on this install (its added and overridden pages, its facts, its own world maps) travel apart
from its pack, as a file of their own (`delve.play.setting_transfer`): an organiser exports and imports them.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from delve.packs.manifest import PackError, PackManifest
from delve.packs.transit import build_pack, install_pack, pack_folders, remove_pack
from delve.play.context import PlayError
from delve.play.setting_transfer import export_additions, import_additions
from delve.web.auth import Organiser, Owner
from delve.web.guard import ADDITIONS_LIMIT, PACK_LIMIT
from delve.web.refusals import refusal

router = APIRouter()

RESTART_DELAY_S = 0.5
"""How long after answering Delve stops for its restart: the answer reaches the browser first."""


def _packs_dir(request: Request) -> Path:
    return request.app.state.config.packs_dir


def _loaded(request: Request) -> dict[str, str]:
    """The packs this Delve loaded when it started, by id, with their versions."""
    return {p.manifest.id: p.manifest.version for p in request.app.state.registries.catalogs.packs}


def _installed(request: Request) -> dict[str, PackManifest]:
    return {pack_id: PackManifest.read(folder) for pack_id, folder in pack_folders(_packs_dir(request)).items()}


def _under_way(request: Request) -> dict[str, Any]:
    """What a restart breaks off: the campaigns whose beat the DM is answering, and the running conversion."""
    storage = request.app.state.storage
    answering = []
    for campaign in storage.campaigns.list():
        beat = storage.beats.current(campaign.id)
        if beat is not None and beat.status == "running":
            answering.append(campaign.name)
    conversion = storage.conversions.running()
    return {"beats": answering, "conversion": conversion.title if conversion is not None else None}


def _restart_json(request: Request) -> dict[str, Any]:
    installed = {pack_id: m.version for pack_id, m in _installed(request).items()}
    return {
        "possible": request.app.state.restart is not None,
        "needed": request.app.state.packs_changed or installed != _loaded(request),
        **_under_way(request),
    }


def _campaigns_using(request: Request, pack_id: str) -> list[str]:
    return [
        c.name for c in request.app.state.storage.campaigns.list() if pack_id in (c.ruleset, c.setting)
    ]


def _pack_json(request: Request, manifest: PackManifest, loaded: dict[str, str]) -> dict[str, Any]:
    return {
        "id": manifest.id,
        "kind": manifest.kind,
        "title": manifest.title,
        "version": manifest.version,
        # In use since Delve started, at this version: else it waits for a restart.
        "active": loaded.get(manifest.id) == manifest.version,
        "campaigns": _campaigns_using(request, manifest.id),
    }


@router.get("/api/packs")
def list_packs(request: Request, principal: Organiser) -> dict[str, Any]:
    """The installed packs by id, each with whether Delve uses it now and the campaigns that name it; the packs
    Delve uses that are no longer installed (`removed`); whether the caller may install (`can_install`, the owner
    alone); and the restart: whether one is needed for what changed, whether Delve can restart itself, and what is
    under way."""
    loaded = _loaded(request)
    installed = _installed(request)
    return {
        "packs": [_pack_json(request, manifest, loaded) for manifest in installed.values()],
        "removed": sorted(set(loaded) - set(installed)),
        "can_install": principal.owner,
        "restart": _restart_json(request),
    }


@router.get("/api/packs/{pack_id}/download")
async def download_pack(request: Request, principal: Organiser, pack_id: str) -> Response:
    """The installed pack as a `.delvepack` file, built from its folder as `delve pack build` builds it (its
    database left out: an install builds it again)."""
    folder = pack_folders(_packs_dir(request)).get(pack_id)
    if folder is None:
        raise HTTPException(status_code=404, detail=f"No pack '{pack_id}' is installed.")

    def built() -> tuple[str, bytes]:
        with tempfile.TemporaryDirectory(prefix="delve-pack-") as temp:
            path = build_pack(folder, Path(temp))
            return path.name, path.read_bytes()

    try:
        name, data = await run_in_threadpool(built)
    except PackError as error:
        raise HTTPException(status_code=409, detail=f"The pack can't be packed: {error}") from None
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return Response(data, media_type="application/zip", headers=headers)


@router.post("/api/packs", status_code=201)
async def upload_pack(request: Request, principal: Owner) -> dict[str, Any]:
    """Install the `.delvepack` file in the body, or update the pack of its id: checked against its manifest and
    built in a process of its own first, so a broken pack changes nothing (422 with why). At most `PACK_LIMIT`
    bytes (413). It is used once Delve restarts. The owner's alone (403)."""
    with tempfile.TemporaryDirectory(prefix="delve-upload-") as temp:
        path = Path(temp) / "upload.delvepack"
        size = 0
        with path.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > PACK_LIMIT:
                    raise HTTPException(status_code=413, detail=f"A pack may be at most {PACK_LIMIT} bytes.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Send the .delvepack file as the body.")
        try:
            manifest = await run_in_threadpool(install_pack, path, _packs_dir(request))
        except PackError as error:
            raise HTTPException(status_code=422, detail=f"The pack wasn't installed: {error}") from None
    request.app.state.packs_changed = True
    return {"pack": _pack_json(request, manifest, _loaded(request)), "restart": _restart_json(request)}


@router.delete("/api/packs/{pack_id}")
async def delete_pack(
    request: Request, principal: Owner, pack_id: str, force: bool = Query(default=False)
) -> dict[str, Any]:
    """Remove the installed pack. A pack a campaign names is removed only with `force` (409 with the campaigns
    otherwise): those campaigns can't be played until it is installed again. Delve stops using it once it restarts.
    The owner's alone (403)."""
    if pack_id not in pack_folders(_packs_dir(request)):
        raise HTTPException(status_code=404, detail=f"No pack '{pack_id}' is installed.")
    using = _campaigns_using(request, pack_id)
    if using and not force:
        return JSONResponse(
            {"error": f"{len(using)} campaign(s) use this pack: {', '.join(using)}.", "campaigns": using},
            status_code=409,
        )
    try:
        await run_in_threadpool(remove_pack, pack_id, _packs_dir(request))
    except PackError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    request.app.state.packs_changed = True
    return {"restart": _restart_json(request)}


@router.post("/api/restart", status_code=202)
async def restart(request: Request, principal: Owner) -> dict[str, Any]:
    """Restart Delve, for the packs that changed: it answers, then stops, and systemd starts it again while its
    socket keeps the requests waiting. What is under way is broken off: a beat the DM is answering fails (its host
    can retry it), a running thorough conversion pauses and goes on. 409 when Delve doesn't run under systemd with its
    socket: then restart it by hand. The owner's alone (403)."""
    stop = request.app.state.restart
    if stop is None:
        raise HTTPException(
            status_code=409, detail="Delve can't restart itself here: restart it as you started it."
        )
    asyncio.get_running_loop().call_later(RESTART_DELAY_S, stop)
    return {"restarting": True, **_under_way(request)}


# ----- a setting's additions -----


@router.get("/api/settings/{setting_id}/additions/export")
async def export_setting_additions(request: Request, principal: Organiser, setting_id: str) -> Response:
    """This install's additions to the setting (its added and overridden pages, its facts, its own world maps with
    their pictures; DM-only content marked so), as a file another Delve imports."""
    _known_setting(request, setting_id)
    data = await run_in_threadpool(export_additions, request.app.state.storage, setting_id)
    headers = {"Content-Disposition": f'attachment; filename="{setting_id}-additions.zip"'}
    return Response(data, media_type="application/zip", headers=headers)


@router.post("/api/settings/{setting_id}/additions")
async def import_setting_additions(
    request: Request, principal: Organiser, setting_id: str, keep: bool = Query(default=True)
) -> dict[str, Any]:
    """Import a file of the setting's additions (the body, at most `ADDITIONS_LIMIT` bytes, 413): its pages, facts and
    maps join the setting's. A page or map of a title or name the setting has already is kept as it is with `keep`
    (the default), else replaced by the file's; a fact the setting holds already is never added twice. 422 for a file
    that isn't one, or is another setting's. Answers what was added, replaced and kept."""
    _known_setting(request, setting_id)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > ADDITIONS_LIMIT:
            raise HTTPException(status_code=413, detail=f"The file may be at most {ADDITIONS_LIMIT} bytes.")
    storage = request.app.state.storage
    try:
        done = await run_in_threadpool(import_additions, storage, setting_id, bytes(data), keep=keep)
    except PlayError as refused:
        raise refusal(refused) from None
    request.app.state.events.publish("setting", {"id": setting_id})
    return {"imported": done.to_dict()}


def _known_setting(request: Request, setting_id: str) -> None:
    if not any(entry.id == setting_id for entry in request.app.state.registries.catalogs.settings):
        raise HTTPException(status_code=404, detail=f"There is no setting '{setting_id}'.")
