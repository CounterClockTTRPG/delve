"""A campaign's world maps and travel (plan 6 Task 8, Review Focus 3; plan 7 Task 10, Review Focus 3): the maps are
copied from the module and the setting and owned by the campaign from then on; the party has one place on them, in km;
travel moves it a leg at a time by a mode (on foot, on horseback, by cart, by river boat, by ship), day by day through
`days.pass_days`, at the mode's pace, the route's terrain and the day's weather, reveals the land on the way, and stops
at an encounter, partway along the route, the journey kept for `travel()` to go on."""

import json
from dataclasses import replace

import pytest

from delve.dice import ScriptedRng, SeededRng
from delve.dm.tools import ToolHost
from delve.domain.modules import ModuleMap
from delve.domain.world import WorldMapSource, WorldPosition
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.grid import cell_at
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid
from delve.modules.source import ModuleSource
from delve.play import characters, days, factions, possessions, travel, world_maps
from delve.play.context import NotFound, PlayError, context_for
from delve.rules.classic import weather_tables
from delve.rules.classic.overland import MILES_TO_KM
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

SECRET = "SECRET-XYZZY"

# A small vale, 1 mile a unit: a road from Oakton to Millbrook (120 miles), a hidden tower, a wood, a bay.
VALE = f"""\
workspace vale {{
    model {{
        city oakton {{ at 0,0 }}
        city millbrook {{ at 120,0 }}
        city harbour {{ at 0,-100 }}
        city far-isle {{ at 25,-160 }}
        city distant {{ at 2000,0 }}
        poi old-tower {{ at 60,60; label "The Drowned Tower"; description "{SECRET}: the lich sleeps."; doc "{SECRET}"; tags [hidden] }}
        poi east-glade {{ at 280,0 }}
        terrain whisper-wood {{ polygon 200,-50 300,-50 300,50 200,50; biome forest }}
        terrain the-bay {{ polygon -50,-200 100,-200 100,-120 -50,-120; biome ocean }}
        road kings-road {{ from oakton; to millbrook; surface dirt }}
        road tower-path {{ from millbrook; to old-tower; surface dirt }}
    }}
    views {{ view world {{ scope vale; include cities, roads, terrain, poi; units miles }} }}
}}
"""


VALE_MAP = WorldMapSource("vale", "The Vale", VALE)


def make_campaign(storage, worldmaps=(VALE_MAP,), setting=""):
    module = storage.modules.create("The Vale")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    storage.module_sources.put(module.id, ModuleSource(worldmaps=tuple(worldmaps)))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, setting=setting, ruleset="osric")


@pytest.fixture
def campaign(storage):
    """A campaign of the vale, without a setting: the plain calendar, its day 1 in spring."""
    return make_campaign(storage)


def at_oakton(ctx):
    world_maps.place_party(ctx, "oakton")
    return ctx


@pytest.fixture
def party(make_ctx):
    """Garrek and Pippa, walking at 12: 24 miles a day."""
    ctx = make_ctx()
    garrek = characters.create(ctx, name="Garrek", sheet={"hp_max": 10})
    pippa = characters.create(ctx, name="Pippa", sheet={"hp_max": 6})
    return garrek, pippa


def clear_days(n: int) -> list[int]:
    """The dice of `n` quiet days: clear weather (1 on the table) and no encounter (6 on the d6)."""
    return [1, 6] * n


def roll_for(season: str, terrain: str, label: str) -> int:
    """The weather roll that lands on `label` in this season and terrain."""
    reached = 0
    for weight, name, _ in weather_tables.table(season, terrain):
        reached += weight
        if name == label:
            return reached
    raise AssertionError(label)


def _clock(ctx, label):
    return next(c for c in ctx.storage.clocks.list(ctx.campaign_id) if c.label == label)


# --- the campaign's world maps ---------------------------------------------------------------------------------------


