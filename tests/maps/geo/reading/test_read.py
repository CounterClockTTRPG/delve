"""The whole reading: a picture and its scale key into a geo map in km and its review."""

import asyncio
import json
import math

import pytest

from delve.maps.geo.geojson import from_geojson, to_geojson
from delve.maps.geo.grid import DEFAULT_CELLS
from delve.maps.geo.reading.read import STEPS, ReadError, ReadStopped, read_picture
from delve.maps.geo.reading.review import Reading
from delve.maps.geo.reading.scale import ScaleKey
from delve.maps.geo.terrain import TERRAIN_LETTERS
from tests.maps.geo.pictures import fake_look, fake_ocr, hex_map

THIRTY_MILES = ScaleKey("hex", 30, "miles")


def _read(synthetic, key=THIRTY_MILES, **kwargs):
    kwargs.setdefault("ocr", fake_ocr(synthetic.truth))
    kwargs.setdefault("look", fake_look(synthetic.truth))
    kwargs.setdefault("progress", lambda step, done, total: None)
    return asyncio.run(read_picture(synthetic.image, key, **kwargs))


def test_one_hex_of_thirty_miles_is_a_grid_of_48_28_km():
    synthetic = hex_map()
    reading = _read(synthetic)
    grid, truth = reading.geo.grid, synthetic.truth.grid
    assert grid.kind == "hex" and grid.orientation == "pointy"
    assert grid.size_km == pytest.approx(48.28032)
    assert (grid.cols, grid.rows) == (truth.cols, truth.rows)
    km_per_px = 48.28032 / truth.size_km
    assert grid.origin[0] == pytest.approx(truth.origin[0] * km_per_px, rel=0.02)
    assert reading.geo.frame.width_km == pytest.approx(synthetic.image.width * km_per_px, rel=0.01)
    assert reading.geo.frame.units == "miles"


def test_each_steps_progress_is_reported_in_order():
    heard = []
    _read(hex_map(), progress=lambda step, done, total: heard.append(step))
    assert heard == list(STEPS) == ["grid", "terrain", "water", "places", "routes"]


def test_a_stop_is_heard_between_the_steps():
    heard = []
    asked = iter([False, False, True])
    with pytest.raises(ReadStopped):
        _read(hex_map(), progress=lambda step, done, total: heard.append(step), should_stop=lambda: next(asked))
    assert heard == ["grid", "terrain"]


def test_the_places_rivers_water_and_road_are_on_the_map_in_km():
    synthetic = hex_map()
    truth = synthetic.truth
    reading = _read(synthetic)
    geo = reading.geo
    km_per_px = geo.grid.size_km / truth.grid.size_km
    for true in truth.places:
        place = geo.feature(true.name)
        assert place is not None and place.layer == "places"
        x, y = place.geometry["coordinates"]
        assert math.dist((x / km_per_px, y / km_per_px), true.point) <= 2
    assert geo.feature("Port Wyn").kind == "port"
    for cell in truth.sea:
        assert geo.terrain[cell] == TERRAIN_LETTERS["sea"]
    for cell in truth.lakes[0]:
        assert geo.terrain[cell] == TERRAIN_LETTERS["lake"]
    river = geo.feature("river-1")
    source, mouth = river.geometry["coordinates"][0], river.geometry["coordinates"][-1]
    assert math.dist([c / km_per_px for c in source], truth.river[0]) < truth.grid.size_km
    assert math.dist([c / km_per_px for c in mouth], truth.river[-1]) < truth.grid.size_km
    roads = [f for f in geo.features if f.layer == "routes"]
    assert len(roads) == 1
    ends = {tuple(roads[0].geometry["coordinates"][0]), tuple(roads[0].geometry["coordinates"][-1])}
    assert ends == {tuple(geo.feature(n).geometry["coordinates"]) for n in truth.road_between}


def test_claude_is_asked_once_for_the_colours_and_suggests_each_terrain():
    synthetic = hex_map()
    prompts = []
    reading = _read(synthetic, look=fake_look(synthetic.truth, prompts=prompts))
    assert sum(p.startswith("# The terrain colours") for p in prompts) == 1
    truth = synthetic.truth
    for cluster in reading.clusters:
        if cluster.terrain is None:
            cells = [c for c in cluster.cells if c not in truth.mixed]
            assert {truth.terrain[c] for c in cells} == {cluster.suggestion}
        else:
            assert cluster.terrain == "sea"


def test_without_a_grid_the_two_points_give_square_cells_and_the_frame_is_a_colour():
    synthetic = hex_map(lines=False)
    key = ScaleKey(None, 100, "km", points=((40.0, 40.0), (140.0, 40.0)))
    reading = _read(synthetic, key)
    grid = reading.geo.grid
    assert grid.kind == "square"
    assert max(grid.cols, grid.rows) == DEFAULT_CELLS
    assert grid.size_km == pytest.approx(max(synthetic.image.size) / DEFAULT_CELLS)
    assert "outside" in {c.suggestion for c in reading.clusters}


def test_a_hex_key_on_a_picture_without_a_grid_is_refused():
    with pytest.raises(ReadError):
        _read(hex_map(lines=False))


def test_a_key_that_doesnt_check_is_refused_before_reading():
    with pytest.raises(ValueError):
        _read(hex_map(), ScaleKey(None, 30, "miles"))


def test_the_reading_round_trips_through_its_json_and_its_map_through_geojson():
    reading = _read(hex_map())
    raw = json.loads(json.dumps(reading.to_dict()))
    assert set(raw) == {"clusters", "doubts"}
    assert set(raw["clusters"][0]) == {"id", "colour", "cells", "suggestion", "terrain"}
    assert len(raw["clusters"][0]["colour"]) == 3
    assert set(raw["doubts"][0]) == {
        "id",
        "kind",
        "ref",
        "message",
        "reading",
        "alternatives",
        "resolved",
        "choice",
        "data",
    }
    geo = from_geojson(json.loads(json.dumps(to_geojson(reading.geo)))).geo
    assert Reading.from_dict(raw, geo) == reading
