"""The world beyond the dungeon (plan 6 Task 8, Decision 7; plan 7 Task 11): for a seat at the table, what its
characters know of it, and the world maps as far as the party knows them; for the organisers, the DM view and the maps
whole.

`GET …/world` is the date, the weather, where the party is, the known quests with their known notes, the known
factions with their standing word and the party's and the PCs' possessions without their notes: never a clock, a
faction's notes, strength or reputation number, a quest not yet known, an NPC's possession or a hidden place's name.

A seat lists and views only the maps the party knows something of, or is on (`world_maps.seat_maps`); any other map
is 404 to it, its name never said. Its view is cut on the server (`knowledge.seat_view`) and its tiles are fogged on
the server, none where nothing is known. A map that doesn't read is 409 `{"error": "map offline"}`, never the DM
view. Every change publishes `world` to the table with the campaign's id alone, never a map's name: each browser reads
the world again through its own routes.

The organisers (plan 6 Task 12) also read and change the factions, the clocks, the quests and the possessions whole,
their DM-only fields too. Factions and quests are put by the id the organiser gives them; clocks and possessions get
theirs from the server, so they are added with POST on the collection.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from delve.domain.world import (
    QUEST_STATUSES,
    CampaignWorldMap,
    Clock,
    Faction,
    Quest,
    QuestNote,
    WorldKnowledge,
)
from delve.maps.geo import pictures
from delve.maps.geo.from_dsl import MILE_KM
from delve.maps.geo.geojson import Imported, PropertyMapping, Scale, from_geojson, to_geojson
from delve.maps.geo.knowledge import KnowledgeError, known_cells, visible_features
from delve.maps.geo.model import GeoMapError
from delve.maps.world import is_workspace
from delve.play import days, factions, possessions, quests, weather, world_maps
from delve.play.context import CampaignContext, PlayError, context_for
from delve.web.auth import Organiser
from delve.web.refusals import refusal
from delve.web.routes.campaigns import get_campaign
from delve.web.routes.characters import catalogs_of
from delve.web.seats import TableSeat

router = APIRouter()

PATH = "/api/campaigns/{campaign_id}/world-maps"
MAP_OFFLINE = {"error": "map offline"}
UNKNOWN_TILE = {"error": "unknown"}
NO_PICTURE = {"error": "no picture"}
PICTURE_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def world_changed(request: Request, campaign_id: str) -> None:
    """The table's: the campaign's id alone, never a map's name, so that each browser reads the world again through
    its own routes."""
    request.app.state.events.publish("world", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id)


def _ctx(request: Request, campaign_id: str) -> CampaignContext:
    get_campaign(request, campaign_id)
    storage = request.app.state.storage
    return context_for(storage, campaign_id, "world", catalogs=catalogs_of(request))


def _map(ctx: CampaignContext, name: str) -> CampaignWorldMap:
    try:
        return world_maps.get(ctx, name)
    except PlayError:
        raise HTTPException(status_code=404, detail="No such world map.") from None


def _quest(quest: Any) -> dict[str, Any]:
    keys = ("id", "title", "giver", "scope", "stakes", "status", "started_day", "ended_day")
    return {
        **{key: getattr(quest, key) for key in keys},
        "log": [{"day": note.day, "text": note.text} for note in quest.log if note.known],
    }


def _at_label(ctx: CampaignContext) -> dict[str, Any] | None:
    """Where the party is: the map, and the place's name while the players' map shows that place."""
    here = world_maps.position(ctx)
    if here is None:
        return None
    label = None
    try:
        world_map = world_maps.get(ctx, here.map)
        if here.at:
            shown = visible_features(world_maps.geo(ctx, world_map.name), world_map.knowledge or WorldKnowledge())
            label = next((f.name for f in shown if f.id == here.at), None)
    except PlayError:
        pass
    return {"map": here.map, "at_label": label}


def _world(ctx: CampaignContext) -> dict[str, Any]:
    storage = ctx.storage
    forecast = weather.current(ctx)
    pcs = {c.id: c.name for c in storage.characters.list(ctx.campaign_id) if c.kind == "pc"}
    return {
        "date": days.today(ctx).label,
        "weather": {"label": forecast.label, "effect": forecast.effect} if forecast is not None else None,
        "position": _at_label(ctx),
        "quests": [_quest(q) for q in storage.quests.list(ctx.campaign_id, known=True)],
        "factions": [
            {"id": f.id, "name": f.name, "standing": factions.standing(f.reputation)}
            for f in storage.factions.list(ctx.campaign_id, known=True)
        ],
        "possessions": [
            possessions.public(p, pcs)
            for p in storage.possessions.list(ctx.campaign_id)
            if p.owner_id is None or p.owner_id in pcs  # an NPC's is the DM's to know
        ],
    }


@router.get("/api/campaigns/{campaign_id}/world")
async def read_world(request: Request, seat: TableSeat, campaign_id: str) -> dict:
    """What the characters know of the world, the same for every seat at the table."""
    return await run_in_threadpool(_world, _ctx(request, campaign_id))


# ----- the seat's world maps -----


@router.get(PATH)
async def list_world_maps(request: Request, seat: TableSeat, campaign_id: str) -> list[dict]:
    """The world maps a seat may view: `[{name, title}]` of the ready maps the party knows something of, or is on."""
    ctx = _ctx(request, campaign_id)
    return [{"name": m.name, "title": m.title} for m in await run_in_threadpool(world_maps.seat_maps, ctx)]


def _seat_map(ctx: CampaignContext, name: str) -> CampaignWorldMap:
    """The map `name` as a seat may see it; 404 for any map not in its list, and 409 for the one the party is on when
    it doesn't read."""
    found = next((m for m in world_maps.seat_maps(ctx) if m.name == name), None)
    if found is not None:
        return found
    here = world_maps.position(ctx)
    if here is not None and here.map == name and any(m.name == name for m in world_maps.maps(ctx)):
        raise HTTPException(status_code=409, detail=MAP_OFFLINE)
    raise HTTPException(status_code=404, detail="No such world map.")