def test_the_modules_maps_are_copied_on_first_use_and_owned_by_the_campaign(ctx):
    [vale] = world_maps.maps(ctx)
    assert (vale.name, vale.title, vale.source, vale.dsl) == ("vale", "The Vale", "module", VALE)
    world_maps.add_place(ctx, "Newtown", "town", "10,10", map="vale")
    assert world_maps.geo(ctx, "vale").feature("newtown") is not None
    assert ctx.storage.module_sources.get(ctx.storage.campaigns.get(ctx.campaign_id).module_id).worldmaps[0].dsl == VALE


def test_the_modules_map_wins_a_name_clash_with_the_settings(storage):
    clash = WorldMapSource("greyhawk-region", "Our Greyhawk", VALE)
    campaign = make_campaign(storage, worldmaps=[clash], setting="greyhawk")
    ctx = context_for(storage, campaign.id, "beat-1", catalogs=over(PlayReference()))
    [only] = world_maps.maps(ctx)
    assert (only.name, only.title, only.source) == ("greyhawk-region", "Our Greyhawk", "module")
    plain = make_campaign(storage, worldmaps=[], setting="greyhawk")
    [region] = world_maps.maps(context_for(storage, plain.id, "beat-1", catalogs=over(PlayReference())))
    assert (region.name, region.title, region.source) == ("greyhawk-region", "Greyhawk region", "setting")


def seat_names(ctx) -> set[str]:
    return {f["name"] for f in world_maps.seat_view(ctx, "vale")["features"]}


def test_a_hidden_place_is_left_out_of_the_seats_view_until_revealed(ctx):
    world_maps.set_start(ctx, "vale", "everything")
    view = json.dumps(world_maps.seat_view(ctx, "vale"))
    assert "Drowned Tower" not in view and SECRET not in view and "Oakton" in view
    dm = world_maps.dm_view(ctx, "vale")
    tower = next(f for f in dm["features"] if f["id"] == "old-tower")
    assert tower["hidden"] and not tower["known"] and tower["dm_notes"].startswith(SECRET)
    world_maps.reveal(ctx, "old-tower")
    view = json.dumps(world_maps.seat_view(ctx, "vale"))
    assert "The Drowned Tower" in view and SECRET not in view
    assert world_maps.get(ctx, "vale").revealed == (), "plateau 6's revealed is no longer written"
    # Plan 7 Task 9: reveal takes any feature now, and an unknown one is refused.
    assert world_maps.reveal(ctx, "oakton")["revealed"] == "oakton"
    with pytest.raises(NotFound):
        world_maps.reveal(ctx, "nowhere")


def test_the_seats_view_shows_the_party(ctx):
    world_maps.set_start(ctx, "vale", "everything")
    assert world_maps.seat_view(ctx, "vale")["party"] is None
    world_maps.place_party(ctx, "millbrook")
    x, y = world_maps.geo(ctx, "vale").feature("millbrook").geometry["coordinates"]
    assert world_maps.seat_view(ctx, "vale")["party"] == [x, y]
    assert "Millbrook" in seat_names(ctx)


# --- the party's place -----------------------------------------------------------------------------------------------


def vale_km(ctx, x, y):
    """A point of the vale's `.map` (miles), in km on its converted geo map."""
    oakton = world_maps.geo(ctx, "vale").feature("oakton").geometry["coordinates"]
    return (oakton[0] + x * MILES_TO_KM, oakton[1] - y * MILES_TO_KM)


def test_place_party(ctx):
    """Plan 7 Task 10: every position is written in km on the map's geo document."""
    out = world_maps.place_party(ctx, "Millbrook")
    mx, my = vale_km(ctx, 120, 0)
    assert out["position"] == {
        "map": "vale",
        "x": pytest.approx(mx),
        "y": pytest.approx(my),
        "at": "millbrook",
        "km": True,
    }
    assert ctx.storage.campaign_states.get(ctx.campaign_id).world.at == "millbrook"
    world_maps.place_party(ctx, "30,40")
    assert world_maps.position(ctx).to_dict() == {"map": "vale", "x": 30.0, "y": 40.0, "at": None, "km": True}
    with pytest.raises(NotFound) as unknown:
        world_maps.place_party(ctx, "Milbrok")
    assert "millbrook" in [c["id"] for c in unknown.value.candidates]


# --- travel on the vale, plateau 6's cases ---------------------------------------------------------------------------


