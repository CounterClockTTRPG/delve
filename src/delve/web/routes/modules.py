"""Modules: list, create, rename, delete, mark a draft ready, and `.dscn` import and export (spec §8.1, §8.3), and the
banners of the module's campaigns, for its page. Organisers only. A module answers its entry in the shared library as
`library` (`library_json`): `{key, version, origin, newer, edited}`, or None.

Every change publishes the event `modules` with the module's id.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from jsonschema import Draft202012Validator
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.cloud import library
from delve.conversions import module_questions
from delve.domain.modules import Module, ModuleMap, homebrew
from delve.maps.dsl import DmapError
from delve.maps.geo import pictures
from delve.maps.geo.tiles import PictureRefused
from delve.maps.sources import cached_source, library_sources
from delve.modules.dscn import EXT, ScenarioError, schema
from delve.modules.dscn import check as check_bundle
from delve.modules.dscn.metadata import check as check_metadata
from delve.modules.dscn.metadata import normalise
from delve.modules.exporter import export_module as export_whole_module
from delve.modules.importer import MEDIA_TYPE, STRUCTURAL, ImportRefused, import_bundle
from delve.modules.source import load_source, missing_refs
from delve.play import banners
from delve.play.module_banners import BannerRefused, use_picture
from delve.storage import ModuleInUse
from delve.web.auth import Organiser
from delve.web.guard import UPLOAD_LIMIT

router = APIRouter()

DEFAULT_MAP = "map"
MISSING_REFS = ("missing-attachment", "missing-entity")
"""The warnings that refuse an export: its refs would dangle, and the import would refuse it."""


def module_json(
    module: Module,
    storage: Any,
    *,
    sources: bool = True,
    map_sources: bool = True,
    updates: Mapping[str, int] | None = None,
    categories: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """A module as the API answers it, with whether it is `empty`, its `library` entry, its `category` (DEL-114) and
    its `banner` (DEL-123); the list leaves out the metadata and the map sources, and has what its filter needs
    instead (`list_facets`). Without `map_sources`, the maps are named without their sources, the metadata kept
    (DEL-172). `updates` are the library's newer versions (`app.state.stores.updates`); `categories`, the category
    names by id, saves a list one lookup a module."""
    maps = [_map_json(m, sources and map_sources) for m in module.maps]
    body: dict[str, Any] = {"id": module.id, "title": module.title, "draft": module.draft}
    if sources:
        body["metadata"] = module.metadata
    body |= {"maps": maps, "head_revision": module.head_revision, "updated_at": module.updated_at}
    body |= {"empty": is_empty(storage, module), "library": library_json(module, storage, updates or {})}
    body |= {"category": category_of(module, storage, categories), "banner": module_banner_json(module)}
    return body if sources else body | list_facets(module.metadata)


def category_of(module: Module, storage: Any, names: Mapping[str, str] | None = None) -> dict[str, str] | None:
    """The module's category as `{id, name}`, None for none."""
    if module.category_id is None:
        return None
    if names is None:
        found = storage.module_categories.get(module.category_id)
        names = {found.id: found.name} if found is not None else {}
    name = names.get(module.category_id)
    return {"id": module.category_id, "name": name} if name is not None else None


def module_banner_json(module: Module) -> dict[str, Any] | None:
    """The module's banner (DEL-123): whether there's a picture (and its `version`, for the address), where it came
    from, and a painting under way or failed (with its error only when failed); None for none. Never its brief."""
    banner = module.banner
    if banner is None:
        return None
    return {
        "version": banner.blob[:12] if banner.blob else None,
        "source": banner.source,
        "status": banner.status,
        "error": banner.error if banner.status == "failed" else None,
    }


def category_names(storage: Any) -> dict[str, str]:
    return {c.id: c.name for c in storage.module_categories.list()}


def library_json(module: Module, storage: Any, updates: Mapping[str, int]) -> dict[str, Any] | None:
    """The module's library entry: its key, the version it is at, `published` or `downloaded`, the entry's newer
    version (None when there is none), and whether the module was `edited` here since; None when it has no entry."""
    if module.library_key is None:
        return None
    return {
        "key": module.library_key,
        "version": module.library_version,
        "origin": module.library_origin,
        "newer": updates.get(module.id),
        "edited": library.edited(storage, module),
    }


