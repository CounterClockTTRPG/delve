"""GeoJSON in and out.

`to_geojson` writes the Delve document: a FeatureCollection in km from the top left, y growing down, with a `delve`
member holding the frame, the grid, the terrain letters and the picture. With `terrain_cells`, it adds a `Polygon` per
cell (`{layer: "terrain", terrain}`), the export for QGIS.

`from_geojson` reads it back exactly, and reads a foreign file too: x east and y north in its own units, scaled by a
`Scale` (the map's width, or two places and the km between them), its properties named by a `PropertyMapping`. An
Azgaar export (`is_azgaar`) maps itself: its cells' biome ids and heights, its burgs, rivers, routes and markers.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from delve.maps.geo.grid import cell_polygon, cells_in_area, default_grid
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, GeoMapError, Grid, PictureRef, water_from_areas
from delve.maps.geo.terrain import (
    LAYER_GEOMETRIES,
    LAYER_KINDS,
    LAYERS,
    NO_TERRAIN,
    PLACE_KINDS,
    ROUTE_KINDS,
    TERRAIN_CLASSES,
    TERRAIN_LETTERS,
    TERRAIN_OF_LETTER,
)

DELVE_VERSION = 1

_CORE = ("layer", "kind", "name", "description", "dm_notes", "tags", "hidden")
"""The properties every feature of a Delve document has; the others are its `props`."""

AZGAAR_BIOMES: dict[int, str] = {
    0: "sea",  # Marine
    1: "desert",  # Hot desert
    2: "desert",  # Cold desert
    3: "plains",  # Savanna
    4: "plains",  # Grassland
    5: "jungle",  # Tropical seasonal forest
    6: "forest",  # Temperate deciduous forest
    7: "jungle",  # Tropical rainforest
    8: "forest",  # Temperate rainforest
    9: "forest",  # Taiga
    10: "arctic",  # Tundra
    11: "arctic",  # Glacier
    12: "swamp",  # Wetland
}
"""Azgaar's default biome ids and Delve's terrain class for each."""

AZGAAR_BIOME_NAMES: dict[str, str] = {
    "marine": "sea",
    "hot desert": "desert",
    "cold desert": "desert",
    "savanna": "plains",
    "grassland": "plains",
    "tropical seasonal forest": "jungle",
    "temperate deciduous forest": "forest",
    "tropical rainforest": "jungle",
    "temperate rainforest": "forest",
    "taiga": "forest",
    "tundra": "arctic",
    "glacier": "arctic",
    "wetland": "swamp",
}
"""The same table by name, lower case, for an export that gives the biome's name."""

AZGAAR_MOUNTAIN_HEIGHT = 67
AZGAAR_HILLS_HEIGHT = 50


@dataclass(frozen=True)
class Scale:
    """How big a foreign map is: its width in km, or two places and the km between them."""

    width_km: float | None = None
    known: tuple[str, str, float] | None = None


@dataclass(frozen=True)
class PropertyMapping:
    """Which properties of a foreign file hold a feature's kind and name, and Delve's kind for each raw kind value."""

    kind: str = "kind"
    name: str = "name"
    values: Mapping[str, str] = field(default_factory=dict)


@dataclass
class Imported:
    geo: GeoMap | None
    warnings: list[str]
    needs_scale: bool = False
    """A foreign file read without a `Scale`: `geo` is None, and `properties` and `kinds` say what it holds."""
    properties: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    """The values of its kind property (`PropertyMapping.kind`)."""


# --- out -------------------------------------------------------------------------------------------------------------


def _feature_out(f: GeoFeature) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "layer": f.layer,
        "kind": f.kind,
        "name": f.name,
        "description": f.description,
        "dm_notes": f.dm_notes,
        "tags": list(f.tags),
        "hidden": f.hidden,
    }
    properties.update({k: v for k, v in f.props.items() if k not in _CORE})
    return {"type": "Feature", "id": f.id, "geometry": f.geometry, "properties": properties}


def _picture_out(p: PictureRef | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"id": p.id, "width_px": p.width_px, "height_px": p.height_px, "km_per_px": p.km_per_px, "asset": p.asset}