def test_a_five_day_road_journey_arrives_with_the_clocks_ticked_five_times(make_ctx, party):
    ctx = at_oakton(make_ctx(*clear_days(5)))
    factions.add_clock(ctx, "The bridge washes out", days=10)
    out = travel.travel(ctx, "millbrook")
    assert out["days"] == 5 and out["arrived"] and out["via_roads"] and out["mode"] == "foot"
    mx, my = vale_km(ctx, 120, 0)
    assert out["position"] == {
        "map": "vale",
        "x": pytest.approx(mx),
        "y": pytest.approx(my),
        "at": "millbrook",
        "km": True,
    }
    assert [leg["miles"] for leg in out["legs"]] == [24.0] * 5
    assert [leg["km"] for leg in out["legs"]] == [round(24 * MILES_TO_KM, 1)] * 5
    assert [leg["terrain"] for leg in out["legs"]] == ["road"] * 5
    assert [leg["date"] for leg in out["legs"]] == ["Day 2", "Day 3", "Day 4", "Day 5", "Day 6"]
    assert all(leg["encounter"] is None and leg["weather"] == "clear" for leg in out["legs"])
    assert _clock(ctx, "The bridge washes out").days_remaining == 5
    assert ctx.storage.campaign_states.get(ctx.campaign_id).day == 6
    assert out["journey"] is None and ctx.storage.campaign_states.get(ctx.campaign_id).journey is None
    assert out["miles"] == 120 and out["miles_left"] == 0 and out["km_left"] == 0


def test_travel_runs_the_new_day_hooks_once_per_day(make_ctx, party, monkeypatch):
    counted = []
    monkeypatch.setitem(days.HOOKS, "count", lambda ctx, day: counted.append(day) or {})
    travel.travel(at_oakton(make_ctx(*clear_days(5))), "millbrook")
    assert counted == [2, 3, 4, 5, 6]


def test_an_unknown_destination_is_refused_with_the_nearest_names(make_ctx, party):
    with pytest.raises(NotFound) as refused:
        travel.travel(at_oakton(make_ctx()), "Milbrook")
    assert "millbrook" in [c["id"] for c in refused.value.candidates]


def test_without_a_world_map_the_refusal_names_advance_days(storage, party):
    """Plan 7 Task 9: the DM can't make a map any more; the hint names advance_days and no tool that isn't there."""
    bare = make_campaign(storage, worldmaps=[])
    ctx = context_for(storage, bare.id, "beat-1", catalogs=over(PlayReference()))
    for refuse in (lambda: travel.travel(ctx, "millbrook"), lambda: world_maps.place_party(ctx, "millbrook")):
        with pytest.raises(PlayError) as refused:
            refuse()
        assert "advance_days" in refused.value.hint and "the campaign's page" in refused.value.hint


def test_without_a_place_the_refusal_names_place_party(make_ctx, party):
    with pytest.raises(PlayError) as refused:
        travel.travel(make_ctx(), "millbrook")
    assert "place_party" in refused.value.hint


def test_without_a_journey_travel_on_is_refused(make_ctx, party):
    with pytest.raises(PlayError, match="No journey under way."):
        travel.travel(at_oakton(make_ctx()))


def test_a_blizzard_day_covers_no_miles_and_still_passes(make_ctx, party):
    ctx = make_ctx()
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    ctx.storage.campaign_states.put(replace(state, day=300))  # winter, on the plain calendar
    blizzard = roll_for("winter", "road", "blizzard")
    ctx = at_oakton(make_ctx(blizzard, 6, *clear_days(5)))
    out = travel.travel(ctx, "millbrook")
    assert out["legs"][0]["weather"] == "blizzard" and out["legs"][0]["miles"] == 0
    assert out["days"] == 6 and out["arrived"]
    assert ctx.storage.campaign_states.get(ctx.campaign_id).day == 306


def test_weather_slows_a_day(make_ctx, party):
    rain = roll_for("spring", "road", "heavy rain")
    out = travel.travel(at_oakton(make_ctx(rain, 6, *clear_days(5))), "millbrook")
    assert out["legs"][0]["weather"] == "heavy rain"
    assert out["legs"][0]["miles"] == pytest.approx(24 * weather_tables_pace("heavy rain"))
    assert out["days"] == 6


