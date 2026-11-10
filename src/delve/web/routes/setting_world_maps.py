"""A setting's own world maps (settings plan Task 9), the third owner beside a module and a campaign.

The organisers, under `/api/settings/{setting_id}/world-maps`, in the shapes of a module's maps (`map_entry`, `map_json`
with the source `setting`, its knowledge null): the list (those in review too), one map, put, delete, a GeoJSON import,
the export, the picture, and a copy of a module's ready map (`setting_maps.copy_module_map`). A picture is read into
one by `POST /api/conversions/worldmap?setting_id=…`, and reviewed and accepted as a module's is
(`delve.web.routes.world_import`). Every change publishes `setting` to the organisers, never `world`: a campaign keeps
the copies it was made with, and only campaigns made from then on copy the setting's ready maps.

A seat at a campaign of the setting, under `/api/campaigns/{campaign_id}/setting/maps`, lists and views the maps that
campaign's setting layer offers (`SettingLayer.world_maps`: the install's ready maps, else the shipped ones), whole, but
never a hidden feature or the DM's notes (`setting_maps.seat_view`), and their picture's tiles as printed. A map in
review is no seat's: it is 404, its name never said.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.world import WorldMapSource
from delve.maps.geo import pictures
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.model import GeoMapError
from delve.maps.world import WorldMapError
from delve.modules.worldmaps import is_fragment
from delve.play import setting_maps
from delve.play.setting_maps import SettingMapTaken
from delve.web.auth import Organiser
from delve.web.routes.module_world_maps import shaped
from delve.web.routes.setting_area import _changed, _seats, _shipped
from delve.web.routes.world import (
    MAP_OFFLINE,
    UNKNOWN_TILE,
    GeoJsonIn,
    WorldMapIn,
    export_response,
    map_entry,
    map_json,
    name_taken,
    picture_response,
    read_geojson,
)
from delve.web.seats import TableSeat

router = APIRouter()

PATH = "/api/settings/{setting_id}/world-maps"
SEATS = "/api/campaigns/{campaign_id}/setting/maps"


class CopyIn(BaseModel):
    module_id: str
    name: str
    as_name: str | None = None


def found(request: Request, setting_id: str, name: str) -> WorldMapSource:
    """The setting's map `name`; 404 for a setting or a map there isn't."""
    _shipped(request, setting_id)
    world_map = request.app.state.storage.setting_maps.get(setting_id, name)
    if world_map is None:
        raise HTTPException(status_code=404, detail="No such world map.")
    return world_map


def map_json_of(world_map: WorldMapSource) -> dict[str, Any]:
    return map_json(world_map, "setting", world_map.geo, None)


# ----- the organisers' -----


@router.get(PATH)
def list_setting_world_maps(request: Request, principal: Organiser, setting_id: str) -> list[dict]:
    """The install's maps of the setting, those in review too."""
    _shipped(request, setting_id)
    return [map_entry(m, "setting") for m in request.app.state.storage.setting_maps.list(setting_id)]


@router.get(PATH + "/{name}")
def read_setting_world_map(request: Request, principal: Organiser, setting_id: str, name: str) -> dict:
    return map_json_of(found(request, setting_id, name))


def _put(request: Request, setting_id: str, name: str, geo: dict[str, Any], title: str) -> WorldMapSource:
    """The setting's map `name` as this Delve document, its water cells following its water areas; its status,
    reading and title kept unless a title is given."""
    _shipped(request, setting_id)
    storage = request.app.state.storage
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A world map needs a name.")
    old = storage.setting_maps.get(setting_id, name)
    reshaped = shaped(geo, old.geo if old is not None else None)
    world_map = WorldMapSource(
        name,
        title.strip() or (old.title if old is not None else name),
        "",
        geo=to_geojson(reshaped),
        picture=reshaped.picture.id if reshaped.picture is not None else None,
        status=old.status if old is not None else "ready",
        reading=old.reading if old is not None else None,
    )
    return storage.setting_maps.put(setting_id, world_map)


@router.put(PATH + "/{name}")
async def put_setting_world_map(
    request: Request, principal: Organiser, setting_id: str, name: str, body: WorldMapIn
) -> dict:
    """Make or replace the setting's map as this Delve document; 422 `{error, problems}` for one that doesn't hold
    together, and nothing is saved. A campaign keeps the copy it was made with."""
    world_map = await run_in_threadpool(_put, request, setting_id, name, body.geo, body.title)
    _changed(request, setting_id)
    return map_json_of(world_map)


@router.delete(PATH + "/{name}", status_code=204)
def delete_setting_world_map(request: Request, principal: Organiser, setting_id: str, name: str) -> Response:
    world_map = found(request, setting_id, name)
    request.app.state.storage.setting_maps.delete(setting_id, world_map.name)
    _changed(request, setting_id)
    return Response(status_code=204)