def to_geojson(geo: GeoMap, *, terrain_cells: bool = False) -> dict[str, Any]:
    """The Delve document of `geo`; with `terrain_cells`, a `Polygon` feature per cell that has a terrain too."""
    grid = geo.grid
    features = [_feature_out(f) for f in geo.features]
    if terrain_cells:
        for i, letter in enumerate(geo.terrain):
            if letter == NO_TERRAIN:
                continue
            ring = [[x, y] for x, y in cell_polygon(grid, i)]
            features.append(
                {
                    "type": "Feature",
                    "id": f"cell-{i}",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {"layer": "terrain", "terrain": TERRAIN_OF_LETTER[letter]},
                }
            )
    return {
        "type": "FeatureCollection",
        "delve": {
            "version": DELVE_VERSION,
            "frame": {"width_km": geo.frame.width_km, "height_km": geo.frame.height_km, "units": geo.frame.units},
            "grid": {
                "kind": grid.kind,
                "size_km": grid.size_km,
                "cols": grid.cols,
                "rows": grid.rows,
                "origin": list(grid.origin),
                "orientation": grid.orientation,
            },
            "terrain": geo.terrain,
            "picture": _picture_out(geo.picture),
        },
        "features": features,
    }


# --- in: the Delve document ------------------------------------------------------------------------------------------


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _read_frame(raw: Any, problems: list[str]) -> Frame | None:
    if not isinstance(raw, dict):
        problems.append("delve.frame is missing")
        return None
    w, h, units = raw.get("width_km"), raw.get("height_km"), raw.get("units", "km")
    if not (_number(w) and _number(h) and w > 0 and h > 0):
        problems.append("delve.frame needs a width_km and a height_km over 0")
        return None
    if units not in ("km", "miles"):
        problems.append(f"delve.frame.units {units!r} isn't km or miles")
        return None
    return Frame(float(w), float(h), units)


def _read_grid(raw: Any, problems: list[str]) -> Grid | None:
    if not isinstance(raw, dict):
        problems.append("delve.grid is missing")
        return None
    kind, size, cols, rows = raw.get("kind"), raw.get("size_km"), raw.get("cols"), raw.get("rows")
    origin, orientation = raw.get("origin", [0.0, 0.0]), raw.get("orientation", "pointy")
    if kind not in ("hex", "square"):
        problems.append(f"delve.grid.kind {kind!r} isn't hex or square")
    elif not (_number(size) and size > 0):
        problems.append("delve.grid.size_km must be over 0")
    elif not (isinstance(cols, int) and isinstance(rows, int) and cols >= 1 and rows >= 1):
        problems.append("delve.grid needs cols and rows of at least 1")
    elif not (isinstance(origin, list) and len(origin) == 2 and all(_number(v) for v in origin)):
        problems.append("delve.grid.origin must be [x, y]")
    elif orientation not in ("pointy", "flat"):
        problems.append(f"delve.grid.orientation {orientation!r} isn't pointy or flat")
    else:
        return Grid(kind, float(size), cols, rows, (float(origin[0]), float(origin[1])), orientation)
    return None


def _read_picture(raw: Any, problems: list[str]) -> PictureRef | None:
    if raw is None:
        return None
    try:
        return PictureRef(
            str(raw["id"]), int(raw["width_px"]), int(raw["height_px"]), float(raw["km_per_px"]), raw.get("asset")
        )
    except (KeyError, TypeError, ValueError):
        problems.append("delve.picture needs an id, width_px, height_px and km_per_px")
        return None


def _read_feature(raw: Any, n: int, seen: set[str], problems: list[str]) -> GeoFeature | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("properties"), dict):
        problems.append(f"feature {n} isn't a Feature with properties")
        return None
    props = raw["properties"]
    fid = raw.get("id")
    if not isinstance(fid, str) or not fid:
        problems.append(f"feature {n} has no id")
        return None
    if fid in seen:
        problems.append(f"the id {fid!r} is used twice")
        return None
    seen.add(fid)
    layer, kind, geometry = props.get("layer"), props.get("kind"), raw.get("geometry")
    if layer not in LAYERS:
        problems.append(f"{fid}: the layer {layer!r} isn't one of {', '.join(LAYERS)}")
        return None
    allowed = LAYER_KINDS[layer]
    if not isinstance(kind, str) or not kind or (allowed is not None and kind not in allowed):
        problems.append(f"{fid}: the kind {kind!r} isn't a kind of {layer}")
        return None
    if not isinstance(geometry, dict) or geometry.get("type") not in LAYER_GEOMETRIES[layer]:
        problems.append(f"{fid}: {layer} need a {' or '.join(LAYER_GEOMETRIES[layer])} geometry")
        return None
    if not isinstance(geometry.get("coordinates"), list):
        problems.append(f"{fid}: its geometry has no coordinates")
        return None
    tags = props.get("tags", [])
    text = {k: props.get(k, "") for k in ("name", "description", "dm_notes")}
    if not all(isinstance(v, str) for v in text.values()) or not isinstance(tags, list):
        problems.append(f"{fid}: name, description and dm_notes must be text, and tags a list")
        return None
    return GeoFeature(
        fid,
        layer,
        kind,
        text["name"],
        geometry,
        description=text["description"],
        dm_notes=text["dm_notes"],
        tags=tuple(str(t) for t in tags),
        hidden=bool(props.get("hidden", False)),
        props={k: v for k, v in props.items() if k not in _CORE},
    )


