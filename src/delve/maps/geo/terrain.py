"""The words of a geo map: its terrain classes, each with a letter and Delve's own colour, and the kinds of its
features per layer."""

from __future__ import annotations

TERRAIN_CLASSES = (
    "plains",
    "forest",
    "hills",
    "mountain",
    "swamp",
    "desert",
    "arctic",
    "jungle",
    "urban",
    "sea",
    "lake",
    "impassable",
)

TERRAIN_LETTERS: dict[str, str] = {
    "plains": "p",
    "forest": "f",
    "hills": "h",
    "mountain": "m",
    "swamp": "s",
    "desert": "d",
    "arctic": "a",
    "jungle": "j",
    "urban": "u",
    "sea": "w",
    "lake": "l",
    "impassable": "x",
}
"""One letter per class, as `GeoMap.terrain` holds them. `NO_TERRAIN` is a cell without one (unknown or unread)."""

NO_TERRAIN = "."

TERRAIN_OF_LETTER: dict[str, str] = {letter: name for name, letter in TERRAIN_LETTERS.items()}

TERRAIN_COLOURS: dict[str, str] = {
    "plains": "#c9b870",
    "forest": "#2d5a2d",
    "hills": "#8a7350",
    "mountain": "#6e6e6e",
    "swamp": "#4a6b3a",
    "desert": "#d4a25a",
    "arctic": "#dcdcd2",
    "jungle": "#2d5a3a",
    "urban": "#9a8a7a",
    "sea": "#2d5f8f",
    "lake": "#3a6da3",
    "impassable": "#3a3030",
}
"""Delve's colour per class; the land colours are plateau 6's biome styles."""

PLACE_KINDS = ("city", "town", "village", "castle", "ruin", "dungeon", "port", "other")
ROUTE_KINDS = ("road", "track", "trail")
WATER_KINDS = ("river", "lake", "sea")
LAYERS = ("places", "routes", "water", "regions")

LAYER_KINDS: dict[str, tuple[str, ...] | None] = {
    "places": PLACE_KINDS,
    "routes": ROUTE_KINDS,
    "water": WATER_KINDS,
    "regions": None,
}
"""The kinds each layer allows; a region's kind (`kingdom`, `region`, …) is free."""

LAYER_GEOMETRIES: dict[str, tuple[str, ...]] = {
    "places": ("Point",),
    "routes": ("LineString",),
    "water": ("LineString", "Polygon"),
    "regions": ("Polygon",),
}
"""The geometry each layer allows: a river is a line from its source to its mouth, a lake or a sea an area."""
