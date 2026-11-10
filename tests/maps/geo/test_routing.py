"""Routes by mode over small hand-built maps: roads, ridges and passes, rivers both ways, fords, ships around land,
the ends' snapping and the refusals, and the speed goal on a Flanaess-sized map."""

import math
import time

import pytest

from delve.maps.geo.grid import cell_at, cell_centre
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid, water_from_areas
from delve.maps.geo.routing import GeoRoute, NoRoute, build_graph, plan, point_along, slowest, stretch_at
from delve.rules.classic.overland import mode_rules
from tests.fixtures.rulesets import osric
from tests.timing import budget

TRAVEL = osric().tables.travel
"""A ruleset's travel rates: OSRIC's, installed as a pack."""

SIZE = 10.0


def square_map(rows: list[str], *features: GeoFeature, size: float = SIZE) -> GeoMap:
    grid = Grid("square", size, len(rows[0]), len(rows))
    return GeoMap(Frame(grid.cols * size, grid.rows * size), grid, "".join(rows), tuple(features))


def line(fid: str, layer: str, kind: str, *points: tuple[float, float], **props) -> GeoFeature:
    return GeoFeature(
        fid, layer, kind, fid, {"type": "LineString", "coordinates": [list(p) for p in points]}, props=props
    )


def place(fid: str, at: tuple[float, float], kind: str = "town", tags: tuple[str, ...] = ()) -> GeoFeature:
    return GeoFeature(fid, "places", kind, fid, {"type": "Point", "coordinates": list(at)}, tags=tags)


def route(geo: GeoMap, mode: str, start, goal, **kw) -> GeoRoute:
    return plan(build_graph(geo, mode_rules(mode, TRAVEL, **kw)), start, goal)


def whats(r: GeoRoute) -> set[str]:
    return {s.what for s in r.stretches}


def cells_of(geo: GeoMap, r: GeoRoute) -> list[str]:
    return [geo.terrain[cell_at(geo.grid, *p)] for p in r.points]


def test_the_road_is_faster_than_across_the_hills():
    hills = ["h" * 10] * 5
    road = line("road", "routes", "road", (5, 25), (50, 45), (95, 25))
    by_road = route(square_map(hills, road), "foot", (5, 25), (95, 25))
    assert "road" in whats(by_road)
    assert by_road.cost_km < 120 < route(square_map(hills), "foot", (5, 25), (95, 25)).cost_km
    assert by_road.points[0] == (5, 25) and by_road.points[-1] == (95, 25)
    assert by_road.km == pytest.approx(sum(s.km for s in by_road.stretches))


def test_a_ship_sails_around_a_peninsula_not_across_it():
    sea = ["wwwwpwwww", "wwwwpwwww", "wwwwpwwww", "wwwwwwwww"]
    geo = square_map(sea)
    r = route(geo, "ship", (5, 5), (85, 5))
    assert r.km > 100
    assert whats(r) == {"sea"}
    assert set(cells_of(geo, r)) == {"w"}
    with pytest.raises(NoRoute, match="on foot"):
        route(geo, "foot", (45, 5), (5, 5))


def test_a_river_boat_is_faster_downstream_than_up():
    geo = square_map(["p" * 20] * 5, line("selintan", "water", "river", (5, 25), (100, 30), (195, 25)))
    down = route(geo, "river", (5, 25), (195, 25))
    up = route(geo, "river", (195, 25), (5, 25))
    assert whats(down) == {"downstream"} and whats(up) == {"upstream"}
    assert down.km == pytest.approx(up.km)
    assert down.cost_km == pytest.approx(down.km / 1.5) and up.cost_km == pytest.approx(up.km / 0.5)


def test_a_river_boat_crosses_a_lake_from_the_rivers_mouth():
    geo = square_map(["pppplllp", "pppplllp", "pppppppp"], line("inflow", "water", "river", (5, 5), (40, 5)))
    r = route(geo, "river", (5, 5), (65, 15))
    assert whats(r) == {"downstream", "lake"}


RIDGE = ["ppppxpppp"] * 6


