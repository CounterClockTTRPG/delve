"""The places on a map picture: town symbols, their labels, and the labels that name a river or a region.

The picture is read at full resolution, in `TILE` px tiles overlapping by `OVERLAP` px, so no array is ever the whole
of a large picture. In each tile:
- the OCR reads the words, and the words on a line join into labels; labels of digits only (the frame's cell numbers)
  are dropped;
- symbols are small compact blobs of ink, solid or ringed (the owner's map draws towns as rings with a dot or a
  star), once the known grid's lines are masked out, outside the words' boxes.

A label is paired with its nearest symbol within `PAIR_HEIGHTS` label heights. A label along a river line is offered as
the river's name, and a label spanning several cells (or letter-spaced) as a region's: neither is paired. A label OCR
isn't sure of, or a symbol without a label, goes to Claude on a numbered crop (`look`, `prompts/labels.md`). A place's
kind is `town` unless its symbol isn't the usual one, which makes a `kind-guessed` doubt."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any

import numpy as np
import shapely
from PIL import Image, ImageDraw

from delve.maps.geo import reading
from delve.maps.geo.grid import cell_at, neighbours
from delve.maps.geo.model import Point
from delve.maps.geo.reading.grid_detect import GridGuess, cell_centres, dilate, erode, outline
from delve.maps.geo.reading.ocr import TILE_OFFSET, OcrWord, PictureOcr
from delve.maps.geo.reading.review import DROP, KEEP, LABEL_CHOICES, Doubt, river_id
from delve.maps.geo.reading.water import Water
from delve.maps.geo.terrain import PLACE_KINDS
from delve.maps.vision import Look, fit_for_vision

TILE = 2048
OVERLAP = 128
PAIR_HEIGHTS = 3.0
"""A label pairs with a symbol at most this many label heights from its box."""
SURE = 60.0
"""An OCR label under this confidence is checked by Claude; one Claude reads nothing on is no label."""
NOISE = 30.0
"""An OCR word under this confidence is noise (hatching, a coast, a tree read as letters)."""
SYMBOL_INK = 140
"""Symbols are looked for in the ink (`reading.DARK`) and again in the darker greys, where a ring drawn as two thin
circles (the owner's map) joins into one."""
SYMBOL_SIDE = (0.1, 0.4)
"""A symbol's size, as shares of a cell (and at least `SYMBOL_MIN_PX`)."""
SYMBOL_MIN_PX = 5
SYMBOL_ASPECT = 1.4
SOLID = 0.6
"""A blob filling this share of its box is a solid symbol; a ring needs a hole of `RING_HOLE` of it."""
RING_HOLE = 0.15
SQUARE = 0.9
LINE_SHARE = 0.04
"""The grid's lines are masked this share of a cell wide (and at least 3 px)."""
CROPS_PER_SHEET = 20
_CROP = (240, 160)


@dataclass(frozen=True)
class ReadPlace:
    id: str
    name: str
    kind: str
    point_px: Point
    symbol: str | None
    """The symbol's shape (`round`, `square`, `ring`), or None for a place read from a label alone."""
    label_box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class PlacesReading:
    places: list[ReadPlace]
    doubts: list[Doubt]
    """Their positions (`data`'s `at`, `place_at` and `box`) are in the picture's pixels; ids are given later."""


@dataclass
class _Label:
    text: str
    box: tuple[int, int, int, int]
    confidence: float
    height: float
    spaced: bool = False
    along: str | None = None
    """The river it runs along."""
    region: bool = False
    symbol: int | None = None
    looked: str | None = None
    """What Claude read on its crop."""

    @property
    def centre(self) -> Point:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)


@dataclass
class _Symbol:
    box: tuple[int, int, int, int]
    shape: str
    label: int | None = None
    looked: str | None = None

    @property
    def centre(self) -> Point:
        return ((self.box[0] + self.box[2]) / 2, (self.box[1] + self.box[3]) / 2)

    @property
    def side(self) -> int:
        return max(self.box[2] - self.box[0], self.box[3] - self.box[1])


def prompt(name: str) -> str:
    """The prompt file `name` of `prompts/`, as packaged."""
    return resources.files("delve.maps.geo.reading").joinpath("prompts", name).read_text("utf-8")


def answer_json(text: str, opener: str) -> Any:
    """The JSON value starting at the first `opener` (`[` or `{`) of Claude's answer, or None."""
    closer = "]" if opener == "[" else "}"
    start, end = text.find(opener), text.rfind(closer)
    if start < 0 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except ValueError:
        return None


