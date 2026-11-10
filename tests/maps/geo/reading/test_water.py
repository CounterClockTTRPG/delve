"""Water: the sea and the lakes from the blue cells, and the rivers from the thin blue lines, with their mouths."""

import math

import pytest
from PIL import ImageDraw

from delve.maps.geo.reading.grid_detect import find_grid
from delve.maps.geo.reading.water import find_water
from tests.maps.geo.pictures import hex_map, square_map


def _read(synthetic):
    return find_water(synthetic.image, find_grid(synthetic.image, synthetic.truth.grid.kind))


def _mouth(trace):
    return trace.points_px[-1] if trace.mouth == "end" else trace.points_px[0]


def _source(trace):
    return trace.points_px[0] if trace.mouth == "end" else trace.points_px[-1]


@pytest.mark.parametrize(
    "make", [hex_map, square_map, lambda: hex_map(orientation="flat")], ids=["hex", "square", "flat"]
)
def test_the_sea_the_lake_and_the_river_flowing_into_the_sea(make):
    synthetic = make()
    truth = synthetic.truth
    water = _read(synthetic)
    assert water.sea == list(truth.sea)
    assert water.lake == list(truth.lakes[0])
    assert not any(body.guessed for body in water.bodies)
    assert len(water.rivers) == 1
    river = water.rivers[0]
    size = truth.grid.size_km
    assert math.dist(_mouth(river), truth.river[-1]) <= size
    assert math.dist(_source(river), truth.river[0]) <= size
    assert not river.flow_guessed


def test_the_frame_keeps_the_pictures_edge_dry_and_the_sea_is_still_sea():
    synthetic = hex_map()
    w, h = synthetic.image.size
    edge = [synthetic.image.getpixel((x, y)) for x in range(w) for y in (0, h - 1)]
    assert set(edge) == {(242, 232, 204)}
    water = _read(synthetic)
    assert {body.kind for body in water.bodies} == {"sea", "lake"}
    assert [body.kind for body in water.bodies if set(body.cells) == set(synthetic.truth.lakes[0])] == ["lake"]


def test_water_off_the_grids_bounds_makes_the_largest_body_a_guessed_sea():
    synthetic = hex_map(sea=False, lakes=2)
    water = _read(synthetic)
    large, small = synthetic.truth.lakes
    assert water.sea == list(large)
    assert water.lake == list(small)
    sea = next(body for body in water.bodies if body.kind == "sea")
    assert sea.guessed


def test_a_river_between_two_lakes_flows_into_the_larger_and_says_it_guessed():
    synthetic = hex_map(sea=False, lakes=2)
    water = _read(synthetic)
    assert len(water.rivers) == 1
    river = water.rivers[0]
    assert math.dist(_mouth(river), synthetic.truth.river[-1]) <= synthetic.truth.grid.size_km
    assert river.flow_guessed
    assert river.ends == ("lake", "sea")  # the larger of two lakes is read as a guessed sea


def test_a_pale_blue_of_saturation_0_22_is_water():
    pale = (180, 214, 230)  # saturation 50 / 230 = 0.217, hue 199°: as the owner's map's shallow sea, (178, 216, 233)
    synthetic = hex_map(water=pale)
    water = _read(synthetic)
    assert water.sea == list(synthetic.truth.sea)
    assert water.lake == list(synthetic.truth.lakes[0])
    assert len(water.rivers) == 1


def test_a_blue_fringe_along_the_coast_is_no_river():
    synthetic = square_map()
    grid = synthetic.truth.grid
    coast = grid.origin[0] + 2 * grid.size_km + 3
    image = synthetic.image.copy()
    ImageDraw.Draw(image).line(
        [(coast, grid.origin[1] + 4), (coast, grid.origin[1] + 4 * grid.size_km)], fill=(47, 111, 192), width=3
    )
    water = find_water(image, find_grid(image, "square"))
    assert len(water.rivers) == 1
