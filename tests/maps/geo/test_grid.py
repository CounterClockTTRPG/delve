"""The terrain grid: squares and hexes of both orientations agree on cells, centres, outlines and neighbours."""

import math

import pytest

from delve.maps.geo.grid import (
    DEFAULT_CELLS,
    cell_at,
    cell_centre,
    cell_polygon,
    cells_in_polygon,
    cells_within,
    default_grid,
    neighbours,
)
from delve.maps.geo.model import Frame, Grid

GRIDS = [
    Grid("square", 10.0, 7, 5),
    Grid("hex", 10.0, 7, 5, orientation="pointy"),
    Grid("hex", 10.0, 7, 5, orientation="flat"),
    Grid("hex", 4.0, 6, 6, origin=(3.0, -2.0), orientation="flat"),
]


@pytest.mark.parametrize("grid", GRIDS, ids=lambda g: f"{g.kind}-{g.orientation}-{g.origin}")
def test_a_cells_centre_lies_in_that_cell_and_inside_its_outline(grid):
    for i in range(grid.cols * grid.rows):
        x, y = cell_centre(grid, i)
        assert cell_at(grid, x, y) == i
        ring = cell_polygon(grid, i)
        assert len(ring) == (5 if grid.kind == "square" else 7)
        assert ring[0] == ring[-1]
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        assert min(xs) < x < max(xs) and min(ys) < y < max(ys)


@pytest.mark.parametrize("grid", GRIDS[1:], ids=lambda g: f"hex-{g.orientation}-{g.origin}")
def test_hex_neighbours_are_six_at_one_cell_apart_and_mutual(grid):
    middle = 2 * grid.cols + 2
    assert len(neighbours(grid, middle)) == 6
    for i in range(grid.cols * grid.rows):
        for n in neighbours(grid, i):
            assert i in neighbours(grid, n)
            assert math.dist(cell_centre(grid, i), cell_centre(grid, n)) == pytest.approx(grid.size_km)


def test_square_neighbours_are_the_eight_around():
    grid = GRIDS[0]
    assert sorted(neighbours(grid, 8)) == [0, 1, 2, 7, 9, 14, 15, 16]
    assert sorted(neighbours(grid, 0)) == [1, 7, 8]
    for i in range(grid.cols * grid.rows):
        for n in neighbours(grid, i):
            assert i in neighbours(grid, n)


def test_pointy_hexes_offset_odd_rows_and_flat_hexes_odd_columns():
    pointy, flat = GRIDS[1], GRIDS[2]
    assert cell_centre(pointy, 7)[0] - cell_centre(pointy, 0)[0] == pytest.approx(5.0)  # row 1 shifted half a hex
    assert cell_centre(pointy, 1)[0] - cell_centre(pointy, 0)[0] == pytest.approx(10.0)  # size_km apart in a row
    assert cell_centre(flat, 1)[1] - cell_centre(flat, 0)[1] == pytest.approx(5.0)  # column 1 shifted half a hex
    assert cell_centre(flat, 7)[1] - cell_centre(flat, 0)[1] == pytest.approx(10.0)


def test_a_point_off_the_grid_is_in_no_cell():
    for grid in GRIDS:
        assert cell_at(grid, -50.0, -50.0) is None
        assert cell_at(grid, 500.0, 10.0) is None


def test_cells_within_a_radius_and_in_a_polygon():
    grid = GRIDS[0]
    assert sorted(cells_within(grid, (15.0, 15.0), 0.1)) == [8]
    assert sorted(cells_within(grid, (15.0, 15.0), 10.0)) == [1, 7, 8, 9, 15]
    assert sorted(cells_in_polygon(grid, [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (0.0, 0.0)])) == [
        0, 1, 7, 8,
    ]  # fmt: skip
    assert cells_in_polygon(grid, [(0.0, 0.0), (4.0, 0.0), (0.0, 4.0)]) == []  # no centre inside


def test_the_default_grid_has_200_squares_along_the_longer_side():
    grid = default_grid(Frame(400.0, 100.0))
    assert DEFAULT_CELLS == 200
    assert (grid.kind, grid.size_km, grid.cols, grid.rows) == ("square", 2.0, 200, 50)
    tall = default_grid(Frame(30.0, 90.0))
    assert (tall.cols, tall.rows) == (67, 200)
