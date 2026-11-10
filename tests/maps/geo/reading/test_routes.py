"""Routes: thin lines of a colour that is no terrain's, nor blue, nor ink."""

import math

from PIL import ImageDraw

from delve.maps.geo.reading.colours import cluster_cells
from delve.maps.geo.reading.grid_detect import find_grid
from delve.maps.geo.reading.routes import find_routes
from delve.maps.geo.reading.water import find_water
from tests.maps.geo.pictures import ROAD, hex_map, square_map


def _routes(synthetic):
    grid = find_grid(synthetic.image, synthetic.truth.grid.kind)
    return find_routes(synthetic.image, grid, cluster_cells(synthetic.image, grid), find_water(synthetic.image, grid))


def test_the_road_is_a_route_between_its_two_towns():
    for synthetic in (hex_map(), square_map(), hex_map(orientation="flat")):
        truth = synthetic.truth
        routes = _routes(synthetic)
        assert len(routes) == 1
        road = routes[0]
        assert road.kind == "road"
        a, b = (truth.place(name).point for name in truth.road_between)
        ends = {road.points_px[0], road.points_px[-1]}
        size = truth.grid.size_km
        assert any(math.dist(e, a) <= size / 2 for e in ends)
        assert any(math.dist(e, b) <= size / 2 for e in ends)


def test_a_dashed_line_is_a_trail():
    synthetic = hex_map()
    draw = ImageDraw.Draw(synthetic.image)
    y = synthetic.truth.place("Corvel").point[1] + 25
    for x in range(260, 470, 12):
        draw.line([(x, y), (x + 6, y)], fill=ROAD, width=2)
    routes = sorted(_routes(synthetic), key=lambda r: r.kind)
    assert [r.kind for r in routes] == ["road", "trail"]


def test_the_river_and_the_grid_are_no_routes():
    synthetic = hex_map()
    ImageDraw.Draw(synthetic.image).line(synthetic.truth.road, fill=(60, 140, 60), width=2)  # in a terrain colour
    assert _routes(synthetic) == []
