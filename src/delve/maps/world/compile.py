"""A view of a world map, compiled: its features with their geometry and resolved style (ttrpg2's `compile_view`).

ttrpg2 wrote a GeoJSON FeatureCollection for Leaflet; Delve keeps the same content as `WorldView`, for the geometry and
the SVG. Coordinates are the author's `x,y` with y up (north), as ttrpg2's Leaflet CRS had them. A polygon keeps its
author's points: the hand-drawn roughening is the renderer's.

`scale` (miles per map unit) is new: a view sets it with `scale <n>`; it is 1 otherwise, as ttrpg2's maps were drawn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from delve.maps.world.parse import KINDS, Coord, Feature, StyleRule, View, WorldMapError, WorldModel, ident_text

Point = tuple[float, float]

BUILTIN_STYLES: list[StyleRule] = [
    StyleRule({"kind": "kingdom"}, {"color": "#888888", "fill-opacity": 0.15, "stroke": "#444", "stroke-width": 1}),
    StyleRule({"kind": "terrain"}, {"color": "#aaaaaa", "fill-opacity": 0.3, "stroke": "#666", "stroke-width": 1}),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "marsh"}, {"color": "#4a6b3a", "fill-opacity": 0.4}
    ),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "forest"}, {"color": "#2d5a2d", "fill-opacity": 0.5}
    ),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "hills"}, {"color": "#8a7350", "fill-opacity": 0.3}
    ),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "desert"}, {"color": "#d4a25a", "fill-opacity": 0.4}
    ),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "mountain"}, {"color": "#6e6e6e", "fill-opacity": 0.5}
    ),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "plains"}, {"color": "#c9b870", "fill-opacity": 0.3}
    ),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "tundra"}, {"color": "#dcdcd2", "fill-opacity": 0.5}
    ),
    StyleRule(
        {"kind": "terrain", "prop": "biome", "op": "=", "value": "jungle"}, {"color": "#2d5a3a", "fill-opacity": 0.5}
    ),
    StyleRule({"kind": "lake"}, {"color": "#3a6da3", "fill-opacity": 0.5, "stroke": "#1a4d83", "stroke-width": 1}),
    StyleRule({"kind": "river"}, {"stroke": "#3a6da3", "stroke-width": 2}),
    StyleRule({"kind": "road"}, {"stroke": "#8a6b3a", "stroke-width": 2}),
    StyleRule({"kind": "city"}, {"marker": "circle", "color": "#222222", "marker-size": 6}),
    StyleRule({"kind": "poi"}, {"marker": "pin", "color": "#bb0000", "marker-size": 8}),
    StyleRule({"kind": "building"}, {"color": "#7B5C3A", "fill-opacity": 0.6, "stroke": "#3a2a1a", "stroke-width": 1}),
    StyleRule({"kind": "street"}, {"stroke": "#aaaaaa", "stroke-width": 2}),
    StyleRule({"kind": "room"}, {"color": "#d8d4c8", "fill-opacity": 0.7, "stroke": "#444", "stroke-width": 1}),
    StyleRule({"kind": "passage"}, {"stroke": "#666666", "stroke-width": 2}),
]
"""ttrpg2's built-in styles: the first layer of the cascade (built-in, workspace, view; the last match wins)."""

INCLUDE_KINDS = {
    "kingdoms": "kingdom",
    "cities": "city",
    "roads": "road",
    "rivers": "river",
    "lakes": "lake",
    "terrain": "terrain",
    "poi": "poi",
    "buildings": "building",
    "streets": "street",
    "dungeons": "dungeon",
    "rooms": "room",
    "passages": "passage",
}
"""A view's `include` words, plural, and the kinds they name."""

_GEOMETRY_PROPS = {"at", "size", "polygon", "points", "via"}


