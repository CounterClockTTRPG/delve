"""Travel on a world map by the mode the DM picks, a leg at a time (plan 6 Task 8, Decision 4; plan 7 Task 10;
ttrpg2 `tools/travel.py`).

A leg runs from the party's place to the destination by the cheapest route for its mode (`delve.maps.geo.routing`,
on the map's graph for that mode, built once and kept until the map changes): on foot, on horseback or by cart over
the land and its roads, by river boat along the rivers and lakes, by ship over the sea and the large lakes. Each day:

1. `days.pass_days(ctx, 1)`: the clocks tick and the date moves, as every new day does;
2. the day's weather in the day's terrain (`weather.weather`), rolled once a day and terrain: the terrain given, else
   road on a route, else the cell's under the day's start (sea and lake as ocean, impassable as mountain);
3. the km: the mode's miles a day (`base pace`, below) × 1.609344 × each stretch's rate × the weather's pace, walking
   the route's stretches (a blizzard is 0, and the day still passes);
4. one encounter check, the ruleset's `encounter_check`: a d6 at 1, a d20 in towns, and what is met when it comes.
   A day's dice are the beat's `<beat>/travel day <n>`, so a leg of many days in one beat rolls fresh each day;
5. the land in sight of the day's way becomes known (`world_maps.reveal_along`).

An encounter stops the leg there, and the party's `Journey` keeps the rest: `travel()` with no destination goes on,
planned again from where the party is (so a map the organiser edited meanwhile is followed). Arrival ends the journey.

The base pace, in miles a day: on foot 2 × the slowest traveller's movement rate (a mount in `by` carries its owner,
at its `fly` when it flies; a vehicle or a ship in `by` carries everyone at its `mv`); on horseback 2 × the mounts'
`mv` (their `fly` when they all fly, and the leg then flies), else 2 × `HORSE_MV`; by cart `CART_MILES_PER_DAY`, or
2 × a vehicle's `mv`; by river boat (`RIVER_BOAT_MPH`, or the boat's `mph`) ± `RIVER_CURRENT_MPH` downstream and
upstream, × `RIVER_HOURS`; by ship (`SHIP_MPH`, or the ship's `mph`) × `SHIP_HOURS`, or 2 × a ship's `mv` without an
`mph`. A house rule's `miles_per_day` replaces it, for the leg and the journey. A forced march is × 1.5, on land.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace
from itertools import pairwise
from typing import Any

from delve.dice import Dice
from delve.domain.world import Journey, Possession
from delve.maps.geo.grid import cell_at
from delve.maps.geo.knowledge import visible_features
from delve.maps.geo.model import GeoMap, Point
from delve.maps.geo.routing import MODES, GeoRoute, NoRoute, Stretch, plan, point_along, slowest, stretch_at
from delve.maps.geo.terrain import PLACE_KINDS, ROUTE_KINDS
from delve.play import characters, days, moves, possessions, quests, wandering, weather, world_maps
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.rules.classic import checks, overland
from delve.rules.classic.overland import MILES_TO_KM, TravelRates
from delve.rules.classic.terrain import TERRAIN_ALIASES

__all__ = ["MAX_DAYS", "TERRAIN_RATES", "distance", "nearest", "route_preview", "travel"]

MAX_DAYS = 60
"""The longest leg one call makes; a longer one is travelled in legs."""

TERRAIN_RATES: dict[str, float] = {
    "road": 1.0,
    "plains": 1.0,
    "wilderness": 1.0,
    "urban": 1.0,
    "forest": 0.5,
    "hills": 0.5,
    "desert": 0.5,
    "arctic": 0.5,
    "swamp": 1 / 3,
    "jungle": 1 / 3,
    "mountain": 1 / 3,
    "ocean": 1.0,
}
"""A day's terrain (as the weather and the encounters name it) and its pace on foot, as a share of the road's: the
rates of `overland.LAND_RATES`, under the names of the weather tables. Ocean is for a boat only."""

FORCED_MARCH = 1.5
LAND_MODES = ("foot", "horse", "cart")
SHIPS = ("ship",)
VEHICLES = ("vehicle", "ship")
WEATHER_TERRAIN = {"sea": "ocean", "lake": "ocean", "impassable": "mountain"}
"""The weather tables' terrain for the terrain classes they don't name."""
ARRIVED_KM = 0.01
"""Within 10 m of the end, the party has arrived."""
NO_JOURNEY = ("No journey under way.", "Name where to: travel(to=…).")


def _terrain_key(raw: str) -> str:
    key = raw.strip().lower()
    return TERRAIN_ALIASES.get(key, key)


def _given_terrain(terrain: str, mode: str) -> str:
    key = _terrain_key(terrain)
    if key and key not in TERRAIN_RATES:
        raise PlayError(f"Unknown terrain '{terrain}'.", f"Use one of: {', '.join(sorted(TERRAIN_RATES))}.")
    if key == "ocean" and mode in LAND_MODES:
        raise PlayError("Over the ocean the party travels by ship.", "Travel with mode ship, or by land.")
    return key


def _mode(mode: str) -> str:
    wanted = mode.strip().lower() or "foot"
    if wanted not in MODES:
        raise PlayError(f"Unknown mode '{mode}'.", f"One of: {', '.join(MODES)}.")
    return wanted


def _rides(ctx: CampaignContext, by: Iterable[str]) -> list[Possession]:
    """The possessions in `by`, each a mount with an owner, a vehicle or a ship."""
    everything = ctx.storage.possessions.list(ctx.campaign_id)
    out = []
    for ref in by:
        found = next((p for p in everything if p.id == ref), None)
        found = found or next((p for p in everything if p.name.casefold() == str(ref).strip().casefold()), None)
        if found is None:
            raise NotFound(f"No possession '{ref}'.", [{"id": p.id, "name": p.name} for p in everything])
        if found.kind == "mount" and found.owner_id is None:
            raise PlayError(
                f"{found.name} belongs to the party: who rides it?", "Give it an owner with update_possession."
            )
        if found.kind not in ("mount", *VEHICLES):
            raise PlayError(f"{found.name} is a {found.kind}: nobody travels on it.", "Name mounts, vehicles or ships.")
        out.append(found)
    return out


def _paces(ctx: CampaignContext, rides: list[Possession], *, ridden: int = 0) -> list[tuple[int, bool]]:
    """Each traveller's movement rate and whether it flies: a mount carries its owner, else the traveller walks (or,
    with `ridden`, rides a horse of that rate)."""
    carried = [possessions.movement(p)[0] for p in rides if p.kind in VEHICLES]
    if carried:
        return [(min(carried), False)]
    mounts = {p.owner_id: possessions.movement(p) for p in rides if p.kind == "mount"}
    paces = []
    for pc in characters.party(ctx):
        mv, fly = mounts.get(pc.id, (0, 0))
        paces.append((fly, True) if fly else (mv, False) if mv else (ridden or pc.sheet.movement_rate, False))
    return paces


class Pace:
    """A leg's speed: the km a clear day covers on each stretch of the route, and whether the leg flies."""

    def __init__(
        self,
        mode: str,
        miles: float,
        *,
        flies: bool = False,
        boat_mph: float | None = None,
        rates: TravelRates | None = None,
    ) -> None:
        self.mode, self.miles, self.flies, self.boat_mph, self.rates = mode, miles, flies, boat_mph, rates

    def km_a_day(self, stretch: Stretch) -> float:
        if self.boat_mph is not None and self.rates is not None:
            current = {"downstream": 1, "upstream": -1}.get(stretch.what, 0) * self.rates.river_current_mph
            return max(0.0, self.boat_mph + current) * self.rates.river_hours * MILES_TO_KM
        return self.miles * MILES_TO_KM * (1.0 if self.flies else stretch.rate)

    def days(self, route: GeoRoute, forced: bool) -> float:
        """The clear days the route takes."""
        boost = FORCED_MARCH if forced and self.mode in LAND_MODES else 1.0
        return sum(s.km / max(self.km_a_day(s) * boost, 1e-9) for s in route.stretches if s.km > 0)