def weather_tables_pace(label: str) -> float:
    return next(m for needle, m in weather_tables.PACE if needle in label)


def test_an_encounter_stops_the_party_partway_and_the_journey_goes_on(make_ctx, party):
    # Day 1 quiet; day 2 the d6 shows 1: the drift (2d6) and the table (1d6) say what is met.
    ctx = at_oakton(make_ctx(1, 6, 1, 1, 3, 4, 2))
    out = travel.travel(ctx, "millbrook")
    assert out["days"] == 2 and not out["arrived"]
    sx, sy = vale_km(ctx, 48, 0)
    assert out["position"] == {"map": "vale", "x": pytest.approx(sx), "y": pytest.approx(sy), "at": None, "km": True}
    met = out["legs"][1]["encounter"]
    assert met["triggered"] and met["result"] == "2d4 bandits"
    assert out["legs"][0]["encounter"] is None
    assert out["journey"] == {"to": "millbrook", "km_left": round(72 * MILES_TO_KM, 1)}
    kept = ctx.storage.campaign_states.get(ctx.campaign_id).journey
    assert (kept.map, kept.mode, kept.to, kept.to_label) == ("vale", "foot", "millbrook", "Millbrook")
    assert kept.done_km == pytest.approx(48 * MILES_TO_KM) and kept.planned_on == world_maps.loaded(ctx, "vale")[0]
    onward = travel.travel(make_ctx(*clear_days(3), beat="beat-2"))  # on with the journey, along the same road
    assert onward["arrived"] and onward["via_roads"] and onward["days"] == 3
    assert world_maps.position(ctx).at == "millbrook" and onward["journey"] is None
    assert ctx.storage.campaign_states.get(ctx.campaign_id).journey is None


def test_a_journey_over_sixty_days_is_refused(make_ctx, party):
    with pytest.raises(PlayError, match="travel in legs"):
        travel.travel(at_oakton(make_ctx()), "distant")
    assert make_ctx().storage.campaign_states.get(make_ctx().campaign_id).day == 1


def test_mounted_travel_is_faster(make_ctx, party):
    ctx = at_oakton(make_ctx(*clear_days(3)))
    horse = {"hp_max": 18, "thac0": 19, "mv": 24}  # OSRIC has no mount defaults
    bess = possessions.add(ctx, "Bess", "mount", owner="Garrek", species="riding horse", stats=horse)
    star = possessions.add(ctx, "Star", "mount", owner="Pippa", species="riding horse", stats=horse)
    out = travel.travel(ctx, "millbrook", by=[bess["id"], star["id"]])
    assert [leg["miles"] for leg in out["legs"]] == [48.0, 48.0, 24.0]  # mv 24: 48 a day
    x, y = vale_km(ctx, 96, 0)
    walking = travel.travel(make_ctx(*clear_days(1), beat="beat-2"), f"{x},{y}", by=[bess["id"]])
    assert walking["legs"][0]["miles"] == 24  # Pippa walks: the slowest sets the pace
    ridden = travel.travel(make_ctx(*clear_days(3), beat="beat-3"), "oakton", mode="horse")
    assert ridden["mode"] == "horse" and [leg["miles"] for leg in ridden["legs"]][:2] == [48.0, 48.0]  # 2 × HORSE_MV


def test_forced_march(make_ctx, party):
    out = travel.travel(at_oakton(make_ctx(*clear_days(4))), "millbrook", forced_march=True)
    assert out["legs"][0]["miles"] == 36 and out["days"] == 4


def test_an_unknown_terrain_mode_and_a_stranger_possession_are_refused(make_ctx, party):
    ctx = at_oakton(make_ctx())
    with pytest.raises(PlayError, match="terrain"):
        travel.travel(ctx, "millbrook", terrain="moon")
    with pytest.raises(PlayError, match="mode"):
        travel.travel(ctx, "millbrook", mode="balloon")
    with pytest.raises(PlayError, match="ship"):
        travel.travel(ctx, "millbrook", terrain="ocean")
    with pytest.raises(NotFound):
        travel.travel(ctx, "millbrook", by=["pos_nothing"])


