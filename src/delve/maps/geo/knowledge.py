"""What the party knows of a world map, and the seat's and the DM's view of it.

A `WorldKnowledge` is everything, or the grid cells the party knows and the features it knows by id; `forgotten` are
the features the DM made it forget. Knowing a cell is knowing what is printed in it: its terrain, the places in it and
the parts of the roads, rivers and regions that cross it. A `hidden` feature is known only by its id.

The seat's view is cut from that knowledge here, on the server: a seat never gets an unknown cell's terrain, a feature
or the part of a line outside the known cells, a hidden feature it doesn't know, `dm_notes`, `props` or the picture's
id. When in doubt, a seat sees less.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import replace
from functools import lru_cache
from typing import Any, Literal, NamedTuple

import shapely
import shapely.errors
import shapely.geometry
import shapely.ops

from delve.domain.world import Journey, WorldKnowledge
from delve.maps.geo.grid import cell_at, cell_polygon, cells_in_area, cells_in_polygon, cells_within
from delve.maps.geo.model import GeoFeature, GeoMap, Grid, Point
from delve.maps.geo.terrain import NO_TERRAIN

SIGHT_KM = 10.0
"""How far the party sees around it as it travels."""

SIGHT_FACTOR = {"hills": 2.0, "mountain": 3.0}
"""How much farther it sees from the cell it stands in, by its terrain."""

SEAT_PICTURE_KEYS = ("width_px", "height_px", "km_per_px", "max_zoom")
"""What a seat gets of the picture: enough to place its tiles, never its id."""

StartHow = Literal["everything", "nothing", "regions", "area"]


class KnowledgeError(ValueError):
    """A start that can't be worked out: an unknown region, or an area of fewer than three points."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class Revealed(NamedTuple):
    knowledge: WorldKnowledge
    places: list[str]
    """The names of the places that became visible, in the map's order."""


# --- what is known ---------------------------------------------------------------------------------------------------


def known_cells(geo: GeoMap, known: WorldKnowledge) -> frozenset[int]:
    """The cells the party knows: every cell when it knows everything."""
    if known.everything:
        return frozenset(range(geo.grid.cells))
    return frozenset(c for c in known.cells if 0 <= c < geo.grid.cells)


@lru_cache(maxsize=32)
def _union(grid: Grid, cells: frozenset[int]) -> shapely.Geometry:
    """The area of `cells`. The cells are snapped to a fine grid first, so that neighbours share their corners and the
    union leaves no slivers between them."""
    if not cells:
        return shapely.Polygon()
    polygons = shapely.set_precision(
        [shapely.Polygon(cell_polygon(grid, i)) for i in sorted(cells)], grid.size_km * 1e-6
    )
    area = shapely.coverage_union_all(polygons)
    if not area.is_valid:
        area = shapely.union_all(polygons, grid_size=grid.size_km * 1e-6)
    return area


def _point_of(f: GeoFeature) -> Point | None:
    if f.geometry.get("type") != "Point":
        return None
    try:
        x, y = f.geometry["coordinates"][:2]
        return (float(x), float(y))
    except (KeyError, TypeError, ValueError):
        return None


def _shape(geometry: dict[str, Any]) -> shapely.Geometry | None:
    try:
        shape = shapely.geometry.shape(geometry)
    except (AttributeError, KeyError, TypeError, ValueError, shapely.errors.GEOSException):
        return None
    if not shape.is_valid:
        shape = shapely.make_valid(shape)
    return None if shape.is_empty else shape