def _from_delve(doc: dict[str, Any]) -> Imported:
    meta = doc["delve"]
    problems: list[str] = []
    if not isinstance(meta, dict) or meta.get("version") != DELVE_VERSION:
        raise GeoMapError("The world map doesn't hold together.", [f"delve.version must be {DELVE_VERSION}"])
    frame = _read_frame(meta.get("frame"), problems)
    grid = _read_grid(meta.get("grid"), problems)
    terrain = meta.get("terrain")
    if grid is not None:
        if not isinstance(terrain, str) or len(terrain) != grid.cells:
            problems.append(f"delve.terrain must hold one letter per cell ({grid.cells})")
        elif bad := sorted(set(terrain) - set(TERRAIN_LETTERS.values()) - {NO_TERRAIN}):
            problems.append(f"delve.terrain has letters that are no terrain: {''.join(bad)}")
    picture = _read_picture(meta.get("picture"), problems)
    features: list[GeoFeature] = []
    seen: set[str] = set()
    for n, raw in enumerate(doc.get("features") or []):
        if (
            isinstance(raw, dict)
            and isinstance(raw.get("properties"), dict)
            and raw["properties"].get("layer") == "terrain"
        ):
            continue  # the QGIS export's cells: the terrain string says the same
        found = _read_feature(raw, n, seen, problems)
        if found is not None:
            features.append(found)
    if problems or frame is None or grid is None:
        raise GeoMapError("The world map doesn't hold together.", problems)
    assert isinstance(terrain, str)
    return Imported(GeoMap(frame, grid, terrain, tuple(features), picture), [])


# --- in: a foreign file ----------------------------------------------------------------------------------------------


def is_azgaar(doc: Mapping[str, Any]) -> bool:
    """Whether `doc` is Azgaar's export, by its features' properties."""
    return any(_azgaar_kind(f.get("properties") or {}) is not None for f in _raw_features(doc))


def _azgaar_kind(props: Mapping[str, Any]) -> str | None:
    if "biome" in props and "height" in props:
        return "cell"
    if "population" in props and "capital" in props:
        return "burg"
    if "discharge" in props:
        return "river"
    if "group" in props:
        return "route"
    if "icon" in props:
        return "marker"
    return None


