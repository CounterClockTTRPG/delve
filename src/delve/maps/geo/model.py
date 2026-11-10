"""The geo map: a frame in km, a grid of terrain cells, layers of features and an optional base picture.

Coordinates are km from the frame's top left, x growing east and y growing down (south), as a picture's pixels do. A
feature's `geometry` is a GeoJSON geometry in those coordinates: a place is a `Point`, a route a `LineString`, a river a
`LineString` from its source to its mouth (downstream is the line's direction), a lake, a sea or a region a `Polygon`.

Treat a `GeoMap` as read-only: its methods are lookups, and `water_from_areas` answers a new one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from delve.maps.geo.terrain import TERRAIN_LETTERS, TERRAIN_OF_LETTER

Point = tuple[float, float]


class GeoMapError(Exception):
    """A document that doesn't hold together: a `message`, and each `problems` found."""

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        self.message = message
        self.problems = list(problems or [])
        super().__init__(f"{message}: {'; '.join(self.problems)}" if self.problems else message)


@dataclass(frozen=True)
class Frame:
    width_km: float
    height_km: float
    units: Literal["km", "miles"] = "km"
    """What distances are shown in; the map itself is always in km."""


@dataclass(frozen=True)
class Grid:
    """The terrain cells, numbered row-major from the top left.

    `size_km` is the distance between the centres of two neighbouring cells (a square's side; a hex's width across
    its flats, so "1 hex = 30 miles" is a `size_km` of 30 miles). Pointy hexes sit in rows, the odd rows offset half a
    hex east; flat hexes sit in columns, the odd columns offset half a hex south. `origin` is the top left of the
    grid's first cell's bounding box."""

    kind: Literal["hex", "square"]
    size_km: float
    cols: int
    rows: int
    origin: tuple[float, float] = (0.0, 0.0)
    orientation: Literal["pointy", "flat"] = "pointy"

    @property
    def cells(self) -> int:
        return self.cols * self.rows


@dataclass(frozen=True)
class GeoFeature:
    id: str
    layer: str
    """One of `terrain.LAYERS`."""
    kind: str
    name: str
    geometry: dict[str, Any]
    description: str = ""
    """What the characters may learn of it."""
    dm_notes: str = ""
    """The DM's alone: never shown to a seat."""
    tags: tuple[str, ...] = ()
    hidden: bool = False
    props: Mapping[str, Any] = field(default_factory=dict)
    """The layer's own: a river's `navigable_km` (from its mouth) and `barrier`, a route's `surface`, a reading's
    `doubt`."""


@dataclass(frozen=True)
class PictureRef:
    id: str
    """The `world_pictures` id: the original's sha256."""
    width_px: int
    height_px: int
    km_per_px: float
    asset: str | None = None
    """The `.dscn` asset that carries it, in an exported module."""


@dataclass(frozen=True)
class GeoMap:
    frame: Frame
    grid: Grid
    terrain: str
    """One letter per cell, row-major (`terrain.TERRAIN_LETTERS`; `.` for none)."""
    features: tuple[GeoFeature, ...]
    picture: PictureRef | None = None
    _by_id: dict[str, GeoFeature] = field(default_factory=dict, init=False, repr=False, compare=False)
    _by_name: dict[str, list[GeoFeature]] = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for f in self.features:
            self._by_id.setdefault(f.id, f)
            self._by_name.setdefault(f.name.casefold(), []).append(f)

    def feature(self, ref: str) -> GeoFeature | None:
        """The feature whose id is `ref`, else the one whose name is `ref` in any case. None when there is none, or
        when several share the name (`features_named` answers them)."""
        found = self._by_id.get(ref)
        if found is not None:
            return found
        named = self._by_name.get(ref.casefold(), [])
        return named[0] if len(named) == 1 else None

    def features_named(self, ref: str) -> list[GeoFeature]:
        """Every feature whose name is `ref` in any case: the candidates for an ambiguous ref."""
        return list(self._by_name.get(ref.casefold(), []))

    def terrain_of(self, cell: int) -> str | None:
        """The terrain class of `cell`; None for a cell without one or off the grid."""
        if not 0 <= cell < len(self.terrain):
            return None
        return TERRAIN_OF_LETTER.get(self.terrain[cell])


_WATER_LETTERS = {"sea": TERRAIN_LETTERS["sea"], "lake": TERRAIN_LETTERS["lake"]}


def _water_cells(geo: GeoMap) -> dict[int, str]:
    from delve.maps.geo.grid import cells_in_area

    cells: dict[int, str] = {}
    for f in geo.features:
        if f.layer == "water" and f.kind in _WATER_LETTERS and f.geometry.get("type") == "Polygon":
            for i in cells_in_area(geo.grid, f.geometry["coordinates"]):
                cells[i] = _WATER_LETTERS[f.kind]
    return cells


def water_from_areas(geo: GeoMap, previous: GeoMap | None = None) -> GeoMap:
    """`geo` with its cells kept to its water areas: a cell whose centre lies in a sea or a lake area becomes sea or
    lake. With `previous` (the stored map, on a save), a sea or lake cell that lay in one of its water areas and lies in
    none now becomes plains, so reshaping a lake moves its cells. Water painted outside any area stays as painted."""
    letters = list(geo.terrain)
    if previous is not None and previous.grid == geo.grid:
        water = set(_WATER_LETTERS.values())
        for i in _water_cells(previous):
            if i < len(letters) and letters[i] in water:
                letters[i] = TERRAIN_LETTERS["plains"]
    for i, letter in _water_cells(geo).items():
        if i < len(letters):
            letters[i] = letter
    terrain = "".join(letters)
    return geo if terrain == geo.terrain else replace(geo, terrain=terrain)