def updates_of(request: Request) -> Mapping[str, int]:
    return request.app.state.stores.updates


def list_facets(metadata: dict[str, Any]) -> dict[str, Any]:
    """The metadata a module list filters on and shows: the setting as written (trimmed; None for none), the
    character levels as `{min, max}` (one level is both; None when the module doesn't say), the tags, and the one-line
    summary its cards show under the title (trimmed; None for none)."""
    meta = normalise(metadata)
    setting = str(meta.get("setting") or "").strip() or None
    levels = meta.get("party", {}).get("levels")
    return {
        "setting": setting,
        "levels": {"min": levels["min"], "max": levels["max"]} if levels else None,
        "tags": [str(tag) for tag in meta.get("tags", [])],
        "summary": str(meta.get("summary") or "").strip() or None,
    }


def is_empty(storage: Any, module: Module) -> bool:
    """Whether the module has nothing to play yet: no texts, no entities, and only maps with no rooms. A map that
    doesn't parse isn't counted as empty: someone wrote something in it."""
    source = load_source(storage, module.id)
    if source.texts or any(source.entities.values()):
        return False
    played = (m for m in module.maps if m.role == "map")
    return not any(_has_rooms(m.source, library_sources(module.maps, m.name)) for m in played)


def _has_rooms(source: str, libraries: Mapping[str, str]) -> bool:
    """Through the one cache of parsed maps (DEL-166), which play and the editor share."""
    if not source.strip():
        return False
    try:
        return bool(cached_source(source, libraries).rooms)
    except DmapError:
        return True


def _map_json(module_map: ModuleMap, source: bool) -> dict[str, Any]:
    body: dict[str, Any] = {"name": module_map.name, "role": module_map.role, "is_default": module_map.is_default}
    return {**body, "source": module_map.source} if source else body


def get_module(request: Request, module_id: str) -> Module:
    module = request.app.state.storage.modules.get(module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="No such module.")
    return module


def changed(request: Request, module_id: str) -> None:
    request.app.state.events.publish("modules", {"id": module_id})


class ModuleIn(BaseModel):
    title: str


class ModulePatch(BaseModel):
    title: str | None = None
    metadata: dict[str, Any] | None = None
    draft: bool | None = None
    """Only `false`: a draft is marked ready, and a module can't become a draft again."""
    category_id: str | None = None
    """Its category (DEL-114); sent as null, none. Left out, unchanged."""


def definition(name: str) -> dict[str, Any]:
    """The `$defs` entry `name` of `scenario.schema.json`, as a schema of its own."""
    return {**schema()["$defs"][name], "$defs": schema()["$defs"]}


def diagnostic(code: str, message: str, path: str | None) -> dict[str, Any]:
    return {"severity": "error", "code": code, "message": message, "path": path}


