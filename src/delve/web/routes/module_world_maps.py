"""A module's world maps (plan 7 Task 11), organisers only, in the shapes of the campaign's: the list, one map, put,
delete, a GeoJSON import, the export and the picture, all on the module's working source (`load_source` /
`save_source`, so each change publishes `modules`). A `.map` one reads converted, its includes compiled in; an include
fragment is no map of its own, never listed or replaced. A module's map knows nothing of a party: its `knowledge` is
null.

The routes are sync, so they run in the threadpool (DEL-166): each save derives the whole module. A change holds the
module's edit lock (`delve.web.routes.module_source.edits`), as the text and entity saves do.

A module's ready map can be copied into a setting's own maps (`delve.web.routes.setting_world_maps`), which new
campaigns of that setting copy in turn.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from delve.domain.world import WorldMapSource
from delve.maps.geo.geojson import from_geojson, to_geojson
from delve.maps.geo.model import GeoMap, GeoMapError, water_from_areas
from delve.maps.world import WorldMapError
from delve.modules.source import ModuleSource, world_includes
from delve.modules.worldmaps import geo_of, get_world_map, is_fragment, put_world_map, remove_world_map, world_maps
from delve.web.routes.module_source import edits, save, source_of
from delve.web.routes.modules import Organiser
from delve.web.routes.world import (
    MAP_OFFLINE,
    GeoJsonIn,
    WorldMapIn,
    export_response,
    map_entry,
    map_json,
    name_taken,
    picture_response,
    read_geojson,
    refused_document,
)

router = APIRouter()

PATH = "/api/modules/{module_id}/world-maps"


def _found(source: ModuleSource, name: str) -> WorldMapSource:
    found = get_world_map(source, name)
    if found is None:
        raise HTTPException(status_code=404, detail="No such world map.")
    return found


def _geo(source: ModuleSource, world_map: WorldMapSource) -> dict[str, Any]:
    try:
        return geo_of(world_map, world_includes(source.worldmaps))
    except WorldMapError:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None


def _json(source: ModuleSource, world_map: WorldMapSource) -> dict[str, Any]:
    return map_json(world_map, "module", _geo(source, world_map), None)


@router.get(PATH)
def list_module_world_maps(request: Request, principal: Organiser, module_id: str) -> list[dict]:
    """The module's world maps, those in review too, without the include fragments."""
    return [map_entry(w, "module") for w in world_maps(source_of(request, module_id))]


@router.get(PATH + "/{name}")
def read_module_world_map(request: Request, principal: Organiser, module_id: str, name: str) -> dict:
    source = source_of(request, module_id)
    return _json(source, _found(source, name))


def shaped(geo: dict[str, Any], previous: dict[str, Any] | None) -> GeoMap:
    """The Delve document `geo` as a geo map, its water cells following its water areas against `previous` (the map's
    document before, when it had one that reads); 422 `{error, problems}` for one that doesn't hold together."""
    try:
        imported = from_geojson(geo).geo
        if imported is None:
            raise GeoMapError("A world map needs its scale", ["the document isn't a Delve world map"])
    except GeoMapError as error:
        raise refused_document(error) from None
    before = None
    if previous is not None:
        try:
            before = from_geojson(previous).geo
        except GeoMapError:
            before = None
    return water_from_areas(imported, before)


def _put(source: ModuleSource, name: str, geo: dict[str, Any], title: str) -> tuple[ModuleSource, WorldMapSource]:
    """The source with the map `name` as this Delve document, its water cells following its water areas; its status,
    reading and title kept unless a title is given."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A world map needs a name.")
    if any(w.name == name and is_fragment(w) for w in source.worldmaps):
        raise HTTPException(status_code=409, detail=f"'{name}' is a part other world maps include.")
    old = get_world_map(source, name)
    previous = None
    if old is not None:
        try:
            previous = geo_of(old, world_includes(source.worldmaps))
        except WorldMapError:
            previous = None
    reshaped = shaped(geo, previous)
    world_map = WorldMapSource(
        name,
        title.strip() or (old.title if old is not None else name),
        "",
        geo=to_geojson(reshaped),
        picture=reshaped.picture.id if reshaped.picture is not None else None,
        status=old.status if old is not None else "ready",
        reading=old.reading if old is not None else None,
    )
    return put_world_map(source, world_map), world_map


@router.put(PATH + "/{name}")
@edits
def put_module_world_map(
    request: Request, principal: Organiser, module_id: str, name: str, body: WorldMapIn
) -> dict:
    """Make or replace the module's map as this Delve document; 422 `{error, problems}` for one that doesn't hold
    together, and nothing is saved. A campaign keeps its own copy until its host upgrades it."""
    source, world_map = _put(source_of(request, module_id), name, body.geo, body.title)
    save(request, module_id, source)
    return map_json(world_map, "module", world_map.geo, None)


@router.delete(PATH + "/{name}", status_code=204)
@edits
def delete_module_world_map(request: Request, principal: Organiser, module_id: str, name: str) -> Response:
    source = source_of(request, module_id)
    save(request, module_id, remove_world_map(source, _found(source, name).name))
    return Response(status_code=204)


@router.post(PATH + "/geojson", status_code=201)
@edits
def import_module_geojson(request: Request, principal: Organiser, module_id: str, body: GeoJsonIn) -> dict:
    """A new map of the module from a GeoJSON file, as the campaign's import reads it."""
    source = source_of(request, module_id)
    imported = read_geojson(body)
    if any(w.name == body.name.strip() for w in source.worldmaps):
        raise name_taken(body.name.strip())
    assert imported.geo is not None
    source, world_map = _put(source, body.name, to_geojson(imported.geo), body.title)
    save(request, module_id, source)
    return {**map_json(world_map, "module", world_map.geo, None), "warnings": imported.warnings}


@router.get(PATH + "/{name}/export.geojson")
def export_module_world_map(request: Request, principal: Organiser, module_id: str, name: str) -> Response:
    source = source_of(request, module_id)
    world_map = _found(source, name)
    return export_response(world_map.name, world_map.status, _geo(source, world_map))


@router.get(PATH + "/{name}/picture")
def module_world_map_picture(request: Request, principal: Organiser, module_id: str, name: str) -> Response:
    world_map = _found(source_of(request, module_id), name)
    return picture_response(request.app.state.storage, world_map.name, world_map.picture)
