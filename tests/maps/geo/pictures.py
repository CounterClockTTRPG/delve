"""Synthetic map pictures for the reading tests, drawn with Pillow: a grid of flat terrain colours inside a cream
margin frame with cell numbers (as the owner's map has), a sea along the grid's left edge, a lake, a river from the
lake to the sea, three labelled towns (one on the river, halfway), a port at the river's mouth, a road between two
towns, the river's name beside it, and one cell of mixed colour. `truth` says what was drawn, in pixels."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

import shapely
from PIL import Image, ImageDraw, ImageFont

from delve.maps.geo.grid import cell_centre, cell_polygon
from delve.maps.geo.model import Grid, Point

COLOURS: dict[str, tuple[int, int, int]] = {
    "plains": (200, 220, 140),
    "forest": (60, 140, 60),
    "hills": (232, 160, 112),
    "mountain": (141, 90, 60),
    "sea": (74, 144, 208),
    "lake": (74, 144, 208),
}
MARGIN = (242, 232, 204)
LINE = (30, 30, 30)
INK = (20, 20, 20)
RIVER = (47, 111, 192)
ROAD = (208, 58, 42)
RIVER_WIDTH = 4
LAND = ("plains", "forest", "hills", "mountain")

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class Label:
    text: str
    box: Box
    words: tuple[tuple[str, Box], ...]
    """Each word and its box, as OCR answers them."""


@dataclass(frozen=True)
class TruePlace:
    name: str
    kind: Literal["town", "port"]
    symbol: Literal["circle", "square"]
    point: Point
    label: Label


@dataclass(frozen=True)
class Truth:
    grid: Grid
    """The grid in pixels: `size_km` is the cell's size in px."""
    margin_px: int
    terrain: tuple[str, ...]
    """Each cell's terrain: one of `LAND`, `sea` or `lake`. The mixed cell has the terrain of its left half."""
    mixed: tuple[int, ...]
    sea: tuple[int, ...]
    lakes: tuple[tuple[int, ...], ...]
    """Each lake's cells, the largest first."""
    river: tuple[Point, ...]
    """From its source (in the small lake) to its mouth (in the sea, or the large lake)."""
    river_name: Label
    places: tuple[TruePlace, ...]
    road: tuple[Point, ...]
    road_between: tuple[str, str]
    cell_numbers: tuple[Label, ...]
    """The digits in the frame."""

    @property
    def labels(self) -> tuple[Label, ...]:
        return (*self.cell_numbers, self.river_name, *(p.label for p in self.places))

    def place(self, name: str) -> TruePlace:
        return next(p for p in self.places if p.name == name)


@dataclass(frozen=True)
class Synthetic:
    image: Image.Image
    truth: Truth


def hex_map(
    *,
    size_px: int = 40,
    cols: int = 16,
    rows: int = 12,
    orientation: Literal["pointy", "flat"] = "pointy",
    lines: bool = True,
    sea: bool = True,
    lakes: int = 1,
    water: tuple[int, int, int] | None = None,
) -> Synthetic:
    """A hex map. Without `lines` no grid is drawn; without `sea` and with `lakes=2` the river runs from a small lake
    to a larger one, and no water touches the grid's bounds. `water` replaces the sea's and the lakes' colour."""
    return _draw("hex", size_px, cols, rows, orientation, lines=lines, sea=sea, lakes=lakes, water=water)


def square_map(*, size_px: int = 32, cols: int = 20, rows: int = 14) -> Synthetic:
    return _draw("square", size_px, cols, rows, "pointy", lines=True, sea=True, lakes=1)


def fake_ocr(truth: Truth) -> Callable[[Image.Image], list[Any]]:
    """A `PictureOcr` answering the drawn labels' words with their boxes, at confidence 95: the words whose box lies
    inside the image it is given, a tile at its `info["offset"]` in the picture (the top left without one), in the
    tile's own pixels."""

    def ocr(image: Image.Image) -> list[Any]:
        from delve.maps.geo.reading.ocr import TILE_OFFSET, OcrWord  # Task 8's

        x, y = image.info.get(TILE_OFFSET, (0, 0))
        w, h = image.size
        return [
            OcrWord(text, (box[0] - x, box[1] - y, box[2] - x, box[3] - y), 95.0)
            for label in truth.labels
            for text, box in label.words
            if x <= box[0] and y <= box[1] and box[2] <= x + w and box[3] <= y + h
        ]

    return ocr


