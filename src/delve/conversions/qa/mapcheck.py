"""The map check (thorough conversion Task 3), from the WGR1 QA's `check.py`, `fixdoors.py` and `shot.mjs`: a
traced `.dmap` parsed and validated, its doors mended when asked, and drawn as `<name>.svg` and `<name>.png` beside it,
the PNG with no browser (`raster`), for the trace agent to compare with the scan.

**Mending doors** (`fix_doors`): a `door between room.a and room.b { … }` on one line whose rooms share less than
`MIN_SHARED_WALL` of wall (the parser refuses it: "they don't meet") becomes `door at X,Y { connects room.a, room.b … }`
in the middle of the gap between the rooms' facing walls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import nearest_points

from delve.conversions.qa.raster import WIDTH, svg_to_png
from delve.maps.dsl import DmapParseError, render, validate
from delve.maps.dsl.geometry import room_polygon
from delve.maps.sources import parse_source

MIN_SHARED_WALL = 0.5
"""Squares of wall two rooms share for a `door between` them to stand."""

_DOOR_BETWEEN = re.compile(r"^([ \t]*)door\s+between\s+room\.(\w+)\s+and\s+room\.(\w+)\s*\{(.*)\}[ \t]*$", re.MULTILINE)


@dataclass
class MapCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    counts: str = ""


def _libraries(path: Path) -> dict[str, str]:
    """The other `.dmap` files beside `path`, by file name: the includes a map may name."""
    return {p.name: p.read_text() for p in sorted(path.parent.glob("*.dmap")) if p != path}


def fix_doors(source: str, libraries: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """`source` with its one-line `door between` doors whose rooms don't meet moved to the rooms' nearest points, and a
    line per door moved. Unchanged when the map doesn't parse without those doors."""
    try:
        model = parse_source(_DOOR_BETWEEN.sub("", source), libraries)
    except DmapParseError:
        return source, []
    polygons = {name: Polygon(room_polygon(room)) for name, room in model.rooms.items()}
    fixes: list[str] = []

    def fix(m: re.Match[str]) -> str:
        indent, a, b, rest = m.groups()
        if a not in polygons or b not in polygons:
            return m.group(0)
        pa, pb = polygons[a], polygons[b]
        shared = pa.boundary.intersection(pb.boundary).length if pa.distance(pb) < 1e-6 else 0.0
        if shared >= MIN_SHARED_WALL:
            return m.group(0)
        gap = pa.distance(pb)
        between = pa.buffer(gap / 2 + 0.01).intersection(pb.buffer(gap / 2 + 0.01))
        if between.is_empty:
            p, q = nearest_points(pa, pb)
            x, y = round((p.x + q.x) / 2, 2), round((p.y + q.y) / 2, 2)
        else:
            x, y = round(between.centroid.x, 2), round(between.centroid.y, 2)
        fixes.append(f"{a}-{b}: shared wall {shared:.2f}, gap {gap:.2f}: door moved to {x},{y}")
        return f"{indent}door at {x},{y} {{ connects room.{a}, room.{b} {rest.strip()} }}"

    return _DOOR_BETWEEN.sub(fix, source), fixes


def check_map(path: Path, svg: Path, png: Path, *, mend_doors: bool = False, width: int = WIDTH) -> MapCheck:
    """`path` checked (and its doors mended in place with `mend_doors`), drawn to `svg` and `png` when it parses."""
    result = MapCheck()
    source = path.read_text()
    libraries = _libraries(path)
    if mend_doors:
        source, result.fixes = fix_doors(source, libraries)
        if result.fixes:
            path.write_text(source)
    try:
        model = parse_source(source, libraries)
    except DmapParseError as e:
        result.errors.append(str(e))
        return result
    for d in validate(model):
        (result.errors if d.severity == "error" else result.warnings).append(f"{d.message} (line {d.line})")
    counts = {"rooms": model.rooms, "corridors": model.corridors, "doors": model.doors, "exits": model.exits}
    result.counts = ", ".join(f"{name} {len(items)}" for name, items in counts.items())
    try:
        drawing = render(model)
        svg.write_text(drawing)
        svg_to_png(drawing, png, width)
    except Exception as e:  # noqa: BLE001 (a renderer's or resvg's failure is the map's error to fix)
        result.errors.append(f"the map can't be drawn: {e}")
    return result
