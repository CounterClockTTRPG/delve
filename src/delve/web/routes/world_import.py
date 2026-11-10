"""Reading a world map's picture, then reviewing and accepting what was read (plan 7 Task 12, spec §3.4). Organisers
only.

`POST /api/conversions/worldmap` starts the reading in the background (`delve.conversions.worldmap`) and answers 202
with the conversion. Its body is the raw picture, the fourth exception to the JSON rule: PNG, JPEG or WebP (415 for
another, from the guard), at most `PICTURE_LIMIT` bytes (413), streamed to `<data dir>/uploads/worldmap-*`, never to
memory. Its key, name, title and target are checked first (422; an owner there isn't is 404, a name taken 409), so a
refused start takes in no picture. Bytes that aren't the type are 400, and a picture over `MAX_PICTURE_PIXELS` is 422,
before any tile is cut. 409 while a conversion runs. At startup, a picture no running job owns is removed
(`remove_leftover_pictures`).

`…/world-maps/{name}/review` applies the organiser's decisions to a map in review (`apply_review`): a colour's terrain
or `outside`, one doubt's choice, or one choice for a whole kind; a decision that doesn't fit is 422 and nothing
changes. `…/accept` makes it ready to play on, 422 "Give every colour a terrain first." while a colour has neither a
terrain nor `outside`. Both answer the map, as `GET …/world-maps/{name}` does, for a campaign, a module and a
setting. A map in review is no seat's, so a review publishes nothing to the table; a campaign's accept does (`world`).
A setting's review and accept publish `setting` to the organisers, never `world`: no campaign changes.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from delve.conversions import ConversionRunning, conversion_json
from delve.conversions.worldmap import MapNameTaken, check_worldmap, start_worldmap
from delve.maps.geo import tiles
from delve.maps.geo.geojson import from_geojson, to_geojson
from delve.maps.geo.model import GeoMapError
from delve.maps.geo.reading.review import Reading, apply_review, unmapped
from delve.maps.geo.reading.scale import ScaleKey
from delve.modules.source import ModuleSource
from delve.modules.worldmaps import put_world_map
from delve.play import world_maps
from delve.web.auth import Organiser
from delve.web.guard import UPLOAD_LIMIT, WORLDMAP_TYPES
from delve.web.routes.conversions import _running, conversions, uploads_folder
from delve.web.routes.module_source import save, source_of
from delve.web.routes.module_world_maps import _found, _json
from delve.web.routes.setting_area import _changed as setting_changed
from delve.web.routes.setting_world_maps import found, map_json_of
from delve.web.routes.world import _campaign_map_json, _ctx, _map, map_json, world_changed

router = APIRouter()

PICTURE_LIMIT = UPLOAD_LIMIT
"""The largest picture to read, in bytes: 64 MB."""
UPLOAD_PREFIX = "worldmap-"
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
UNMAPPED = "Give every colour a terrain first."
NOT_IN_REVIEW = "The world map isn't in review."


def remove_leftover_pictures(app: FastAPI) -> list[Path]:
    """Remove the uploaded pictures that no running job owns; answers the files removed."""
    owned = {live.upload for live in conversions(app).live.values()}
    left = [p for p in sorted(uploads_folder(app).glob(f"{UPLOAD_PREFIX}*")) if p not in owned]
    for path in left:
        path.unlink(missing_ok=True)
    return left


# ----- reading a picture -----


def _key(cell: str, distance: str, units: str, points: str) -> ScaleKey:
    """The scale key from the query; `ValueError` for one that doesn't check."""
    if cell not in ("hex", "square", "none"):
        raise ValueError("The grid is hex, square or none.")
    if units not in ("km", "miles"):
        raise ValueError("The units are km or miles.")
    try:
        value = float(distance)
    except ValueError:
        raise ValueError("The distance must be a number.") from None
    marked = None
    if points.strip():
        try:
            x1, y1, x2, y2 = (float(p) for p in points.split(","))
        except ValueError:
            raise ValueError("The points are x1,y1,x2,y2 on the picture.") from None
        marked = ((x1, y1), (x2, y2))
    key = ScaleKey(None if cell == "none" else cell, value, units, marked)  # type: ignore[arg-type]
    key.check()
    return key


