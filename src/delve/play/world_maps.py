"""A campaign's world maps and the party's place on them (plan 6 Task 8, spec §10; plan 7 Task 9).

At creation, and for a campaign from before plateau 6 on first use (it has none), the pinned revision's `ready` world
maps (source `module`) and then its setting's (source `setting`: the install's ready maps of the setting, else the
shipped setting's own; `delve.play.setting_maps`) are copied into the campaign; on a name clash the module's map wins.
Every copy starts with nothing known. After that the campaign owns them: `save_geo` changes its copy, never the
module's or the setting's, and a setting map added later changes no campaign made before it.

Plateau 7 plays on the geo model (`delve.maps.geo`). A plateau 6 `.map` copy is converted once, on its first read
(`ensure_geo`); one from before plateau 7 knows everything, as its seats saw it, its `revealed` places too. What the
party knows of a map is its `knowledge`, and the seat's view is cut from it (`seat_view`).

A map's hidden features are the DM's until `reveal` names them. The seat's view never holds a hidden one, nor any
feature's `dm_notes`.

The whole party shares one world position (`CampaignState.world`): a split party is a dungeon-map matter.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import replace
from typing import Any

from delve.domain.world import CampaignWorldMap, WorldKnowledge, WorldMapSource, WorldPosition
from delve.maps.geo import knowledge as known_of
from delve.maps.geo.from_dsl import FromDsl, from_view
from delve.maps.geo.geojson import from_geojson, to_geojson
from delve.maps.geo.knowledge import SIGHT_KM, StartHow
from delve.maps.geo.model import GeoFeature, GeoMap, GeoMapError, Point, water_from_areas
from delve.maps.geo.routing import ModeRules, RouteGraph, build_graph
from delve.maps.geo.terrain import PLACE_KINDS
from delve.maps.world import WorldMapError, compile_view, is_workspace, parse
from delve.modules.source import ModuleSource, pinned_source, world_includes
from delve.modules.worldmaps import geo_of
from delve.play.context import CampaignContext, NotFound, PlayError

__all__ = [
    "accept",
    "add_place",
    "current_map",
    "delete",
    "describe",
    "dm_view",
    "ensure_geo",
    "ensure_seeded",
    "feature_point",
    "geo",
    "get",
    "graph",
    "hide",
    "knowledge",
    "loaded",
    "locate_geo",
    "maps",
    "party_point",
    "place_party",
    "position",
    "reveal",
    "reveal_along",
    "reveal_area",
    "reveal_around",
    "save_geo",
    "seat_maps",
    "seat_view",
    "seed",
    "set_start",
]

NO_MAP_HINT = "The organiser adds world maps on the campaign's page; until then, narrate the journey with advance_days."

_GEO: dict[tuple[str, str], tuple[str, str, GeoMap]] = {}
"""Each campaign map's geo map, with the `updated_at` it was read at and the digest of its document. A write that
changes only what the party knows moves `updated_at` but not the digest, so the map (and its graphs) are kept."""

_GRAPHS: dict[tuple[str, str], tuple[str, dict[tuple[str, bool], RouteGraph]]] = {}
"""Each campaign map's routing graphs by mode and `flies`, with the digest of the document they were built from."""

_FROM_DSL: dict[tuple[str, str], tuple[str, FromDsl]] = {}
"""The conversion of each map's `.map` text, with the digest of the text and its includes, for plateau 6 positions."""


# --- the copies ------------------------------------------------------------------------------------------------------


def _setting_maps(ctx: CampaignContext) -> tuple[list[WorldMapSource], dict[str, str]]:
    """The setting's maps and what they may include: through the setting layer, the install's ready maps of the
    setting, else the shipped setting's own."""
    if ctx.setting is None:
        return [], {}
    own = list(ctx.setting.world_maps())
    return own, world_includes(own)


