"""What the party knows of a world map, and the seat's and the DM's view of it. The seat sees less when in doubt: a
hidden place, `dm_notes`, a place in an unknown area and the part of a line in unknown land never reach it."""

import json

import pytest

from delve.domain.world import Journey, WorldKnowledge
from delve.maps.geo.grid import cell_at
from delve.maps.geo.knowledge import (
    SIGHT_FACTOR,
    SIGHT_KM,
    KnowledgeError,
    dm_view,
    forget_area,
    forget_feature,
    known_cells,
    reveal_along,
    reveal_area,
    reveal_feature,
    seat_view,
    start,
    visible_features,
)
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid

GRID = Grid("square", 10.0, 10, 10)
"""100 × 100 km in cells of 10 km; cell 11 is the one around (15, 15)."""

SECRET = "SECRET-XYZZY"


def _place(id_: str, name: str, x: float, y: float, **kw) -> GeoFeature:
    return GeoFeature(id_, "places", kw.pop("kind", "town"), name, {"type": "Point", "coordinates": [x, y]}, **kw)


def _line(id_: str, layer: str, kind: str, name: str, *points: tuple[float, float], **kw) -> GeoFeature:
    return GeoFeature(id_, layer, kind, name, {"type": "LineString", "coordinates": [list(p) for p in points]}, **kw)


def _box(x0: float, y0: float, x1: float, y1: float) -> list[list[list[float]]]:
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]


GREYHAWK = _place("greyhawk", "Greyhawk", 15.0, 15.0, kind="city", description="The Free City.")
HARDBY = _place("hardby", "Hardby", 85.0, 15.0, kind="port")
MILL = _place("mill", "Mill", 15.0, 25.0, kind="village", dm_notes=f"The miller is a spy: {SECRET}-notes")
LAIR = _place("lair", f"{SECRET}-lair", 25.0, 15.0, kind="dungeon", hidden=True, tags=("hidden", "evil"))
FAR = _place("far", f"{SECRET}-far", 85.0, 85.0, kind="ruin")
HILLTOP = _place("hilltop", "Hilltop", 55.0, 55.0, kind="castle")
ROAD = _line("road", "routes", "road", "The Hardby road", (15.0, 15.0), (85.0, 15.0))
RIVER = _line("selintan", "water", "river", "Selintan", (5.0, 5.0), (5.0, 95.0), props={"navigable_km": 50})
REGION = GeoFeature("nyrond", "regions", "kingdom", "Nyrond", {"type": "Polygon", "coordinates": _box(0, 0, 30, 30)})

TERRAIN = "p" * 55 + "h" + "p" * 44
"""Plains, with a hill at cell 55, around (55, 55)."""

GEO = GeoMap(
    Frame(100.0, 100.0, "miles"), GRID, TERRAIN, (GREYHAWK, HARDBY, MILL, LAIR, FAR, HILLTOP, ROAD, RIVER, REGION)
)

CORNER = (0, 1, 2, 10, 11, 12, 20, 21, 22)
"""The cells of the 30 × 30 km in the top left: Greyhawk, the mill and the lair's."""


def _ids(features) -> list[str]:
    return [f.id for f in features]


def _seat(known: WorldKnowledge, **kw) -> dict:
    args = {"name": "region", "title": "The region", "party": None, "journey": None, "picture": None}
    return seat_view(GEO, known, **{**args, **kw}, tiles_version="v1")


def _coords(view: dict, id_: str) -> list:
    return next(f for f in view["features"] if f["id"] == id_)["geometry"]["coordinates"]


# --- what is known ---------------------------------------------------------------------------------------------------


def test_known_cells_are_every_cell_when_everything_is_known():
    assert known_cells(GEO, WorldKnowledge(everything=True)) == frozenset(range(100))
    assert known_cells(GEO, WorldKnowledge(cells=(11, 12, 400))) == frozenset({11, 12})


def test_everything_shows_all_but_the_hidden_and_the_forgotten():
    shown = _ids(visible_features(GEO, WorldKnowledge(everything=True, forgotten=("far",))))
    assert shown == ["greyhawk", "hardby", "mill", "hilltop", "road", "selintan", "nyrond"]


def test_forgotten_hides_a_place_in_a_known_area():
    known = WorldKnowledge(cells=CORNER, forgotten=("mill",))
    assert _ids(visible_features(GEO, known)) == ["greyhawk", "road", "selintan", "nyrond"]