async def read_places(
    image: Image.Image, grid_px: GridGuess, *, ocr: PictureOcr | None, look: Look, water: Water | None = None
) -> PlacesReading:
    words, symbols, smalls = await asyncio.to_thread(_scan, image, grid_px, ocr)
    if ocr is None:
        symbols = [s for s in symbols if not _in_a_row(s, smalls)]
    labels = _labels([w for w in words if not _digits(w.text)])
    rivers = [shapely.LineString(r.points_px) for r in (water.rivers if water else []) if len(r.points_px) >= 2]
    _classify(labels, symbols, rivers, grid_px.size_px)
    _pair(labels, symbols)
    await _look(image, labels, symbols, look)
    return _result(labels, symbols, grid_px, water)


# --- scanning the tiles


def _tiles(width: int, height: int) -> list[tuple[int, int, int, int]]:
    step = TILE - OVERLAP
    xs = range(0, max(1, width - OVERLAP), step)
    ys = range(0, max(1, height - OVERLAP), step)
    return [(x, y, min(width, x + TILE), min(height, y + TILE)) for y in ys for x in xs]


def _scan(
    image: Image.Image, grid_px: GridGuess, ocr: PictureOcr | None
) -> tuple[list[OcrWord], list[_Symbol], list[tuple[int, int, int, int]]]:
    width, height = image.size
    grid = grid_px.pixel_grid()
    centres = cell_centres(grid)
    corners = outline(grid)
    line = max(3, round(grid_px.size_px * LINE_SHARE))
    words: list[OcrWord] = []
    found: list[tuple[tuple[int, int, int, int], str]] = []
    smalls: list[tuple[int, int, int, int]] = []
    for box in _tiles(width, height):
        x0, y0, x1, y1 = box
        grey = np.asarray(image.crop(box).convert("L"))
        lines = _grid_lines(box, centres, corners, grid_px.size_px, line)
        for threshold in (reading.DARK, SYMBOL_INK):
            ink = grey < threshold
            # The grid's lines are taken out where the ink is thin, so a symbol drawn over one stays whole.
            ink &= ~(lines & ~dilate(erode(ink, 1), 1))
            if threshold == reading.DARK and ocr is not None:
                # The OCR reads the ink alone, black on white: the terrain colours and the grid only confuse it.
                clean = Image.fromarray(np.where(ink, 0, 255).astype(np.uint8))
                clean.info[TILE_OFFSET] = (x0, y0)
                for w in ocr(clean):
                    bx0, by0, bx1, by1 = w.box
                    words.append(OcrWord(w.text, (bx0 + x0, by0 + y0, bx1 + x0, by1 + y0), w.confidence))
            for bx0, by0, bx1, by1, count in _components(ink):
                # A blob cut by the tile's edge is read whole in the next tile, which overlaps this one.
                if (
                    (bx0 == 0 < x0)
                    or (by0 == 0 < y0)
                    or (bx1 == x1 - x0 < width - x0)
                    or (by1 == y1 - y0 < height - y0)
                ):
                    continue
                blob = (bx0 + x0, by0 + y0, bx1 + x0, by1 + y0)
                side = max(bx1 - bx0, by1 - by0)
                if threshold == reading.DARK and 3 <= side <= SYMBOL_SIDE[1] * grid_px.size_px:
                    smalls.append(blob)
                shape = _shape(ink[by0:by1, bx0:bx1], count, grid_px.size_px)
                if shape is not None:
                    found.append((blob, shape))
    words = _distinct_words([w for w in words if _wordlike(w)])
    # A word hides the blobs inside it (its letters), unless it is a single letter: OCR reads a symbol as one.
    boxes = [_grow(w.box, 2) for w in words if len(re.sub(r"[\W_]", "", w.text)) >= 2]
    symbols: list[_Symbol] = []
    # The larger first, so a ring's dot (or a symbol read at both thresholds) is one symbol.
    for blob, shape in sorted(set(found), key=lambda f: (-(f[0][2] - f[0][0]) * (f[0][3] - f[0][1]), f)):
        cx, cy = (blob[0] + blob[2]) / 2, (blob[1] + blob[3]) / 2
        if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes):
            continue
        if any(s.box[0] <= cx <= s.box[2] and s.box[1] <= cy <= s.box[3] for s in symbols):
            continue
        symbols.append(_Symbol(blob, shape))
    symbols.sort(key=lambda s: (s.box[1], s.box[0]))
    return words, symbols, sorted(set(smalls))


