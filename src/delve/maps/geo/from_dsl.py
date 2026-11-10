"""Plateau 6's `.map` world maps, converted once into geo maps.

`from_view` takes a compiled view (`delve.maps.world.compile_view`): its units through its `scale` make km (miles ×
1.609344), y is flipped (the DSL's grows north), and the frame is the features' bounding box plus 5% on every side. The
grid is `default_grid`, and a cell under no terrain is plains. Each DSL feature keeps its name as its id; what Delve's
layers can't say is simplified, with a warning.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from delve.maps.geo.grid import cells_in_area, default_grid
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Point, water_from_areas
from delve.maps.geo.terrain import PLACE_KINDS, TERRAIN_CLASSES, TERRAIN_LETTERS
from delve.maps.world.compile import WorldFeature, WorldView

MILE_KM = 1.609344

UNIT_KM: dict[str, float] = {"miles": MILE_KM, "mile": MILE_KM, "km": 1.0, "feet": 0.0003048, "ft": 0.0003048}
"""A view's `units` in km; another word is read as miles, with a warning."""

BIOMES: dict[str, str] = {name: name for name in TERRAIN_CLASSES} | {
    "marsh": "swamp",
    "tundra": "arctic",
    "mountains": "mountain",
}
"""A DSL terrain's `biome` and its terrain class; another biome is plains, with a warning."""

MARGIN = 0.05


@dataclass(frozen=True)
class FromDsl:
    geo: GeoMap
    warnings: list[str]
    names: dict[str, str]
    """Each DSL name and its feature's id (the same name)."""
    _left: float = field(default=0.0, repr=False)
    _top: float = field(default=0.0, repr=False)
    _km: float = field(default=1.0, repr=False)

    def km(self, point: tuple[float, float]) -> Point:
        """A point in the DSL's own units, as km on `geo`: where a plateau 6 position stands now."""
        x, y = point
        return ((x - self._left) * self._km, (self._top - y) * self._km)


def _middle(f: WorldFeature) -> Point:
    ring = f.coords[:-1] if len(f.coords) > 1 and f.coords[0] == f.coords[-1] else f.coords
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def _notes(f: WorldFeature) -> str:
    """The DSL's `description` and `doc`: plateau 6 made them the DM's."""
    parts = []
    description, doc = f.properties.get("description"), f.properties.get("doc")
    if isinstance(description, str) and description:
        parts.append(description)
    if doc not in (None, "", True):
        parts.append(f"doc: {doc}")
    return "\n\n".join(parts)


def _place_kind(f: WorldFeature) -> str:
    if f.kind == "city":
        pop = f.properties.get("pop")
        if isinstance(pop, (int, float)) and not isinstance(pop, bool):
            return "city" if pop >= 10_000 else "village" if pop < 1_000 else "town"
        return "town"
    category = f.properties.get("category")
    if isinstance(category, str) and category in PLACE_KINDS:
        return category
    tags = {t.casefold() for t in f.tags}
    if "dungeon" in tags:
        return "dungeon"
    if tags & {"ruin", "ruins", "ruined"}:
        return "ruin"
    return "other"


def from_view(view: WorldView, *, revealed: Collection[str] = ()) -> FromDsl:
    """`view` as a geo map. A hidden feature named in `revealed` (plateau 6's revealed places) is no longer hidden."""
    warn: Counter[str] = Counter()
    units = view.units.casefold()
    if units not in UNIT_KM:
        warn[f"The view's units {view.units!r} are read as miles."] += 1
    unit_km = UNIT_KM.get(units, MILE_KM) * view.scale

    coords = [p for f in view.features for p in f.coords]
    if not coords:
        coords = [(0.0, 0.0), (1.0, 1.0)]
    x0, x1 = min(p[0] for p in coords), max(p[0] for p in coords)
    y0, y1 = min(p[1] for p in coords), max(p[1] for p in coords)
    pad = MARGIN * max(x1 - x0, y1 - y0, 1e-9)
    if pad <= 1e-9:
        pad = 1.0
    left, top = x0 - pad, y1 + pad
    frame = Frame((x1 - x0 + 2 * pad) * unit_km, (y1 - y0 + 2 * pad) * unit_km, "miles" if units in ("miles", "mile") else "km")  # fmt: skip
    grid = default_grid(frame)

    def km(p: tuple[float, float]) -> list[float]:
        return [(p[0] - left) * unit_km, (top - p[1]) * unit_km]

    def line(f: WorldFeature) -> dict[str, Any]:
        return {"type": "LineString", "coordinates": [km(p) for p in f.coords]}

    def polygon(f: WorldFeature) -> dict[str, Any]:
        return {"type": "Polygon", "coordinates": [[km(p) for p in f.coords]]}

    def point(p: Point) -> dict[str, Any]:
        return {"type": "Point", "coordinates": km(p)}

    letters = [TERRAIN_LETTERS["plains"]] * grid.cells
    features: list[GeoFeature] = []
    names: dict[str, str] = {}
    seen: set[str] = set()
    for f in view.features:
        made: tuple[str, str, dict[str, Any], dict[str, Any]] | None = None  # layer, kind, geometry, props
        if f.kind in ("city", "poi") and f.geometry == "Point":
            made = ("places", _place_kind(f), point(f.coords[0]), {})
        elif f.kind == "road" and f.geometry == "LineString":
            surface = f.properties.get("surface")
            kind = surface if surface in ("track", "trail") else "road"
            made = ("routes", kind, line(f), {"surface": surface} if isinstance(surface, str) else {})
        elif f.kind == "river" and f.geometry == "LineString":
            made = ("water", "river", line(f), {})
        elif f.kind == "lake" and f.geometry == "Polygon":
            made = ("water", "lake", polygon(f), {})
        elif f.kind == "kingdom" and f.geometry == "Polygon":
            made = ("regions", "kingdom", polygon(f), {})
        elif f.kind == "terrain" and f.geometry == "Polygon":
            biome = str(f.properties.get("biome", "")).casefold()
            cls = BIOMES.get(biome)
            if cls is None:
                warn[f"The biome {biome or '(none)'!r} isn't one Delve knows: its cells are plains."] += 1
                cls = "plains"
            for i in cells_in_area(grid, polygon(f)["coordinates"]):
                letters[i] = TERRAIN_LETTERS[cls]
            warn["The terrain areas became terrain cells: their names and notes are left out."] += 1
            continue
        elif f.kind in ("building", "room") and f.geometry == "Polygon":
            made = ("places", "other", point(_middle(f)), {})
            warn[f"A {f.kind} became a place at its centre."] += 1
        elif f.kind in ("street", "passage") and f.geometry == "LineString":
            made = ("routes", "trail", line(f), {})
            warn[f"A {f.kind} became a trail."] += 1
        if made is None:
            warn[f"A {f.kind} was left out: Delve's world maps don't draw it."] += 1
            continue
        layer, kind, geometry, props = made
        fid = f.name
        if fid in seen:
            warn[f"The name {f.name!r} is used twice: the second is left out."] += 1
            continue
        seen.add(fid)
        names[f.name] = fid
        features.append(
            GeoFeature(
                fid,
                layer,
                kind,
                f.label,
                geometry,
                dm_notes=_notes(f),
                tags=tuple(t for t in f.tags if t != "hidden"),
                hidden=f.hidden and f.name not in revealed,
                props=props,
            )
        )
    geo = water_from_areas(GeoMap(frame, grid, "".join(letters), tuple(features)))
    warnings = [w if n == 1 else f"{w} ({n}×)" for w, n in warn.items()]
    return FromDsl(geo, warnings, names, left, top, unit_km)