def _pace(ctx: CampaignContext, mode: str, rides: list[Possession], miles_per_day: float) -> Pace:
    """The leg's pace by its mode (the module's docstring), or the DM's `miles_per_day`."""
    if mode == "foot":
        paces = _paces(ctx, rides)
        if not paces or min(mv for mv, _ in paces) <= 0:
            raise PlayError("Nobody travels: the party has no characters that move.", "Create the PCs first.")
        flies = all(f for _, f in paces)
        base: float = 2 * min(mv for mv, _ in paces)
    elif mode == "horse":
        if not characters.party(ctx):
            raise PlayError("Nobody travels: the party has no characters that move.", "Create the PCs first.")
        paces = _paces(ctx, [p for p in rides if p.kind == "mount"], ridden=ctx.rules.travel.horse_mv)
        flies = all(f for _, f in paces)
        base = 2 * min(mv for mv, _ in paces)
    elif mode == "cart":
        carts = [possessions.movement(p)[0] for p in rides if p.kind == "vehicle"]
        flies, base = False, 2 * min(carts) if carts and min(carts) > 0 else ctx.rules.travel.cart_miles_per_day
    elif mode == "river":
        boats = [possessions.mph(p) for p in rides if p.kind in VEHICLES]
        mph = min((b for b in boats if b is not None), default=ctx.rules.travel.river_boat_mph)
        if miles_per_day > 0:
            return Pace(mode, miles_per_day)
        return Pace(mode, mph * ctx.rules.travel.river_hours, boat_mph=mph, rates=ctx.rules.travel)
    else:
        ships = [p for p in rides if p.kind in SHIPS]
        flies = False
        if ships:
            speeds = [possessions.mph(p) for p in ships]
            base = min(
                s * ctx.rules.travel.ship_hours if s is not None else 2 * possessions.movement(p)[0]
                for p, s in zip(ships, speeds, strict=True)
            )
        else:
            base = ctx.rules.travel.ship_mph * ctx.rules.travel.ship_hours
    if base <= 0:
        raise PlayError("Nobody travels: what carries them doesn't move.", "Give it a movement rate (mv or mph).")
    return Pace(mode, miles_per_day if miles_per_day > 0 else base, flies=flies)