def test_a_hidden_place_shows_only_when_the_party_knows_it():
    assert "lair" not in _ids(visible_features(GEO, WorldKnowledge(cells=CORNER)))
    assert "lair" in _ids(visible_features(GEO, reveal_feature(WorldKnowledge(), "lair")))


def test_a_known_feature_shows_whole_outside_the_known_area():
    known = WorldKnowledge(features=("road",))
    assert _ids(visible_features(GEO, known)) == ["road"]
    assert visible_features(GEO, known)[0].geometry == ROAD.geometry


def test_forget_feature_undoes_reveal_feature_and_the_other_way_round():
    known = forget_feature(reveal_feature(WorldKnowledge(cells=CORNER), "greyhawk"), "greyhawk")
    assert known.features == () and known.forgotten == ("greyhawk",)
    assert "greyhawk" not in _ids(visible_features(GEO, known))
    known = reveal_feature(known, "greyhawk")
    assert known.features == ("greyhawk",) and known.forgotten == ()


def test_a_road_from_a_known_cell_into_unknown_ones_is_cut_at_the_edge():
    (road,) = [f for f in visible_features(GEO, WorldKnowledge(cells=CORNER)) if f.id == "road"]
    assert road.geometry == {"type": "LineString", "coordinates": [[15.0, 15.0], [30.0, 15.0]]}


def test_an_area_is_clipped_and_a_line_left_with_nothing_is_dropped():
    known = WorldKnowledge(cells=(11,))
    shown = {f.id: f for f in visible_features(GEO, known)}
    assert set(shown) == {"greyhawk", "road", "nyrond"}
    assert shown["nyrond"].geometry["type"] == "Polygon"
    xs = [x for x, _ in shown["nyrond"].geometry["coordinates"][0]]
    assert min(xs) == 10.0 and max(xs) == 20.0


# --- the seat's view -------------------------------------------------------------------------------------------------


def test_no_secret_reaches_the_seat():
    view = _seat(WorldKnowledge(cells=CORNER), picture={"id": f"{SECRET}-picture", "km_per_px": 0.1, "max_zoom": 2})
    text = json.dumps(view)
    assert SECRET not in text
    assert "dm_notes" not in text and "hidden" not in text and "props" not in text and "navigable_km" not in text
    assert view["picture"] == {"km_per_px": 0.1, "max_zoom": 2}


def test_no_secret_reaches_the_seat_when_everything_is_known_either():
    text = json.dumps(_seat(WorldKnowledge(everything=True, forgotten=("far",))))
    assert SECRET not in text


def test_the_seat_view_holds_the_known_cells_terrain_and_features():
    view = _seat(WorldKnowledge(cells=CORNER), party=(15.0, 15.0))
    assert view["name"] == "region" and view["title"] == "The region" and view["units"] == "miles"
    assert view["frame"] == {"width_km": 100.0, "height_km": 100.0}
    assert view["grid"]["kind"] == "square" and view["grid"]["cols"] == 10
    assert view["tiles_version"] == "v1"
    assert view["known"] == {"all": False, "cells": [[0, 3], [10, 13], [20, 23]]}
    assert view["terrain"] == "ppp.......ppp.......ppp......." + "." * 70
    assert view["party"] == [15.0, 15.0]
    assert view["journey"] is None
    greyhawk = next(f for f in view["features"] if f["id"] == "greyhawk")
    assert greyhawk == {
        "id": "greyhawk",
        "layer": "places",
        "kind": "city",
        "name": "Greyhawk",
        "description": "The Free City.",
        "geometry": {"type": "Point", "coordinates": [15.0, 15.0]},
        "tags": [],
    }


def test_the_seat_never_gets_the_hidden_tag():
    view = _seat(reveal_feature(WorldKnowledge(), "lair"))
    (lair,) = view["features"]
    assert lair["tags"] == ["evil"]


def test_everything_known_is_one_run():
    assert _seat(WorldKnowledge(everything=True))["known"] == {"all": True, "cells": [[0, 100]]}