def _copy(ctx: CampaignContext, origin: str, world_map: WorldMapSource, includes: dict[str, str]) -> CampaignWorldMap:
    """The campaign's copy of a module's or a setting's map: a `.map` one gets its geo document too, and every map
    starts with nothing known. An include fragment is copied as text only, for the maps that include it."""
    geo = world_map.geo
    if geo is None and is_workspace(world_map.dsl):
        try:
            geo = geo_of(world_map, includes)
        except WorldMapError:
            geo = None
    fragment = world_map.geo is None and not is_workspace(world_map.dsl)
    return CampaignWorldMap(
        ctx.campaign_id,
        world_map.name,
        world_map.title or world_map.name,
        origin,  # type: ignore[arg-type]
        world_map.dsl,
        geo=geo,
        picture=world_map.picture,
        knowledge=None if fragment else WorldKnowledge(),
    )


def seed(ctx: CampaignContext, source: ModuleSource | None) -> int:
    """Copy the module's `ready` world maps, then the setting's, that the campaign doesn't have by name; how many. A
    map in review is never copied."""
    have = {m.name for m in ctx.storage.world_maps.list(ctx.campaign_id)}
    module_maps = list(source.worldmaps) if source else []
    origins = [("module", w, world_includes(module_maps)) for w in module_maps if w.status == "ready"]
    setting_maps, setting_includes = _setting_maps(ctx)
    origins += [("setting", w, setting_includes) for w in setting_maps]
    added = 0
    with ctx.storage.transaction():
        for origin, world_map, includes in origins:
            if world_map.name in have:
                continue
            ctx.storage.world_maps.put(_copy(ctx, origin, world_map, includes))
            have.add(world_map.name)
            added += 1
    return added


def ensure_seeded(ctx: CampaignContext) -> None:
    """Copy the maps into a campaign that has none yet: one from before plateau 6."""
    if ctx.storage.world_maps.list(ctx.campaign_id):
        return
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    seed(ctx, pinned_source(ctx.storage, campaign.module_id, campaign.revision) if campaign else None)


def maps(ctx: CampaignContext) -> list[CampaignWorldMap]:
    """The campaign's world maps, in the order they came; a `.map` one not yet converted is converted first."""
    ensure_seeded(ctx)
    return [ensure_geo(ctx, m) for m in ctx.storage.world_maps.list(ctx.campaign_id)]


def _is_map(world_map: CampaignWorldMap) -> bool:
    """A world map of its own: a geo document, or a `.map` workspace (not an include fragment)."""
    return world_map.geo is not None or is_workspace(world_map.dsl)


def ensure_geo(ctx: CampaignContext, world_map: CampaignWorldMap) -> CampaignWorldMap:
    """`world_map` with its geo document: a `.map` one without is converted, with the campaign's includes. Only `geo`
    and `knowledge` are written, and the knowledge only when it has none: a map from before plateau 7 then knows
    everything, its revealed places too, as its seats saw it. A fragment, or a text that doesn't read, is left as it
    is."""
    if world_map.geo is not None or not is_workspace(world_map.dsl):
        return world_map
    try:
        compiled = compile_view(parse(world_map.dsl, _includes(ctx)))
    except WorldMapError:
        return world_map
    converted = from_view(compiled, revealed=world_map.revealed).geo
    known = world_map.knowledge
    if known is None:
        known = WorldKnowledge(
            everything=True, features=tuple(r for r in world_map.revealed if converted.feature(r) is not None)
        )
    with ctx.storage.transaction():
        return ctx.storage.world_maps.put(replace(world_map, geo=to_geojson(converted), knowledge=known))


def _refuse_review(world_map: CampaignWorldMap) -> CampaignWorldMap:
    if world_map.status == "review":
        raise PlayError(
            f"The world map {world_map.title} is still in review.",
            "The organiser accepts it on the campaign's page; until then, narrate the journey with advance_days.",
        )
    return world_map