@router.post(PATH + "/geojson", status_code=201)
async def import_setting_geojson(request: Request, principal: Organiser, setting_id: str, body: GeoJsonIn) -> dict:
    """A new map of the setting from a GeoJSON file, as the campaign's import reads it."""
    _shipped(request, setting_id)
    imported = await run_in_threadpool(read_geojson, body)
    if request.app.state.storage.setting_maps.get(setting_id, body.name.strip()) is not None:
        raise name_taken(body.name.strip())
    assert imported.geo is not None
    world_map = await run_in_threadpool(_put, request, setting_id, body.name, to_geojson(imported.geo), body.title)
    _changed(request, setting_id)
    return {**map_json_of(world_map), "warnings": imported.warnings}


def _copy(request: Request, setting_id: str, body: CopyIn) -> WorldMapSource:
    _shipped(request, setting_id)
    storage = request.app.state.storage
    try:
        return setting_maps.copy_module_map(
            storage,
            setting_id,
            body.module_id,
            body.name,
            as_name=body.as_name,
            settings=request.app.state.registries.catalogs.settings,
        )
    except SettingMapTaken as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except KeyError:
        missing = "There is no such module." if storage.modules.get(body.module_id) is None else None
        detail = missing or f"The module has no world map '{body.name}'."
        raise HTTPException(status_code=422, detail=detail) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except WorldMapError:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None


@router.post(PATH + "/copy", status_code=201)
async def copy_module_world_map(request: Request, principal: Organiser, setting_id: str, body: CopyIn) -> dict:
    """A module's ready map becomes the setting's, as a Delve document; 409 for a name the setting has, 422 for a
    module or a map there isn't, or one in review."""
    world_map = await run_in_threadpool(_copy, request, setting_id, body)
    _changed(request, setting_id)
    return map_json_of(world_map)


@router.get(PATH + "/{name}/export.geojson")
async def export_setting_world_map(request: Request, principal: Organiser, setting_id: str, name: str) -> Response:
    world_map = found(request, setting_id, name)
    assert world_map.geo is not None
    return await run_in_threadpool(export_response, world_map.name, world_map.status, world_map.geo)


@router.get(PATH + "/{name}/picture")
async def setting_world_map_picture(request: Request, principal: Organiser, setting_id: str, name: str) -> Response:
    world_map = found(request, setting_id, name)
    return await run_in_threadpool(picture_response, request.app.state.storage, world_map.name, world_map.picture)


# ----- the seats' -----


def _offered(request: Request, campaign_id: str) -> list[WorldMapSource]:
    """The ready maps the campaign's setting offers a seat, without the include fragments."""
    layer = _seats(request, campaign_id)
    return [m for m in layer.world_maps() if m.status == "ready" and not is_fragment(m)]


def _seat_map(maps: list[WorldMapSource], name: str) -> WorldMapSource:
    world_map = next((m for m in maps if m.name == name), None)
    if world_map is None:
        raise HTTPException(status_code=404, detail="No such world map.")
    return world_map


@router.get(SEATS)
async def list_table_setting_maps(request: Request, seat: TableSeat, campaign_id: str) -> list[dict]:
    """`[{name, title}]` of the setting's ready maps."""
    maps = await run_in_threadpool(_offered, request, campaign_id)
    return [{"name": m.name, "title": m.title or m.name} for m in maps]


def _view(request: Request, campaign_id: str, name: str) -> dict[str, Any]:
    maps = _offered(request, campaign_id)
    try:
        return setting_maps.seat_view(request.app.state.storage, _seat_map(maps, name), maps)
    except (WorldMapError, GeoMapError):
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None


@router.get(SEATS + "/{name}/view")
async def table_setting_map_view(request: Request, seat: TableSeat, campaign_id: str, name: str) -> dict:
    """The setting's map whole, as a seat sees it: never a hidden feature or the DM's notes."""
    return await run_in_threadpool(_view, request, campaign_id, name)


def _tile(request: Request, campaign_id: str, name: str, z: int, x: int, y: int) -> bytes | None:
    world_map = _seat_map(_offered(request, campaign_id), name)
    if world_map.picture is None:
        return None
    return pictures.tile(request.app.state.storage, world_map.picture, z, x, y)


@router.get(SEATS + "/{name}/tiles/{z}/{x}/{y}")
async def table_setting_map_tile(
    request: Request, seat: TableSeat, campaign_id: str, name: str, z: int, x: int, y: int
) -> Response:
    """A tile of the map's picture as printed; 404 for none."""
    data = await run_in_threadpool(_tile, request, campaign_id, name, z, x, y)
    if data is None:
        raise HTTPException(status_code=404, detail=UNKNOWN_TILE)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    return Response(data, media_type="image/jpeg", headers=headers)