def _raw_features(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    features = doc.get("features")
    return [f for f in features if isinstance(f, dict)] if isinstance(features, list) else []


def _parts(geometry: Any) -> Iterator[dict[str, Any]]:
    """A geometry's single parts: a `Multi…` one split."""
    if not isinstance(geometry, dict) or not isinstance(geometry.get("coordinates"), list):
        return
    kind = geometry.get("type")
    if kind in ("Point", "LineString", "Polygon"):
        yield geometry
    elif kind in ("MultiPoint", "MultiLineString", "MultiPolygon"):
        for coords in geometry["coordinates"]:
            yield {"type": kind[len("Multi") :], "coordinates": coords}


@dataclass
class _Item:
    """A foreign feature, classified: a `layer` (or `terrain`, for cells to paint) and its raw geometry."""

    layer: str
    kind: str
    name: str
    geometry: dict[str, Any]
    dm_notes: str = ""
    tags: tuple[str, ...] = ()


def _truthy(value: Any) -> bool:
    return value not in (None, 0, "", "0", False, "false", "False")


def _azgaar_item(props: Mapping[str, Any], geometry: dict[str, Any], warn: Counter[str]) -> _Item | None:
    kind = _azgaar_kind(props)
    gtype = geometry["type"]
    name = str(props.get("name") or "")
    if kind == "cell" and gtype == "Polygon":
        biome = props.get("biome")
        if isinstance(biome, str):
            cls = AZGAAR_BIOME_NAMES.get(biome.strip().casefold())
        else:
            cls = AZGAAR_BIOMES.get(biome) if isinstance(biome, int) and not isinstance(biome, bool) else None
        if cls is None:
            warn[f"Azgaar's biome {biome!r} isn't one Delve knows: its cells are plains."] += 1
            cls = "plains"
        height = props.get("height")
        if cls != "sea" and _number(height):
            if height >= AZGAAR_MOUNTAIN_HEIGHT:
                cls = "mountain"
            elif height >= AZGAAR_HILLS_HEIGHT:
                cls = "hills"
        return _Item("terrain", cls, name, geometry)
    if kind == "burg" and gtype == "Point":
        population = props.get("population")
        thousands = float(population) if _number(population) else 0.0
        if _truthy(props.get("port")):
            place = "port"
        else:
            place = "city" if thousands >= 5 else "town" if thousands >= 1 else "village"
        return _Item("places", place, name, geometry, tags=("capital",) if _truthy(props.get("capital")) else ())
    if kind == "river" and gtype == "LineString":
        return _Item("water", "river", name, geometry)
    if kind == "route" and gtype == "LineString":
        group = str(props.get("group") or "").casefold()
        if "sea" in group:
            warn["Sea routes were left out: a ship finds its own way."] += 1
            return None
        route = "trail" if "trail" in group else "road" if "road" in group else "track"
        return _Item("routes", route, name, geometry)
    if kind == "marker" and gtype == "Point":
        marker = str(props.get("type") or "")
        place = "dungeon" if "dungeon" in marker.casefold() else "ruin" if "ruin" in marker.casefold() else "other"
        return _Item("places", place, name or marker.replace("-", " ").capitalize(), geometry)
    warn[f"A {kind or 'feature'} with a {gtype} geometry was left out: Delve doesn't read it."] += 1
    return None


def _mapped_item(
    props: Mapping[str, Any], geometry: dict[str, Any], mapping: PropertyMapping, warn: Counter[str]
) -> _Item | None:
    raw = props.get(mapping.kind)
    raw_kind = "" if raw is None else str(raw)
    kind = str(mapping.values.get(raw_kind, raw_kind)).strip().casefold()
    name_raw = props.get(mapping.name)
    name = "" if name_raw is None else str(name_raw)
    notes = props.get("description")
    dm_notes = notes if isinstance(notes, str) else ""  # a foreign description may say anything: it is the DM's
    gtype = geometry["type"]
    if gtype == "Polygon" and kind in ("sea", "lake"):
        return _Item("water", kind, name, geometry, dm_notes)
    if gtype == "Polygon" and kind in TERRAIN_CLASSES:
        return _Item("terrain", kind, name, geometry)
    if gtype == "LineString" and kind == "river":
        return _Item("water", "river", name, geometry, dm_notes)
    if gtype == "Point" and kind in PLACE_KINDS:
        return _Item("places", kind, name, geometry, dm_notes)
    if gtype == "LineString" and kind in ROUTE_KINDS:
        return _Item("routes", kind, name, geometry, dm_notes)
    if gtype == "Polygon" and kind in ("region", "kingdom"):
        return _Item("regions", kind, name, geometry, dm_notes)
    warn[f"The features of kind {raw_kind or '(none)'!r} ({gtype}) were left out: they map to no Delve kind."] += 1
    return None


def _points(coords: Any) -> Iterator[tuple[float, float]]:
    if isinstance(coords, list) and len(coords) >= 2 and _number(coords[0]) and _number(coords[1]):
        yield (float(coords[0]), float(coords[1]))
    elif isinstance(coords, list):
        for c in coords:
            yield from _points(c)


def _transform(coords: Any, fn: Any) -> Any:
    if isinstance(coords, list) and len(coords) >= 2 and _number(coords[0]) and _number(coords[1]):
        return list(fn(float(coords[0]), float(coords[1])))
    return [_transform(c, fn) for c in coords]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def _unique(base: str, seen: set[str]) -> str:
    fid, n = base, 1
    while fid in seen:
        n += 1
        fid = f"{base}-{n}"
    seen.add(fid)
    return fid


def _factor(scale: Scale, items: list[_Item], width: float) -> float:
    if scale.known is not None:
        a, b, km = scale.known
        found: dict[str, tuple[float, float]] = {}
        for item in items:
            if item.layer == "places":
                found.setdefault(item.name.casefold(), next(_points(item.geometry["coordinates"])))
        missing = [n for n in (a, b) if n.casefold() not in found]
        if missing:
            raise GeoMapError("The known distance names places that aren't on the map.", [f"no place {n!r}" for n in missing])  # fmt: skip
        apart = math.dist(found[a.casefold()], found[b.casefold()])
        if apart == 0 or not (_number(km) and km > 0):
            raise GeoMapError("The known distance can't scale the map.", [f"{a} and {b} must be apart, by over 0 km"])
        return km / apart
    if not (_number(scale.width_km) and scale.width_km and scale.width_km > 0):
        raise GeoMapError("The map's width can't scale it.", ["width_km must be over 0"])
    return scale.width_km / width


def _from_foreign(doc: Mapping[str, Any], mapping: PropertyMapping, scale: Scale | None) -> Imported:
    raw_features = _raw_features(doc)
    properties = sorted({k for f in raw_features for k in (f.get("properties") or {})})
    kinds = sorted({str(v) for f in raw_features if (v := (f.get("properties") or {}).get(mapping.kind)) is not None})
    if scale is None or (scale.width_km is None and scale.known is None):
        return Imported(None, [], needs_scale=True, properties=properties, kinds=kinds)

    azgaar = is_azgaar(doc)
    warn: Counter[str] = Counter()
    items: list[_Item] = []
    for f in raw_features:
        props = f.get("properties") or {}
        for part in _parts(f.get("geometry")):
            item = _azgaar_item(props, part, warn) if azgaar else _mapped_item(props, part, mapping, warn)
            if item is not None:
                items.append(item)
    coords = [p for item in items for p in _points(item.geometry["coordinates"])]
    if not coords:
        raise GeoMapError("The file holds nothing Delve can put on a map.", list(warn))
    x0, x1 = min(p[0] for p in coords), max(p[0] for p in coords)
    y0, y1 = min(p[1] for p in coords), max(p[1] for p in coords)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        raise GeoMapError("The map has no area.", ["its features lie on one line"])
    k = _factor(scale, items, x1 - x0)
    frame = Frame((x1 - x0) * k, (y1 - y0) * k)
    grid = default_grid(frame)

    def to_km(x: float, y: float) -> tuple[float, float]:
        return ((x - x0) * k, (y1 - y) * k)  # y flipped: it grows down

    letters = [TERRAIN_LETTERS["plains"]] * grid.cells
    features: list[GeoFeature] = []
    seen: set[str] = set()
    for item in items:
        geometry = {"type": item.geometry["type"], "coordinates": _transform(item.geometry["coordinates"], to_km)}
        if item.layer == "terrain":
            for i in cells_in_area(grid, geometry["coordinates"]):
                letters[i] = TERRAIN_LETTERS[item.kind]
            continue
        fid = _unique(_slug(item.name) or item.kind, seen)
        features.append(
            GeoFeature(fid, item.layer, item.kind, item.name, geometry, dm_notes=item.dm_notes, tags=item.tags)
        )
    geo = water_from_areas(GeoMap(frame, grid, "".join(letters), tuple(features)))
    warnings = [w if n == 1 else f"{w} ({n}×)" for w, n in warn.items()]
    return Imported(geo, warnings, properties=properties, kinds=kinds)


def from_geojson(
    doc: Mapping[str, Any], *, mapping: PropertyMapping | None = None, scale: Scale | None = None
) -> Imported:
    """The geo map of `doc`. A Delve document (it has `delve`) reads back exactly, and raises `GeoMapError` with its
    problems when it doesn't hold together. A foreign one is read through `mapping` (Azgaar's maps itself) and scaled
    by `scale`; without one, it answers `needs_scale` and no map."""
    if not isinstance(doc, Mapping) or doc.get("type") != "FeatureCollection":
        raise GeoMapError("A world map is a GeoJSON FeatureCollection.", ["the document isn't one"])
    if "delve" in doc:
        return _from_delve(dict(doc))
    return _from_foreign(doc, mapping or PropertyMapping(), scale)
