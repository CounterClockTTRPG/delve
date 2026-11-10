"""The scale key the organiser gives with a picture: one cell's distance ("1 hex = 30 miles"), or the distance between
two points picked on the picture when it has no grid. The form asks for each part; nothing here parses text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from delve.maps.geo.model import Point

KM_PER_MILE = 1.609344


@dataclass(frozen=True)
class ScaleKey:
    cell: Literal["hex", "square"] | None
    """The grid's cells, or None for a picture without a grid (then `points` carry the scale)."""
    distance: float
    """One cell's size across (a hex across its flats), or the distance between `points`."""
    units: Literal["km", "miles"]
    points: tuple[Point, Point] | None = None
    """Two points on the picture, in its pixels, `distance` apart."""

    def km(self) -> float:
        """`distance` in km."""
        return self.distance * KM_PER_MILE if self.units == "miles" else float(self.distance)

    def check(self) -> None:
        if self.cell is None and self.points is None:
            raise ValueError("a picture without a grid needs two points and their distance")
        if not self.distance > 0:
            raise ValueError("the distance must be more than 0")
        if self.points is not None and tuple(self.points[0]) == tuple(self.points[1]):
            raise ValueError("the two points must differ")
