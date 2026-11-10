"""Finding a picture's grid: the kind the organiser named, its size and orientation, where it starts and how far it
runs.

The ink (`reading.DARK`) is projected on the picture's axes, and each projection's period gives the candidate cell
sizes. Each candidate is folded: the ink's pixels are summed modulo the grid's period into one tile, which shows the
cell's outline when the size is right, and its offset is found by matching the tile against the drawn outline (an FFT
cross-correlation). The sharpest fold wins. The grid's extent is then the run of cells whose outline is inked, so a
margin frame around it stays out."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw

from delve.maps.geo import reading
from delve.maps.geo.grid import cell_polygon
from delve.maps.geo.model import Grid, Point

_SQRT3 = math.sqrt(3.0)
MIN_CELL_PX = 8
LINED = 0.75
"""A cell is inside the grid when this share of the points along its outline is ink."""
MIN_CONFIDENCE = 0.5
_COARSE = np.linspace(-0.03, 0.03, 61)
_FINE = np.linspace(-0.0015, 0.0015, 31)
_COARSE_POINTS = 300_000
_FINE_POINTS = 2_000_000


@dataclass(frozen=True)
class GridGuess:
    kind: Literal["hex", "square"]
    size_px: float
    """As `model.Grid.size_km`, in the picture's pixels: a square's side, a hex across its flats."""
    origin_px: Point
    """The top left of the first cell's bounding box, as `model.Grid.origin`."""
    orientation: Literal["pointy", "flat"]
    confidence: float
    """The share of the cells' outlines found inked, 0–1."""
    cols: int
    rows: int
    even: bool = field(default=True, compare=False, repr=False)
    """Whether the first row (pointy) or column (flat) is an even one of the lattice it was found on."""

    def pixel_grid(self) -> Grid:
        """The grid in the picture's pixels: `size_km` holds `size_px`."""
        return Grid(self.kind, self.size_px, self.cols, self.rows, self.origin_px, self.orientation)

    def scaled(self, factor: float) -> GridGuess:
        """The same grid in pixels `factor` times larger."""
        x, y = self.origin_px
        return GridGuess(
            self.kind,
            self.size_px * factor,
            (x * factor, y * factor),
            self.orientation,
            self.confidence,
            self.cols,
            self.rows,
        )


def find_grid(image: Image.Image, cell: Literal["hex", "square"]) -> GridGuess | None:
    """The picture's grid of `cell`s, or None when it has none (too little ink in a regular pattern)."""
    small, factor = reading.analysis_copy(image)
    ink = reading.grey(small) < reading.DARK
    ys, xs = np.nonzero(ink)
    if len(xs) < 50:
        return None
    h, w = ink.shape
    px = _period(ink.sum(axis=0).astype(np.float64), w)
    py = _period(ink.sum(axis=1).astype(np.float64), h)
    candidates: list[tuple[Literal["pointy", "flat"], float]] = []
    if cell == "square":
        candidates += [("pointy", p) for p in (px, py) if p]
    else:
        if px:
            candidates += [("pointy", 2 * px), ("flat", 2 * px / _SQRT3)]
        if py:
            candidates += [("flat", 2 * py), ("pointy", 2 * py / _SQRT3)]
    xs_f = xs.astype(np.float64) + 0.5
    ys_f = ys.astype(np.float64) + 0.5
    coarse = _every(len(xs_f), _COARSE_POINTS)
    best: tuple[float, Literal["pointy", "flat"], float, Point] | None = None
    for orientation, size in _distinct(candidates):
        if not MIN_CELL_PX <= size <= min(w, h) / 2:
            continue
        for d in _COARSE:
            score, phase = _fold_score(cell, orientation, size * (1 + d), xs_f[coarse], ys_f[coarse])
            if best is None or score > best[0]:
                best = (score, orientation, size * (1 + d), phase)
    if best is None or best[0] <= 0:
        return None
    _, orientation, size, phase = best
    fine = _every(len(xs_f), _FINE_POINTS)
    found = max(
        ((*_fold_score(cell, orientation, size * (1 + d), xs_f[fine], ys_f[fine]), size * (1 + d)) for d in _FINE),
        key=lambda found: found[0],
    )
    _, phase, size = found
    guess = _extent(ink, cell, orientation, size, phase)
    if guess is None:
        return None
    if not guess.even:
        # A hex lattice looks the same a row (pointy) or a column (flat) on, half a cell across. The model offsets the
        # odd rows or columns, so the first one has to be an even one: take the lattice that makes it so.
        _, _, cp, rp = _periods(cell, orientation, size)
        shift = (size / 2, rp) if orientation == "pointy" else (cp, size / 2)
        guess = _extent(ink, cell, orientation, size, (phase[0] + shift[0], phase[1] + shift[1]))
    if guess is None or guess.confidence < MIN_CONFIDENCE:
        return None
    return guess.scaled(factor) if factor != 1.0 else guess