def _grid_lines(
    box: tuple[int, int, int, int], centres: np.ndarray, corners: np.ndarray, size: float, width: int
) -> np.ndarray:
    x0, y0, x1, y1 = box
    canvas = Image.new("1", (x1 - x0, y1 - y0), 0)
    draw = ImageDraw.Draw(canvas)
    near = (
        (centres[:, 0] > x0 - size)
        & (centres[:, 0] < x1 + size)
        & (centres[:, 1] > y0 - size)
        & (centres[:, 1] < y1 + size)
    )
    for cx, cy in centres[near]:
        ring = [(cx + dx - x0, cy + dy - y0) for dx, dy in corners]
        draw.line([*ring, ring[0]], fill=1, width=width)
    return np.asarray(canvas, dtype=bool)


def _components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """The 8-connected blobs of `mask`, as `(x0, y0, x1, y1, pixels)`, found from the runs of each row."""
    h, w = mask.shape
    if not mask.any():
        return []
    edges = np.diff(np.pad(mask.astype(np.int8), ((0, 0), (1, 1))), axis=1)
    ry, rx0 = np.nonzero(edges == 1)
    _, rx1 = np.nonzero(edges == -1)
    n = len(rx0)
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    starts = np.searchsorted(ry, np.arange(h + 1)).tolist()
    xs0, xs1 = rx0.tolist(), rx1.tolist()
    for y in range(1, h):
        i, i_end, j, j_end = starts[y - 1], starts[y], starts[y], starts[y + 1]
        while i < i_end and j < j_end:
            if xs0[i] <= xs1[j] and xs0[j] <= xs1[i]:  # touching, diagonals included
                a, b = root(i), root(j)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            if xs1[i] < xs1[j]:
                i += 1
            else:
                j += 1
    roots = np.array([root(i) for i in range(n)])
    _, group = np.unique(roots, return_inverse=True)
    g = int(group.max()) + 1
    bx0 = np.full(g, w)
    np.minimum.at(bx0, group, rx0)
    bx1 = np.zeros(g, dtype=np.int64)
    np.maximum.at(bx1, group, rx1)
    by0 = np.full(g, h)
    np.minimum.at(by0, group, ry)
    by1 = np.zeros(g, dtype=np.int64)
    np.maximum.at(by1, group, ry + 1)
    count = np.bincount(group, weights=rx1 - rx0, minlength=g).astype(np.int64)
    return [(int(bx0[k]), int(by0[k]), int(bx1[k]), int(by1[k]), int(count[k])) for k in range(g)]


def _shape(blob: np.ndarray, count: int, cell: float) -> str | None:
    """`round`, `square` or `ring` for a blob that looks like a symbol (`blob` is its box's ink), else None."""
    h, w = blob.shape
    side = max(w, h)
    if not max(SYMBOL_MIN_PX, SYMBOL_SIDE[0] * cell) <= side <= SYMBOL_SIDE[1] * cell:
        return None
    if side > SYMBOL_ASPECT * min(w, h):
        return None
    fill = count / (w * h)
    if fill >= SQUARE:
        return "square"
    if fill >= SOLID:
        return "round"
    background = np.pad(~blob, 1, constant_values=True)
    outside = 0
    for x0, y0, x1, y1, n in _components(background):
        if x0 == 0 or y0 == 0 or x1 == w + 2 or y1 == h + 2:
            outside += n
    hole = int(background.sum()) - outside
    return "ring" if hole >= RING_HOLE * w * h else None


def _in_a_row(symbol: _Symbol, smalls: Sequence[tuple[int, int, int, int]]) -> bool:
    """Whether the blob has a neighbour of its height on its line: a letter of a label, when there is no OCR to say
    where the labels are."""
    x0, y0, x1, y1 = symbol.box
    h = y1 - y0
    cy = (y0 + y1) / 2
    for b in smalls:
        if b == symbol.box:
            continue
        bh = b[3] - b[1]
        if not 0.6 * h <= bh <= 1.6 * h or abs((b[1] + b[3]) / 2 - cy) > 0.5 * h:
            continue
        gap = max(b[0] - x1, x0 - b[2])
        if gap < h:
            return True
    return False


