"""The terrain colours: each cell's interior is sampled, the samples quantised together, and every cell takes the
colour cluster most of its samples have. The organiser maps each cluster to a terrain class once (Task 8's review)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from PIL import Image

from delve.maps.geo import reading
from delve.maps.geo.model import Grid
from delve.maps.geo.reading.grid_detect import GridGuess, cell_centres, outline

MAX_CLUSTERS = 16
MIXED_SHARE = 0.6
"""A cell whose largest cluster has less than this share of its samples is mixed."""
INTERIOR = 0.7
"""The middle of a cell that is sampled, which leaves out its outline and most of what is drawn on it."""
MERGE_DISTANCE = 24.0
"""Quantised colours closer than this (RGB) are one cluster: a flat colour the quantiser split, or JPEG noise."""
SAMPLES_PER_CELL = 144


@dataclass(frozen=True)
class Clusters:
    palette: list[tuple[int, int, int]]
    """Each cluster's colour; the clusters are ordered by how many cells they hold, most first."""
    cell_cluster: list[int]
    """Each cell's cluster, row-major; -1 for a cell with no pixel inside the picture."""
    mixed: list[int]
    """The cells whose colours are mixed (`MIXED_SHARE`)."""


def interior_offsets(grid: Grid, share: float = INTERIOR, most: int = SAMPLES_PER_CELL) -> np.ndarray:
    """Points in the middle `share` of a cell, relative to its centre, on a lattice of at most about `most`."""
    ring = outline(grid) * share
    polygon = shapely.Polygon(ring)
    step = max(1.0, math.sqrt(polygon.area / most))
    (x0, y0), (x1, y1) = ring.min(axis=0), ring.max(axis=0)
    xs, ys = np.meshgrid(np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step))
    xs, ys = xs.ravel(), ys.ravel()
    inside = shapely.contains_xy(polygon, xs, ys)
    return np.column_stack([xs[inside], ys[inside]])


def sample_cells(pixels: np.ndarray, grid: Grid, share: float = INTERIOR) -> tuple[np.ndarray, np.ndarray]:
    """Each cell's interior samples of `pixels` (an (h, w, …) array) as (cells, samples, …), and which samples lie
    inside the picture."""
    h, w = pixels.shape[:2]
    points = np.rint(cell_centres(grid)[:, None, :] + interior_offsets(grid, share)[None, :, :] - 0.5).astype(np.int64)
    x, y = points[..., 0], points[..., 1]
    inside = (x >= 0) & (x < w) & (y >= 0) & (y < h)
    return pixels[np.clip(y, 0, h - 1), np.clip(x, 0, w - 1)], inside


def cluster_cells(image: Image.Image, grid_px: GridGuess) -> Clusters:
    small, factor = reading.analysis_copy(image)
    grid = grid_px.scaled(1 / factor).pixel_grid()
    values, inside = sample_cells(np.asarray(small), grid)
    ink = values.astype(np.float64) @ np.array([0.299, 0.587, 0.114]) < reading.DARK
    usable = inside & ~ink
    # A cell drawn almost all in ink (a dark forest, a mountain's hatching) is read with its ink.
    dark = usable.sum(axis=1) < 0.2 * inside.sum(axis=1)
    usable[dark] = inside[dark]
    cells = grid.cells
    if not usable.any():
        return Clusters([], [-1] * cells, [])
    owner = np.broadcast_to(np.arange(cells)[:, None], usable.shape)[usable]
    samples = values[usable]
    quantised = Image.fromarray(samples.reshape(1, -1, 3)).quantize(MAX_CLUSTERS, method=Image.Quantize.MEDIANCUT)
    index = np.asarray(quantised).ravel()
    entries = np.array(quantised.getpalette()[: 3 * MAX_CLUSTERS], dtype=np.float64).reshape(-1, 3)
    groups = _merge(entries, np.bincount(index, minlength=len(entries)))
    label = groups[index]
    n_groups = int(groups.max()) + 1
    counts = np.bincount(owner * n_groups + label, minlength=cells * n_groups).reshape(cells, n_groups)
    total = counts.sum(axis=1)
    majority = counts.argmax(axis=1)
    share = np.where(total > 0, counts.max(axis=1) / np.maximum(total, 1), 1.0)
    colour = np.array(
        [samples[label == g].mean(axis=0) if (label == g).any() else np.zeros(3) for g in range(n_groups)]
    )
    held = np.bincount(majority[total > 0], minlength=n_groups)
    kept = sorted((g for g in range(n_groups) if held[g]), key=lambda g: (-held[g], tuple(np.rint(colour[g]))))
    renumber = {g: k for k, g in enumerate(kept)}
    return Clusters(
        palette=[tuple(int(c) for c in np.rint(colour[g])) for g in kept],  # type: ignore[misc]
        cell_cluster=[renumber[int(majority[i])] if total[i] else -1 for i in range(cells)],
        mixed=[i for i in range(cells) if total[i] and share[i] < MIXED_SHARE],
    )


def _merge(entries: np.ndarray, population: np.ndarray) -> np.ndarray:
    """Each palette entry's group: the entries by population, each joining the first group within
    `MERGE_DISTANCE`."""
    groups = np.full(len(entries), -1, dtype=np.int64)
    heads: list[int] = []
    for e in sorted(range(len(entries)), key=lambda e: (-population[e], e)):
        if population[e] == 0:
            groups[e] = 0
            continue
        near = [k for k, head in enumerate(heads) if np.linalg.norm(entries[e] - entries[head]) < MERGE_DISTANCE]
        if near:
            groups[e] = near[0]
        else:
            groups[e] = len(heads)
            heads.append(e)
    return groups