def cell_centres(grid: Grid) -> np.ndarray:
    """Every cell's centre, row-major, as an (n, 2) array: `grid.cell_centre` for all cells at once."""
    c, r = (a.ravel() for a in np.meshgrid(np.arange(grid.cols), np.arange(grid.rows)))
    ox, oy = grid.origin
    s = grid.size_km
    if grid.kind == "square":
        return np.column_stack([ox + (c + 0.5) * s, oy + (r + 0.5) * s])
    rad = s / _SQRT3
    if grid.orientation == "pointy":
        return np.column_stack([ox + s * (c + 0.5 + 0.5 * (r & 1)), oy + rad + 1.5 * rad * r])
    return np.column_stack([ox + rad + 1.5 * rad * c, oy + s * (r + 0.5 + 0.5 * (c & 1))])


def outline(grid: Grid) -> np.ndarray:
    """A cell's outline relative to its centre: its corners, as a (k, 2) array."""
    unit = Grid(grid.kind, grid.size_km, 1, 1, (0.0, 0.0), grid.orientation)
    ring = np.array(cell_polygon(unit, 0)[:-1])
    return ring - ring.mean(axis=0)


def dilate(mask: np.ndarray, k: int) -> np.ndarray:
    """`mask` grown by `k` pixels each way (a square of 2k + 1)."""
    return _sweep(mask, k, np.logical_or)


def erode(mask: np.ndarray, k: int) -> np.ndarray:
    """`mask` shrunk by `k` pixels each way; the picture's edge counts as outside."""
    return _sweep(mask, k, np.logical_and)


def _sweep(mask: np.ndarray, k: int, op: np.ufunc) -> np.ndarray:
    out = mask.copy()
    fill = op is np.logical_or
    for axis in (0, 1):
        src = out.copy()
        n = src.shape[axis]
        for d in range(1, k + 1):
            if d >= n:
                if not fill:
                    out[:] = False
                break
            lo = [slice(None)] * 2
            hi = [slice(None)] * 2
            lo[axis], hi[axis] = slice(0, n - d), slice(d, n)
            op(out[tuple(lo)], src[tuple(hi)], out=out[tuple(lo)])
            op(out[tuple(hi)], src[tuple(lo)], out=out[tuple(hi)])
            if not fill:
                edge = [slice(None)] * 2
                edge[axis] = slice(n - d, n)
                out[tuple(edge)] = False
                edge[axis] = slice(0, d)
                out[tuple(edge)] = False
    return out


def _every(n: int, most: int) -> slice:
    return slice(None, None, max(1, math.ceil(n / most)))


def _distinct(
    candidates: list[tuple[Literal["pointy", "flat"], float]],
) -> list[tuple[Literal["pointy", "flat"], float]]:
    out: list[tuple[Literal["pointy", "flat"], float]] = []
    for orientation, size in candidates:
        if not any(o == orientation and abs(s - size) <= 0.01 * size for o, s in out):
            out.append((orientation, size))
    return out