def fake_look(
    truth: Truth, *, labels: bool = True, terrain: bool = True, prompts: list[str] | None = None
) -> Callable[[str, bytes, str], Awaitable[str]]:
    """A `Look` answering from the truth, by the prompt alone: the terrain of each colour it lists (the nearest drawn
    colour; the frame's is `outside`), and the label nearest each crop's position. Without `labels` or `terrain` it
    reads nothing of that kind. Each prompt is kept in `prompts`."""

    async def look(prompt: str, image: bytes, media_type: str) -> str:
        assert media_type == "image/png" and image.startswith(b"\x89PNG")
        if prompts is not None:
            prompts.append(prompt)
        if prompt.startswith("# The terrain colours"):
            if not terrain:
                return "I can't tell."
            named = [*COLOURS.items(), ("outside", MARGIN)]
            answer = {}
            for n, code in re.findall(r"- colour (\d+): #([0-9a-f]{6})", prompt):
                rgb = tuple(int(code[k : k + 2], 16) for k in (0, 2, 4))
                answer[n] = min(named, key=lambda item: math.dist(item[1], rgb))[0]
            return json.dumps(answer)
        found = []
        for n, x, y in re.findall(r"- (\d+): .*? at \((-?\d+), (-?\d+)\)", prompt):
            here = (float(x), float(y))
            near = [(math.dist(p.point, here), p.name) for p in truth.places]
            near += [
                (math.dist(_centre(lb.box), here), lb.text)
                for lb in (truth.river_name, *(p.label for p in truth.places))
            ]
            d, name = min(near)
            found.append({"n": int(n), "label": name if labels and d <= 1.5 * truth.grid.size_km else ""})
        return json.dumps(found)

    return look


def _centre(box: Box) -> Point:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def _bbox(kind: str, orientation: str, size: float, cols: int, rows: int) -> tuple[float, float]:
    if kind == "square":
        return cols * size, rows * size
    r = size / math.sqrt(3.0)
    if orientation == "pointy":
        return size * (cols + 0.5), r * (2 + 1.5 * (rows - 1))
    return r * (2 + 1.5 * (cols - 1)), size * (rows + 0.5)


def _font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default()


def _label(draw: ImageDraw.ImageDraw, text: str, centre_x: float, bottom: float) -> Label:
    """Draws `text` centred on `centre_x` with its ink's bottom at `bottom`, and answers its boxes."""
    font = _font()
    x0, _, x1, y1 = draw.textbbox((0, 0), text, font=font)
    ox = round(centre_x - (x1 - x0) / 2) - x0
    oy = round(bottom) - y1
    draw.text((ox, oy), text, fill=INK, font=font)
    box = draw.textbbox((ox, oy), text, font=font)
    words = []
    start = 0
    for word in text.split(" "):
        prefix = text[:start]
        wx0 = ox + (draw.textlength(prefix, font=font) if prefix else 0)
        wb = draw.textbbox((round(wx0), oy), word, font=font)
        words.append((word, (wb[0], wb[1], wb[2], wb[3])))
        start += len(word) + 1
    return Label(text, (box[0], box[1], box[2], box[3]), tuple(words))


def _ring(grid: Grid, i: int) -> list[tuple[float, float]]:
    return [(x, y) for x, y in cell_polygon(grid, i)[:-1]]