def test_a_journey_line_is_clipped_and_the_destination_hidden_while_unknown():
    journey = Journey("region", "foot", "hardby", "Hardby", ((15.0, 15.0), (50.0, 15.0), (85.0, 15.0)), 70.0, 5.0)
    view = _seat(WorldKnowledge(cells=CORNER), journey=journey)
    assert view["journey"] == {
        "mode": "foot",
        "to_label": None,
        "points": [[15.0, 15.0], [30.0, 15.0]],
        "done_km": 5.0,
        "km": 70.0,
    }
    view = _seat(WorldKnowledge(cells=CORNER, features=("hardby",)), journey=journey)
    assert view["journey"]["to_label"] == "Hardby"


def test_a_journey_line_is_cut_at_its_first_way_into_unknown_land():
    journey = Journey("region", "foot", "x", None, ((15.0, 15.0), (15.0, 65.0), (15.0, 95.0)), 80.0)
    known = WorldKnowledge(cells=(*CORNER, 81, 91))  # known again at the far end
    assert _seat(known, journey=journey)["journey"]["points"] == [[15.0, 15.0], [15.0, 30.0]]


def test_a_journey_from_unknown_land_shows_no_line():
    journey = Journey("region", "foot", "greyhawk", "Greyhawk", ((85.0, 85.0), (15.0, 15.0)), 99.0)
    view = _seat(WorldKnowledge(cells=CORNER), journey=journey)
    assert view["journey"]["points"] == []
    assert view["journey"]["to_label"] == "Greyhawk"


# --- the DM's view ---------------------------------------------------------------------------------------------------


def test_the_dm_view_holds_everything_and_says_what_is_known():
    journey = Journey("region", "foot", "hardby", "Hardby", ((15.0, 15.0), (85.0, 15.0)), 70.0)
    view = dm_view(
        GEO,
        WorldKnowledge(cells=CORNER),
        name="region",
        title="The region",
        party=(15.0, 15.0),
        journey=journey,
        picture={"id": "abc", "km_per_px": 0.1},
    )
    assert view["picture"] == {"id": "abc", "km_per_px": 0.1}
    assert view["terrain"] == TERRAIN
    assert view["known"] == {"all": False, "cells": [[0, 3], [10, 13], [20, 23]]}
    features = {f["id"]: f for f in view["features"]}
    assert set(features) == {f.id for f in GEO.features}
    assert features["mill"]["dm_notes"].startswith("The miller is a spy")
    assert features["lair"]["hidden"] is True and features["lair"]["known"] is False
    assert features["greyhawk"]["known"] is True and features["far"]["known"] is False
    assert features["road"]["geometry"] == ROAD.geometry  # whole, never clipped
    assert features["selintan"]["props"] == {"navigable_km": 50}
    assert view["journey"]["points"] == [[15.0, 15.0], [85.0, 15.0]]
    assert view["journey"]["to"] == "hardby"
    assert view["party"] == [15.0, 15.0]


# --- the start -------------------------------------------------------------------------------------------------------


def test_start_from_everything_or_nothing():
    assert start(GEO, "everything") == WorldKnowledge(everything=True)
    assert start(GEO, "nothing") == WorldKnowledge()


def test_start_from_a_region_knows_its_cells_and_the_part_of_its_road_inside():
    known = start(GEO, "regions", regions=["NYROND"])
    assert known.cells == CORNER
    (road,) = [f for f in visible_features(GEO, known) if f.id == "road"]
    assert road.geometry["coordinates"] == [[15.0, 15.0], [30.0, 15.0]]


def test_start_from_a_drawn_area():
    known = start(GEO, "area", ring=[(40.0, 40.0), (70.0, 40.0), (70.0, 70.0), (40.0, 70.0)])
    assert known.cells == (44, 45, 46, 54, 55, 56, 64, 65, 66)
    assert _ids(visible_features(GEO, known)) == ["hilltop"]


def test_start_refuses_an_unknown_region_and_a_ring_of_two_points():
    with pytest.raises(KnowledgeError, match="Atlantis"):
        start(GEO, "regions", regions=["Atlantis"])
    with pytest.raises(KnowledgeError):
        start(GEO, "regions", regions=["greyhawk"])  # a place, not a region
    with pytest.raises(KnowledgeError):
        start(GEO, "area", ring=[(0.0, 0.0), (10.0, 10.0)])
    with pytest.raises(KnowledgeError):
        start(GEO, "somewhere")  # type: ignore[arg-type]


# --- travel reveals --------------------------------------------------------------------------------------------------