def _lists(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [_lists(v) for v in value]
    return float(value)


def _geometry(shape: shapely.Geometry, dimension: int) -> dict[str, Any] | None:
    """The GeoJSON geometry of the parts of `shape` of that dimension (0 points, 1 lines, 2 areas), dropping the
    lower-dimensional bits a clip leaves where a line only touches the edge; None when nothing is left."""
    parts = [p for p in shapely.get_parts(shape) if shapely.get_dimensions(p) == dimension and not p.is_empty]
    if not parts:
        return None
    if len(parts) == 1:
        one = parts[0]
    else:
        one = {0: shapely.MultiPoint, 1: shapely.MultiLineString, 2: shapely.MultiPolygon}[dimension](parts)
    mapped = shapely.geometry.mapping(one)
    return {"type": mapped["type"], "coordinates": _lists(mapped["coordinates"])}


def _clipped(f: GeoFeature, geo: GeoMap, cells: frozenset[int]) -> GeoFeature | None:
    """`f` as far as it lies in `cells`; None when nothing of it does."""
    point = _point_of(f)
    if point is not None:
        return f if cell_at(geo.grid, *point) in cells else None
    shape = _shape(f.geometry)
    if shape is None or not cells:
        return None
    area = _union(geo.grid, cells)
    if shapely.covers(area, shape):
        return f
    try:
        inside = shapely.intersection(shape, area)
    except shapely.errors.GEOSException:
        return None
    geometry = _geometry(inside, shapely.get_dimensions(shape))
    return None if geometry is None else replace(f, geometry=geometry)


def _seen(f: GeoFeature, known: WorldKnowledge) -> bool | None:
    """Whether `f` shows by the knowledge alone: False never, True whole, None as far as it lies in the known cells."""
    if f.id in known.forgotten:
        return False
    if f.id in known.features:
        return True
    if f.hidden:
        return False
    return True if known.everything else None


def visible_features(geo: GeoMap, known: WorldKnowledge) -> list[GeoFeature]:
    """The features the party knows, in the map's order.

    Never a forgotten one; a known one whole; a hidden one only when known; every other one when the party knows
    everything; else a point in a known cell, and a line or an area clipped to the known cells, dropped when nothing
    of it is left."""
    cells = known_cells(geo, known)
    out = []
    for f in geo.features:
        seen = _seen(f, known)
        if seen is None:
            clipped = _clipped(f, geo, cells)
            if clipped is not None:
                out.append(clipped)
        elif seen:
            out.append(f)
    return out


def _runs(cells: Iterable[int]) -> list[list[int]]:
    """Cell numbers as sorted half-open runs, as `WorldKnowledge` stores them."""
    return WorldKnowledge(cells=tuple(cells)).to_dict()["cells"]


# --- the views -------------------------------------------------------------------------------------------------------


def _frame_and_grid(geo: GeoMap) -> dict[str, Any]:
    grid = geo.grid
    return {
        "units": geo.frame.units,
        "frame": {"width_km": geo.frame.width_km, "height_km": geo.frame.height_km},
        "grid": {
            "kind": grid.kind,
            "size_km": grid.size_km,
            "cols": grid.cols,
            "rows": grid.rows,
            "origin": list(grid.origin),
            "orientation": grid.orientation,
        },
    }


def _point_out(point: Point | None) -> list[float] | None:
    return None if point is None else [float(point[0]), float(point[1])]


def _line_ahead_of_unknown(points: Sequence[Point], area: shapely.Geometry) -> list[list[float]]:
    """The journey's line from its start up to where it first leaves the known area; nothing when it starts outside."""
    if len(points) < 2 or area.is_empty:
        return []
    line = shapely.LineString(points)
    if line.length == 0:
        return []
    outside = shapely.difference(line, area)
    if outside.is_empty:
        return [_point_out(p) for p in points]
    ends = [shapely.Point(part.coords[0]) for part in shapely.get_parts(outside) if part.geom_type == "LineString"]
    if not ends:
        return [_point_out(p) for p in points]
    cut = min(line.project(end) for end in ends)
    if cut <= 0:
        return []
    return _lists(list(shapely.ops.substring(line, 0, cut).coords))


def _feature_out(f: GeoFeature) -> dict[str, Any]:
    return {
        "id": f.id,
        "layer": f.layer,
        "kind": f.kind,
        "name": f.name,
        "description": f.description,
        "geometry": f.geometry,
        "tags": [t for t in f.tags if t != "hidden"],
    }


def seat_view(
    geo: GeoMap,
    known: WorldKnowledge,
    *,
    name: str,
    title: str,
    party: Point | None,
    journey: Journey | None,
    picture: dict[str, Any] | None,
    tiles_version: str,
) -> dict[str, Any]:
    """What a seat sees of the map: the known cells, their terrain (`.` in every unknown cell), the visible features
    without `dm_notes`, `hidden` or `props`, the party, and the journey's line as far as it runs in known land, with
    the destination's name only once that place is visible. Of the picture, only `SEAT_PICTURE_KEYS`."""
    cells = known_cells(geo, known)
    features = visible_features(geo, known)
    terrain = (
        geo.terrain if known.everything else "".join(t if i in cells else NO_TERRAIN for i, t in enumerate(geo.terrain))
    )
    journey_out = None
    if journey is not None:
        shown = {f.id for f in features}
        destination = geo.feature(journey.to)
        journey_out = {
            "mode": journey.mode,
            "to_label": journey.to_label if destination is not None and destination.id in shown else None,
            "points": _line_ahead_of_unknown(journey.points, _union(geo.grid, cells)),
            "done_km": journey.done_km,
            "km": journey.km,
        }
    return {
        "name": name,
        "title": title,
        **_frame_and_grid(geo),
        "picture": None if picture is None else {k: picture[k] for k in SEAT_PICTURE_KEYS if k in picture},
        "tiles_version": tiles_version,
        "known": {"all": known.everything, "cells": _runs(cells)},
        "terrain": terrain,
        "features": [_feature_out(f) for f in features],
        "party": _point_out(party),
        "journey": journey_out,
    }


def dm_view(
    geo: GeoMap,
    known: WorldKnowledge,
    *,
    name: str,
    title: str,
    party: Point | None,
    journey: Journey | None,
    picture: dict[str, Any] | None,
) -> dict[str, Any]:
    """The whole map for the DM: every feature whole, with its `dm_notes`, `hidden`, `props` and whether the party
    knows it (`known`), the whole terrain, the known cells, the journey whole and the picture as given."""
    shown = {f.id for f in visible_features(geo, known)}
    return {
        "name": name,
        "title": title,
        **_frame_and_grid(geo),
        "picture": picture,
        "known": {"all": known.everything, "cells": _runs(known_cells(geo, known))},
        "terrain": geo.terrain,
        "features": [
            {
                **_feature_out(f),
                "tags": list(f.tags),
                "dm_notes": f.dm_notes,
                "hidden": f.hidden,
                "props": dict(f.props),
                "known": f.id in shown,
            }
            for f in geo.features
        ],
        "party": _point_out(party),
        "journey": None if journey is None else journey.to_dict(),
    }


# --- setting and changing it -----------------------------------------------------------------------------------------


def _region_cells(geo: GeoMap, ref: str) -> list[int]:
    regions = [f for f in geo.features if f.layer == "regions"]
    found = [f for f in regions if f.id == ref] or [f for f in regions if f.name.casefold() == ref.casefold()]
    if not found:
        raise KnowledgeError(f"There is no region {ref!r} on this map.")
    if len(found) > 1:
        raise KnowledgeError(
            f"Several regions are named {ref!r}: name one by its id ({', '.join(f.id for f in found)})."
        )
    geometry = found[0].geometry
    if geometry.get("type") == "Polygon":
        return cells_in_area(geo.grid, geometry["coordinates"])
    if geometry.get("type") == "MultiPolygon":
        return [i for rings in geometry["coordinates"] for i in cells_in_area(geo.grid, rings)]
    return []


def start(geo: GeoMap, how: StartHow, *, regions: Sequence[str] = (), ring: Sequence[Point] = ()) -> WorldKnowledge:
    """What the party knows at the start: everything, nothing, the cells of some regions (their roads come with them,
    clipped), or the cells of an area drawn as a ring."""
    if how == "everything":
        return WorldKnowledge(everything=True)
    if how == "nothing":
        return WorldKnowledge()
    if how == "regions":
        return WorldKnowledge(cells=tuple(sorted({i for ref in regions for i in _region_cells(geo, ref)})))
    if how == "area":
        if len(ring) < 3:
            raise KnowledgeError("An area needs at least three points.")
        return WorldKnowledge(cells=tuple(sorted(cells_in_polygon(geo.grid, ring))))
    raise KnowledgeError(f"Unknown start {how!r}: everything, nothing, regions or area.")


def _with_cells(known: WorldKnowledge, cells: Iterable[int]) -> WorldKnowledge:
    cells = tuple(sorted(set(cells)))
    return known if cells == known.cells else replace(known, cells=cells)


def _visible_place_ids(geo: GeoMap, known: WorldKnowledge, cells: frozenset[int]) -> set[str]:
    out = set()
    for f in geo.features:
        if f.layer != "places":
            continue
        seen = _seen(f, known)
        if seen or (seen is None and _clipped(f, geo, cells) is not None):
            out.add(f.id)
    return out


def _around(geo: GeoMap, point: Point, radius_km: float) -> set[int]:
    """The cells whose centre is within `radius_km` of `point`, and the cell it is in."""
    cells = set(cells_within(geo.grid, point, radius_km))
    here = cell_at(geo.grid, *point)
    if here is not None:
        cells.add(here)
    return cells


def _samples(points: Sequence[Point], step: float) -> list[Point]:
    """The line's points every `step` km or less, its vertices included."""
    out = [tuple(points[0])]
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        n = max(1, math.ceil(math.dist((x0, y0), (x1, y1)) / step))
        out.extend((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1))
    return out


def reveal_along(
    geo: GeoMap, known: WorldKnowledge, points: Sequence[Point], *, sight_km: float = SIGHT_KM
) -> Revealed:
    """The knowledge with the cells within sight of the line, sampled every half cell, and the names of the places
    that became visible. The sight is `sight_km`, times `SIGHT_FACTOR` of the cell each sample is in. A hidden place
    never becomes visible this way."""
    if known.everything or not points:
        return Revealed(known, [])
    before = known_cells(geo, known)
    cells = set(before)
    for point in _samples(points, geo.grid.size_km / 2):
        here = cell_at(geo.grid, *point)
        factor = SIGHT_FACTOR.get(geo.terrain_of(here) or "", 1.0) if here is not None else 1.0
        cells |= _around(geo, point, sight_km * factor)
    after = _with_cells(known, cells)
    if after is known:
        return Revealed(known, [])
    was = _visible_place_ids(geo, known, before)
    now = _visible_place_ids(geo, after, known_cells(geo, after))
    return Revealed(after, [f.name for f in geo.features if f.id in now and f.id not in was])


def reveal_feature(known: WorldKnowledge, id: str) -> WorldKnowledge:
    """The party knows the feature `id`, whole, wherever it lies; a forgotten one is remembered."""
    features = known.features if id in known.features else (*known.features, id)
    return replace(known, features=features, forgotten=tuple(f for f in known.forgotten if f != id))


def forget_feature(known: WorldKnowledge, id: str) -> WorldKnowledge:
    """The party forgets the feature `id`: it shows no more, even in known cells."""
    forgotten = known.forgotten if id in known.forgotten else (*known.forgotten, id)
    return replace(known, features=tuple(f for f in known.features if f != id), forgotten=forgotten)


def reveal_area(geo: GeoMap, known: WorldKnowledge, centre: Point, radius_km: float) -> WorldKnowledge:
    """The party knows the cells within `radius_km` of `centre` (and the one it is in)."""
    if known.everything:
        return known
    return _with_cells(known, set(known_cells(geo, known)) | _around(geo, centre, radius_km))


def forget_area(geo: GeoMap, known: WorldKnowledge, centre: Point, radius_km: float) -> WorldKnowledge:
    """The party no longer knows the cells within `radius_km` of `centre` (and the one it is in). Knowing everything
    becomes knowing every other cell. A feature it knew by id that lies in the area is let go of too, so it shows only
    as far as it lies in the cells still known: a road through the area is cut there, and a hidden place in it goes."""
    area = _around(geo, centre, radius_km)
    cells = known_cells(geo, known) - area
    shape = _union(geo.grid, frozenset(area))
    keep = []
    for id in known.features:
        f = geo.feature(id)
        if f is not None and f.id == id and _touches(f, geo, frozenset(area), shape):
            continue
        keep.append(id)
    return replace(known, everything=False, cells=tuple(sorted(cells)), features=tuple(keep))


def _touches(f: GeoFeature, geo: GeoMap, area: frozenset[int], shape: shapely.Geometry) -> bool:
    point = _point_of(f)
    if point is not None:
        return cell_at(geo.grid, *point) in area
    feature = _shape(f.geometry)
    return feature is not None and not shape.is_empty and shapely.intersects(feature, shape)