def _seat_view(ctx: CampaignContext, name: str) -> dict[str, Any]:
    _seat_map(ctx, name)
    try:
        return world_maps.seat_view(ctx, name)
    except PlayError:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None


@router.get(PATH + "/{name}/view")
async def seat_view(request: Request, seat: TableSeat, campaign_id: str, name: str) -> dict:
    """The map as the players know it: the known land, its visible features without the DM's notes, the party and
    its journey cut at the known edge. Nothing turns it into the DM view."""
    return await run_in_threadpool(_seat_view, _ctx(request, campaign_id), name)


def _seat_tile(ctx: CampaignContext, name: str, z: int, x: int, y: int) -> bytes | None:
    world_map = _seat_map(ctx, name)
    try:
        geo_map = world_maps.geo(ctx, world_map.name)
    except PlayError:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None
    if geo_map.picture is None:
        return None
    cells = known_cells(geo_map, world_map.knowledge or WorldKnowledge())
    return pictures.seat_tile(ctx.storage, geo_map.picture.id, geo_map, cells, z, x, y)


@router.get(PATH + "/{name}/tiles/{z}/{x}/{y}")
async def seat_tile(request: Request, seat: TableSeat, campaign_id: str, name: str, z: int, x: int, y: int) -> Response:
    """A tile of the map's picture as the seat may see it, fogged on the server where the party knows nothing; none
    at all where it knows nothing of the whole tile."""
    data = await run_in_threadpool(_seat_tile, _ctx(request, campaign_id), name, z, x, y)
    if data is None:
        raise HTTPException(status_code=404, detail=UNKNOWN_TILE)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"}
    return Response(data, media_type="image/jpeg", headers=headers)


# ----- the organisers' world maps -----


def map_entry(world_map: Any, source: str) -> dict[str, Any]:
    """A map in the organisers' lists: `{name, title, status, source, picture}`."""
    return {
        "name": world_map.name,
        "title": world_map.title,
        "status": world_map.status,
        "source": source,
        "picture": world_map.picture is not None,
    }


def map_json(world_map: Any, source: str, geo: dict[str, Any] | None, knowledge: WorldKnowledge | None) -> dict:
    """A map whole, as the organiser edits it."""
    return {
        "name": world_map.name,
        "title": world_map.title,
        "source": source,
        "status": world_map.status,
        "geo": geo,
        "picture": world_map.picture,
        "knowledge": knowledge.to_dict() if knowledge is not None else None,
        "reading": world_map.reading,
    }