def _draw(
    kind: Literal["hex", "square"],
    size: int,
    cols: int,
    rows: int,
    orientation: Literal["pointy", "flat"],
    *,
    lines: bool,
    sea: bool,
    lakes: int,
    water: tuple[int, int, int] | None = None,
) -> Synthetic:
    colours = COLOURS | ({"sea": water, "lake": water} if water else {})
    margin = max(size, 36)
    grid = Grid(kind, float(size), cols, rows, (float(margin), float(margin)), orientation)
    bw, bh = _bbox(kind, orientation, size, cols, rows)
    image = Image.new("RGB", (math.ceil(bw) + 2 * margin, math.ceil(bh) + 2 * margin), MARGIN)
    draw = ImageDraw.Draw(image)

    def at(c: int, r: int) -> int:
        return r * cols + c

    lc, lr = round(cols * 0.75), rows // 2 - 1
    small_lake = (at(lc, lr), at(lc + 1, lr), at(lc, lr + 1))
    sea_cells: tuple[int, ...] = ()
    lake_cells: list[tuple[int, ...]] = [small_lake]
    if sea:
        sea_cells = tuple(at(c, r) for r in range(rows) for c in (0, 1))
        mouth_cell = at(1, lr)
    else:
        big = (at(2, lr - 1), at(2, lr), at(2, lr + 1), at(3, lr), at(3, lr + 1))
        lake_cells.insert(0, big)
        mouth_cell = at(3, lr)
    if lakes == 1 and not sea:
        raise ValueError("a map without a sea needs two lakes")
    wet = {i: "sea" for i in sea_cells} | {i: "lake" for lake in lake_cells for i in lake}
    mixed = at(6, 2)

    terrain = []
    for i in range(grid.cells):
        c, r = i % cols, i // cols
        terrain.append(wet.get(i) or LAND[((c // 4) + 2 * (r // 6)) % 4])
    terrain[mixed] = "forest"

    for i in range(grid.cells):
        ring = _ring(grid, i)
        draw.polygon(ring, fill=colours[terrain[i]])
    right = shapely.Polygon(_ring(grid, mixed)).intersection(shapely.box(cell_centre(grid, mixed)[0], -1e6, 1e6, 1e6))
    draw.polygon(list(right.exterior.coords)[:-1], fill=COLOURS["hills"])
    if lines:
        for i in range(grid.cells):
            draw.line([*_ring(grid, i), _ring(grid, i)[0]], fill=LINE, width=1)

    numbers = []
    for c in range(cols):
        x = cell_centre(grid, at(c, 0))[0]
        numbers.append(_label(draw, f"{c + 1:02d}00", x, margin * 0.7))
    for r in range(rows):
        y = cell_centre(grid, at(0, r))[1]
        numbers.append(_label(draw, f"00{r + 1:02d}", margin / 2, y + 5))

    # The river: from inside the small lake, west to inside the sea (or the large lake), with a level stretch in the
    # middle for the river town.
    xs, ys = cell_centre(grid, at(lc, lr))
    xs -= 0.3 * size
    xe, ye = cell_centre(grid, mouth_cell)
    xe += 0.3 * size
    shape = [(0, 0), (0.1, -0.35), (0.4, -0.35), (0.45, 0), (0.6, 0), (0.7, 0.35), (0.9, 0.35), (1, 0)]

    def along(t: float, dy: float = 0.0) -> Point:
        return (xs + (xe - xs) * t, ys + (ye - ys) * t + dy * size)

    river = tuple(along(t, dy) for t, dy in shape)
    draw.line(river, fill=RIVER, width=RIVER_WIDTH, joint="curve")

    places = []
    x, y = along(0.525)
    places.append(_town(draw, "Arden", "town", (x, y - 10)))
    for name, (c, r) in (("Brask", (4, rows - 3)), ("Corvel", (9, rows - 2))):
        places.append(_town(draw, name, "town", cell_centre(grid, at(c, r))))
    mx = cell_centre(grid, mouth_cell)[0] + 0.75 * size
    my = along((mx - xs) / (xe - xs))[1] - 0.45 * size
    places.append(_town(draw, "Port Wyn", "port", (mx, my)))

    a, b = places[1].point, places[2].point
    road = (a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 0.3 * size), b)
    draw.line(road, fill=ROAD, width=2)
    for p in places:
        _symbol(draw, p.symbol, p.point)

    x, y = along(0.25, -0.35)
    river_name = _label(draw, "ELDRIN", x, y - RIVER_WIDTH / 2 - 4)

    truth = Truth(
        grid=grid,
        margin_px=margin,
        terrain=tuple(terrain),
        mixed=(mixed,),
        sea=tuple(sorted(sea_cells)),
        lakes=tuple(tuple(sorted(lake)) for lake in lake_cells),
        river=river,
        river_name=river_name,
        places=tuple(places),
        road=road,
        road_between=(places[1].name, places[2].name),
        cell_numbers=tuple(numbers),
    )
    return Synthetic(image, truth)


def _symbol(draw: ImageDraw.ImageDraw, symbol: str, point: Point) -> None:
    x, y = point
    if symbol == "circle":
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=INK)
    else:
        draw.rectangle((x - 4, y - 4, x + 4, y + 4), fill=INK)


def _town(draw: ImageDraw.ImageDraw, name: str, kind: Literal["town", "port"], point: Point) -> TruePlace:
    """The place's label; its symbol is drawn last, over the road."""
    symbol: Literal["circle", "square"] = "square" if kind == "port" else "circle"
    label = _label(draw, name, point[0], point[1] - 7)
    return TruePlace(name, kind, symbol, point, label)