# --- travel by mode on the weald (plan 7 Task 10, Review Focus 3) ----------------------------------------------------

_ROWS = [
    "pppppppppp" + "x" + "ppppppppp",
    "pppppppppp" + "x" + "ppppppppp",
    "ppp" + "llll" + "ppp" + "x" + "ppppppppp",
    "ppp" + "llll" + "ppp" + "x" + "ppppppppp",
    "ppp" + "llpl" + "ppp" + "x" + "ppppppppp",
    "ppp" + "llll" + "ppp" + "x" + "ppppppppp",
    "pp" + "hhhhhh" + "pp" + "x" + "ppppppppp",
    "pppppppppp" + "x" + "ppppppppp",
    "ppppppppp" + "mmm" + "pppppppp",
    "w" * 20,
]


def _place(id_, name, x, y, **kw):
    return GeoFeature(id_, "places", kw.pop("kind", "town"), name, {"type": "Point", "coordinates": [x, y]}, **kw)


def _line_feature(id_, layer, kind, name, points, **kw):
    return GeoFeature(id_, layer, kind, name, {"type": "LineString", "coordinates": [list(p) for p in points]}, **kw)


WEALD = GeoMap(
    Frame(200.0, 100.0),
    Grid("square", 10.0, 20, 10),
    "".join(_ROWS),
    (
        _place("ashby", "Ashby", 5, 15),
        _place("westgate", "Westgate", 95, 15),
        _place("eastgate", "Eastgate", 115, 15),
        _place("westmere", "Westmere", 27, 45, kind="port"),
        _place("eastmere", "Eastmere", 73, 45, kind="port"),
        _place("isle", "Isle", 55, 45, kind="village"),
        _place("smugglers", "Smugglers' Den", 50, 15, kind="other", hidden=True, dm_notes=SECRET),
        _place("spring", "Spring", 185, 15, kind="village"),
        _place("lowford", "Lowford", 125, 75),
        _place("southwest", "Southwest", 15, 88, kind="port"),
        _place("southeast", "Southeast", 185, 88, kind="port"),
        _line_feature("north-road", "routes", "road", "The North Road", [(5, 15), (95, 15)]),
        _line_feature("the-run", "water", "river", "The Run", [(190, 10), (150, 40), (120, 75)]),
    ),
)
"""200 × 100 km in cells of 10 km: an impassable ridge down column 10, crossed only at its pass (a mountain cell, row
8); a lake (columns 3–6, rows 2–5) with an island, Isle, and a port on each shore; a road from Ashby to Westgate past a
hidden den; the Run flowing from Spring down to Lowford; and the sea along the bottom, a port at each end."""


@pytest.fixture
def weald(make_ctx, party):
    """`weald(at, *dice, beat=…)`: a context with the party at a place of the weald, the campaign's own geo map."""
    world_maps.save_geo(make_ctx(), "weald", to_geojson(WEALD), "The Weald")

    def placed(at, *dice, beat="beat-1"):
        ctx = make_ctx(*dice, beat=beat)
        world_maps.place_party(ctx, at, map="weald")
        return ctx

    return placed


def _cells(route_points):
    return {cell_at(WEALD.grid, *p) for p in route_points}


def test_a_ship_crosses_the_lake_that_a_foot_leg_walks_around(weald):
    ctx = weald("westmere")
    walked = travel.route_preview(ctx, "eastmere")
    sailed = travel.route_preview(ctx, "eastmere", mode="ship")
    assert sailed["km"] < walked["km"]
    assert not {WEALD.terrain[c] for c in _cells(walked["points"])} & {"l", "w"}
    assert "l" in {WEALD.terrain[c] for c in _cells(sailed["points"])}
    out = travel.travel(weald("westmere", *clear_days(2), beat="beat-2"), "eastmere", mode="ship")
    assert out["arrived"] and out["days"] == 1 and out["mode"] == "ship"