def _campaign_map_json(world_map: CampaignWorldMap) -> dict[str, Any]:
    return map_json(world_map, world_map.source, world_map.geo, world_map.knowledge)


def refused_document(error: GeoMapError) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": error.message, "problems": error.problems})


@router.get("/api/campaigns/{campaign_id}/organiser/world-maps")
async def list_organisers_world_maps(request: Request, principal: Organiser, campaign_id: str) -> list[dict]:
    """Every world map of the campaign, those in review too, without the include fragments."""
    ctx = _ctx(request, campaign_id)
    listed = await run_in_threadpool(world_maps.maps, ctx)
    return [map_entry(m, m.source) for m in listed if m.geo is not None or is_workspace(m.dsl)]


def _dm_view(ctx: CampaignContext, name: str) -> dict[str, Any]:
    _map(ctx, name)
    try:
        return world_maps.dm_view(ctx, name)
    except PlayError:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None


@router.get(PATH + "/{name}/dm-view")
async def dm_view(request: Request, principal: Organiser, campaign_id: str, name: str) -> dict:
    """Every feature whole, with its DM notes and whether the party knows it."""
    return await run_in_threadpool(_dm_view, _ctx(request, campaign_id), name)


class WorldMapIn(BaseModel):
    title: str = ""
    geo: dict[str, Any]


class MappingIn(BaseModel):
    name: str = "name"
    kind: str = "kind"
    values: dict[str, str] = Field(default_factory=dict)


class KnownDistanceIn(BaseModel):
    from_: str = Field(alias="from")
    to: str
    distance: float = Field(gt=0)
    units: Literal["km", "miles"] = "km"


class GeoJsonIn(BaseModel):
    name: str
    title: str = ""
    document: dict[str, Any]
    mapping: MappingIn | None = None
    width_km: float | None = Field(default=None, gt=0)
    known: KnownDistanceIn | None = None


def read_geojson(body: GeoJsonIn) -> Imported:
    """The import's map, scaled by the known distance (miles made km) or the width; 422 `needs: "scale"` with the
    properties and kinds found when it has neither and needs one, and 422 with the problems of a file that doesn't
    hold together."""
    scale = None
    if body.known is not None:
        km = body.known.distance * (MILE_KM if body.known.units == "miles" else 1.0)
        scale = Scale(known=(body.known.from_, body.known.to, km))
    elif body.width_km is not None:
        scale = Scale(width_km=body.width_km)
    mapping = PropertyMapping(**body.mapping.model_dump()) if body.mapping is not None else None
    try:
        imported = from_geojson(body.document, mapping=mapping, scale=scale)
    except GeoMapError as error:
        raise refused_document(error) from None
    if imported.geo is None:
        detail = {
            "error": "The map needs its size.",
            "needs": "scale",
            "properties": imported.properties,
            "kinds": imported.kinds,
        }
        raise HTTPException(status_code=422, detail=detail)
    return imported


def name_taken(name: str) -> HTTPException:
    return HTTPException(status_code=409, detail=f"There is a world map named '{name}' already.")


def export_response(name: str, status: str, geo: dict[str, Any]) -> Response:
    """The Delve document with a polygon for each terrain cell, as a download; a map in review is never exported."""
    if status == "review":
        raise HTTPException(status_code=409, detail="The world map is still in review.")
    try:
        loaded = from_geojson(geo).geo
    except GeoMapError as error:
        raise refused_document(error) from None
    if loaded is None:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE)
    body = json.dumps(to_geojson(loaded, terrain_cells=True))
    headers = {"Content-Disposition": f'attachment; filename="{_file_name(name)}.geojson"'}
    return Response(body, media_type="application/geo+json", headers=headers)


def picture_response(storage: Any, name: str, picture_id: str | None) -> Response:
    """The map's original picture, as a download in its own type."""
    found = pictures.original(storage, picture_id) if picture_id else None
    if found is None:
        raise HTTPException(status_code=404, detail=NO_PICTURE)
    data, mime = found
    extension = PICTURE_EXTENSIONS.get(mime, "bin")
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'attachment; filename="{_file_name(name)}.{extension}"',
    }
    return Response(data, media_type=mime, headers=headers)