async def _receive_picture(request: Request, folder: Path, mime: str) -> Path:
    """The body, streamed to a new file in `folder`: 413 past `PICTURE_LIMIT`. A refused upload leaves no file."""
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=UPLOAD_PREFIX, suffix=EXTENSIONS[mime], dir=folder)
    path = Path(name)
    size = 0
    try:
        with os.fdopen(fd, "wb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > PICTURE_LIMIT:
                    raise HTTPException(
                        status_code=413, detail=f"A world map's picture may be at most {PICTURE_LIMIT} bytes."
                    )
                file.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _check_picture(path: Path, mime: str) -> None:
    """400 for bytes that aren't a `mime` picture, 422 for too many pixels; the file is removed then."""
    try:
        tiles.open_picture(path, mime).close()
    except tiles.PictureRefused as refused:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=refused.status, detail=refused.message) from None


@router.post("/api/conversions/worldmap", status_code=202)
async def read_world_picture(
    request: Request,
    principal: Organiser,
    module_id: str = "",
    campaign_id: str = "",
    setting_id: str = "",
    name: str = "",
    title: str = "",
    cell: str = "hex",
    distance: str = "",
    units: str = "km",
    points: str = "",
) -> dict:
    """Read the picture in the body into a world map in review of the module, the campaign or the setting, with its
    scale key: one cell's distance, or with no grid (`cell=none`) two points on the picture and the distance between
    them."""
    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in WORLDMAP_TYPES:
        raise HTTPException(status_code=415, detail="Send the picture as PNG, JPEG or WebP.")
    services = conversions(request.app)
    target = {
        "module_id": module_id,
        "campaign_id": campaign_id,
        "setting_id": setting_id,
        "name": name,
        "title": title,
    }
    try:
        key = _key(cell, distance, units, points)
        if campaign_id and not module_id and not setting_id:
            await run_in_threadpool(world_maps.maps, _ctx(request, campaign_id))  # its module's maps first
        await run_in_threadpool(check_worldmap, services.storage, key, target, services.settings)
    except MapNameTaken as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except KeyError:
        raise HTTPException(status_code=404, detail="No such module, campaign or setting.") from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    if services.live:  # don't take in a whole picture only to refuse it
        raise _running(ConversionRunning(services.storage.conversions.running()))
    path = await _receive_picture(request, uploads_folder(request.app), mime)
    await run_in_threadpool(_check_picture, path, mime)
    try:
        conversion = await start_worldmap(services, path, mime, key, target)
    except ConversionRunning as error:
        raise _running(error) from None
    except MapNameTaken as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except (KeyError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return conversion_json(conversion)


# ----- the review and the accept -----


class ReviewIn(BaseModel):
    clusters: dict[str, str] = Field(default_factory=dict)
    decisions: dict[str, str] = Field(default_factory=dict)
    kinds: dict[str, str] = Field(default_factory=dict)


def _reading(world_map: Any) -> Reading:
    """The map's reading over its geo map; 409 for a map that isn't in review."""
    if world_map.status != "review" or world_map.reading is None or world_map.geo is None:
        raise HTTPException(status_code=409, detail=NOT_IN_REVIEW)
    try:
        geo = from_geojson(world_map.geo).geo
    except GeoMapError:
        geo = None
    if geo is None:
        raise HTTPException(status_code=409, detail=NOT_IN_REVIEW)
    return Reading.from_dict(world_map.reading, geo)


def _reviewed(world_map: Any, body: ReviewIn) -> Any:
    """The map after the decisions; 422 for one that doesn't fit, and nothing changes."""
    reading = _reading(world_map)
    try:
        reviewed = apply_review(reading, clusters=body.clusters, decisions=body.decisions, kinds=body.kinds)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return replace(world_map, geo=to_geojson(reviewed.geo), reading=reviewed.to_dict())


def _check_mapped(world_map: Any) -> None:
    if world_map.status == "review" and unmapped(_reading(world_map)):
        raise HTTPException(status_code=422, detail=UNMAPPED)


CAMPAIGN = "/api/campaigns/{campaign_id}/world-maps/{name}"
MODULE = "/api/modules/{module_id}/world-maps/{name}"


def _review_campaign(request: Request, campaign_id: str, name: str, body: ReviewIn) -> dict[str, Any]:
    ctx = _ctx(request, campaign_id)
    reviewed = _reviewed(_map(ctx, name), body)
    return _campaign_map_json(ctx.storage.world_maps.put(reviewed))


@router.post(CAMPAIGN + "/review")
async def review_campaign_map(
    request: Request, principal: Organiser, campaign_id: str, name: str, body: ReviewIn
) -> dict:
    """The campaign's map in review after these decisions."""
    return await run_in_threadpool(_review_campaign, request, campaign_id, name, body)


def _accept_campaign(request: Request, campaign_id: str, name: str) -> dict[str, Any]:
    ctx = _ctx(request, campaign_id)
    world_map = _map(ctx, name)
    _check_mapped(world_map)
    return _campaign_map_json(world_maps.accept(ctx, world_map.name))


@router.post(CAMPAIGN + "/accept")
async def accept_campaign_map(request: Request, principal: Organiser, campaign_id: str, name: str) -> dict:
    """The campaign's map becomes ready, to be played on; 422 while a colour has no terrain."""
    accepted = await run_in_threadpool(_accept_campaign, request, campaign_id, name)
    world_changed(request, campaign_id)
    return accepted


def _module_review(source: ModuleSource, name: str, body: ReviewIn) -> tuple[ModuleSource, Any]:
    reviewed = _reviewed(_found(source, name), body)
    return put_world_map(source, reviewed), reviewed


@router.post(MODULE + "/review")
async def review_module_map(request: Request, principal: Organiser, module_id: str, name: str, body: ReviewIn) -> dict:
    """The module's map in review after these decisions."""
    source, reviewed = await run_in_threadpool(_module_review, source_of(request, module_id), name, body)
    save(request, module_id, source)
    return map_json(reviewed, "module", reviewed.geo, None)


def _module_accept(source: ModuleSource, name: str) -> tuple[ModuleSource, Any]:
    world_map = _found(source, name)
    _check_mapped(world_map)
    accepted = replace(world_map, status="ready")
    return put_world_map(source, accepted), accepted


@router.post(MODULE + "/accept")
async def accept_module_map(request: Request, principal: Organiser, module_id: str, name: str) -> dict:
    """The module's map becomes ready: campaigns made from then on copy it."""
    source, accepted = await run_in_threadpool(_module_accept, source_of(request, module_id), name)
    save(request, module_id, source)
    return await run_in_threadpool(_json, source, accepted)


SETTING = "/api/settings/{setting_id}/world-maps/{name}"


def _setting_review(request: Request, setting_id: str, name: str, body: ReviewIn) -> dict[str, Any]:
    reviewed = _reviewed(found(request, setting_id, name), body)
    return map_json_of(request.app.state.storage.setting_maps.put(setting_id, reviewed))


@router.post(SETTING + "/review")
async def review_setting_map(
    request: Request, principal: Organiser, setting_id: str, name: str, body: ReviewIn
) -> dict:
    """The setting's map in review after these decisions."""
    reviewed = await run_in_threadpool(_setting_review, request, setting_id, name, body)
    setting_changed(request, setting_id)
    return reviewed


def _setting_accept(request: Request, setting_id: str, name: str) -> dict[str, Any]:
    world_map = found(request, setting_id, name)
    _check_mapped(world_map)
    return map_json_of(request.app.state.storage.setting_maps.put(setting_id, replace(world_map, status="ready")))


@router.post(SETTING + "/accept")
async def accept_setting_map(request: Request, principal: Organiser, setting_id: str, name: str) -> dict:
    """The setting's map becomes ready: campaigns of the setting made from then on copy it; none made before changes."""
    accepted = await run_in_threadpool(_setting_accept, request, setting_id, name)
    setting_changed(request, setting_id)
    return accepted
