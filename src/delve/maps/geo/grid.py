"""The terrain grid's geometry: which cell a point is in, a cell's centre, outline and neighbours, and the cells of an
area. Squares and hexes (pointy in odd-row offset rows, flat in odd-column offset columns); see `model.Grid`."""

from __future__ import annotations

import math
from collections.abc import Sequence

import shapely

from delve.maps.geo.model import Frame, Grid, Point

DEFAULT_CELLS = 200
"""A map without a grid of its own gets this many squares along its longer side."""

_SQRT3 = math.sqrt(3.0)


def _radius(grid: Grid) -> float:
    """A hex's centre-to-corner distance."""
    return grid.size_km / _SQRT3


def _centre(grid: Grid, col: int, row: int) -> Point:
    ox, oy = grid.origin
    s = grid.size_km
    if grid.kind == "square":
        return (ox + (col + 0.5) * s, oy + (row + 0.5) * s)
    r = _radius(grid)
    if grid.orientation == "pointy":
        return (ox + s * (col + 0.5 + 0.5 * (row & 1)), oy + r + 1.5 * r * row)
    return (ox + r + 1.5 * r * col, oy + s * (row + 0.5 + 0.5 * (col & 1)))


def _approx(grid: Grid, x: float, y: float) -> tuple[int, int]:
    """A column and a row at or next to the cell of (x, y)."""
    ox, oy = grid.origin
    s = grid.size_km
    if grid.kind == "square":
        return math.floor((x - ox) / s), math.floor((y - oy) / s)
    r = _radius(grid)
    if grid.orientation == "pointy":
        row = round((y - oy - r) / (1.5 * r))
        return round((x - ox) / s - 0.5 - 0.5 * (row & 1)), row
    col = round((x - ox - r) / (1.5 * r))
    return col, round((y - oy) / s - 0.5 - 0.5 * (col & 1))


def cell_at(grid: Grid, x: float, y: float) -> int | None:
    """The cell (x, y) lies in; None off the grid."""
    col, row = _approx(grid, x, y)
    if grid.kind == "hex":
        # A hex is the set of points nearest its centre: take the nearest of the centres around the estimate.
        best = min(
            ((c, r) for c in range(col - 1, col + 2) for r in range(row - 1, row + 2)),
            key=lambda cr: math.dist(_centre(grid, *cr), (x, y)),
        )
        col, row = best
    if not (0 <= col < grid.cols and 0 <= row < grid.rows):
        return None
    return row * grid.cols + col


def cell_centre(grid: Grid, i: int) -> Point:
    return _centre(grid, i % grid.cols, i // grid.cols)


def cell_polygon(grid: Grid, i: int) -> list[Point]:
    """The cell's outline, a closed ring."""
    cx, cy = cell_centre(grid, i)
    if grid.kind == "square":
        h = grid.size_km / 2
        ring = [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]
    else:
        r = _radius(grid)
        start = 30 if grid.orientation == "pointy" else 0
        ring = [
            (cx + r * math.cos(math.radians(start + 60 * k)), cy + r * math.sin(math.radians(start + 60 * k)))
            for k in range(6)
        ]
    return [*ring, ring[0]]


_SQUARE_STEPS = [(dc, dr) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dc, dr) != (0, 0)]
_POINTY_STEPS = (
    [(-1, 0), (1, 0), (-1, -1), (0, -1), (-1, 1), (0, 1)],  # an even row
    [(-1, 0), (1, 0), (0, -1), (1, -1), (0, 1), (1, 1)],  # an odd row, offset east
)
_FLAT_STEPS = (
    [(0, -1), (0, 1), (-1, -1), (-1, 0), (1, -1), (1, 0)],  # an even column
    [(0, -1), (0, 1), (-1, 0), (-1, 1), (1, 0), (1, 1)],  # an odd column, offset south
)


def neighbours(grid: Grid, i: int) -> list[int]:
    """The cells around `i`: six for a hex, eight for a square (the diagonals too)."""
    col, row = i % grid.cols, i // grid.cols
    if grid.kind == "square":
        steps = _SQUARE_STEPS
    elif grid.orientation == "pointy":
        steps = _POINTY_STEPS[row & 1]
    else:
        steps = _FLAT_STEPS[col & 1]
    out = []
    for dc, dr in steps:
        c, r = col + dc, row + dr
        if 0 <= c < grid.cols and 0 <= r < grid.rows:
            out.append(r * grid.cols + c)
    return out


def _cells_near(grid: Grid, x0: float, y0: float, x1: float, y1: float) -> list[int]:
    """Every cell whose centre may lie in the box: a cell's margin around it."""
    c0, r0 = _approx(grid, x0, y0)
    c1, r1 = _approx(grid, x1, y1)
    cols = range(max(0, min(c0, c1) - 1), min(grid.cols, max(c0, c1) + 2))
    rows = range(max(0, min(r0, r1) - 1), min(grid.rows, max(r0, r1) + 2))
    return [r * grid.cols + c for r in rows for c in cols]


def cells_within(grid: Grid, point: Point, radius_km: float) -> list[int]:
    """The cells whose centre is at most `radius_km` from `point`."""
    x, y = point
    near = _cells_near(grid, x - radius_km, y - radius_km, x + radius_km, y + radius_km)
    return [i for i in near if math.dist(cell_centre(grid, i), point) <= radius_km]


def _cells_in(grid: Grid, shape: shapely.Geometry) -> list[int]:
    if shape.is_empty:
        return []
    x0, y0, x1, y1 = shape.bounds
    near = _cells_near(grid, x0, y0, x1, y1)
    if not near:
        return []
    centres = [cell_centre(grid, i) for i in near]
    inside = shapely.contains_xy(shape, [c[0] for c in centres], [c[1] for c in centres])
    return [i for i, yes in zip(near, inside, strict=True) if yes]


def cells_in_polygon(grid: Grid, ring: Sequence[Sequence[float]]) -> list[int]:
    """The cells whose centre lies inside the ring."""
    if len(ring) < 3:
        return []
    return _cells_in(grid, shapely.Polygon([tuple(p[:2]) for p in ring]))


def cells_in_area(grid: Grid, rings: Sequence[Sequence[Sequence[float]]]) -> list[int]:
    """The cells whose centre lies inside a GeoJSON polygon's `coordinates`: its outer ring less its holes."""
    if not rings or len(rings[0]) < 3:
        return []
    shell = [tuple(p[:2]) for p in rings[0]]
    holes = [[tuple(p[:2]) for p in hole] for hole in rings[1:] if len(hole) >= 3]
    return _cells_in(grid, shapely.Polygon(shell, holes))


def default_grid(frame: Frame) -> Grid:
    """Squares, `DEFAULT_CELLS` along the frame's longer side."""
    size = max(frame.width_km, frame.height_km) / DEFAULT_CELLS
    cols = max(1, math.ceil(frame.width_km / size - 1e-9))
    rows = max(1, math.ceil(frame.height_km / size - 1e-9))
    return Grid("square", size, cols, rows)
