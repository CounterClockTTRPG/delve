"""Reading a map picture into a geo map: its grid and scale, the terrain colours, the water, the places and the
routes. Everything here is deterministic and runs on Pillow and numpy alone.

A picture bigger than `ANALYSIS_MAX_PIXELS` is read through a downscaled copy for the grid, the colours and the water;
their pixel results are scaled back to the picture's own pixels."""

from __future__ import annotations

import math
import weakref

import numpy as np
from PIL import Image

ANALYSIS_MAX_PIXELS = 40_000_000

DARK = 80
"""A pixel darker than this (0–255 grey) is ink: a grid line, a label, a symbol."""

_last: tuple[weakref.ref[Image.Image], tuple[int, int], int, Image.Image, float] | None = None


def analysis_copy(image: Image.Image) -> tuple[Image.Image, float]:
    """The RGB picture to analyse and its factor (picture px per analysis px, 1.0 when the picture is small enough).
    The last copy is kept, as the steps of one reading ask for the same picture in turn."""
    global _last
    budget = ANALYSIS_MAX_PIXELS
    if _last is not None:
        ref, size, kept_budget, copy, factor = _last
        if ref() is image and size == image.size and kept_budget == budget:
            return copy, factor
    w, h = image.size
    factor = 1.0
    copy = image if image.mode == "RGB" else image.convert("RGB")
    if w * h > budget:
        factor = math.sqrt(w * h / budget)
        copy = copy.resize((max(1, round(w / factor)), max(1, round(h / factor))), Image.Resampling.BOX)
        factor = w / copy.size[0]
    _last = (weakref.ref(image), image.size, budget, copy, factor)
    return copy, factor


def grey(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"))
