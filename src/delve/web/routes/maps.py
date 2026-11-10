"""A module's maps, in the shapes dungml's editor uses: read, save, rename, render, feature names, simplify.

Organisers only. A source that doesn't parse answers 400 `{error, line, column}`, and a `map` isn't saved then; a
`library` is saved even if it doesn't parse on its own. Every change publishes the event `modules`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.modules import Module, ModuleMap
from delve.maps.dsl import DmapError, feature_def_origins, simplify
from delve.maps.sources import library_sources, parse_map, parse_source, resolve_includes
from delve.modules.dscn import parse_ref
from delve.modules.source import SourceStorage, load_source, save_source
from delve.web.auth import Organiser
from delve.web.routes.dsl import parse_error, render_json
from delve.web.routes.module_source import editing
from delve.web.routes.modules import changed, get_module

router = APIRouter()

Role = Literal["map", "library"]
MapName = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^/\\\x00-\x1f]+$")]


def map_detail(module: Module, module_map: ModuleMap) -> dict[str, Any]:
    return {
        "module_id": module.id,
        "name": module_map.name,
        "role": module_map.role,
        "is_default": module_map.is_default,
        "updated_at": module.updated_at,
        "source": module_map.source,
    }


def get_map(module: Module, name: str) -> ModuleMap:
    found = next((m for m in module.maps if m.name == name), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No such map in this module.")
    return found


def _with_a_default(request: Request, module: Module) -> Module:
    """The module, with its first `map` made the default if none is (as dungml keeps a project's default)."""
    if any(m.is_default for m in module.maps):
        return module
    first = next((m for m in module.maps if m.role == "map"), None)
    if first is None:
        return module
    return request.app.state.storage.modules.set_default_map(module.id, first.name)


async def _check_parses(module: Module, name: str, source: str) -> None:
    try:
        await run_in_threadpool(parse_source, source, library_sources(module.maps, exclude=name))
    except DmapError as error:
        raise parse_error(error) from None


class MapIn(BaseModel):
    name: MapName
    role: Role


class MapUpdate(BaseModel):
    source: str | None = None
    role: Role | None = None
    new_name: MapName | None = None


class SourceIn(BaseModel):
    source: str | None = None


class RenderIn(SourceIn):
    renderer: str | None = None


class SimplifyIn(SourceIn):
    door_spurs: bool = False


@router.get("/api/modules/{module_id}/maps/{name}")
def read_map(request: Request, principal: Organiser, module_id: str, name: str) -> dict:
    module = get_module(request, module_id)
    return map_detail(module, get_map(module, name))


@router.post("/api/modules/{module_id}/maps", status_code=201)
def create_map(request: Request, principal: Organiser, module_id: str, body: MapIn) -> dict:
    """A new, empty map; the default if the module has none."""
    module = get_module(request, module_id)
    if any(m.name == body.name for m in module.maps):
        raise HTTPException(status_code=409, detail="The module already has a map with this name.")
    module = request.app.state.storage.modules.put_map(module_id, ModuleMap(body.name, body.role, "", False))
    module = _with_a_default(request, module)
    changed(request, module_id)
    return map_detail(module, get_map(module, body.name))


@router.put("/api/modules/{module_id}/maps/{name}")
async def update_map(request: Request, principal: Organiser, module_id: str, name: str, body: MapUpdate) -> dict:
    """Save the source, role or name. A map whose new source or role doesn't parse is left as it was (400). A new name
    is followed by the texts and keys on the map, in the same transaction; `updated_texts` lists the texts changed."""
    module = get_module(request, module_id)
    current = get_map(module, name)
    new_name = body.new_name if body.new_name is not None else name
    if new_name != name and any(m.name == new_name for m in module.maps):
        raise HTTPException(status_code=409, detail="The module already has a map with this name.")
    updated = replace(
        current,
        name=new_name,
        source=current.source if body.source is None else body.source,
        role=current.role if body.role is None else body.role,
    )
    if updated.role == "library":
        updated = replace(updated, is_default=False)
    elif body.source is not None or current.role != "map":
        await _check_parses(module, name, updated.source)

    module, updated_texts = await run_in_threadpool(_save_map, request, module_id, name, updated)
    changed(request, module_id)
    return {**map_detail(module, get_map(module, updated.name)), "updated_texts": updated_texts}


def _save_map(request: Request, module_id: str, name: str, updated: ModuleMap) -> tuple[Module, list[str]]:
    """Save map `name` as `updated`, following a new name in the source, in one transaction. In the threadpool, as it
    waits on locks: the module's edit lock first, then the database's, the order the source routes take them (DEL-166),
    so neither holds one while it waits for the other."""
    storage = request.app.state.storage
    updated_texts: list[str] = []
    with editing(module_id), storage.transaction():
        module = storage.modules.put_map(module_id, updated)
        if updated.name != name:
            module = storage.modules.delete_map(module_id, name)
            updated_texts = _follow_rename(storage, module_id, name, updated.name)
        module = _with_a_default(request, module)
    return module, updated_texts


def _follow_rename(storage: SourceStorage, module_id: str, old: str, new: str) -> list[str]:
    """Point the source's texts on map `old`, and the explicit keys whose `node` is on it, at `new`, so that their
    headings keep their links (walkthrough E1). The ids of the texts changed. The caller holds the module's edit lock."""
    source = load_source(storage, module_id)
    texts = [replace(t, map=new) if t.map == old else t for t in source.texts]
    keys = [_key_on(k, old, new) for k in source.keys]
    updated = [t.id for t in source.texts if t.map == old]
    if updated or keys != source.keys:
        save_source(storage, module_id, replace(source, texts=texts, keys=keys))
    return updated


def _key_on(key: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    ref = parse_ref(str(key.get("node") or ""))
    if ref is None or ref.kind != "map" or ref.id != old:
        return key
    return {**key, "node": f"map:{new}" + (f"#{ref.fragment}" if ref.fragment is not None else "")}


@router.delete("/api/modules/{module_id}/maps/{name}", status_code=204)
def delete_map(request: Request, principal: Organiser, module_id: str, name: str) -> Response:
    module = get_module(request, module_id)
    get_map(module, name)
    module = request.app.state.storage.modules.delete_map(module_id, name)
    _with_a_default(request, module)
    changed(request, module_id)
    return Response(status_code=204)


@router.put("/api/modules/{module_id}/maps/{name}/default")
def set_default_map(request: Request, principal: Organiser, module_id: str, name: str) -> dict:
    module = get_module(request, module_id)
    if get_map(module, name).role != "map":
        raise HTTPException(status_code=400, detail="Only a map, not a library, can be the default.")
    module = request.app.state.storage.modules.set_default_map(module_id, name)
    changed(request, module_id)
    return map_detail(module, get_map(module, name))


@router.post("/api/modules/{module_id}/maps/{name}/render")
async def render_map(request: Request, principal: Organiser, module_id: str, name: str, body: RenderIn) -> dict:
    """`{svg, diagnostics}` for the editor's buffer (`source`), or the stored source; includes from the module."""
    module = get_module(request, module_id)
    get_map(module, name)
    try:
        dmap = await run_in_threadpool(parse_map, module.maps, name, body.source)
    except DmapError as error:
        raise parse_error(error) from None
    return await run_in_threadpool(render_json, dmap, body.renderer)


@router.post("/api/modules/{module_id}/maps/{name}/feature-names")
async def feature_names(request: Request, principal: Organiser, module_id: str, name: str, body: SourceIn) -> dict:
    """The feature_def names the map can use: `names`, sorted, and `groups` by the file defining them.

    Both are empty when the source doesn't parse, which leaves the editor's dropdown on its last good value.
    """
    module = get_module(request, module_id)
    source = get_map(module, name).source if body.source is None else body.source
    origins = await run_in_threadpool(_origins, source, library_sources(module.maps, exclude=name))
    return feature_groups(origins)


def feature_groups(origins: dict[str, str]) -> dict[str, Any]:
    """`{names, groups}` of the feature names `origins` maps to the file defining each."""
    by_source: dict[str, list[str]] = {}
    for feature, origin in origins.items():
        by_source.setdefault(origin, []).append(feature)
    groups = [
        {"source": origin, "names": sorted(by_source[origin], key=str.lower)}
        for origin in sorted(by_source, key=str.lower)
    ]
    return {"names": sorted(origins, key=str.lower), "groups": groups}


def _origins(source: str, libraries: dict[str, str]) -> dict[str, str]:
    try:
        return feature_def_origins(source, include_sources=resolve_includes(source, libraries))
    except DmapError:
        return {}


@router.post("/api/modules/{module_id}/maps/{name}/simplify")
async def simplify_map(request: Request, principal: Organiser, module_id: str, name: str, body: SimplifyIn) -> dict:
    """The simplified source with every change, applied or left alone. Nothing is saved: the editor applies it."""
    module = get_module(request, module_id)
    source = get_map(module, name).source if body.source is None else body.source
    libraries = library_sources(module.maps, exclude=name)
    try:
        result = await run_in_threadpool(_simplify, source, libraries, body.door_spurs)
    except DmapError as error:
        raise parse_error(error) from None
    return {**result.as_dict(), "saved": False}


def _simplify(source: str, libraries: dict[str, str], door_spurs: bool):
    return simplify(source, include_sources=resolve_includes(source, libraries), door_spurs=door_spurs)