def _encounter_json(found: checks.EncounterResult) -> dict[str, Any]:
    keys = ("terrain", "triggered", "tier", "result", "category", "monster", "note")
    return {key: getattr(found, key) for key in keys if getattr(found, key) not in ("", None)}


def _day_terrain(geo: GeoMap, point: Point, given: str, stretch: Stretch) -> str:
    """The terrain of a day, for its weather and its encounters: the one given, else road on a route, ocean on the
    sea or a lake, else the cell's under the day's start, else wilderness."""
    if given:
        return given
    if stretch.what in ROUTE_KINDS:
        return "road"
    if stretch.what in WEATHER_TERRAIN:
        return WEATHER_TERRAIN[stretch.what]
    cell = cell_at(geo.grid, *point)
    cls = geo.terrain_of(cell) if cell is not None else None
    key = WEATHER_TERRAIN.get(cls or "", cls or "")
    return key if key in TERRAIN_RATES else "wilderness"


def _walk(route: GeoRoute, done: float, pace: Pace, share: float) -> float:
    """The km a day takes the party along the route from `done`, at `share` of a clear day's pace."""
    if share <= 0:
        return 0.0
    left, at = 1.0, done
    while left > 1e-12 and at < route.km - 1e-9:
        stretch = stretch_at(route, at)
        speed = pace.km_a_day(stretch) * share
        if speed <= 0:
            break
        end = stretch.start_km + stretch.km
        reach = at + left * speed
        if reach <= end + 1e-9:
            return min(reach, route.km) - done
        left -= (end - at) / speed
        at = end
    return min(at, route.km) - done