def test_an_impassable_ridge_is_crossed_only_at_its_pass():
    pass_road = line("pass", "routes", "trail", (35, 55), (65, 55))
    geo = square_map(RIDGE, pass_road)
    r = route(geo, "foot", (5, 5), (85, 5))
    assert "trail" in whats(r)
    assert any(p[1] == 55 for p in r.points)
    ridge_points = [p for p in r.points if geo.terrain[cell_at(geo.grid, *p)] == "x"]
    assert all(p[1] == 55 for p in ridge_points)
    with pytest.raises(NoRoute, match="on foot"):
        route(square_map(RIDGE), "foot", (5, 5), (85, 5))


def test_a_diagonal_ridge_is_not_slipped_through_at_its_corners():
    geo = square_map(["xppp", "pxpp", "ppxp", "pppx"])
    with pytest.raises(NoRoute):
        route(geo, "foot", (35, 5), (5, 35))


def test_a_flyer_goes_straight_over_the_ridge():
    r = route(square_map(RIDGE), "horse", (5, 5), (85, 5), flies=True)
    assert r.km == pytest.approx(80)
    assert "impassable" in whats(r)


def test_a_barrier_river_is_crossed_at_the_ford_and_nowhere_else():
    river = line("rhine", "water", "river", (40, 0), (40, 60), barrier=True)
    ford = place("ford", (35, 55), kind="other", tags=("ford",))
    plains = ["p" * 9] * 6
    r = route(square_map(plains, river, ford), "foot", (5, 5), (85, 5))
    assert r.km > 120
    assert any(p == cell_centre(Grid("square", SIZE, 9, 6), 5 * 9 + 3) for p in r.points)
    with pytest.raises(NoRoute):
        route(square_map(plains, river), "foot", (5, 5), (85, 5))
    across = route(square_map(plains, line("brook", "water", "river", (40, 0), (40, 60))), "foot", (5, 5), (85, 5))
    assert across.km == pytest.approx(80)


def test_a_road_crosses_a_barrier_river_on_its_bridge():
    river = line("rhine", "water", "river", (40, 0), (40, 60), barrier=True)
    road = line("road", "routes", "road", (25, 35), (65, 35))
    r = route(square_map(["p" * 9] * 6, river, road), "foot", (5, 5), (85, 5))
    assert "road" in whats(r)


ISLAND = ["wwwwwww", "wwwwwww", "pwwwpww", "wwwwwww"]


def test_a_land_journey_to_an_island_is_refused_naming_the_mode():
    geo = square_map(ISLAND)
    with pytest.raises(NoRoute, match="on horseback") as refused:
        plan(build_graph(geo, mode_rules("horse", TRAVEL)), (5, 25), (45, 25), goal_label="Lendore")
    assert "Lendore" in refused.value.reason


def test_a_ships_leg_from_an_inland_town_is_refused_and_one_from_a_port_snaps_to_its_water():
    geo = square_map(["pppwwww", "pppwwww", "pppwwww"])
    with pytest.raises(NoRoute, match="Dyvers isn't on the sea") as refused:
        plan(build_graph(geo, mode_rules("ship", TRAVEL)), (5, 5), (65, 5), start_label="Dyvers")
    assert refused.value.reason.startswith("Dyvers")
    r = route(geo, "ship", (25, 15), (65, 5))
    assert r.points[0] == (25, 15) and r.points[-1] == (65, 5)
    assert cells_of(geo, r)[1] == "w"


def test_a_river_boats_leg_from_a_town_one_cell_from_the_river_snaps_to_it():
    geo = square_map(["p" * 20] * 5, line("selintan", "water", "river", (5, 25), (195, 25)))
    r = route(geo, "river", (50, 33), (190, 25))
    assert r.points[0] == (50, 33)
    assert math.dist(r.points[0], r.points[1]) <= SIZE
    with pytest.raises(NoRoute, match="isn't on a river or a lake"):
        route(geo, "river", (50, 5), (190, 25))


