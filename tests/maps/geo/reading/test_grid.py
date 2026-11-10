"""Finding the grid of a map picture: its kind, size, origin, extent and orientation."""

import math

import pytest
from PIL import Image

from delve.maps.geo import reading
from delve.maps.geo.reading.grid_detect import find_grid
from tests.maps.geo.pictures import hex_map, square_map

PICTURES = {
    "hex-pointy": lambda: hex_map(),
    "hex-flat": lambda: hex_map(orientation="flat"),
    "hex-pointy-small": lambda: hex_map(size_px=24, cols=20, rows=16),
    "square": lambda: square_map(),
}


def _close_to(guess, truth):
    grid = truth.grid
    assert guess is not None
    assert guess.kind == grid.kind
    assert abs(guess.size_px - grid.size_km) <= 0.02 * grid.size_km
    assert math.dist(guess.origin_px, grid.origin) <= grid.size_km / 2
    if grid.kind == "hex":
        assert guess.orientation == grid.orientation


@pytest.mark.parametrize("name", PICTURES)
def test_the_grid_is_found_within_2_percent_and_half_a_cell(name):
    synthetic = PICTURES[name]()
    guess = find_grid(synthetic.image, synthetic.truth.grid.kind)
    _close_to(guess, synthetic.truth)
    assert (guess.cols, guess.rows) == (synthetic.truth.grid.cols, synthetic.truth.grid.rows)
    assert guess.confidence > 0.5


def test_the_frame_is_not_part_of_the_grid():
    synthetic = hex_map()
    guess = find_grid(synthetic.image, "hex")
    grid = guess.pixel_grid()
    assert grid.origin[0] > 0 and grid.origin[1] > 0
    assert grid.cells == synthetic.truth.grid.cells


def test_a_picture_with_no_grid_gives_none():
    assert find_grid(hex_map(lines=False).image, "hex") is None
    assert find_grid(Image.new("RGB", (400, 300), (200, 220, 140)), "square") is None


def test_a_big_picture_is_read_through_a_smaller_copy(monkeypatch):
    synthetic = hex_map()
    w, h = synthetic.image.size
    big = synthetic.image.resize((w * 2, h * 2), Image.Resampling.NEAREST)
    monkeypatch.setattr(reading, "ANALYSIS_MAX_PIXELS", w * h)
    guess = find_grid(big, "hex")
    assert guess is not None
    assert abs(guess.size_px - 80) <= 1.6
    assert math.dist(guess.origin_px, (2 * synthetic.truth.margin_px,) * 2) <= 40
