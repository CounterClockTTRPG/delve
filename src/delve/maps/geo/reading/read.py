"""The whole reading of a map picture with its scale key, step by step: the grid, the terrain colours, the water, the
places and the routes, into a geo map in km and its review (`review.Reading`).

The CPU work runs in a thread, and `should_stop` is asked between the steps. Claude is asked once for the terrain (a
contact sheet of each colour's cells, `prompts/clusters.md`) and for the labels OCR couldn't read (`places`). The
water's colours take the water's class; every other colour starts unmapped, its cells `.`, with a doubt."""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import shapely
from PIL import Image, ImageDraw

from delve.maps.geo.grid import DEFAULT_CELLS, cell_centre, cell_polygon
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid, Point
from delve.maps.geo.reading.colours import Clusters, cluster_cells
from delve.maps.geo.reading.grid_detect import GridGuess, find_grid
from delve.maps.geo.reading.ocr import PictureOcr
from delve.maps.geo.reading.places import PlacesReading, answer_json, prompt, read_places
from delve.maps.geo.reading.review import (
    DROP,
    KEEP,
    OUTSIDE,
    REVERSE,
    ClusterReading,
    Doubt,
    Reading,
    initial,
    order_doubts,
    river_id,
)
from delve.maps.geo.reading.routes import RouteTrace, find_routes
from delve.maps.geo.reading.scale import ScaleKey
from delve.maps.geo.reading.water import Water, find_water
from delve.maps.geo.terrain import NO_TERRAIN, TERRAIN_CLASSES, TERRAIN_LETTERS
from delve.maps.vision import Look, fit_for_vision

STEPS = ("grid", "terrain", "water", "places", "routes")
SAMPLES_PER_CLUSTER = 4
_SAMPLE_PX = 96


class ReadStopped(Exception):
    """`should_stop` answered True: the reading was stopped before its next step."""


class ReadError(ValueError):
    """The picture can't be read with its key: no grid of the kind named was found."""


async def read_picture(
    image: Image.Image,
    key: ScaleKey,
    *,
    ocr: PictureOcr | None,
    look: Look,
    progress: Callable[[str, int, int], None],
    should_stop: Callable[[], bool] = lambda: False,
) -> Reading:
    key.check()

    def begin(step: str) -> None:
        if should_stop():
            raise ReadStopped(f"The reading was stopped before its {step} step.")
        progress(step, 0, 0)

    begin("grid")
    guess, km_per_px = await asyncio.to_thread(_grid, image, key)
    begin("terrain")
    clusters = await asyncio.to_thread(cluster_cells, image, guess)
    suggestions = await _suggest(image, guess, clusters, look)
    begin("water")
    water = await asyncio.to_thread(find_water, image, guess)
    begin("places")
    places = await read_places(image, guess, ocr=ocr, look=look, water=water)
    begin("routes")
    routes = await asyncio.to_thread(find_routes, image, guess, clusters, water)
    if should_stop():
        raise ReadStopped("The reading was stopped at its end.")
    return _reading(image, key, guess, km_per_px, clusters, suggestions, water, places, routes)


def _grid(image: Image.Image, key: ScaleKey) -> tuple[GridGuess, float]:
    """The picture's grid in pixels and its km per pixel."""
    if key.cell is not None:
        guess = find_grid(image, key.cell)
        if guess is None:
            raise ReadError(f"No {key.cell} grid was found in the picture: mark two points and their distance instead.")
        return guess, key.km() / guess.size_px
    assert key.points is not None  # key.check()
    width, height = image.size
    size = max(width, height) / DEFAULT_CELLS
    guess = GridGuess("square", size, (0.0, 0.0), "pointy", 1.0, math.ceil(width / size), math.ceil(height / size))
    return guess, key.km() / math.dist(*key.points)


# --- the terrain colours, with Claude's suggestion