def _file_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "world-map"


@router.get(PATH + "/{name}")
async def read_world_map(request: Request, principal: Organiser, campaign_id: str, name: str) -> dict:
    ctx = _ctx(request, campaign_id)
    return _campaign_map_json(await run_in_threadpool(_map, ctx, name))


def _save(ctx: CampaignContext, name: str, geo: dict[str, Any], title: str) -> CampaignWorldMap:
    """Put the map, keeping its status: a map in review stays in review until it is accepted."""
    world_maps.maps(ctx)  # the module's and the setting's first, so a new map never hides one of theirs
    old = ctx.storage.world_maps.get(ctx.campaign_id, name.strip())
    try:
        return world_maps.save_geo(ctx, name, geo, title, status=old.status if old is not None else "ready")
    except GeoMapError as error:
        raise refused_document(error) from None
    except PlayError as error:
        raise HTTPException(status_code=422, detail=error.message) from None


@router.put(PATH + "/{name}")
async def put_world_map(request: Request, principal: Organiser, campaign_id: str, name: str, body: WorldMapIn) -> dict:
    """Make or replace the map as this Delve document, keeping what the party knows; a document that doesn't hold
    together is 422 `{error, problems}`, and nothing is saved."""
    ctx = _ctx(request, campaign_id)
    saved = await run_in_threadpool(_save, ctx, name, body.geo, body.title)
    world_changed(request, campaign_id)
    return _campaign_map_json(saved)


@router.delete(PATH + "/{name}", status_code=204)
def delete_world_map(request: Request, principal: Organiser, campaign_id: str, name: str) -> Response:
    ctx = _ctx(request, campaign_id)
    try:
        world_maps.delete(ctx, name)
    except PlayError:
        raise HTTPException(status_code=404, detail="No such world map.") from None
    world_changed(request, campaign_id)
    return Response(status_code=204)


class KnowledgeIn(BaseModel):
    how: Literal["everything", "nothing", "regions", "area"]
    regions: list[str] = Field(default_factory=list)
    ring: list[tuple[float, float]] = Field(default_factory=list)


def _start(ctx: CampaignContext, name: str, body: KnowledgeIn) -> WorldKnowledge:
    world_map = _map(ctx, name)
    try:
        return world_maps.set_start(ctx, world_map.name, body.how, regions=body.regions, ring=body.ring)
    except KnowledgeError as error:
        raise HTTPException(status_code=422, detail=error.message) from None
    except PlayError:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE) from None


@router.put(PATH + "/{name}/knowledge")
async def put_knowledge(request: Request, principal: Organiser, campaign_id: str, name: str, body: KnowledgeIn) -> dict:
    """What the party knows of the map from now on: everything, nothing, some regions, or an area drawn as a ring."""
    ctx = _ctx(request, campaign_id)
    known = await run_in_threadpool(_start, ctx, name, body)
    world_changed(request, campaign_id)
    return known.to_dict()


def _import(ctx: CampaignContext, body: GeoJsonIn) -> tuple[CampaignWorldMap, list[str]]:
    imported = read_geojson(body)
    world_maps.maps(ctx)
    if ctx.storage.world_maps.get(ctx.campaign_id, body.name.strip()) is not None:
        raise name_taken(body.name.strip())
    assert imported.geo is not None
    return _save(ctx, body.name, to_geojson(imported.geo), body.title), imported.warnings


@router.post(PATH + "/geojson", status_code=201)
async def import_geojson(request: Request, principal: Organiser, campaign_id: str, body: GeoJsonIn) -> dict:
    """A new map from a GeoJSON file: a Delve document as it is, a foreign one through its mapping and scaled."""
    ctx = _ctx(request, campaign_id)
    saved, warnings = await run_in_threadpool(_import, ctx, body)
    world_changed(request, campaign_id)
    return {**_campaign_map_json(saved), "warnings": warnings}


@router.get(PATH + "/{name}/export.geojson")
def export_world_map(request: Request, principal: Organiser, campaign_id: str, name: str) -> Response:
    """Sync, so in the threadpool (DEL-166): reading the map reads its whole document."""
    world_map = _map(_ctx(request, campaign_id), name)
    if world_map.geo is None:
        raise HTTPException(status_code=409, detail=MAP_OFFLINE)
    return export_response(world_map.name, world_map.status, world_map.geo)