def test_a_land_leg_to_an_island_is_refused_naming_the_mode(weald):
    with pytest.raises(PlayError, match="on foot"):
        travel.travel(weald("westmere"), "isle")
    assert travel.route_preview(weald("westmere"), "isle", mode="ship")["km"] > 0


def test_a_ship_from_an_inland_town_is_refused_and_from_a_port_snaps_to_its_water(weald):
    with pytest.raises(PlayError, match="Westgate isn't on the sea"):
        travel.travel(weald("westgate"), "eastmere", mode="ship")
    out = travel.travel(weald("southwest", *clear_days(4)), "southeast", mode="ship")
    assert out["legs"][0]["miles"] == 36 and out["legs"][0]["terrain"] == "ocean"  # SHIP_MPH × SHIP_HOURS


def test_a_river_boat_is_faster_downstream_and_snaps_to_a_river_a_cell_away(weald):
    down = travel.route_preview(weald("spring"), "lowford", mode="river")
    up = travel.route_preview(weald("lowford"), "spring", mode="river")
    assert down["days"] < up["days"]
    out = travel.travel(weald("spring", *clear_days(3)), "lowford", mode="river")
    assert out["arrived"] and out["days"] == 2 and out["legs"][0]["miles"] == 30  # (2 + 1) × 10
    back = travel.travel(weald("lowford", *clear_days(7), beat="beat-2"), "spring", mode="river")
    assert back["arrived"] and back["days"] > out["days"] and back["legs"][1]["miles"] == 10  # (2 - 1) × 10
    with pytest.raises(PlayError, match="Westgate isn't on a river or a lake."):
        travel.travel(weald("westgate"), "lowford", mode="river")


def test_a_boats_and_a_ships_mph_set_their_pace(weald):
    ctx = weald("spring", *clear_days(2))
    skiff = possessions.add(ctx, "The Skiff", "vehicle", stats={"mph": 3})
    out = travel.travel(ctx, "lowford", mode="river", by=[skiff["id"]])
    assert out["legs"][0]["miles"] == 40  # (3 + 1) × 10
    ctx = weald("southwest", *clear_days(3), beat="beat-2")  # 114 sea miles: 3 days at 48
    gull = possessions.add(ctx, "The Gull", "ship", stats={"mph": 4})
    assert travel.travel(ctx, "southeast", mode="ship", by=[gull["id"]])["legs"][0]["miles"] == 48  # 4 × 12
    assert possessions.mph(ctx.storage.possessions.get(ctx.campaign_id, gull["id"])) == 4
    with pytest.raises(PlayError, match="mph"):
        possessions.add(ctx, "The Leak", "ship", stats={"mph": -1})


def test_an_impassable_ridge_is_crossed_only_at_its_pass_and_a_griffon_flies_over_it(weald):
    walked = travel.route_preview(weald("westgate"), "eastgate")
    ridge = [p for p in walked["points"] if 100 <= p[0] <= 110]
    assert ridge and all(80 <= p[1] <= 90 for p in ridge)  # the pass, row 8
    assert walked["slowest"][0]["what"] == "mountain"
    ctx = weald("westgate", *clear_days(1), beat="beat-2")
    for pc in ("Garrek", "Pippa"):
        griffon = {"hp_max": 30, "thac0": 13, "mv": 12, "fly": 30}  # OSRIC has no mount defaults
        possessions.add(ctx, f"{pc}'s griffon", "mount", owner=pc, species="griffon", stats=griffon)
    rides = [p["id"] for p in possessions.listing(ctx)["possessions"]]
    flown = travel.travel(ctx, "eastgate", mode="horse", by=rides)
    assert flown["arrived"] and flown["days"] == 1 and flown["km"] == pytest.approx(20, abs=0.1)