def test_the_sight_constants():
    assert SIGHT_KM == 10.0
    assert SIGHT_FACTOR == {"hills": 2.0, "mountain": 3.0}


def test_reveal_along_knows_the_cells_in_sight_and_names_the_places_it_uncovered():
    revealed = reveal_along(GEO, WorldKnowledge(), [(15.0, 15.0), (15.0, 25.0)])
    known = known_cells(GEO, revealed.knowledge)
    assert {11, 21, 1, 10, 12, 20, 22, 31} <= known
    assert 33 not in known
    assert revealed.places == ["Greyhawk", "Mill"]  # never the hidden lair, next door
    again = reveal_along(GEO, revealed.knowledge, [(15.0, 15.0), (15.0, 25.0)])
    assert again.places == [] and again.knowledge == revealed.knowledge


def test_sight_from_a_hill_cell_reaches_twice_as_far():
    on_the_plain = known_cells(GEO, reveal_along(GEO, WorldKnowledge(), [(35.0, 55.0)]).knowledge)
    on_the_hill = known_cells(GEO, reveal_along(GEO, WorldKnowledge(), [(55.0, 55.0)]).knowledge)
    assert on_the_plain == {53, 43, 52, 54, 63}  # centres within 10 km
    assert cell_at(GRID, 55.0, 75.0) in on_the_hill  # 20 km south
    assert cell_at(GRID, 55.0, 85.0) not in on_the_hill
    assert len(on_the_hill) == 13


def test_reveal_along_samples_the_line_every_half_cell():
    known = known_cells(GEO, reveal_along(GEO, WorldKnowledge(), [(5.0, 95.0), (95.0, 95.0)], sight_km=0.1).knowledge)
    assert known == frozenset(range(90, 100))


def test_reveal_along_changes_nothing_when_everything_is_known():
    known = WorldKnowledge(everything=True)
    assert reveal_along(GEO, known, [(15.0, 15.0), (85.0, 85.0)]) == (known, [])


# --- areas -----------------------------------------------------------------------------------------------------------


def test_reveal_area_knows_the_cells_around_a_point():
    known = reveal_area(GEO, WorldKnowledge(), (85.0, 85.0), 10.0)
    assert known_cells(GEO, known) == {88, 78, 87, 89, 98}
    assert reveal_area(GEO, WorldKnowledge(), (85.0, 85.0), 1.0).cells == (88,)


def test_forget_area_takes_the_cells_out():
    known = forget_area(GEO, WorldKnowledge(cells=CORNER), (25.0, 25.0), 1.0)
    assert known.cells == (0, 1, 2, 10, 11, 12, 20, 21)


def test_forget_area_on_everything_hides_the_areas_place_and_cuts_the_road_through_it():
    known = forget_area(GEO, WorldKnowledge(everything=True), (55.0, 15.0), 5.0)
    assert known.everything is False
    assert set(known_cells(GEO, known)) == set(range(100)) - {15}
    hidden = forget_area(GEO, WorldKnowledge(everything=True), (55.0, 55.0), 5.0)
    assert "hilltop" not in _ids(visible_features(GEO, hidden))
    (road,) = [f for f in visible_features(GEO, known) if f.id == "road"]
    assert road.geometry == {
        "type": "MultiLineString",
        "coordinates": [[[15.0, 15.0], [50.0, 15.0]], [[60.0, 15.0], [85.0, 15.0]]],
    }


def test_forget_area_lets_go_of_a_known_feature_in_it():
    known = forget_area(GEO, WorldKnowledge(cells=CORNER, features=("road", "lair")), (25.0, 15.0), 1.0)
    assert known.features == ()
    shown = {f.id: f for f in visible_features(GEO, known)}
    assert "lair" not in shown  # a hidden place goes whole
    assert shown["road"].geometry["coordinates"] == [[15.0, 15.0], [20.0, 15.0]]


def test_a_road_across_known_hexes_stays_whole():
    grid = Grid("hex", 10.0, 30, 20, orientation="flat")
    road = _line("road", "routes", "road", "Road", (3.0, 51.0), (240.0, 57.0))
    geo = GeoMap(Frame(270.0, 210.0), grid, "p" * grid.cells, (road,))
    (seen,) = visible_features(geo, WorldKnowledge(cells=tuple(range(grid.cells // 2))))
    assert seen.geometry["type"] == "LineString"  # no slivers between the hexes to cut it