async def _suggest(image: Image.Image, guess: GridGuess, clusters: Clusters, look: Look) -> dict[int, str]:
    if not clusters.palette:
        return {}
    sheet = _cluster_sheet(image, guess, clusters)
    lines = []
    for n, colour in enumerate(clusters.palette):
        count = clusters.cell_cluster.count(n)
        lines.append(f"- colour {n}: {_hex(colour)}, {count} cells")
    text = (
        prompt("clusters.md").replace("{classes}", ", ".join(TERRAIN_CLASSES)).replace("{clusters}", "\n".join(lines))
    )
    png, media_type = fit_for_vision(sheet)
    try:
        answer = answer_json(await look(text, png, media_type), "{")
    except Exception:  # noqa: BLE001 - without a suggestion the organiser maps the colour alone
        answer = None
    out: dict[int, str] = {}
    for raw, terrain in answer.items() if isinstance(answer, dict) else []:
        try:
            n = int(raw)
        except ValueError:
            continue
        if 0 <= n < len(clusters.palette) and terrain in (*TERRAIN_CLASSES, OUTSIDE):
            out[n] = terrain
    return out


def _cluster_sheet(image: Image.Image, guess: GridGuess, clusters: Clusters) -> Image.Image:
    """One row per colour: its number, then a few of its cells, spread over the map."""
    grid = guess.pixel_grid()
    mixed = set(clusters.mixed)
    rows = len(clusters.palette)
    step = _SAMPLE_PX + 8
    sheet = Image.new("RGB", (48 + SAMPLES_PER_CLUSTER * step, rows * step), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    half = guess.size_px / 2
    for n in range(rows):
        cells = [i for i, c in enumerate(clusters.cell_cluster) if c == n and i not in mixed]
        cells = cells or [i for i, c in enumerate(clusters.cell_cluster) if c == n]
        picked = [cells[k * len(cells) // SAMPLES_PER_CLUSTER] for k in range(min(SAMPLES_PER_CLUSTER, len(cells)))]
        y = n * step
        draw.text((8, y + _SAMPLE_PX // 2 - 6), str(n), fill=(200, 0, 0))
        for k, cell in enumerate(dict.fromkeys(picked)):
            cx, cy = cell_centre(grid, cell)
            crop = image.crop((round(cx - half), round(cy - half), round(cx + half), round(cy + half))).convert("RGB")
            sheet.paste(crop.resize((_SAMPLE_PX, _SAMPLE_PX)), (48 + k * step, y + 4))
    return sheet


def _hex(colour: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*colour)


# --- the reading


def _reading(
    image: Image.Image,
    key: ScaleKey,
    guess: GridGuess,
    kpp: float,
    clusters: Clusters,
    suggestions: dict[int, str],
    water: Water,
    places: PlacesReading,
    routes: list[RouteTrace],
) -> Reading:
    width, height = image.size
    ox, oy = guess.origin_px
    grid = Grid(guess.kind, guess.size_px * kpp, guess.cols, guess.rows, (ox * kpp, oy * kpp), guess.orientation)
    frame = Frame(width * kpp, height * kpp, key.units)

    def km(point: Point) -> list[float]:
        return [round(point[0] * kpp, 4), round(point[1] * kpp, 4)]

    terrain = [NO_TERRAIN] * grid.cells
    features: list[GeoFeature] = []
    doubts: list[Doubt] = []

    # The water bodies: their cells are certain, and an area each.
    body_of: dict[int, str] = {}
    for n, body in enumerate(water.bodies):
        for cell in body.cells:
            terrain[cell] = TERRAIN_LETTERS[body.kind]
            body_of[cell] = body.kind
        ids = []
        for k, ring in enumerate(_areas(grid, body.cells)):
            fid = f"water-{n + 1}" if k == 0 else f"water-{n + 1}-{k + 1}"
            ids.append(fid)
            features.append(GeoFeature(fid, "water", body.kind, "", {"type": "Polygon", "coordinates": ring}))
        if body.guessed and ids:
            other = "lake" if body.kind == "sea" else "sea"
            doubts.append(
                Doubt(
                    "",
                    "water-kind-guessed",
                    ids[0],
                    f"No water reaches the map's edge, so this {body.kind} is a guess.",
                    body.kind,
                    [body.kind, other],
                    data={"at": list(cell_centre(grid, body.cells[0])), "cells": list(body.cells), "features": ids},
                )
            )

    # The colours: water's colours take the water's class, the others wait for the organiser.
    cluster_readings = []
    for n, colour in enumerate(clusters.palette):
        everything = [i for i, c in enumerate(clusters.cell_cluster) if c == n]
        wet = Counter(body_of[i] for i in everything if i in body_of)
        own = [i for i in everything if i not in body_of]
        mapped = wet.most_common(1)[0][0] if everything and sum(wet.values()) >= 0.5 * len(everything) else None
        cluster_readings.append(ClusterReading(n, colour, own, suggestions.get(n), mapped))
        if mapped is None:
            suggestion = suggestions.get(n)
            choices = [*([KEEP] if suggestion else []), *_first(suggestion, TERRAIN_CLASSES), OUTSIDE]
            doubts.append(
                Doubt(
                    "",
                    "cluster-unmapped",
                    str(n),
                    f"The colour {_hex(colour)} has no terrain yet.",
                    suggestion or "",
                    choices,
                )
            )
    for cell in clusters.mixed:
        if cell in body_of:
            continue
        doubts.append(
            Doubt(
                "",
                "cell-mixed",
                f"cell:{cell}",
                "This cell has more than one colour.",
                str(clusters.cell_cluster[cell]),
                [KEEP, *TERRAIN_CLASSES, OUTSIDE],
                data={"at": list(cell_centre(grid, cell))},
            )
        )

    # The rivers, from source to mouth.
    for n, trace in enumerate(water.rivers):
        if len(trace.points_px) < 2:
            continue
        points = trace.points_px[::-1] if trace.mouth == "start" else trace.points_px
        fid = river_id(n)
        coords = [km(p) for p in points]
        features.append(GeoFeature(fid, "water", "river", "", {"type": "LineString", "coordinates": coords}))
        if trace.mouth is None:
            doubts.append(
                Doubt(
                    "",
                    "river-no-mouth",
                    fid,
                    "Neither end of this river reaches water.",
                    KEEP,
                    [KEEP, REVERSE, DROP],
                    data={"at": coords[0]},
                )
            )
        elif trace.flow_guessed:
            doubts.append(
                Doubt(
                    "",
                    "river-flow-guessed",
                    fid,
                    "Both ends of this river reach water, so which way it flows is a guess.",
                    KEEP,
                    [KEEP, REVERSE],
                    data={"at": coords[0], **({"flows": list(trace.ends)} if trace.ends else {})},
                )
            )

    # The places.
    for place in places.places:
        features.append(
            GeoFeature(place.id, "places", place.kind, place.name, {"type": "Point", "coordinates": km(place.point_px)})
        )
    for doubt in places.doubts:
        data = dict(doubt.data)
        for k in ("at", "place_at"):
            if k in data:
                data[k] = km(tuple(data[k]))  # type: ignore[arg-type]
        if "box" in data:
            x0, y0, x1, y1 = data["box"]
            data["box"] = [*km((x0, y0)), *km((x1, y1))]
        doubts.append(replace(doubt, data=data))

    # The routes, their ends at the places they reach.
    ends = [(p.point_px, p) for p in places.places]
    for k, route in enumerate(routes, start=1):
        points = list(route.points_px)
        for at in (0, -1):
            near = min(ends, key=lambda e: math.dist(e[0], points[at]), default=None)
            if near is not None and math.dist(near[0], points[at]) <= guess.size_px:
                points[at] = near[0]
        coords = [km(p) for p in points]
        features.append(
            GeoFeature(
                f"route-{k}",
                "routes",
                route.kind,
                "",
                {"type": "LineString", "coordinates": coords},
                props={"surface": route.kind},
            )
        )

    geo = GeoMap(frame, grid, "".join(terrain), tuple(features))
    return initial(geo, cluster_readings, order_doubts(doubts))


def _first(first: str | None, choices: tuple[str, ...]) -> list[str]:
    return [*([first] if first in choices else []), *(c for c in choices if c != first)]


def _areas(grid: Grid, cells: list[int]) -> list[list[list[list[float]]]]:
    """The cells' union as polygons' rings (each exterior, then its holes), in km."""
    union = shapely.union_all([shapely.Polygon(cell_polygon(grid, i)) for i in cells]).buffer(0)
    parts: list[Any] = list(union.geoms) if hasattr(union, "geoms") else [union]
    out = []
    for part in sorted(parts, key=lambda p: -p.area):
        if part.is_empty or part.geom_type != "Polygon":
            continue
        rings = [part.exterior, *part.interiors]
        out.append([[[round(x, 4), round(y, 4)] for x, y in ring.coords] for ring in rings])
    return out