def test_a_foot_leg_to_a_port_inside_its_bays_area_snaps_to_the_shore_and_arrives():
    bay = GeoFeature(
        "wooly-bay",
        "water",
        "lake",
        "Woolly Bay",
        {"type": "Polygon", "coordinates": [[[60, 0], [100, 0], [100, 50], [60, 50], [60, 0]]]},
    )
    hardby = place("hardby", (64, 25), kind="port")
    geo = water_from_areas(square_map(["p" * 10] * 5, bay, hardby))
    assert geo.terrain[cell_at(geo.grid, 64, 25)] == "l"
    r = route(geo, "foot", (5, 25), (64, 25))
    assert r.points[-1] == (64, 25)
    assert whats(r) == {"plains"}
    assert r.km == pytest.approx(59, abs=1)


def test_outside_the_map_is_crossed_by_no_mode():
    geo = square_map(["pp.pp"] * 3)
    for mode, kw in (("foot", {}), ("horse", {"flies": True})):
        with pytest.raises(NoRoute):
            route(geo, mode, (5, 5), (45, 5), **kw)


def test_ties_go_to_the_road():
    road = line("road", "routes", "road", (5, 5), (95, 5))
    r = route(square_map(["p" * 10] * 2, road), "foot", (5, 5), (95, 5))
    assert whats(r) == {"road"}


def test_a_ship_sails_a_large_lake_and_a_navigable_river_but_not_a_pond():
    geo = square_map(
        ["lpppplll", "ppppplll"],
        line("river", "water", "river", (5, 15), (35, 15), (55, 5), navigable_km=30),
    )
    r = route(geo, "ship", (40, 12), (75, 15))
    assert {"lake"} <= whats(r)
    with pytest.raises(NoRoute):
        route(geo, "ship", (5, 5), (75, 15))


def test_walking_along_a_route():
    road = line("road", "routes", "road", (5, 5), (45, 5))
    geo = square_map(["hhhhhhhh"] * 2, road)
    r = route(geo, "foot", (5, 5), (75, 15))
    assert point_along(r, 0) == r.points[0] and point_along(r, r.km + 5) == r.points[-1]
    assert point_along(r, 20) == pytest.approx((25, 5))
    assert stretch_at(r, 10).what == "road" and stretch_at(r, r.km - 1).what == "hills"
    assert stretch_at(r, 10).start_km == 0
    assert slowest(r, n=1)[0].what == "hills"


def _flanaess_like(grid: Grid) -> GeoMap:
    """A deterministic map of mixed terrain, with long roads and rivers of 500 segments between them."""
    letters = "pppfhpmspfpdhp"
    terrain = "".join(letters[(i * 7 + (i // grid.cols) * 3) % len(letters)] for i in range(grid.cells))
    features = []
    w, h = grid.cols, grid.rows
    for k in range(25):
        pts = [cell_centre(grid, ((k * 17 + j * 3) % h) * w + (j * w) // 10 % w) for j in range(11)]
        layer, kind = ("routes", "road") if k % 2 else ("water", "river")
        features.append(line(f"l{k}", layer, kind, *pts))
    assert sum(len(f.geometry["coordinates"]) - 1 for f in features) >= 250
    features += [
        line(
            f"m{k}",
            "routes",
            "track",
            cell_centre(grid, (k * 61) % grid.cells),
            cell_centre(grid, (k * 61 + 5) % grid.cells),
        )
        for k in range(250)
    ]
    frame = Frame(*cell_centre(grid, grid.cells - 1))
    return GeoMap(frame, grid, terrain, tuple(features))


@pytest.mark.parametrize(
    "grid",
    [Grid("square", 1.0, 200, 200), Grid("hex", 30 * 1.609344, 155, 105, orientation="flat")],
    ids=["square-200x200", "hex-155x105"],
)
def test_the_speed_goal(grid):
    geo = _flanaess_like(grid)
    for mode in ("foot", "river"):
        began = time.perf_counter()
        graph = build_graph(geo, mode_rules(mode, TRAVEL))
        assert time.perf_counter() - began < budget(2.0)
    graph = build_graph(geo, mode_rules("foot", TRAVEL))
    began = time.perf_counter()
    r = plan(graph, cell_centre(grid, 0), cell_centre(grid, grid.cells - 1))
    assert time.perf_counter() - began < budget(1.0)
    assert r.km > 0