def get(ctx: CampaignContext, name: str) -> CampaignWorldMap:
    """The campaign's map `name`; refused with every map's name, and with how to go on when it has none."""
    listed = maps(ctx)
    found = next((m for m in listed if m.name == name.strip()), None)
    if found is None:
        if not listed:
            raise PlayError("This campaign has no world map.", NO_MAP_HINT)
        raise NotFound(f"No world map '{name}'.", [{"id": m.name, "name": m.title} for m in listed])
    return found


def current_map(ctx: CampaignContext, name: str = "") -> CampaignWorldMap:
    """The map `name`, else the one the party is on, else the campaign's first ready one. A map in review is
    refused: it is never played on."""
    if name.strip():
        return _refuse_review(get(ctx, name))
    here = position(ctx)
    if here is not None:
        return _refuse_review(get(ctx, here.map))
    listed = [m for m in maps(ctx) if _is_map(m) and m.status == "ready"]
    if not listed:
        raise PlayError("This campaign has no world map.", NO_MAP_HINT)
    return listed[0]


def _includes(ctx: CampaignContext) -> dict[str, str]:
    """What the campaign's maps may `!include`: each other, by name and file name."""
    return world_includes(
        [WorldMapSource(m.name, m.title, m.dsl) for m in ctx.storage.world_maps.list(ctx.campaign_id)]
    )


# --- changing them ---------------------------------------------------------------------------------------------------


def delete(ctx: CampaignContext, name: str) -> None:
    """Remove the map; the party loses its place if it was on it."""
    world_map = get(ctx, name)
    with ctx.storage.transaction():
        ctx.storage.world_maps.delete(ctx.campaign_id, world_map.name)
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        if state.world is not None and state.world.map == world_map.name:
            state = ctx.storage.campaign_states.put(replace(state, world=None))
        if state.journey is not None and state.journey.map == world_map.name:
            ctx.storage.campaign_states.put(replace(state, journey=None))
        ctx.log("world_map", action="deleted", map=world_map.name)


def reveal(ctx: CampaignContext, feature: str, map: str = "") -> dict[str, Any]:
    """The party learns of a feature, any feature: a region's land (its cells) becomes known, anything else the
    feature itself, wherever it lies, even a hidden one."""
    world_map = current_map(ctx, map)
    geo_map = geo(ctx, world_map.name)
    found = _find(geo_map, feature, f"No feature '{feature}' on {world_map.title}.")
    known = knowledge(ctx, world_map.name)
    if found.layer == "regions":
        cells = set(known.cells) | set(known_of.start(geo_map, "regions", regions=[found.id]).cells)
        after = known if known.everything else replace(known, cells=tuple(sorted(cells)))
    else:
        after = known_of.reveal_feature(known, found.id)
    if after != known:
        with ctx.storage.transaction():
            ctx.storage.world_maps.put(replace(world_map, knowledge=after))
            ctx.log("world_map", action="revealed", map=world_map.name, feature=found.id)
    return {"map": world_map.name, "revealed": found.id, "label": found.name}


# --- the party's place -----------------------------------------------------------------------------------------------


def position(ctx: CampaignContext) -> WorldPosition | None:
    return ctx.storage.campaign_states.get(ctx.campaign_id).world


def move_to(ctx: CampaignContext, map_name: str, point: tuple[float, float], at: str | None) -> WorldPosition:
    """Put the party at `point` of the map, in km on its geo map, `at` the feature there, if any."""
    here = WorldPosition(map_name, float(point[0]), float(point[1]), at, km=True)
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    ctx.storage.campaign_states.put(replace(state, world=here))
    return here


def place_party(ctx: CampaignContext, at: str, map: str = "") -> dict[str, Any]:
    """Put the party at a place (a feature, or `x,y` in km) of the map: the one named, else the one it is on, else
    the campaign's first; the land in sight of it becomes known."""
    world_map = current_map(ctx, map)
    name, point = locate_geo(geo(ctx, world_map.name), at)
    with ctx.storage.transaction():
        here = move_to(ctx, world_map.name, point, name)
        ctx.log("world_position", **here.to_dict())
        places = reveal_around(ctx, world_map.name, point)
    return {"position": here.to_dict(), "came_into_sight": places}