def schema_diagnostics(subschema: dict[str, Any], value: Any, at: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """The errors of `value` against `subschema`, each at the path of its field (`party/levels`; for a missing
    property, that property)."""
    found = []
    for error in sorted(Draft202012Validator(subschema).iter_errors(value), key=lambda e: list(e.absolute_path)):
        path = [*at, *(str(p) for p in error.absolute_path)]
        if error.validator == "required" and isinstance(error.instance, dict):
            path += [p for p in error.validator_value if p not in error.instance][:1]
        found.append(diagnostic("schema", error.message, "/".join(path)))
    return found


def metadata_diagnostics(request: Request, module_id: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """The errors of a module's descriptive metadata: the manifest's shapes (spec §3.1) and what the schema can't
    check (ranges, dates, the cover). The manifest's structural keys aren't metadata."""
    found = []
    properties = schema()["properties"]
    for key, value in metadata.items():
        if key in STRUCTURAL:
            found.append(diagnostic("structural", f"{key} is a part of the module, not its metadata.", key))
        elif key in properties:
            found += schema_diagnostics({**properties[key], "$defs": schema()["$defs"]}, value, (key,))
    if found:
        return found
    source = load_source(request.app.state.storage, module_id)

    def asset(id: str) -> dict[str, str] | None:
        attachment = source.attachment(id)
        if attachment is None:
            return None
        return {"type": attachment.type, "audience": attachment.audience}

    findings = check_metadata(metadata, asset_lookup=asset)
    return [diagnostic(f.code, f.message, None) for f in findings if f.severity == "error"]


def _title(raw: str) -> str:
    title = raw.strip()
    if not title:
        raise HTTPException(status_code=422, detail="A module needs a title.")
    return title


@router.get("/api/modules")
def list_modules(request: Request, principal: Organiser) -> list[dict]:
    """Every module. A plain `def`, so its reads (each library module's hash, an export the first time: DEL-163) run in
    the thread pool, not on the event loop."""
    storage, updates = request.app.state.storage, updates_of(request)
    names = category_names(storage)
    return [module_json(m, storage, sources=False, updates=updates, categories=names) for m in storage.modules.list()]


@router.post("/api/modules", status_code=201)
def create_module(request: Request, principal: Organiser, body: ModuleIn) -> dict:
    """A new module with one empty map, `map`, which is its default; it is homebrew (DEL-226)."""
    modules = request.app.state.storage.modules
    module = modules.create(_title(body.title), homebrew({}))
    module = modules.put_map(module.id, ModuleMap(DEFAULT_MAP, "map", "", True))
    changed(request, module.id)
    return module_json(module, request.app.state.storage, updates=updates_of(request))


@router.post("/api/modules/import", status_code=201)
async def import_module(request: Request, principal: Organiser) -> dict:
    """A new module from the `.dscn` zip in the body. The guard has let only a zip content type through."""
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > UPLOAD_LIMIT:
            raise HTTPException(status_code=413, detail=f"A .dscn upload may be at most {UPLOAD_LIMIT} bytes.")
    try:
        result = await run_in_threadpool(import_bundle, request.app.state.storage, bytes(data))
    except ScenarioError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except ImportRefused as error:
        diagnostics = [d.as_dict() for d in error.diagnostics]
        raise HTTPException(status_code=400, detail={"error": str(error), "diagnostics": diagnostics}) from None
    warnings = list(result.warnings)
    module = result.module
    cover = (module.metadata or {}).get("cover")
    if module.banner is None and isinstance(cover, str) and cover.startswith("asset:"):
        # The bundle's cover, as if the organiser had picked it: its middle band (DEL-378).
        try:
            module = await run_in_threadpool(use_picture, request.app.state.storage, module.id, cover[6:], 0.5)
        except BannerRefused as refused:
            warnings.append(f"The cover can't be the banner: {refused.message}")
        except Exception as error:  # noqa: BLE001 - the module is stored: a failing cover must not fail the import
            warnings.append(f"The cover can't be the banner: {type(error).__name__}")
    for sha, mime in result.pictures:
        try:
            await run_in_threadpool(pictures.store_blob, request.app.state.storage, sha, mime)
        except (PictureRefused, LookupError) as error:
            warnings.append(f"A world map's picture can't be used: {error}")
    changed(request, module.id)
    body = module_json(module, request.app.state.storage, updates=updates_of(request))
    return {**body, "warnings": warnings}


@router.get("/api/modules/{module_id}")
def read_module(request: Request, principal: Organiser, module_id: str, map_sources: bool = True) -> dict:
    """The module; `?map_sources=false` leaves the maps' sources out (DEL-172), for a caller that wants the metadata:
    Thracia's are 667 KB."""
    storage = request.app.state.storage
    return module_json(get_module(request, module_id), storage, map_sources=map_sources, updates=updates_of(request))


@router.patch("/api/modules/{module_id}")
def patch_module(request: Request, principal: Organiser, module_id: str, body: ModulePatch) -> dict:
    module = get_module(request, module_id)
    modules = request.app.state.storage.modules
    if body.metadata is not None:
        diagnostics = metadata_diagnostics(request, module_id, body.metadata)
        if diagnostics:
            detail = {"error": "The metadata doesn't fit the module schema.", "diagnostics": diagnostics}
            raise HTTPException(status_code=422, detail=detail)
    if body.draft and not module.draft:
        raise HTTPException(status_code=422, detail="A module can't become a draft again.")
    if body.title is not None:
        module = modules.rename(module_id, _title(body.title))
    if body.metadata is not None:
        module = modules.set_metadata(module_id, body.metadata)
    if body.draft is False and module.draft:
        module = modules.set_draft(module_id, False)
    if "category_id" in body.model_fields_set:
        try:
            module = modules.set_category(module_id, body.category_id)
        except KeyError:
            raise HTTPException(status_code=422, detail="No such category.") from None
    changed(request, module_id)
    return module_json(module, request.app.state.storage, updates=updates_of(request))


@router.delete("/api/modules/{module_id}", status_code=204)
def delete_module(request: Request, principal: Organiser, module_id: str) -> Response:
    get_module(request, module_id)
    try:
        request.app.state.storage.modules.delete(module_id)
    except ModuleInUse as error:
        detail = {"error": "Campaigns are played from this module.", "campaigns": list(error.campaign_ids)}
        raise HTTPException(status_code=409, detail=detail) from None
    changed(request, module_id)
    return Response(status_code=204)


@router.get("/api/modules/{module_id}/questions")
def read_questions(request: Request, principal: Organiser, module_id: str) -> list[dict]:
    """`[{conversion_id, questions, remarks}]`: what Claude asked while making the module, from every job of the
    module (never only the last ones `GET /api/conversions` lists)."""
    get_module(request, module_id)
    return module_questions(request.app.state.storage, module_id)


@router.get("/api/modules/{module_id}/banners")
def list_banners(request: Request, principal: Organiser, module_id: str) -> list[dict]:
    """`[{campaign_id, name, image_id}]`: the banners of the module's campaigns that have one, for the module's page,
    in the campaigns' order."""
    get_module(request, module_id)
    storage = request.app.state.storage
    listed = []
    for campaign in storage.campaigns.list():
        shown = banners.current(storage, campaign.id) if campaign.module_id == module_id else None
        if shown is not None:
            listed.append({"campaign_id": campaign.id, "name": campaign.name, "image_id": shown.id})
    return listed


@router.get("/api/modules/{module_id}/banners/{campaign_id}")
async def module_banner(
    request: Request, principal: Organiser, module_id: str, campaign_id: str, size: Literal["card"] | None = None
) -> Response:
    """The banner of one of the module's campaigns; 404 for another module's campaign, or one without a banner."""
    from delve.web.routes.play import banner_response  # it imports this module through `campaigns`

    get_module(request, module_id)
    storage = request.app.state.storage
    campaign = storage.campaigns.get(campaign_id)
    if campaign is None or campaign.module_id != module_id:
        raise HTTPException(status_code=404, detail="No such campaign of this module.")
    return await banner_response(request, banners.current(storage, campaign_id), size)


@router.get("/api/modules/{module_id}/export.dscn")
async def export_module(request: Request, principal: Organiser, module_id: str) -> Response:
    """The whole module as a `.dscn` zip: its metadata, maps, texts, keys, entities and attachments. A module that
    refers to an attachment or an entity it doesn't have is refused (409), since its export wouldn't import; so, as a
    safety net, is a bundle the `.dscn` validator finds errors in, with the `problems` listed. The validator doesn't
    look for overlapping rooms, a warning (DEL-171)."""
    module = get_module(request, module_id)
    storage = request.app.state.storage
    # Off the event loop, with one derive, the exporter's, and no overlap check: its warnings aren't shown (DEL-171).
    found = await run_in_threadpool(lambda: missing_refs(load_source(storage, module_id)))
    missing = [dataclasses.asdict(w) for w in found if w.code in MISSING_REFS]
    if missing:
        detail = {"error": "the module refers to missing attachments or entities", "warnings": missing}
        raise HTTPException(status_code=409, detail=detail)
    bundle = await run_in_threadpool(export_whole_module, storage, module_id)
    report = await run_in_threadpool(check_bundle, bundle, overlaps=False)
    problems = [str(d) for d in report.diagnostics if d.severity == "error"]
    if problems:
        detail = {"error": "the export doesn't validate: " + "; ".join(problems), "problems": problems}
        raise HTTPException(status_code=409, detail=detail)
    data = await run_in_threadpool(bundle.to_zip)
    filename = f"{_slug(module.title)}{EXT}"
    return Response(data, media_type=MEDIA_TYPE, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "module"