def _grow(box: tuple[int, int, int, int], by: float) -> tuple[int, int, int, int]:
    return (round(box[0] - by), round(box[1] - by), round(box[2] + by), round(box[3] + by))


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def _distinct_words(words: list[OcrWord]) -> list[OcrWord]:
    """The words, once each: a word in two tiles' overlap is read twice."""
    out: list[OcrWord] = []
    for w in sorted(words, key=lambda w: (-w.confidence, w.box)):
        if not any(o.text.casefold() == w.text.casefold() and _iou(o.box, w.box) > 0.5 for o in out):
            out.append(w)
    return sorted(out, key=lambda w: (w.box[1], w.box[0]))


# --- labels


def _wordlike(word: OcrWord) -> bool:
    """Whether an OCR word may be part of a label: sure enough, mostly letters, and two of them unless OCR is sure
    of a single letter (a letter-spaced label's)."""
    letters = sum(ch.isalpha() for ch in word.text)
    if word.confidence < NOISE or letters < 0.6 * len(word.text):
        return _number(word.text)  # the frame's numbers hide no symbol; they are dropped later, never reported
    return letters >= 2 or word.confidence >= SURE


def _number(text: str) -> bool:
    """Two digits or more, as the frame's cell numbers: a lone "6" or "0" is more likely a symbol OCR misread."""
    stripped = re.sub(r"[\W_]", "", text)
    return len(stripped) >= 2 and stripped.isdigit()


def _digits(text: str) -> bool:
    stripped = re.sub(r"[\W_]", "", text)
    return not stripped or stripped.isdigit()


