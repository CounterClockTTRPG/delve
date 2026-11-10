"""The water of a map picture: the sea and the lakes from the cells that are mostly blue, and the rivers from the
thin blue lines, each followed to its mouth to find which way it flows.

A water body touching the grid's bounds (the detected grid's extent, never the picture's edge, which a margin frame
keeps dry) is sea; when none does, the largest is taken for the sea, and says it is a guess. A river's mouth is the
end that reaches water: the one at the sea when both do, else the one at the larger body, as a guess."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np
import shapely
from PIL import Image, ImageDraw

from delve.maps.geo import reading
from delve.maps.geo.grid import cell_at, neighbours
from delve.maps.geo.model import Grid, Point
from delve.maps.geo.reading.colours import sample_cells
from delve.maps.geo.reading.grid_detect import GridGuess, cell_centres, dilate, erode, outline

BLUE_HUE = (180.0, 250.0)
"""Degrees."""
BLUE_MIN_SATURATION = 0.20
"""The plan said 0.25; the owner's map's shallow sea, (178, 216, 233), has 0.236."""
BLUE_MIN_VALUE = 0.25
WATER_SHARE = 0.5
"""A cell at least this share blue (of what isn't ink) is water."""
RIVER_MAX_WIDTH = 0.2
"""Blue narrower than this share of a cell (each way) is a line, not a body: a river."""
RIVER_MIN_LENGTH = 0.75
"""A river runs at least this many cells; shorter blue lines are noise (a body's ragged edge)."""
SHORE_SHARE = 0.8
"""A blue line running this much of its length beside water is a shore's fringe, not a river."""


@dataclass(frozen=True)
class WaterBody:
    cells: list[int]
    kind: Literal["sea", "lake"]
    guessed: bool = False
    """Classed by its size, as no body touches the grid's bounds."""


@dataclass(frozen=True)
class RiverTrace:
    points_px: list[Point]
    mouth: Literal["start", "end"] | None
    """The end where it flows out; None when neither end reaches water."""
    flow_guessed: bool = False
    """Both ends reach water and neither is a sure sea: the mouth is the end at the larger body."""
    ends: tuple[str, str] | None = None
    """When the flow is guessed, what it flows from and into, as read: `sea` or `lake`, or `river` for a branch's end
    at a river, so the review can say which way it reads (DEL-94)."""


@dataclass(frozen=True)
class Water:
    bodies: list[WaterBody]
    rivers: list[RiverTrace]

    @property
    def sea(self) -> list[int]:
        return sorted(i for body in self.bodies if body.kind == "sea" for i in body.cells)

    @property
    def lake(self) -> list[int]:
        return sorted(i for body in self.bodies if body.kind == "lake" for i in body.cells)


def blue_mask(image: Image.Image) -> np.ndarray:
    """The picture's blue pixels (`BLUE_HUE`, `BLUE_MIN_SATURATION`, `BLUE_MIN_VALUE`)."""
    hsv = np.asarray(image.convert("HSV"))
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lo, hi = (math.ceil(d * 255 / 360) for d in BLUE_HUE)
    return (h >= lo) & (h <= hi) & (s >= math.ceil(BLUE_MIN_SATURATION * 255)) & (v >= math.ceil(BLUE_MIN_VALUE * 255))


def find_water(image: Image.Image, grid_px: GridGuess) -> Water:
    small, factor = reading.analysis_copy(image)
    grid = grid_px.scaled(1 / factor).pixel_grid()
    blue = blue_mask(small)
    ink = reading.grey(small) < reading.DARK
    blue_s, inside = sample_cells(blue, grid)
    ink_s, _ = sample_cells(ink, grid)
    wet = (blue_s & inside).sum(axis=1)
    dry = (inside & ~blue_s & ~ink_s).sum(axis=1)
    water = (wet > 0) & (wet >= WATER_SHARE * (wet + dry))
    bodies = _bodies(grid, [i for i in range(grid.cells) if water[i]])
    rivers = _rivers(blue, _cells_mask(grid, water, blue.shape), grid, bodies, factor)
    return Water(bodies, rivers)


def _cells_mask(grid: Grid, cells: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    """The pixels of the cells flagged in `cells`."""
    canvas = Image.new("1", (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(canvas)
    corners = outline(grid)
    centres = cell_centres(grid)
    for i in np.flatnonzero(cells):
        cx, cy = centres[i]
        draw.polygon([(cx + dx, cy + dy) for dx, dy in corners], fill=1)
    return np.asarray(canvas, dtype=bool)


def _bodies(grid: Grid, wet: list[int]) -> list[WaterBody]:
    left = set(wet)
    found: list[list[int]] = []
    for start in wet:
        if start not in left:
            continue
        left.discard(start)
        body, queue = [start], deque([start])
        while queue:
            for n in neighbours(grid, queue.popleft()):
                if n in left:
                    left.discard(n)
                    body.append(n)
                    queue.append(n)
        found.append(sorted(body))

    def on_bounds(i: int) -> bool:
        c, r = i % grid.cols, i // grid.cols
        return c in (0, grid.cols - 1) or r in (0, grid.rows - 1)

    touching = [any(on_bounds(i) for i in body) for body in found]
    if any(touching):
        return [WaterBody(body, "sea" if t else "lake") for body, t in zip(found, touching, strict=True)]
    if not found:
        return []
    largest = max(range(len(found)), key=lambda k: (len(found[k]), -k))
    return [WaterBody(body, "sea" if k == largest else "lake", guessed=True) for k, body in enumerate(found)]


def _rivers(blue: np.ndarray, wet: np.ndarray, grid: Grid, bodies: list[WaterBody], factor: float) -> list[RiverTrace]:
    """The thin blue lines on land (`wet` is the water cells' pixels), as traces with their mouths."""
    k = max(2, round(grid.size_km * RIVER_MAX_WIDTH))
    wide = (dilate(erode(blue, k), k) & blue) | wet
    thin = blue & ~dilate(wide, 1)
    thin = erode(dilate(thin, 1), 1) & ~wide  # bridges a line drawn over the river
    h, w = wide.shape
    paths = _paths(_skeleton(thin), max(6, round(grid.size_km * RIVER_MIN_LENGTH)))
    body_of = {i: n for n, body in enumerate(bodies) for i in body.cells}
    reach = k + 3

    def water_at(x: int, y: int) -> WaterBody | None:
        """The body an end reaches: the one under the nearest wide blue within `reach`; a pool too small for a cell
        is a lake of no cells."""
        x0, y0 = max(0, x - reach), max(0, y - reach)
        ys, xs = np.nonzero(wide[y0 : min(h, y + reach + 1), x0 : min(w, x + reach + 1)])
        if not len(xs):
            return None
        xs, ys = xs + x0, ys + y0
        j = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
        cell = cell_at(grid, xs[j] + 0.5, ys[j] + 0.5)
        n = body_of.get(cell) if cell is not None else None
        return bodies[n] if n is not None else WaterBody([], "lake")

    shore = dilate(wide, k)
    traces = []
    for path, joins in paths:
        if np.mean([shore[y, x] for x, y in path]) >= SHORE_SHARE:
            continue
        start, end = water_at(*path[0]), water_at(*path[-1])
        mouth: Literal["start", "end"] | None
        guessed = False
        ends: tuple[str, str] | None = None
        if joins:
            # A branch running into a river: it flows into it, unless its other end is at a sure sea.
            mouth = "start" if start is not None and _sure_sea(start) else "end"
            guessed = mouth == "start"
            if guessed and start is not None:
                ends = ("river", start.kind)
        elif start is not None and end is not None:
            if _sure_sea(start) != _sure_sea(end):
                mouth = "start" if _sure_sea(start) else "end"
            else:
                mouth = "start" if len(start.cells) > len(end.cells) else "end"
                guessed = True
                ends = (end.kind, start.kind) if mouth == "start" else (start.kind, end.kind)
        elif start is not None or end is not None:
            mouth = "start" if start is not None else "end"
        else:
            mouth = None
        line = shapely.LineString([(x + 0.5, y + 0.5) for x, y in path]).simplify(0.75)
        points = [(float(x) * factor, float(y) * factor) for x, y in line.coords]
        traces.append(RiverTrace(points, mouth, guessed, ends))
    return traces


def _sure_sea(body: WaterBody) -> bool:
    return body.kind == "sea" and not body.guessed


def _skeleton(mask: np.ndarray) -> np.ndarray:
    """Zhang–Suen thinning, on the mask's pixels only."""
    h, w = mask.shape
    stride = w + 2
    a = np.zeros((h + 2) * stride, dtype=bool)
    a.reshape(h + 2, stride)[1:-1, 1:-1] = mask
    idx = np.flatnonzero(a)
    offsets = [-stride, -stride + 1, 1, stride + 1, stride, stride - 1, -1, -stride - 1]  # P2 … P9, clockwise from N
    changed = True
    while changed and len(idx):
        changed = False
        for step in (0, 1):
            n = np.stack([a[idx + o] for o in offsets])
            count = n.sum(axis=0)
            turns = (~n & np.roll(n, -1, axis=0)).sum(axis=0)
            p2, _, p4, _, p6, _, p8, _ = n
            if step == 0:
                keep = (p2 & p4 & p6) | (p4 & p6 & p8)
            else:
                keep = (p2 & p4 & p8) | (p2 & p6 & p8)
            remove = (count >= 2) & (count <= 6) & (turns == 1) & ~keep
            if remove.any():
                a[idx[remove]] = False
                idx = idx[~remove]
                changed = True
    return a.reshape(h + 2, stride)[1:-1, 1:-1]


def _paths(skeleton: np.ndarray, min_length: int) -> list[tuple[list[tuple[int, int]], bool]]:
    """The skeleton's lines, each as pixels and whether it joins a line found before (a branch, ending at the
    junction). Each piece of the skeleton gives its longest line first, then the branches off it."""
    ys, xs = np.nonzero(skeleton)
    pixels = set(zip(xs.tolist(), ys.tolist(), strict=True))
    steps = [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0)]

    def around(p: tuple[int, int], within: set[tuple[int, int]]) -> list[tuple[int, int]]:
        return [(p[0] + dx, p[1] + dy) for dx, dy in steps if (p[0] + dx, p[1] + dy) in within]

    def pieces(within: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
        left, out = set(within), []
        for p in sorted(within, key=lambda p: (p[1], p[0])):
            if p not in left:
                continue
            left.discard(p)
            piece, queue = {p}, deque([p])
            while queue:
                for q in around(queue.popleft(), left):
                    left.discard(q)
                    piece.add(q)
                    queue.append(q)
            out.append(piece)
        return out

    def farthest(sources: list[tuple[int, int]], within: set[tuple[int, int]]) -> list[tuple[int, int]]:
        parent: dict[tuple[int, int], tuple[int, int] | None] = dict.fromkeys(sources)
        queue, last = deque(sources), sources[0]
        while queue:
            last = queue.popleft()
            for q in around(last, within):
                if q not in parent:
                    parent[q] = last
                    queue.append(q)
        line, p = [], last
        while p is not None:
            line.append(p)
            p = parent[p]
        return line  # from the farthest pixel back to a source

    out: list[tuple[list[tuple[int, int]], bool]] = []
    for piece in pieces(pixels):
        if len(piece) < min_length:
            continue
        first = min(piece, key=lambda p: (p[1], p[0]))
        one_end = farthest([first], piece)[0]
        line = farthest([one_end], piece)[::-1]
        if len(line) < min_length:
            continue
        out.append((line, False))
        traced = set(line)
        work = [piece - traced]
        while work:
            rest = work.pop()
            for branch in pieces(rest):
                if len(branch) < min_length:
                    continue
                joins = sorted((p for p in branch if around(p, traced)), key=lambda p: (p[1], p[0]))
                if not joins:
                    continue
                line = farthest(joins[:1], branch)  # from the free end to the junction
                if len(line) >= min_length:
                    out.append((line, True))
                traced |= set(line)
                work.append(branch - set(line))
    return out