@dataclass(frozen=True)
class WorldFeature:
    kind: str
    name: str
    """Its identifier; a passage's is `passage-<n>`."""
    geometry: str
    """`Point`, `LineString` or `Polygon` (a closed ring)."""
    coords: tuple[Point, ...]
    properties: dict[str, Any]
    """Its other properties: `description`, `doc`, `pop`, `biome`, `surface`, `from`, `to`… A DSL `kind` is
    `category`. `description` and `doc` are the DM's: never show them to the players."""
    style: dict[str, Any]
    tags: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """What the map calls it: its `label`, else its name in words (`castle-of-bones` is "Castle Of Bones")."""
        label = self.properties.get("label")
        if isinstance(label, str) and label:
            return label
        return re.sub(r"\b\w", lambda m: m.group().upper(), self.name.replace("-", " "))

    @property
    def hidden(self) -> bool:
        """Tagged `hidden`: the players don't see it until the DM reveals it."""
        return "hidden" in self.tags

    @property
    def at(self) -> Point | None:
        return self.coords[0] if self.geometry == "Point" else None


@dataclass(frozen=True)
class WorldView:
    name: str
    workspace: str
    scope: str
    units: str
    """`miles` unless the view says otherwise."""
    scale: float
    """Map units to `units`: 1 unless the view sets `scale`."""
    kinds: frozenset[str]
    features: tuple[WorldFeature, ...]
    _by_name: dict[str, WorldFeature] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._by_name.update({f.name: f for f in self.features})

    def feature(self, name: str) -> WorldFeature | None:
        return self._by_name.get(name)


def _matches(selector: dict[str, Any], feat: Feature) -> bool:
    if "tag" in selector:
        return selector["tag"] in (feat.get("tags") or [])
    if selector.get("kind") != feat.kind:
        return False
    if "prop" not in selector:
        return True
    value = feat.get_one(selector["prop"])
    if value is None:
        return False
    op, target = selector["op"], selector["value"]
    try:
        if op == "=":
            return bool(value == target)
        if op == "!=":
            return bool(value != target)
        a, b = float(value), float(target)
    except (TypeError, ValueError):
        return False
    return {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}.get(op, False)


def _style(feat: Feature, view: View, ws: WorldModel) -> dict[str, Any]:
    style: dict[str, Any] = {}
    for layer in (BUILTIN_STYLES, ws.styles, view.styles):
        for rule in layer:
            if _matches(rule.selector, feat):
                style.update(rule.attrs)
    return style


def _pt(c: Coord) -> Point:
    return (c.x, c.y)


def _ring(points: list[Coord]) -> tuple[Point, ...]:
    ring = [_pt(p) for p in points]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return tuple(ring)


def _rect(at: Coord, size: Coord) -> tuple[Point, ...]:
    x, y, w, h = at.x, at.y, size.x, size.y
    return ((x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y))


def _room_centre(room: Feature) -> Point | None:
    at, size = room.get_one("at"), room.get_one("size")
    if isinstance(at, Coord) and isinstance(size, Coord):
        return (at.x + size.x / 2, at.y + size.y / 2)
    poly = room.get("polygon")
    if poly:
        return (sum(p.x for p in poly) / len(poly), sum(p.y for p in poly) / len(poly))
    return None


def _geometry(feat: Feature, ws: WorldModel, scope_index: dict[str, Feature]) -> tuple[str, tuple[Point, ...]] | None:
    k = feat.kind
    if k in ("city", "poi"):
        c = feat.get_one("at")
        if isinstance(c, Coord):
            return "Point", (_pt(c),)
    elif k in ("building", "room"):
        poly = feat.get("polygon")
        if poly:
            return "Polygon", _ring(poly)
        at, size = feat.get_one("at"), feat.get_one("size")
        if isinstance(at, Coord) and isinstance(size, Coord):
            return "Polygon", _rect(at, size)
    elif k == "road":
        line: list[Point] = []
        ends = [ws.index.get(ident_text(feat.get_one(end))) if feat.get_one(end) else None for end in ("from", "to")]
        if ends[0] is not None and isinstance(ends[0].get_one("at"), Coord):
            line.append(_pt(ends[0].get_one("at")))
        line.extend(_pt(v) for v in feat.get("via", []) or [] if isinstance(v, Coord))
        if ends[1] is not None and isinstance(ends[1].get_one("at"), Coord):
            line.append(_pt(ends[1].get_one("at")))
        if len(line) >= 2:
            return "LineString", tuple(line)
    elif k == "passage":
        a = scope_index.get(ident_text(feat.get_one("from"))) if feat.get_one("from") else None
        b = scope_index.get(ident_text(feat.get_one("to"))) if feat.get_one("to") else None
        if a and b:
            ac, bc = _room_centre(a), _room_centre(b)
            if ac and bc:
                return "LineString", (ac, bc)
    elif k in ("river", "street"):
        pts = feat.get("points")
        if pts:
            return "LineString", tuple(_pt(c) for c in pts)
    elif k in ("kingdom", "terrain", "lake"):
        pts = feat.get("polygon")
        if pts:
            return "Polygon", _ring(pts)
    return None