def _period(profile: np.ndarray, length: int) -> float | None:
    """The fundamental period of an ink profile, from its autocorrelation, refined on a multiple of it."""
    p = profile - profile.mean()
    n = len(p)
    spectrum = np.fft.rfft(p, 2 * n)
    ac = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    if ac[0] <= 0:
        return None
    ac = ac / ac[0]
    lo, hi = MIN_CELL_PX // 2, min(n // 2, length // 3)
    if hi <= lo + 1:
        return None
    k = np.arange(lo, hi)
    peaks = k[(ac[k] > ac[k - 1]) & (ac[k] >= ac[k + 1])]
    if len(peaks) == 0:
        return None
    top = ac[peaks].max()
    if top < 0.1:
        return None
    first = int(peaks[ac[peaks] >= 0.7 * top][0])
    period = _vertex(ac, first)
    m = min(32, int((n / 2) // period))
    if m >= 2:
        around = round(m * period)
        reach = max(1, round(period / 3))
        window = np.arange(max(1, around - reach), min(n - 1, around + reach + 1))
        if len(window):
            lag = int(window[np.argmax(ac[window])])
            period = _vertex(ac, lag) / m
    return period


def _vertex(values: np.ndarray, k: int) -> float:
    """The sub-sample position of the peak at `k` (a parabola through it and its neighbours)."""
    if not 0 < k < len(values) - 1:
        return float(k)
    a, b, c = values[k - 1], values[k], values[k + 1]
    denominator = a - 2 * b + c
    return float(k) if denominator == 0 else k + 0.5 * (a - c) / denominator


def _periods(cell: str, orientation: str, size: float) -> tuple[float, float, float, float]:
    """The lattice's repeat in x and y, and the column and row pitch. A hex lattice repeats every two rows (pointy)
    or two columns (flat), so the odd ones keep their offset."""
    if cell == "square":
        return size, size, size, size
    rad = size / _SQRT3
    if orientation == "pointy":
        return size, 3 * rad, size, 1.5 * rad
    return 3 * rad, size, 1.5 * rad, size


def _template(cell: str, orientation: str, size: float, tx: float, ty: float, nx: int, ny: int) -> np.ndarray:
    """The cell outlines of one lattice tile, drawn in `nx` x `ny` bins, with the first cell's box at (0, 0)."""
    kx, ky = nx / tx, ny / ty
    _, _, cp, rp = _periods(cell, orientation, size)
    span = Grid(
        cell,
        size,
        math.ceil(3 * tx / cp) + 2,
        math.ceil(3 * ty / rp) + 2,
        (-tx, -ty),
        orientation,  # type: ignore[arg-type]
    )
    tile = Image.new("L", (nx, ny), 0)
    draw = ImageDraw.Draw(tile)
    corners = outline(span)
    for cx, cy in cell_centres(span):
        ring = [((cx + dx) * kx, (cy + dy) * ky) for dx, dy in corners]
        draw.line([*ring, ring[0]], fill=255, width=1)
    return np.asarray(tile, dtype=np.float64) / 255.0


def _fold_score(
    cell: str, orientation: Literal["pointy", "flat"], size: float, xs: np.ndarray, ys: np.ndarray
) -> tuple[float, Point]:
    """How sharply the ink folds into this grid's outline (−1 to 1), and the grid's offset in pixels."""
    tx, ty, _, _ = _periods(cell, orientation, size)
    nx, ny = max(4, round(tx)), max(4, round(ty))
    bx = np.minimum((np.mod(xs, tx) * (nx / tx)).astype(np.int64), nx - 1)
    by = np.minimum((np.mod(ys, ty) * (ny / ty)).astype(np.int64), ny - 1)
    fold = np.bincount(by * nx + bx, minlength=nx * ny).reshape(ny, nx).astype(np.float64)
    template = _template(cell, orientation, size, tx, ty, nx, ny)
    corr = np.fft.ifft2(np.fft.fft2(fold - fold.mean()) * np.conj(np.fft.fft2(template - template.mean()))).real
    sy, sx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    on = np.roll(template, (int(sy), int(sx)), axis=(0, 1)) > 0.5
    if on.all() or not on.any():
        return 0.0, (0.0, 0.0)
    a, b = fold[on].mean(), fold[~on].mean()
    score = 0.0 if a + b == 0 else (a - b) / (a + b)
    return float(score), (sx * tx / nx, sy * ty / ny)


def _longest_run(flags: np.ndarray) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    start = None
    for i, flag in enumerate([*flags.tolist(), False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if best is None or i - start > best[1] - best[0] + 1:
                best = (start, i - 1)
            start = None
    return best


def _extent(
    ink: np.ndarray, cell: Literal["hex", "square"], orientation: Literal["pointy", "flat"], size: float, phase: Point
) -> GridGuess | None:
    """The run of cells whose outline is inked, on the lattice of `size` at `phase`."""
    h, w = ink.shape
    tx, ty, cp, rp = _periods(cell, orientation, size)
    ox = phase[0] - tx * (math.floor(phase[0] / tx) + 1)
    oy = phase[1] - ty * (math.floor(phase[1] / ty) + 1)
    cols = math.ceil((w - ox) / cp) + 1
    rows = math.ceil((h - oy) / rp) + 1
    base = Grid(cell, size, cols, rows, (ox, oy), orientation)
    centres = cell_centres(base)
    corners = outline(base)
    steps = np.array([0.2, 0.4, 0.6, 0.8])
    edges = np.concatenate(
        [corners[k] + steps[:, None] * (corners[(k + 1) % len(corners)] - corners[k]) for k in range(len(corners))]
    )
    points = np.rint(centres[:, None, :] + edges[None, :, :] - 0.5).astype(np.int64)
    inside = (points[..., 0] >= 0) & (points[..., 0] < w) & (points[..., 1] >= 0) & (points[..., 1] < h)
    valid = inside.all(axis=1)
    near = dilate(ink, 1)
    px = np.clip(points[..., 0], 0, w - 1)
    py = np.clip(points[..., 1], 0, h - 1)
    score = near[py, px].mean(axis=1)
    lined = (valid & (score >= LINED)).reshape(rows, cols)
    valid2 = valid.reshape(rows, cols)
    r_sel = slice(0, rows)
    c_run = r_run = None
    for _ in range(3):
        counts = valid2[r_sel].sum(axis=0)
        frac = np.where(counts > 0, lined[r_sel].sum(axis=0) / np.maximum(counts, 1), 0.0)
        c_run = _longest_run(frac >= 0.5)
        if c_run is None:
            return None
        c_sel = slice(c_run[0], c_run[1] + 1)
        counts = valid2[:, c_sel].sum(axis=1)
        frac = np.where(counts > 0, lined[:, c_sel].sum(axis=1) / np.maximum(counts, 1), 0.0)
        r_run = _longest_run(frac >= 0.5)
        if r_run is None:
            return None
        r_sel = slice(r_run[0], r_run[1] + 1)
    assert c_run is not None and r_run is not None
    (c0, c1), (r0, r1) = c_run, r_run
    if c1 - c0 < 1 or r1 - r0 < 1:
        return None
    grid_scores = score.reshape(rows, cols)[r0 : r1 + 1, c0 : c1 + 1][valid2[r0 : r1 + 1, c0 : c1 + 1]]
    confidence = float(grid_scores.mean()) if grid_scores.size else 0.0
    even = cell == "square" or (r0 if orientation == "pointy" else c0) % 2 == 0
    cx, cy = centres[r0 * cols + c0]
    if cell == "square":
        origin = (cx - size / 2, cy - size / 2)
    elif orientation == "pointy":
        origin = (cx - size / 2, cy - size / _SQRT3)
    else:
        origin = (cx - size / _SQRT3, cy - size / 2)
    return GridGuess(
        cell, float(size), (float(origin[0]), float(origin[1])), orientation, confidence, c1 - c0 + 1, r1 - r0 + 1, even
    )