def _line(route: GeoRoute, start: float, end: float) -> list[Point]:
    """The route's line from `start` to `end` km."""
    out = [point_along(route, start)]
    along = 0.0
    for a, b in pairwise(route.points):
        along += math.dist(a, b)
        if start < along < end:
            out.append(b)
    out.append(point_along(route, end))
    return out


def _label(geo: GeoMap, fid: str | None, ref: str) -> str:
    found = geo.feature(fid) if fid else None
    return found.name if found is not None else ref


def _here(ctx: CampaignContext, world_map: Any) -> tuple[Point, str | None]:
    point = world_maps.party_point(ctx, world_map.name)
    if point is None:
        raise PlayError(f"The party has no place on {world_map.title}.", "Put it there first with place_party(at=…).")
    here = world_maps.position(ctx)
    return point, here.at if here is not None else None


def _plan(
    ctx: CampaignContext, name: str, geo: GeoMap, mode: str, flies: bool, start: Point, at: str | None, goal: Point,
    goal_label: str,
) -> GeoRoute:  # fmt: skip
    graph = world_maps.graph(ctx, name, overland.mode_rules(mode, ctx.rules.travel, flies=flies))
    start_label = _label(geo, at, "the party's place")
    try:
        return plan(graph, start, goal, start_label=start_label, goal_label=goal_label)
    except NoRoute as no:
        raise PlayError(
            no.reason, "Choose another mode, or travel in legs by way of a place that joins them."
        ) from None