def _labels(words: list[OcrWord]) -> list[_Label]:
    """The words joined into labels, line by line: a word joins the label it continues on its line."""
    groups: list[list[OcrWord]] = []
    for w in sorted(words, key=lambda w: (w.box[0], w.box[1])):
        h = w.box[3] - w.box[1]
        best = None
        for g in groups:
            last = g[-1]
            lh = last.box[3] - last.box[1]
            overlap = min(last.box[3], w.box[3]) - max(last.box[1], w.box[1])
            if overlap < 0.5 * min(h, lh):
                continue
            single = len(w.text) == 1 and len(last.text) == 1
            gap = w.box[0] - last.box[2]
            if -0.2 * max(h, lh) <= gap <= (1.5 if single else 1.0) * max(h, lh):
                best = g
                break
        if best is None:
            groups.append([w])
        else:
            best.append(w)
    labels = []
    for g in groups:
        box = (
            min(w.box[0] for w in g),
            min(w.box[1] for w in g),
            max(w.box[2] for w in g),
            max(w.box[3] for w in g),
        )
        heights = sorted(w.box[3] - w.box[1] for w in g)
        spaced = len(g) >= 3 and sum(len(w.text) == 1 for w in g) >= 0.6 * len(g)
        text = _spaced_text(g) if spaced else " ".join(w.text for w in g)
        labels.append(_Label(text, box, min(w.confidence for w in g), float(heights[len(heights) // 2]), spaced))
    return sorted(labels, key=lambda lb: (lb.box[1], lb.box[0]))


def _spaced_text(words: list[OcrWord]) -> str:
    """A letter-spaced label's text: the letters joined, with a space where the gap is wider than usual."""
    gaps = [b.box[0] - a.box[2] for a, b in itertools.pairwise(words)]
    usual = sorted(gaps)[len(gaps) // 2] if gaps else 0
    text = words[0].text
    for gap, w in zip(gaps, words[1:], strict=True):
        text += (" " if gap > 1.8 * max(usual, 1) else "") + w.text
    return text


def _classify(labels: list[_Label], symbols: list[_Symbol], rivers: list[shapely.LineString], cell: float) -> None:
    """Marks the labels along a river and the labels of a region; a label with a symbol right beside it is neither."""
    for label in labels:
        box = shapely.box(*label.box)
        if any(box.distance(shapely.box(*s.box)) <= label.height for s in symbols):
            continue
        x0, y0, x1, y1 = label.box
        if x1 - x0 > label.height and rivers:
            strips = [shapely.box(x0 + (x1 - x0) * k / 8, y0, x0 + (x1 - x0) * (k + 1) / 8, y1) for k in range(8)]
            best = None
            for n, river in enumerate(rivers):
                near = sum(strip.distance(river) <= label.height for strip in strips)
                if near >= 4 and (best is None or near > best[0]):
                    best = (near, n)
            if best is not None:
                label.along = river_id(best[1])
                continue
        label.region = label.spaced or (x1 - x0) > 2 * cell


def _pair(labels: list[_Label], symbols: list[_Symbol]) -> None:
    """Each place label with its nearest free symbol, the nearest pairs first."""
    pairs = []
    for n, label in enumerate(labels):
        if label.along or label.region:
            continue
        box = shapely.box(*label.box)
        for k, symbol in enumerate(symbols):
            d = box.distance(shapely.box(*symbol.box))
            if d <= PAIR_HEIGHTS * label.height:
                pairs.append((d, n, k))
    for _, n, k in sorted(pairs):
        if labels[n].symbol is None and symbols[k].label is None:
            labels[n].symbol, symbols[k].label = k, n


# --- Claude on the crops


async def _look(image: Image.Image, labels: list[_Label], symbols: list[_Symbol], look: Look) -> None:
    items: list[tuple[str, tuple[int, int, int, int], _Label | _Symbol]] = []
    for label in labels:
        if label.confidence < SURE:
            items.append(("label", _grow(label.box, label.height), label))
    for symbol in symbols:
        if symbol.label is None:
            r = 3 * symbol.side  # wide enough for its label on either side
            cx, cy = symbol.centre
            items.append(("symbol", (round(cx - 2 * r), round(cy - r), round(cx + 2 * r), round(cy + r)), symbol))
    for start in range(0, len(items), CROPS_PER_SHEET):
        batch = items[start : start + CROPS_PER_SHEET]
        sheet = _sheet(image, [box for _, box, _ in batch])
        lines = []
        for n, (what, box, _) in enumerate(batch, start=1):
            x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
            if what == "label":
                lines.append(f"- {n}: a label at ({x}, {y}): read it")
            else:
                lines.append(f"- {n}: a place's symbol at ({x}, {y}): read the label beside it")
        text = prompt("labels.md").replace("{items}", "\n".join(lines))
        png, media_type = fit_for_vision(sheet)
        try:
            answer = answer_json(await look(text, png, media_type), "[")
        except Exception:  # noqa: BLE001 - a failed look leaves the reading to the review
            answer = None
        read: dict[int, str] = {}
        for entry in answer if isinstance(answer, list) else []:
            if isinstance(entry, dict) and isinstance(entry.get("n"), int) and isinstance(entry.get("label"), str):
                read[entry["n"]] = entry["label"].strip()
        for n, (_, _, item) in enumerate(batch, start=1):
            item.looked = read.get(n, "")


def _sheet(image: Image.Image, boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    """The crops on one sheet, four to a row, each under its number."""
    cw, ch = _CROP
    columns = min(4, len(boxes))
    rows = math.ceil(len(boxes) / columns)
    sheet = Image.new("RGB", (columns * (cw + 8), rows * (ch + 24)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for n, box in enumerate(boxes):
        crop = image.crop(box).convert("RGB")
        crop.thumbnail((cw, ch), Image.Resampling.LANCZOS)
        x, y = (n % columns) * (cw + 8), (n // columns) * (ch + 24)
        draw.text((x + 4, y + 4), str(n + 1), fill=(200, 0, 0))
        sheet.paste(crop, (x + 4, y + 20))
    return sheet


# --- the result


def _result(labels: list[_Label], symbols: list[_Symbol], grid_px: GridGuess, water: Water | None) -> PlacesReading:
    doubts: list[Doubt] = []
    unpaired = [n for n, lb in enumerate(labels) if lb.symbol is None]
    # A symbol Claude read the label of takes the unpaired label it names, if there is one near.
    for symbol in symbols:
        if symbol.label is None and symbol.looked:
            for n in unpaired:
                label = labels[n]
                near = math.dist(label.centre, symbol.centre) <= 2 * PAIR_HEIGHTS * label.height
                if near and label.text.casefold() == symbol.looked.casefold() and label.symbol is None:
                    label.symbol, symbol.label = symbols.index(symbol), n
                    break
    shapes = [s.shape for s in symbols]
    usual = max(sorted(set(shapes)), key=shapes.count) if shapes else None
    sizes = sorted(s.side for s in symbols if s.shape == usual)
    usual_side = sizes[len(sizes) // 2] if sizes else 0
    places: list[ReadPlace] = []
    claimed: set[int] = set()
    n_label = 0
    for label in labels:
        if label.symbol is not None:
            continue
        if label.looked is not None:
            if not label.looked:
                continue  # OCR wasn't sure, and Claude reads no label there: noise, not a label
            label.text = label.looked
        n_label += 1
        free = [
            (math.dist(label.centre, s.centre), k)
            for k, s in enumerate(symbols)
            if s.label is None and not s.looked and k not in claimed
        ]
        near = [f for f in free if f[0] <= 2 * PAIR_HEIGHTS * label.height]
        place_at = label.centre
        if near and not label.along and not label.region:
            k = min(near)[1]
            claimed.add(k)
            place_at = symbols[k].centre
        likely = "river-name" if label.along else "region-name" if label.region else "place"
        river = label.along or _nearest_river(label.centre, water)
        offered = [c for c in LABEL_CHOICES if c != "river-name" or river is not None]
        alternatives = [likely, *(c for c in offered if c != likely)]
        feature = f"label-{n_label}"
        doubts.append(
            Doubt(
                "",
                "label-unpaired",
                river if likely == "river-name" and river else feature,
                f"The label “{label.text}” has no place symbol beside it.",
                label.text,
                alternatives,
                data={
                    "at": list(label.centre),
                    "text": label.text,
                    "box": list(label.box),
                    "place_at": list(place_at),
                    "feature": feature,
                    "river": river,
                    "river_was": "",
                },
            )
        )
    ordered = sorted(
        (k for k, s in enumerate(symbols) if k not in claimed),
        key=lambda k: (symbols[k].centre[1], symbols[k].centre[0]),
    )
    for k in ordered:
        symbol = symbols[k]
        pid = f"place-{len(places) + 1}"
        label = labels[symbol.label] if symbol.label is not None else None
        name = label.text if label is not None else (symbol.looked or "")
        at = list(symbol.centre)
        if label is not None and label.confidence < SURE:
            looked = label.looked or ""
            if looked and looked.casefold() != label.text.casefold():
                name = looked
                doubts.append(
                    Doubt(
                        "",
                        "label-uncertain",
                        pid,
                        f"The label “{looked}” may be misread.",
                        looked,
                        [KEEP, label.text, DROP],
                        data={"at": at, "ocr": label.text},
                    )
                )
            elif not looked:
                doubts.append(
                    Doubt(
                        "",
                        "label-uncertain",
                        pid,
                        f"The label “{label.text}” may be misread.",
                        label.text,
                        [KEEP, DROP],
                        data={"at": at, "ocr": label.text},
                    )
                )
        if not name:
            doubts.append(
                Doubt("", "symbol-unlabelled", pid, "A place's symbol has no label.", "", [KEEP, DROP], data={"at": at})
            )
        kind = "town"
        if symbol.shape != usual:
            kind = _kind_of(symbol, usual_side, grid_px, water)
            doubts.append(
                Doubt(
                    "",
                    "kind-guessed",
                    pid,
                    f"This symbol isn't the usual town's: it may be a {kind}.",
                    kind,
                    [kind, *(k for k in PLACE_KINDS if k != kind)],
                    data={"at": at},
                )
            )
        places.append(ReadPlace(pid, name, kind, symbol.centre, symbol.shape, label.box if label else None))
    return PlacesReading(places, doubts)


def _nearest_river(point: Point, water: Water | None) -> str | None:
    """The id of the river nearest `point`, if the reading found any."""
    if water is None:
        return None
    best = None
    for n, river in enumerate(water.rivers):
        if len(river.points_px) < 2:
            continue
        d = shapely.LineString(river.points_px).distance(shapely.Point(point))
        if best is None or d < best[0]:
            best = (d, n)
    return river_id(best[1]) if best else None


def _kind_of(symbol: _Symbol, usual_side: float, grid_px: GridGuess, water: Water | None) -> str:
    """The likely kind of a place whose symbol isn't the usual one: a port by the water, a city when its symbol is
    larger, a village when smaller, else something else."""
    if water is not None and _by_water(symbol.centre, grid_px, water):
        return "port"
    if usual_side and symbol.side > 1.4 * usual_side:
        return "city"
    if usual_side and symbol.side < 0.7 * usual_side:
        return "village"
    return "other"


def _by_water(point: Point, grid_px: GridGuess, water: Water) -> bool:
    grid = grid_px.pixel_grid()
    wet = set(water.sea) | set(water.lake)
    cell = cell_at(grid, *point)
    if cell is not None and (cell in wet or any(n in wet for n in neighbours(grid, cell))):
        return True
    here = shapely.Point(point)
    return any(
        len(r.points_px) >= 2 and shapely.LineString(r.points_px).distance(here) <= grid_px.size_px / 2
        for r in water.rivers
    )