@router.get(PATH + "/{name}/picture")
def world_map_picture(request: Request, principal: Organiser, campaign_id: str, name: str) -> Response:
    """The map's picture as it was given, for the organiser to keep beside the export; in the threadpool (DEL-166)."""
    world_map = _map(_ctx(request, campaign_id), name)
    return picture_response(request.app.state.storage, world_map.name, world_map.picture)


# ----- the organisers' factions, clocks, quests and possessions (plan 6 Task 12) -----


def _missing(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No such {what}.")


class FactionIn(BaseModel):
    name: str | None = None
    alignment: str | None = None
    goals: str | None = None
    scope: str | None = None
    known: bool | None = None
    strength: int | None = None
    reputation: int | None = None
    notes_md: str | None = None


@router.get("/api/campaigns/{campaign_id}/factions")
def list_factions(request: Request, principal: Organiser, campaign_id: str) -> list[dict]:
    return factions.list_factions(_ctx(request, campaign_id))


def _faction(ctx: CampaignContext, faction_id: str) -> Faction:
    found = ctx.storage.factions.get(ctx.campaign_id, faction_id)
    if found is None:
        raise _missing("faction")
    return found


@router.get("/api/campaigns/{campaign_id}/factions/{faction_id}")
def read_faction(request: Request, principal: Organiser, campaign_id: str, faction_id: str) -> dict:
    return factions.faction_json(_faction(_ctx(request, campaign_id), faction_id))


@router.put("/api/campaigns/{campaign_id}/factions/{faction_id}")
def put_faction(
    request: Request, principal: Organiser, campaign_id: str, faction_id: str, body: FactionIn
) -> dict:
    """Make the faction or change the fields given; a new one needs a name. The strength clamps at 0…100 and the
    reputation at ±100."""
    ctx = _ctx(request, campaign_id)
    faction = ctx.storage.factions.get(campaign_id, faction_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if faction is None:
        if not (changes.get("name") or "").strip() or not factions.slug(faction_id):
            raise refusal(PlayError("A new faction needs a name.", "Give it one: 'The Thieves' Guild'."))
        faction = Faction(campaign_id=campaign_id, id=factions.slug(faction_id), name="")
    if "name" in changes and not changes["name"].strip():
        raise refusal(PlayError("A faction needs a name."))
    if "strength" in changes:
        changes["strength"] = max(0, min(100, changes["strength"]))
    if "reputation" in changes:
        changes["reputation"] = max(-100, min(100, changes["reputation"]))
    faction = replace(
        faction, **{k: v.strip() if isinstance(v, str) and k != "notes_md" else v for k, v in changes.items()}
    )
    ctx.storage.factions.put(faction)
    world_changed(request, campaign_id)
    return factions.faction_json(faction)


@router.delete("/api/campaigns/{campaign_id}/factions/{faction_id}", status_code=204)
def delete_faction(request: Request, principal: Organiser, campaign_id: str, faction_id: str) -> Response:
    """Its clocks stay, without a faction."""
    ctx = _ctx(request, campaign_id)
    ctx.storage.factions.delete(campaign_id, _faction(ctx, faction_id).id)
    world_changed(request, campaign_id)
    return Response(status_code=204)


class ClockIn(BaseModel):
    label: str | None = None
    kind: str | None = None
    faction: str | None = None
    days_remaining: int | None = Field(default=None, ge=0)
    segments: int | None = Field(default=None, ge=1)
    filled: int | None = Field(default=None, ge=0)
    on_complete: str | None = None


def _clock(ctx: CampaignContext, clock_id: str) -> Clock:
    found = ctx.storage.clocks.get(int(clock_id)) if clock_id.isdigit() else None
    if found is None or found.campaign_id != ctx.campaign_id:
        raise _missing("clock")
    return found


def _clock_from(ctx: CampaignContext, clock: Clock, body: ClockIn) -> Clock:
    """`clock` with the body's fields, as `factions.shaped_clock` checks them and says when it is complete."""
    try:
        return factions.shaped_clock(ctx, clock, body.model_dump(exclude_unset=True))
    except PlayError as error:
        raise refusal(error) from None


@router.get("/api/campaigns/{campaign_id}/clocks")
def list_clocks(request: Request, principal: Organiser, campaign_id: str) -> list[dict]:
    """Every clock, the running ones first, then the completed ones."""
    listed = factions.clocks(_ctx(request, campaign_id))
    return listed["clocks"] + listed["completed"]


@router.post("/api/campaigns/{campaign_id}/clocks", status_code=201)
def add_clock(request: Request, principal: Organiser, campaign_id: str, body: ClockIn) -> dict:
    ctx = _ctx(request, campaign_id)
    blank = Clock(id=0, campaign_id=campaign_id, label="", kind="countdown", started_day=factions.day_number(ctx))
    added = ctx.storage.clocks.add(_clock_from(ctx, blank, body))
    world_changed(request, campaign_id)
    return factions.clock_json(added)


@router.get("/api/campaigns/{campaign_id}/clocks/{clock_id}")
def read_clock(request: Request, principal: Organiser, campaign_id: str, clock_id: str) -> dict:
    return factions.clock_json(_clock(_ctx(request, campaign_id), clock_id))


@router.put("/api/campaigns/{campaign_id}/clocks/{clock_id}")
def put_clock(request: Request, principal: Organiser, campaign_id: str, clock_id: str, body: ClockIn) -> dict:
    ctx = _ctx(request, campaign_id)
    changed = _clock_from(ctx, _clock(ctx, clock_id), body)
    ctx.storage.clocks.put(changed)
    world_changed(request, campaign_id)
    return factions.clock_json(changed)


@router.delete("/api/campaigns/{campaign_id}/clocks/{clock_id}", status_code=204)
def delete_clock(request: Request, principal: Organiser, campaign_id: str, clock_id: str) -> Response:
    ctx = _ctx(request, campaign_id)
    ctx.storage.clocks.delete(_clock(ctx, clock_id).id)
    world_changed(request, campaign_id)
    return Response(status_code=204)


class QuestNoteIn(BaseModel):
    day: int = Field(ge=1)
    text: str
    known: bool = True


class QuestIn(BaseModel):
    title: str | None = None
    giver: str | None = None
    scope: str | None = None
    stakes: str | None = None
    status: str | None = None
    known: bool | None = None
    related: list[str] | None = None
    log: list[QuestNoteIn] | None = None
    notes_md: str | None = None


def _quest_of(ctx: CampaignContext, quest_id: str) -> Quest:
    found = ctx.storage.quests.get(ctx.campaign_id, quest_id)
    if found is None:
        raise _missing("quest")
    return found


@router.get("/api/campaigns/{campaign_id}/quests")
def list_quests(request: Request, principal: Organiser, campaign_id: str) -> list[dict]:
    ctx = _ctx(request, campaign_id)
    return [quests.quest_json(q) for q in ctx.storage.quests.list(campaign_id)]


@router.get("/api/campaigns/{campaign_id}/quests/{quest_id}")
def read_quest(request: Request, principal: Organiser, campaign_id: str, quest_id: str) -> dict:
    return quests.quest_json(_quest_of(_ctx(request, campaign_id), quest_id))


@router.put("/api/campaigns/{campaign_id}/quests/{quest_id}")
def put_quest(request: Request, principal: Organiser, campaign_id: str, quest_id: str, body: QuestIn) -> dict:
    """Make the quest (available and not yet known, unless told) or change the fields given; a new one needs a
    title. An active quest has started, and a complete or failed one has ended, on today's day unless already."""
    ctx = _ctx(request, campaign_id)
    quest = ctx.storage.quests.get(campaign_id, quest_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if quest is None:
        slug = factions.slug(quest_id)
        if not (changes.get("title") or "").strip() or not slug:
            raise refusal(PlayError("A new quest needs a title."))
        quest = Quest(campaign_id=campaign_id, id=slug, title="")
    if "title" in changes and not changes["title"].strip():
        raise refusal(PlayError("A quest needs a title."))
    if changes.get("status", quest.status) not in QUEST_STATUSES:
        raise refusal(PlayError(f"Unknown status '{changes['status']}'.", f"Use one of: {', '.join(QUEST_STATUSES)}."))
    if changes.get("scope", quest.scope) not in quests.SCOPES:
        raise refusal(PlayError(f"Unknown scope '{changes['scope']}'.", f"Use one of: {', '.join(quests.SCOPES)}."))
    if "log" in changes:
        changes["log"] = tuple(QuestNote(n.day, n.text, n.known) for n in body.log or ())
    if "related" in changes:
        changes["related"] = tuple(changes["related"])
    quest = replace(quest, **changes)
    today = factions.day_number(ctx)
    if quest.status != "available" and quest.started_day is None:
        quest = replace(quest, started_day=today)
    ended = quest.status in quests.ENDED
    quest = replace(quest, ended_day=(quest.ended_day or today) if ended else None)
    ctx.storage.quests.put(quest)
    world_changed(request, campaign_id)
    return quests.quest_json(quest)


@router.delete("/api/campaigns/{campaign_id}/quests/{quest_id}", status_code=204)
def delete_quest(request: Request, principal: Organiser, campaign_id: str, quest_id: str) -> Response:
    ctx = _ctx(request, campaign_id)
    ctx.storage.quests.delete(campaign_id, _quest_of(ctx, quest_id).id)
    world_changed(request, campaign_id)
    return Response(status_code=204)


class PossessionIn(BaseModel):
    name: str | None = None
    kind: str | None = None
    owner: str | None = None
    species: str | None = None
    location: str | None = None
    value_gp: int | None = Field(default=None, ge=0)
    description: str | None = None
    notes_md: str | None = None
    stats: dict[str, Any] | None = None
    inventory: list[str] | None = None


def _possession_id(ctx: CampaignContext, possession_id: str) -> str:
    if ctx.storage.possessions.get(ctx.campaign_id, possession_id) is None:
        raise _missing("possession")
    return possession_id


@router.get("/api/campaigns/{campaign_id}/possessions")
def list_possessions(request: Request, principal: Organiser, campaign_id: str) -> list[dict]:
    """Every possession, with its DM-only notes."""
    ctx = _ctx(request, campaign_id)
    return [possessions.detail(ctx, p.id) for p in ctx.storage.possessions.list(campaign_id)]


@router.post("/api/campaigns/{campaign_id}/possessions", status_code=201)
def add_possession(request: Request, principal: Organiser, campaign_id: str, body: PossessionIn) -> dict:
    ctx = _ctx(request, campaign_id)
    fields = body.model_dump(exclude_none=True)
    notes = fields.pop("notes_md", "")
    try:
        added = possessions.add(ctx, fields.pop("name", ""), fields.pop("kind", ""), notes=notes, **fields)
        answer = possessions.detail(ctx, added["id"])
    except PlayError as error:
        raise refusal(error) from None
    world_changed(request, campaign_id)
    return answer


@router.get("/api/campaigns/{campaign_id}/possessions/{possession_id}")
def read_possession(request: Request, principal: Organiser, campaign_id: str, possession_id: str) -> dict:
    ctx = _ctx(request, campaign_id)
    return possessions.detail(ctx, _possession_id(ctx, possession_id))


@router.put("/api/campaigns/{campaign_id}/possessions/{possession_id}")
def put_possession(
    request: Request, principal: Organiser, campaign_id: str, possession_id: str, body: PossessionIn
) -> dict:
    """Change the fields given; `stats` are merged over the current ones, `owner` "" gives it to the party."""
    ctx = _ctx(request, campaign_id)
    ref = _possession_id(ctx, possession_id)
    fields = body.model_dump(exclude_none=True)
    if "notes_md" in fields:
        fields["notes"] = fields.pop("notes_md")
    try:
        possessions.update(ctx, ref, **fields)
        answer = possessions.detail(ctx, ref)
    except PlayError as error:
        raise refusal(error) from None
    world_changed(request, campaign_id)
    return answer


@router.delete("/api/campaigns/{campaign_id}/possessions/{possession_id}", status_code=204)
def delete_possession(request: Request, principal: Organiser, campaign_id: str, possession_id: str) -> Response:
    ctx = _ctx(request, campaign_id)
    possessions.remove(ctx, _possession_id(ctx, possession_id))
    world_changed(request, campaign_id)
    return Response(status_code=204)
