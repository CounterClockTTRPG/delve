"""The GeoMap: finding a feature by id or name, the terrain of a cell, and the water cells kept to the water areas."""

from dataclasses import replace

from delve.maps.geo.grid import cell_at
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid, water_from_areas
from delve.maps.geo.terrain import LAYERS, TERRAIN_CLASSES, TERRAIN_COLOURS, TERRAIN_LETTERS

GRID = Grid("square", 10.0, 10, 10)


def _area(id_: str, kind: str, x0: float, y0: float, x1: float, y1: float) -> GeoFeature:
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return GeoFeature(id_, "water", kind, id_.title(), {"type": "Polygon", "coordinates": [ring]})


def _map(*features: GeoFeature, terrain: str = "p" * 100) -> GeoMap:
    return GeoMap(Frame(100.0, 100.0), GRID, terrain, features)


def test_every_terrain_class_has_a_letter_and_a_colour():
    assert set(TERRAIN_LETTERS) == set(TERRAIN_CLASSES)
    assert len(set(TERRAIN_LETTERS.values())) == len(TERRAIN_CLASSES)
    assert "." not in TERRAIN_LETTERS.values()
    assert set(TERRAIN_COLOURS) == set(TERRAIN_CLASSES)
    assert LAYERS == ("places", "routes", "water", "regions")


def test_a_feature_by_id_else_by_its_exact_name_in_any_case():
    a = GeoFeature("greyhawk", "places", "city", "Greyhawk", {"type": "Point", "coordinates": [1.0, 1.0]})
    b = GeoFeature("hardby", "places", "town", "Hardby", {"type": "Point", "coordinates": [5.0, 5.0]})
    c = GeoFeature("hardby-keep", "places", "castle", "Hardby", {"type": "Point", "coordinates": [6.0, 5.0]})
    geo = _map(a, b, c)
    assert geo.feature("greyhawk") is a
    assert geo.feature("GREYHAWK") is a
    assert geo.feature("hardby") is b  # the id wins
    assert geo.feature("Hard") is None  # never a prefix
    assert geo.features_named("HARDBY") == [b, c]
    assert geo.feature("hardby-keep") is c


def test_the_terrain_of_a_cell():
    geo = _map(terrain="f" + "." + "p" * 98)
    assert geo.terrain_of(0) == "forest"
    assert geo.terrain_of(1) is None
    assert geo.terrain_of(2) == "plains"
    assert geo.terrain_of(100) is None


def test_a_lake_areas_cells_become_lake():
    geo = water_from_areas(_map(_area("mere", "lake", 0.0, 0.0, 30.0, 30.0)))
    lake = [i for i, t in enumerate(geo.terrain) if t == "l"]
    assert lake == [0, 1, 2, 10, 11, 12, 20, 21, 22]


def test_a_sea_areas_cells_become_sea():
    geo = water_from_areas(_map(_area("deep", "sea", 70.0, 70.0, 100.0, 100.0)))
    assert geo.terrain[cell_at(GRID, 85.0, 85.0)] == "w"
    assert geo.terrain.count("w") == 9


def test_shrinking_a_lake_gives_its_old_cells_back_as_plains_and_painted_water_stays():
    painted = "p" * 99 + "w"  # a sea cell painted with the brush, in no area
    before = water_from_areas(_map(_area("mere", "lake", 0.0, 0.0, 30.0, 30.0), terrain=painted))
    shrunk = replace(before, features=(_area("mere", "lake", 0.0, 0.0, 10.0, 10.0),))
    after = water_from_areas(shrunk, previous=before)
    assert [i for i, t in enumerate(after.terrain) if t == "l"] == [0]
    assert after.terrain[1] == after.terrain[22] == "p"
    assert after.terrain[99] == "w"


def test_without_the_previous_map_old_water_cells_stay():
    geo = _map(_area("mere", "lake", 0.0, 0.0, 10.0, 10.0), terrain="l" * 3 + "p" * 97)
    assert water_from_areas(geo).terrain[:3] == "lll"