def test_a_journey_goes_on_planned_again_after_the_organiser_edits_the_map(weald, make_ctx):
    ctx = weald("westgate", 1, 1, 3, 4, 2)  # an encounter on the first day
    out = travel.travel(ctx, "eastgate", terrain="road")
    assert not out["arrived"] and out["journey"]["to"] == "eastgate"
    before = ctx.storage.campaign_states.get(ctx.campaign_id).journey.planned_on
    rows = list(_ROWS)
    rows[2] = rows[2][:10] + "p" + rows[2][11:]  # a second pass, at row 2
    world_maps.save_geo(ctx, "weald", to_geojson(replace(WEALD, terrain="".join(rows))))
    assert world_maps.loaded(ctx, "weald")[0] != before
    onward = travel.travel(make_ctx(*clear_days(4), beat="beat-2"))
    assert onward["arrived"] and world_maps.position(ctx).at == "eastgate"
    assert onward["days"] < 4, "the new pass is nearer than the old"


def test_the_land_along_the_way_becomes_known_and_its_places_come_into_sight(weald):
    ctx = weald("westmere", *clear_days(4))
    out = travel.travel(ctx, "eastmere")
    assert out["arrived"] and "Eastmere" in out["came_into_sight"]
    assert "Smugglers' Den" not in out["came_into_sight"], "a hidden place never comes into sight"
    known = world_maps.knowledge(ctx, "weald")
    assert cell_at(WEALD.grid, 50, 15) in known.cells and cell_at(WEALD.grid, 185, 88) not in known.cells
    assert SECRET not in json.dumps(world_maps.seat_view(ctx, "weald"))


def test_a_house_rules_miles_per_day_is_kept_by_the_journey(weald, make_ctx):
    ctx = weald("ashby", 1, 1, 3, 4, 2)  # 90 road km: 55.9 miles; an encounter on the first day
    out = travel.travel(ctx, "westgate", miles_per_day=30, terrain="road")
    assert out["legs"][0]["miles"] == 30 and not out["arrived"]
    assert ctx.storage.campaign_states.get(ctx.campaign_id).journey.miles_per_day == 30
    onward = travel.travel(make_ctx(*clear_days(2), beat="beat-2"))
    assert onward["arrived"] and onward["days"] == 1 and onward["legs"][0]["miles"] == pytest.approx(25.9, abs=0.1)


def test_the_route_answers_its_slowest_stretches(weald):
    out = travel.route_preview(weald("westgate"), "eastgate")
    assert out["mode"] == "foot" and out["units"] == "km" and out["to"] == "eastgate"
    pass_ = out["slowest"][0]
    assert pass_["what"] == "mountain" and pass_["days"] == pytest.approx(pass_["km"] / (24 * MILES_TO_KM / 3), abs=0.1)
    assert out["days"] > pass_["days"]
    with pytest.raises(PlayError, match="by cart"):  # no cart crosses the mountain pass
        travel.route_preview(weald("westgate"), "eastgate", mode="cart")


# --- the setting's map: Greyhawk to Hardby -----------------------------------------------------------------------


def greyhawk_campaign(storage):
    return make_campaign(storage, worldmaps=[], setting="greyhawk")


def test_greyhawk_to_hardby_on_foot_by_the_road_is_about_four_days(storage):
    campaign = greyhawk_campaign(storage)
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng(clear_days(4)), catalogs=over(PlayReference()))
    for name in ("Garrek", "Pippa"):
        characters.create(ctx, name=name, sheet={"hp_max": 8})
    world_maps.place_party(ctx, "greyhawk")
    region = world_maps.geo(ctx, "greyhawk-region")
    hardby = region.feature("hardby").geometry["coordinates"]
    assert region.terrain_of(cell_at(region.grid, *hardby)) == "lake", "Hardby's point lies inside the Wooly Bay"
    out = travel.travel(ctx, "hardby")
    assert out["arrived"] and out["days"] == 4 and out["via_roads"]
    assert 70 <= out["miles"] <= 90 and [leg["miles"] for leg in out["legs"]][:3] == [24.0] * 3
    assert world_maps.position(ctx).at == "hardby" and world_maps.position(ctx).km