def travel(
    ctx: CampaignContext,
    to: str = "",
    *,
    mode: str = "foot",
    terrain: str = "",
    by: Iterable[str] = (),
    forced_march: bool = False,
    miles_per_day: float = 0,
    map: str = "",
) -> dict[str, Any]:
    """One leg of a journey: from the party's place to `to` (empty: on with the journey under way) by `mode`, a day
    at a time, until it arrives or an encounter stops it. `{mode, days, arrived, position, legs: [{date, terrain,
    weather, miles, km, encounter}], clocks, via_roads, miles, miles_left, km, km_left, came_into_sight, journey}`, and
    `left_maps`: the module's maps the party had a place on, which it leaves by setting off (DEL-331)."""
    if miles_per_day < 0:
        raise PlayError("miles_per_day is a number of miles, 0 for the table's pace.")
    journey = ctx.storage.campaign_states.get(ctx.campaign_id).journey
    if not to.strip():
        if journey is None:
            raise PlayError(*NO_JOURNEY)
        to, mode, map = journey.to, journey.mode, journey.map
        by = by or journey.by
        miles_per_day = miles_per_day or journey.miles_per_day
    mode = _mode(mode)
    world_map = world_maps.current_map(ctx, map)
    digest, geo = world_maps.loaded(ctx, world_map.name)
    start, at = _here(ctx, world_map)
    goal_id, goal = world_maps.locate_geo(geo, to)
    goal_label = _label(geo, goal_id, to)
    given = _given_terrain(terrain, mode)
    by = tuple(by)
    rides = _rides(ctx, by)
    pace = _pace(ctx, mode, rides, float(miles_per_day))
    trip = _plan(ctx, world_map.name, geo, mode, pace.flies, start, at, goal, goal_label)
    if trip.km <= ARRIVED_KM:
        raise PlayError(f"The party is already at {goal_label}.")
    estimate = math.ceil(pace.days(trip, forced_march) - 1e-9)
    if estimate > MAX_DAYS:
        miles = trip.km / MILES_TO_KM
        raise PlayError(
            f"{miles:.0f} miles is about {estimate} days of travel, more than {MAX_DAYS}: travel in legs.",
            "Name a place on the way, and travel on from there.",
        )
    boost = FORCED_MARCH if forced_march and mode in LAND_MODES else 1.0
    level = max(1, round(quests.avg_party_level(ctx)))
    legs: list[dict[str, Any]] = []
    clocks: dict[str, Any] = {}
    done = 0.0
    via_roads = False
    with ctx.storage.transaction():
        for _ in range(MAX_DAYS):
            point = point_along(trip, done)
            stretch = stretch_at(trip, done)
            day_terrain = _day_terrain(geo, point, given, stretch)
            passed = days.pass_days(ctx, 1, reason=f"travel to {goal_label}")
            for key, value in passed.get("clocks", {}).items():
                clocks[key] = clocks.get(key, []) + list(value) if key == "completed" else list(value)
            today = ctx.storage.campaign_states.get(ctx.campaign_id).day
            sky = weather.weather(ctx, day_terrain)
            km = _walk(trip, done, pace, sky.pace * boost)
            via_roads = via_roads or any(
                s.what in ROUTE_KINDS and s.start_km < done + km and s.start_km + s.km > done for s in trip.stretches
            )
            done += km
            dice = Dice(ctx.dice.rng, ctx.storage.rolls, ctx.campaign_id, f"{ctx.beat}/travel day {today}")
            met = checks.encounter_check(
                dice,
                ctx.lookups,
                terrain=day_terrain,
                level=level,
                rules=ctx.rules,
                encounters=ctx.ruleset.encounters if ctx.ruleset is not None else None,
                world=wandering.world(ctx),
            )
            legs.append(
                {
                    "date": passed["date"].label,
                    "terrain": day_terrain,
                    "weather": sky.label,
                    "miles": round(km / MILES_TO_KM, 1),
                    "km": round(km, 1),
                    "encounter": _encounter_json(met) if met.triggered else None,
                }
            )
            if done >= trip.km - ARRIVED_KM or met.triggered:
                break
        arrived = done >= trip.km - ARRIVED_KM
        end = trip.points[-1] if arrived else point_along(trip, done)
        moved = world_maps.move_to(ctx, world_map.name, end, goal_id if arrived else None)
        sighted = world_maps.reveal_along(ctx, world_map.name, _line(trip, 0.0, min(done, trip.km)))
        kept = None
        if not arrived:
            kept = Journey(
                world_map.name,
                mode,
                to,
                goal_label if goal_id else None,
                trip.points,
                trip.km,
                done_km=done,
                by=by,
                planned_on=digest,
                miles_per_day=float(miles_per_day),
            )
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        ctx.storage.campaign_states.put(replace(state, journey=kept))
        ctx.log(
            "travel",
            to=to,
            mode=mode,
            days=len(legs),
            arrived=arrived,
            distance_km=round(done, 1),
            position=moved.to_dict(),
        )
    # Set off overland, the party is on none of the module's maps: no one stays behind on the camp's map while the
    # rest are on the tower's (DEL-331).
    left = moves.leave_maps(ctx, [c.id for c in characters.party(ctx)]) if legs else []
    km_left = max(0.0, trip.km - done)
    out: dict[str, Any] = {
        "mode": mode,
        "days": len(legs),
        "arrived": arrived,
        "position": moved.to_dict(),
        "legs": legs,
        "clocks": clocks,
        "via_roads": via_roads,
        "miles": round(done / MILES_TO_KM, 1),
        "miles_left": round(km_left / MILES_TO_KM, 1),
        "km": round(done, 1),
        "km_left": round(km_left, 1),
        "came_into_sight": sighted,
        "journey": None if kept is None else {"to": kept.to, "km_left": round(km_left, 1)},
    }
    if left:
        out["left_maps"] = left
    if not arrived:
        out["note"] = "The journey keeps the rest of the way: travel() goes on from here."
    return out