def _properties(feat: Feature) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for prop in feat.properties.values():
        if prop.name in _GEOMETRY_PROPS or prop.name == "tags":
            continue
        name = "category" if prop.name == "kind" else prop.name
        values = [_pt(v) if isinstance(v, Coord) else v if isinstance(v, (int, float, str)) else ident_text(v)
                  for v in prop.values]  # fmt: skip
        out[name] = values[0] if len(values) == 1 else (values or True)
    return out


def _scope(ws: WorldModel, view: View) -> tuple[str, list[Feature], dict[str, Feature]]:
    scope_p = view.properties.get("scope")
    scope_id = ident_text(scope_p.values[0]) if scope_p and scope_p.values else ws.name
    if scope_id == ws.name:
        return scope_id, ws.model, ws.index
    target = ws.index.get(scope_id)
    if target is None:
        return scope_id, [], {}
    idx: dict[str, Feature] = {}
    for c in target.children:
        if c.name:
            idx[c.name] = c
            idx[f"{scope_id}.{c.name}"] = c
    return scope_id, target.children, idx


def _number(view: View, prop: str, default: float) -> float:
    p = view.properties.get(prop)
    if p is None or not p.values:
        return default
    try:
        value = float(p.values[0])
    except (TypeError, ValueError):
        raise WorldMapError(p.line, f"view {view.name!r}: {prop} must be a number") from None
    if value <= 0:
        raise WorldMapError(p.line, f"view {view.name!r}: {prop} must be more than 0")
    return value


def compile_view(model: WorldModel, view: str | None = None) -> WorldView:
    """The view `view` of `model`; its first view when None, and a view of the whole workspace when it has none.
    Raises `WorldMapError` for a view it doesn't have."""
    if view is None:
        chosen = model.views[0] if model.views else View(name=model.name)
    else:
        found = next((v for v in model.views if v.name == view), None)
        if found is None:
            names = ", ".join(v.name for v in model.views) or "none"
            raise WorldMapError(None, f"no view {view!r} in {model.name!r} (its views: {names})")
        chosen = found
    scope, features, scope_index = _scope(model, chosen)
    inc = chosen.properties.get("include")
    kinds = frozenset(INCLUDE_KINDS.get(v, v) for v in inc.values) if inc and inc.values else KINDS
    units_p = chosen.properties.get("units")
    units = str(units_p.values[0]) if units_p and units_p.values else "miles"

    out: list[WorldFeature] = []
    passages = 0
    for f in features:
        if f.kind not in kinds:
            continue
        geom = _geometry(f, model, scope_index)
        if geom is None:
            continue
        name = f.name
        if not name:
            passages += 1
            name = f"passage-{passages}"
        tags = tuple(str(t) for t in f.get("tags") or [])
        out.append(WorldFeature(f.kind, name, geom[0], geom[1], _properties(f), _style(f, chosen, model), tags))
    return WorldView(
        name=chosen.name,
        workspace=model.name,
        scope=scope,
        units=units,
        scale=_number(chosen, "scale", 1.0),
        kinds=kinds,
        features=tuple(out),
    )