def test_a_party_placed_by_plateau_6_travels_from_the_right_place_and_is_stored_in_km(storage):
    campaign = greyhawk_campaign(storage)
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng(clear_days(4)), catalogs=over(PlayReference()))
    world_maps.maps(ctx)
    state = storage.campaign_states.get(campaign.id)
    storage.campaign_states.put(replace(state, world=WorldPosition("greyhawk-region", 500.0, 500.0, None)))
    for name in ("Garrek", "Pippa"):
        characters.create(ctx, name=name, sheet={"hp_max": 8})
    out = travel.travel(ctx, "hardby")
    assert out["arrived"] and out["days"] == 4
    here = world_maps.position(ctx)
    hardby = world_maps.geo(ctx, "greyhawk-region").feature("hardby").geometry["coordinates"]
    assert here.km and (here.x, here.y) == pytest.approx(tuple(hardby))


# --- the tools -------------------------------------------------------------------------------------------------------


@pytest.fixture
def call(storage, campaign, party):
    host = ToolHost(storage, lambda: SeededRng(3), catalogs=over(PlayReference()))
    return lambda tool, /, beat="beat-1", **args: host.call(campaign.id, beat, tool, args)


def test_the_tools(call):
    assert call("place_party", at="oakton")["position"]["at"] == "oakton"
    assert call("distance", a="oakton", b="millbrook")["miles"] == 120
    by_road = call("distance", a="oakton", b="millbrook", mode="foot")
    assert by_road["mode"] == "foot" and by_road["miles"] == pytest.approx(120, abs=0.5)
    near = call("nearest", kind="town", n=2)
    assert [p["name"] for p in near["places"]] == ["harbour", "millbrook"]  # not Oakton, where the party is
    other = call("nearest", kind="other", n=5)
    assert {p["name"]: p["hidden"] for p in other["places"]} == {"old-tower": True, "east-glade": True}
    assert "error" in call("nearest", kind="poi")
    assert call("route", to="millbrook")["days"] == 5
    journey = call("travel", to="millbrook")
    assert "error" not in journey and journey["legs"]
    shown = call("world_map")
    assert shown["name"] == "vale" and "old-tower" in {f["id"] for f in shown["features"]}
    tower = call("world_map", feature="old-tower")["feature"]
    assert tower["dm_notes"].startswith(SECRET) and (tower["hidden"], tower["known"]) == (True, False)
    assert "doc" not in tower and not tower["description"]
    assert call("reveal_place", feature="old-tower")["revealed"] == "old-tower"
    assert "error" in call("travel", to="nowhere-at-all")


def test_the_tools_visibility(call, storage):
    host = ToolHost(storage, lambda: SeededRng(3), catalogs=over(PlayReference()))
    for name in ("world_map", "route"):
        assert not host.spec(name).player_visible
    for name in ("travel", "place_party", "distance", "nearest", "reveal_place"):
        assert host.spec(name).player_visible
    names = ("travel", "route", "place_party", "reveal_place")
    assert {n for n in names if host.spec(n).mutates} == {"travel", "place_party", "reveal_place"}
    assert "clocks" in host.spec("travel").dm_only_keys
    assert host.spec("travel").params["properties"]["mode"]["enum"] == ["foot", "horse", "cart", "river", "ship"]


def test_setting_off_overland_leaves_the_modules_maps(make_ctx, party):
    """DEL-331: after an 8-day journey to Dyvers the party stood on two module maps at once, Hamt on the tower's and
    the rest on Freddie's camp, and the map tools refused; travel leaves them all, keeping what they learned."""
    from delve.maps import state as map_state
    from delve.maps.state import CharacterView, MapState

    garrek, pippa = party
    ctx = at_oakton(make_ctx(*clear_days(5)))
    camp = MapState(
        characters={garrek.id: CharacterView("room.hut", frozenset({"room.hut"})), pippa.id: CharacterView("room.hut")}
    )
    ctx.storage.map_states.put(ctx.campaign_id, "crypt", map_state.to_json(camp))
    out = travel.travel(ctx, "millbrook")
    assert out["left_maps"] == ["crypt"]
    left = map_state.from_json(ctx.storage.map_states.get(ctx.campaign_id, "crypt"))
    assert {cid: view.location for cid, view in left.characters.items()} == {garrek.id: None, pippa.id: None}
    assert left.characters[garrek.id].nodes == frozenset({"room.hut"}), "what they know of the map stays"
