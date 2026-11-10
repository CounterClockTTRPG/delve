"""The routes of a map picture: thin lines of a colour that is neither blue, nor ink, nor near any terrain colour,
nor a blend of two of them (the soft edge between two colours in a JPEG), running at least `MIN_CELLS` cells. A line
whose drawn pixels leave gaps along it is dashed, a `trail`; else it is a `road`."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

import numpy as np
import shapely
from PIL import Image, ImageDraw

from delve.maps.geo import reading
from delve.maps.geo.model import Grid
from delve.maps.geo.reading.colours import Clusters
from delve.maps.geo.reading.grid_detect import GridGuess, cell_centres, dilate, outline
from delve.maps.geo.reading.water import Water, _paths, _skeleton, blue_mask

MIN_CELLS = 3.0
COLOUR_DISTANCE = 60.0
"""A route's colour is at least this far (RGB) from every terrain colour."""
BLEND_DISTANCE = 24.0
"""A colour this close to the line between two colours is a blend of them, not a route."""
DASHED = 0.85
"""A line with less than this share of its length drawn is dashed (a grid line crossing a road leaves a gap too)."""
_INK = (30.0, 30.0, 30.0)
_BAND = 256


@dataclass(frozen=True)
class RouteTrace:
    points_px: list[tuple[float, float]]
    kind: Literal["road", "trail"]


def find_routes(image: Image.Image, grid_px: GridGuess, clusters: Clusters, water: Water) -> list[RouteTrace]:
    small, factor = reading.analysis_copy(image)
    grid = grid_px.scaled(1 / factor).pixel_grid()
    size = grid.size_km
    ink = reading.grey(small) < reading.DARK
    blue = blue_mask(small)
    away = ~dilate(ink | blue, 1) & _land(grid, ink.shape, set(water.sea) | set(water.lake))
    colours = [tuple(float(c) for c in p) for p in clusters.palette]
    blends = list(itertools.combinations([*colours, _INK, *_blue_colours(small, blue)], 2))
    pixels = np.asarray(small)
    drawn = np.zeros(ink.shape, dtype=bool)
    for y0 in range(0, pixels.shape[0], _BAND):
        band = pixels[y0 : y0 + _BAND].astype(np.float32)
        ys, xs = np.nonzero(away[y0 : y0 + _BAND])
        if not len(xs):
            continue
        values = band[ys, xs]
        keep = np.ones(len(xs), dtype=bool)
        for c in colours:
            keep &= np.linalg.norm(values - np.array(c, dtype=np.float32), axis=1) > COLOUR_DISTANCE
        for a, b in blends:
            if not keep.any():
                break
            keep &= _from_segment(values, a, b) > BLEND_DISTANCE
        drawn[ys[keep] + y0, xs[keep]] = True
    gap = max(2, round(0.1 * size))
    joined = dilate(drawn, gap)  # its skeleton is the line, bridged where a grid line or a dash broke it
    near_drawn = dilate(drawn, 1)
    traces = []
    for path, _ in _paths(_skeleton(joined), max(6, round(MIN_CELLS * size))):
        shown = float(np.mean([near_drawn[y, x] for x, y in path]))
        line = shapely.LineString([(x + 0.5, y + 0.5) for x, y in path]).simplify(1.5)
        points = [(float(x) * factor, float(y) * factor) for x, y in line.coords]
        traces.append(RouteTrace(points, "road" if shown >= DASHED else "trail"))
    return traces


def _land(grid: Grid, shape: tuple[int, ...], wet: set[int]) -> np.ndarray:
    """The pixels of the grid's cells that aren't water."""
    canvas = Image.new("1", (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(canvas)
    corners = outline(grid)
    for i, (cx, cy) in enumerate(cell_centres(grid)):
        if i in wet:
            continue
        draw.polygon([(cx + dx, cy + dy) for dx, dy in corners], fill=1)
    return np.asarray(canvas, dtype=bool)


def _blue_colours(small: Image.Image, blue: np.ndarray) -> list[tuple[float, float, float]]:
    """The picture's typical blue, whose blends with the land are a river's soft edge."""
    if not blue.any():
        return []
    values = np.asarray(small)[blue]
    step = max(1, len(values) // 100_000)
    return [tuple(float(v) for v in np.median(values[::step], axis=0))]  # type: ignore[misc]


def _from_segment(values: np.ndarray, a: tuple[float, ...], b: tuple[float, ...]) -> np.ndarray:
    """Each colour's distance from the segment between colours `a` and `b`."""
    pa = np.array(a, dtype=np.float32)
    ab = np.array(b, dtype=np.float32) - pa
    length = float(ab @ ab)
    if length == 0:
        return np.linalg.norm(values - pa, axis=1)
    t = np.clip((values - pa) @ ab / length, 0.0, 1.0)
    return np.linalg.norm(values - (pa + t[:, None] * ab), axis=1)