def route_preview(
    ctx: CampaignContext,
    to: str,
    *,
    mode: str = "foot",
    by: Iterable[str] = (),
    miles_per_day: float = 0,
    map: str = "",
) -> dict[str, Any]:
    """The route a leg would take, without travelling: `{map, mode, units, km, miles, days, points, slowest: [{what,
    km, days}], to}`, `days` at a clear day's pace."""
    mode = _mode(mode)
    world_map = world_maps.current_map(ctx, map)
    geo = world_maps.geo(ctx, world_map.name)
    start, at = _here(ctx, world_map)
    goal_id, goal = world_maps.locate_geo(geo, to)
    pace = _pace(ctx, mode, _rides(ctx, by), float(miles_per_day))
    trip = _plan(ctx, world_map.name, geo, mode, pace.flies, start, at, goal, _label(geo, goal_id, to))
    return {
        "map": world_map.name,
        "mode": mode,
        "units": geo.frame.units,
        "km": round(trip.km, 1),
        "miles": round(trip.km / MILES_TO_KM, 1),
        "days": round(pace.days(trip, False), 1),
        "points": [[round(x, 2), round(y, 2)] for x, y in trip.points],
        "slowest": [
            {"what": s.what, "km": round(s.km, 1), "days": round(s.km / max(pace.km_a_day(s), 1e-9), 1)}
            for s in slowest(trip)
        ],
        "to": goal_id or to,
    }


def distance(ctx: CampaignContext, a: str, b: str, map: str = "", mode: str = "") -> dict[str, Any]:
    """Between two places: by the route of `mode` when one is given, else the straight line."""
    world_map = world_maps.current_map(ctx, map)
    geo = world_maps.geo(ctx, world_map.name)
    (id_a, pa), (id_b, pb) = world_maps.locate_geo(geo, a), world_maps.locate_geo(geo, b)
    out: dict[str, Any] = {"map": world_map.name, "from": id_a or a, "to": id_b or b}
    if mode.strip():
        wanted = _mode(mode)
        graph = world_maps.graph(ctx, world_map.name, overland.mode_rules(wanted, ctx.rules.travel))
        try:
            km = plan(graph, pa, pb, start_label=_label(geo, id_a, a), goal_label=_label(geo, id_b, b)).km
        except NoRoute as no:
            raise PlayError(no.reason, "Choose another mode.") from None
        out["mode"] = wanted
    else:
        km = math.dist(pa, pb)
    return out | {"km": round(km, 1), "miles": round(km / MILES_TO_KM, 1), "units": geo.frame.units}


def nearest(ctx: CampaignContext, kind: str = "city", n: int = 3, map: str = "") -> dict[str, Any]:
    """The `n` places of `kind` nearest the party, as the crow flies, but the one it is at; each marked `hidden`
    when the players don't see it."""
    wanted = kind.strip().lower()
    if wanted not in PLACE_KINDS:
        raise PlayError(f"Unknown kind '{kind}'.", f"One of: {', '.join(PLACE_KINDS)}.")
    world_map = world_maps.current_map(ctx, map)
    geo = world_maps.geo(ctx, world_map.name)
    here, at = _here(ctx, world_map)
    shown = {f.id for f in visible_features(geo, world_maps.knowledge(ctx, world_map.name))}
    found = sorted(
        ((math.dist(here, world_maps.feature_point(f)), f) for f in geo.features
         if f.layer == "places" and f.kind == wanted and f.id != at),
        key=lambda found: found[0],
    )[: max(1, int(n))]  # fmt: skip
    places = [
        {"name": f.id, "label": f.name, "km": round(km, 1), "miles": round(km / MILES_TO_KM, 1), "hidden": f.id not in shown}
        for km, f in found
    ]  # fmt: skip
    return {"map": world_map.name, "kind": wanted, "places": places}