# --- the geo model (plan 7 Task 9) -----------------------------------------------------------------------------------


def _digest(doc: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _loaded(ctx: CampaignContext, world_map: CampaignWorldMap) -> tuple[str, GeoMap]:
    """The digest of the map's geo document and its geo map, read once and kept while the document is the same."""
    world_map = ensure_geo(ctx, world_map)
    if world_map.geo is None:
        raise PlayError(
            f"The world map '{world_map.name}' doesn't read.", "The organiser fixes it on the campaign's page."
        )
    key = (ctx.campaign_id, world_map.name)
    cached = _GEO.get(key)
    if cached is not None and cached[0] == world_map.updated_at:
        return cached[1], cached[2]
    digest = _digest(world_map.geo)
    if cached is not None and cached[1] == digest:
        _GEO[key] = (world_map.updated_at, digest, cached[2])
        return digest, cached[2]
    loaded = from_geojson(world_map.geo).geo
    if loaded is None:
        raise PlayError(
            f"The world map '{world_map.name}' has no scale.", "The organiser sets it on the campaign's page."
        )
    _GEO[key] = (world_map.updated_at, digest, loaded)
    return digest, loaded


def geo(ctx: CampaignContext, name: str) -> GeoMap:
    """The campaign map `name` as a geo map; refused when it doesn't read. Treat it as read-only."""
    return _loaded(ctx, get(ctx, name))[1]


def loaded(ctx: CampaignContext, name: str) -> tuple[str, GeoMap]:
    """The digest of the map's geo document and its geo map: a journey's `planned_on`. The digest stays while only
    what the party knows changes."""
    return _loaded(ctx, get(ctx, name))


def graph(ctx: CampaignContext, name: str, rules: ModeRules) -> RouteGraph:
    """The map's routing graph for a mode (and whether it flies), built once and kept until the map changes."""
    digest, geo_map = _loaded(ctx, get(ctx, name))
    key = (ctx.campaign_id, name.strip())
    cached = _GRAPHS.get(key)
    if cached is None or cached[0] != digest:
        cached = (digest, {})
        _GRAPHS[key] = cached
    mode = (rules.mode, rules.flies)
    if mode not in cached[1]:
        cached[1][mode] = build_graph(geo_map, rules)
    return cached[1][mode]


def save_geo(
    ctx: CampaignContext, name: str, geo: dict[str, Any], title: str = "", *, status: str = "ready"
) -> CampaignWorldMap:
    """Put the map `name` as this Delve GeoJSON document, keeping where it came from and what the party knows (a new
    one knows nothing). Its water cells follow its water areas: a reshaped lake moves its cells. Raises
    `GeoMapError` with its problems for a document that doesn't hold together."""
    name = name.strip()
    if not name:
        raise PlayError("A world map needs a name.")
    if status not in ("ready", "review"):
        raise PlayError(f"Unknown status '{status}': ready or review.")
    imported = from_geojson(geo)
    if imported.geo is None:
        raise GeoMapError("A world map needs its scale", ["the document isn't a Delve world map"])
    ensure_seeded(ctx)
    old = ctx.storage.world_maps.get(ctx.campaign_id, name)
    previous = None
    if old is not None and old.geo is not None:
        try:
            previous = from_geojson(old.geo).geo
        except GeoMapError:
            previous = None
    shaped = water_from_areas(imported.geo, previous)
    doc = to_geojson(shaped)
    picture = shaped.picture.id if shaped.picture is not None else None
    with ctx.storage.transaction():
        if old is None:
            saved = CampaignWorldMap(
                ctx.campaign_id,
                name,
                title.strip() or name,
                "campaign",
                "",
                geo=doc,
                picture=picture,
                status=status,  # type: ignore[arg-type]
                knowledge=WorldKnowledge(),
            )
        else:
            saved = replace(
                old,
                title=title.strip() or old.title,
                geo=doc,
                picture=picture,
                status=status,  # type: ignore[arg-type]
                knowledge=old.knowledge if old.knowledge is not None else WorldKnowledge(),
            )
        stored = ctx.storage.world_maps.put(saved)
        ctx.log("world_map", action="created" if old is None else "edited", map=name)
    return stored


def accept(ctx: CampaignContext, name: str) -> CampaignWorldMap:
    """The organiser accepts what Delve read: the map in review becomes ready, to be played on."""
    world_map = get(ctx, name)
    if world_map.status != "review":
        return world_map
    with ctx.storage.transaction():
        accepted = ctx.storage.world_maps.put(replace(world_map, status="ready"))
        ctx.log("world_map", action="accepted", map=world_map.name)
    return accepted


# --- places on a geo map ---------------------------------------------------------------------------------------------

_XY = re.compile(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*")


def _find(geo_map: GeoMap, ref: str, missing: str) -> GeoFeature:
    """The feature `ref` (an id, or a name in any case); an ambiguous name is refused with its candidates, an unknown
    one with the names that come closest."""
    ref = ref.strip()
    found = geo_map.feature(ref) if ref else None
    if found is not None:
        return found
    named = geo_map.features_named(ref)
    if len(named) > 1:
        raise NotFound(f"Several features are named '{ref}'.", [{"id": f.id, "name": f.name} for f in named])
    by_word = {f.id: f for f in geo_map.features} | {f.name.casefold(): f for f in geo_map.features}
    close = difflib.get_close_matches(ref.casefold(), list(by_word), n=5, cutoff=0.6)
    candidates = list({by_word[c].id: by_word[c] for c in close}.values()) or list(geo_map.features[:10])
    raise NotFound(missing, [{"id": f.id, "name": f.name} for f in candidates])


def _middle(coords: list[Any]) -> Point:
    return (sum(float(p[0]) for p in coords) / len(coords), sum(float(p[1]) for p in coords) / len(coords))


def feature_point(f: GeoFeature) -> Point:
    """Where a feature is, for putting the party there: a place's point, a line's middle vertex, an area's middle."""
    kind, coords = f.geometry.get("type"), f.geometry.get("coordinates")
    if kind == "Point":
        return (float(coords[0]), float(coords[1]))
    if kind == "LineString":
        middle = coords[len(coords) // 2]
        return (float(middle[0]), float(middle[1]))
    if kind == "Polygon":
        ring = coords[0][:-1] if len(coords[0]) > 1 and coords[0][0] == coords[0][-1] else coords[0]
        return _middle(ring)
    if kind == "MultiPolygon":
        return _middle([p for polygon in coords for p in polygon[0]])
    return _middle([p for part in coords for p in part])


def locate_geo(geo_map: GeoMap, ref: str) -> tuple[str | None, Point]:
    """The feature's id (None for a bare point) and the point of `ref`, a feature or `x,y` in km; an unknown place
    is refused with the names that come closest, a point off the map with the map's size."""
    xy = _XY.fullmatch(ref)
    if xy is not None:
        x, y = float(xy.group(1)), float(xy.group(2))
        if not (0 <= x <= geo_map.frame.width_km and 0 <= y <= geo_map.frame.height_km):
            raise PlayError(
                f"The point {x:g},{y:g} is off the map.",
                f"x and y are km from the top left, up to {geo_map.frame.width_km:.0f},{geo_map.frame.height_km:.0f}.",
            )
        return None, (x, y)
    try:
        found = _find(geo_map, ref, f"No place '{ref}' on the map.")
    except NotFound as unknown:
        raise NotFound(unknown.message, unknown.candidates, hint="Name a place on the map, or give x,y.") from None
    return found.id, feature_point(found)


def _new_id(geo_map: GeoMap, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "place"
    taken = {f.id for f in geo_map.features}
    fid, n = base, 1
    while fid in taken:
        n += 1
        fid = f"{base}-{n}"
    return fid


def add_place(
    ctx: CampaignContext,
    name: str,
    kind: str,
    at: str,
    *,
    description: str = "",
    notes: str = "",
    hidden: bool = False,
    map: str = "",
) -> dict[str, Any]:
    """The DM adds a place to the campaign's map: a point at `at` (a place or `x,y` in km), with a new id (its name,
    made unique). `description` is what the characters may learn of it, `notes` the DM's alone; a `hidden` place
    stays the DM's until `reveal`, else it shows where the party knows the land."""
    name = name.strip()
    if not name:
        raise PlayError("A place needs a name.")
    if kind not in PLACE_KINDS:
        raise PlayError(f"Unknown kind '{kind}'.", f"One of {', '.join(PLACE_KINDS)}.")
    world_map = current_map(ctx, map)
    geo_map = _loaded(ctx, world_map)[1]
    _, point = locate_geo(geo_map, at)
    fid = _new_id(geo_map, name)
    added = GeoFeature(
        fid,
        "places",
        kind,
        name,
        {"type": "Point", "coordinates": [point[0], point[1]]},
        description=description.strip(),
        dm_notes=notes.strip(),
        hidden=hidden,
    )
    with ctx.storage.transaction():
        ctx.storage.world_maps.put(
            replace(world_map, geo=to_geojson(replace(geo_map, features=(*geo_map.features, added))))
        )
        ctx.log("world_map", action="place added", map=world_map.name, feature=fid)
    return {"map": world_map.name, "id": fid, "name": name, "kind": kind, "at": list(point), "hidden": hidden}


# --- what the party knows --------------------------------------------------------------------------------------------


def knowledge(ctx: CampaignContext, name: str) -> WorldKnowledge:
    """What the party knows of the map `name`."""
    return ensure_geo(ctx, get(ctx, name)).knowledge or WorldKnowledge()


def _know(ctx: CampaignContext, world_map: CampaignWorldMap, known: WorldKnowledge, action: str) -> None:
    if known == (world_map.knowledge or WorldKnowledge()):
        return
    with ctx.storage.transaction():
        ctx.storage.world_maps.put(replace(world_map, knowledge=known))
        ctx.log("world_map", action=action, map=world_map.name)


def set_start(
    ctx: CampaignContext, name: str, how: StartHow, *, regions: tuple[str, ...] | list[str] = (), ring: Any = ()
) -> WorldKnowledge:
    """What the party knows of the map at the start: everything, nothing, some regions, or an area drawn as a ring.
    Raises `KnowledgeError` for a region that isn't there or an area of fewer than three points."""
    world_map = ensure_geo(ctx, get(ctx, name))
    known = known_of.start(_loaded(ctx, world_map)[1], how, regions=regions, ring=ring)
    _know(ctx, world_map, known, "start")
    return known


def _visible_places(geo_map: GeoMap, known: WorldKnowledge) -> list[str]:
    return [f.id for f in known_of.visible_features(geo_map, known) if f.layer == "places"]


def reveal_around(ctx: CampaignContext, name: str, point: Point) -> list[str]:
    """The land in sight of `point` becomes known; the names of the places that came into sight (never a hidden
    one)."""
    return reveal_along(ctx, name, [point])


def reveal_along(ctx: CampaignContext, name: str, points: list[Point]) -> list[str]:
    """The land in sight of the line `points` becomes known, in one write; the names of the places that came into
    sight (never a hidden one)."""
    world_map = ensure_geo(ctx, get(ctx, name))
    known = world_map.knowledge or WorldKnowledge()
    revealed = known_of.reveal_along(_loaded(ctx, world_map)[1], known, points)
    _know(ctx, world_map, revealed.knowledge, "sighted")
    return revealed.places


def hide(ctx: CampaignContext, feature: str, map: str = "") -> dict[str, Any]:
    """The party forgets a feature, any feature: a place, a road. It shows no more, even where the party knows the
    land, until `reveal`."""
    world_map = current_map(ctx, map)
    geo_map = geo(ctx, world_map.name)
    found = _find(geo_map, feature, f"No feature '{feature}' on {world_map.title}.")
    known = known_of.forget_feature(world_map.knowledge or WorldKnowledge(), found.id)
    with ctx.storage.transaction():
        ctx.storage.world_maps.put(
            replace(world_map, knowledge=known)
        )
        ctx.log("world_map", action="hidden", map=world_map.name, feature=found.id)
    return {"map": world_map.name, "hidden": found.id, "label": found.name}


def reveal_area(
    ctx: CampaignContext, at: str, radius_km: float = SIGHT_KM, map: str = "", *, forget: bool = False
) -> dict[str, Any]:
    """The party knows the land within `radius_km` of `at` (a place, or `x,y` in km); with `forget`, it no longer
    does: it forgets it, or it was never theirs to know. The answer names the places that came into sight, or went
    out of it."""
    if not 0 < radius_km <= 1000:
        raise PlayError("The radius is a number of km, more than 0 and at most 1000.")
    world_map = current_map(ctx, map)
    geo_map = geo(ctx, world_map.name)
    _, point = locate_geo(geo_map, at)
    known = world_map.knowledge or WorldKnowledge()
    if forget:
        after = known_of.forget_area(geo_map, known, point, radius_km)
    else:
        after = known_of.reveal_area(geo_map, known, point, radius_km)
    before, now = _visible_places(geo_map, known), _visible_places(geo_map, after)
    changed = [p for p in before if p not in now] if forget else [p for p in now if p not in before]
    _know(ctx, world_map, after, "forgot an area" if forget else "revealed an area")
    names = {f.id: f.name for f in geo_map.features}
    return {
        "map": world_map.name,
        "at": [point[0], point[1]],
        "radius_km": radius_km,
        "forgotten" if forget else "came_into_sight": [names[p] for p in changed],
    }


def _knows_something(known: WorldKnowledge | None) -> bool:
    return known is not None and bool(known.everything or known.cells or known.features)


def seat_maps(ctx: CampaignContext) -> list[CampaignWorldMap]:
    """The maps a seat may be shown: the `ready` world maps (not fragments) that the party knows something of, or
    is on."""
    here = position(ctx)
    return [
        m
        for m in maps(ctx)
        if m.status == "ready"
        and m.geo is not None
        and (_knows_something(m.knowledge) or (here is not None and here.map == m.name))
    ]


def party_point(ctx: CampaignContext, name: str) -> Point | None:
    """The party's point on the map `name`, in km; None when it isn't on it. A plateau 6 position is converted: by
    the place it is at, else its point through the `.map`'s units."""
    here = position(ctx)
    if here is None or here.map != name.strip():
        return None
    if here.km:
        return (here.x, here.y)
    geo_map = geo(ctx, here.map)
    at = geo_map.feature(here.at) if here.at else None
    if at is not None and at.geometry.get("type") == "Point":
        return feature_point(at)
    converted = _converted(ctx, get(ctx, here.map))
    return converted.km((here.x, here.y)) if converted is not None else None


def _converted(ctx: CampaignContext, world_map: CampaignWorldMap) -> FromDsl | None:
    """The conversion of the map's `.map` text, kept while the text and its includes are the same; None for a map
    without a text that reads."""
    if not is_workspace(world_map.dsl):
        return None
    includes = _includes(ctx)
    digest = _digest({"dsl": world_map.dsl, "includes": includes})
    key = (ctx.campaign_id, world_map.name)
    cached = _FROM_DSL.get(key)
    if cached is None or cached[0] != digest:
        try:
            cached = (digest, from_view(compile_view(parse(world_map.dsl, includes))))
        except WorldMapError:
            return None
        _FROM_DSL[key] = cached
    return cached[1]


def _picture(ctx: CampaignContext, geo_map: GeoMap) -> dict[str, Any] | None:
    """The map's picture as the views give it, once it is cut into tiles; None without one."""
    ref = geo_map.picture
    stored = ctx.storage.world_pictures.get(ref.id) if ref is not None else None
    if ref is None or stored is None:
        return None
    return {
        "id": ref.id,
        "width_px": ref.width_px,
        "height_px": ref.height_px,
        "km_per_px": ref.km_per_px,
        "max_zoom": stored.max_zoom,
    }


def _journey(ctx: CampaignContext, name: str) -> Any:
    journey = ctx.storage.campaign_states.get(ctx.campaign_id).journey
    return journey if journey is not None and journey.map == name else None


def seat_view(ctx: CampaignContext, name: str) -> dict[str, Any]:
    """What a seat sees of the map: what the party knows of it, the party and its journey as far as it runs in known
    land (`knowledge.seat_view`). `tiles_version` is a digest of the known cells and the picture."""
    world_map = ensure_geo(ctx, get(ctx, name))
    geo_map = _loaded(ctx, world_map)[1]
    known = world_map.knowledge or WorldKnowledge()
    picture = _picture(ctx, geo_map)
    version = json.dumps([picture["id"] if picture else None, known.everything, known.to_dict()["cells"]])
    return known_of.seat_view(
        geo_map,
        known,
        name=world_map.name,
        title=world_map.title,
        party=party_point(ctx, world_map.name),
        journey=_journey(ctx, world_map.name),
        picture=picture,
        tiles_version=hashlib.sha256(version.encode()).hexdigest()[:16],
    )


def dm_view(ctx: CampaignContext, name: str) -> dict[str, Any]:
    """The whole map for the DM (`knowledge.dm_view`)."""
    world_map = ensure_geo(ctx, get(ctx, name))
    geo_map = _loaded(ctx, world_map)[1]
    return known_of.dm_view(
        geo_map,
        world_map.knowledge or WorldKnowledge(),
        name=world_map.name,
        title=world_map.title,
        party=party_point(ctx, world_map.name),
        journey=_journey(ctx, world_map.name),
        picture=_picture(ctx, geo_map),
    )


def _described(f: GeoFeature, shown: set[str]) -> dict[str, Any]:
    return {
        "id": f.id,
        "layer": f.layer,
        "kind": f.kind,
        "name": f.name,
        "hidden": f.hidden,
        "known": f.id in shown,
        "tags": list(f.tags),
    }


def describe(ctx: CampaignContext, name: str = "", feature: str = "") -> dict[str, Any]:
    """For the DM: the map's features, each marked `hidden` (the DM's until revealed) and `known` (on the players'
    map), and where the party is; or one feature with its description and its `dm_notes`."""
    world_map = current_map(ctx, name)
    geo_map = geo(ctx, world_map.name)
    shown = {f.id for f in known_of.visible_features(geo_map, world_map.knowledge or WorldKnowledge())}
    if feature.strip():
        found = _find(geo_map, feature, f"No feature '{feature}' on {world_map.title}.")
        return {
            "map": world_map.name,
            "feature": {
                **_described(found, shown),
                **dict(found.props),
                "description": found.description,
                "dm_notes": found.dm_notes,
                "at": list(feature_point(found)),
            },
        }
    here = position(ctx)
    return {
        "name": world_map.name,
        "title": world_map.title,
        "source": world_map.source,
        "maps": [{"name": m.name, "title": m.title} for m in maps(ctx) if _is_map(m)],
        "units": geo_map.frame.units,
        "size_km": [geo_map.frame.width_km, geo_map.frame.height_km],
        "features": [_described(f, shown) for f in geo_map.features],
        "position": here.to_dict() if here is not None and here.map == world_map.name else None,
    }
