"""Plateau 6's `.map` world maps converted into geo maps: every view of the four ttrpg2 fixtures, the kinds, the DM's
notes, and the setting's region map at its new scale."""

import math

import pytest

from delve.maps.geo.from_dsl import from_view
from delve.maps.geo.geojson import from_geojson, to_geojson
from delve.maps.geo.grid import cell_at
from delve.maps.world import compile_view, parse
from tests.fixtures.settings import GreyhawkSetting
from tests.maps.world import INCLUDES, read

MILE = 1.609344


def _view(text: str, view: str | None = None):
    return compile_view(parse(text, INCLUDES), view)


@pytest.mark.parametrize(
    ("name", "view"),
    [
        ("greyhawk-region.map", "world"),
        ("wastes-of-cynidicea.map", "world"),
        ("wastes-of-cynidicea.map", "sulm-akar-city"),  # with the sulm-akar-buildings.map include
        ("cantona.map", "region"),
        ("cantona.map", "city"),
    ],
)
def test_the_ttrpg2_maps_convert(name, view):
    compiled = _view(read(name), view)
    converted = from_view(compiled)
    geo = converted.geo
    assert geo.features
    assert len(geo.terrain) == geo.grid.cols * geo.grid.rows
    assert set(converted.names) <= {f.name for f in compiled.features}
    for dsl_name, feature_id in converted.names.items():
        assert dsl_name == feature_id
        assert geo.feature(feature_id) is not None
    for feature in geo.features:
        for x, y in _points(feature.geometry):
            assert 0 <= x <= geo.frame.width_km and 0 <= y <= geo.frame.height_km
    assert from_geojson(to_geojson(geo)).geo == geo  # a valid Delve document


def _points(geometry: dict) -> list[list[float]]:
    coords = geometry["coordinates"]
    if geometry["type"] == "Point":
        return [coords]
    if geometry["type"] == "LineString":
        return coords
    return [p for ring in coords for p in ring]


GREYHAWK = from_view(_view(read("greyhawk-region.map")))


def test_the_region_map_converts_with_its_kinds():
    geo = GREYHAWK.geo
    assert geo.frame.units == "miles"
    assert (geo.grid.kind, max(geo.grid.cols, geo.grid.rows)) == ("square", 200)
    greyhawk = geo.feature("greyhawk")
    assert (greyhawk.layer, greyhawk.kind, greyhawk.name) == ("places", "city", "Greyhawk")  # pop 60,000
    assert geo.feature("hardby").kind == "town"  # pop 5,000
    assert geo.feature("tellach").kind == "village"  # pop 80
    assert geo.feature("castle-greyhawk").kind == "dungeon"  # tagged ruined and dungeon
    assert geo.feature("Castle Greyhawk") is geo.feature("castle-greyhawk")
    assert geo.feature("ambush-site").kind == "other"
    track = geo.feature("castle-track")
    assert (track.layer, track.kind, track.props["surface"]) == ("routes", "track", "track")
    road = geo.feature("south-coast")
    assert (road.kind, road.props["surface"]) == ("road", "dirt")
    assert (geo.feature("selintan").layer, geo.feature("selintan").kind) == ("water", "river")
    assert geo.feature("nyr-dyv").kind == "lake"


def test_lakes_and_terrain_become_cells_and_y_grows_down():
    geo = GREYHAWK.geo
    # Greyhawk (500,500) lies north of Hardby (640,385) in the DSL, whose y grows north: here it is above.
    gy = geo.feature("greyhawk").geometry["coordinates"][1]
    hy = geo.feature("hardby").geometry["coordinates"][1]
    assert gy < hy
    nyr_dyv = [[x, y] for x, y in geo.feature("nyr-dyv").geometry["coordinates"][0][:-1]]
    middle = (sum(p[0] for p in nyr_dyv) / 4, sum(p[1] for p in nyr_dyv) / 4)
    assert geo.terrain_of(cell_at(geo.grid, *middle)) == "lake"
    assert {"forest", "hills", "mountain", "plains", "lake"} <= {geo.terrain_of(i) for i in range(len(geo.terrain))}


def test_hidden_comes_from_the_tag_and_a_revealed_place_is_no_longer_hidden():
    (source,) = GreyhawkSetting().world_maps()  # its two campaign places are tagged hidden
    region = from_view(_view(source.dsl)).geo
    assert region.feature("clan-temple").hidden
    assert "hidden" not in region.feature("clan-temple").tags
    assert not region.feature("greyhawk").hidden
    revealed = from_view(_view(source.dsl), revealed={"clan-temple"})
    assert not revealed.geo.feature("clan-temple").hidden
    assert revealed.geo.feature("ambush-site").hidden


def test_the_description_and_the_doc_are_the_dms_never_the_players():
    text = """
workspace w {
    model {
        city a { at 0,0; description "SECRET-XYZZY the mayor"; doc locations/a.md }
        city b { at 10,10 }
    }
}
"""
    geo = from_view(_view(text)).geo
    a = geo.feature("a")
    assert a.description == ""
    assert "SECRET-XYZZY the mayor" in a.dm_notes
    assert "locations/a.md" in a.dm_notes


def test_buildings_streets_and_unknown_biomes_are_simplified_with_a_warning():
    text = """
workspace w {
    model {
        city town { at 0,0
            contains {
                building inn { at 10,10; size 6,4 }
                street main { points 0,0 30,0 }
            }
        }
        terrain flats { polygon 0,0 40,0 40,40 0,40; biome salt }
        terrain bog { polygon 0,0 20,0 20,20 0,20; biome marsh }
    }
    views { view town { scope town; units feet } view all { scope w; include terrain; units miles } }
}
"""
    town = from_view(_view(text, "town"))
    inn = town.geo.feature("inn")
    assert (inn.layer, inn.kind, inn.geometry["type"]) == ("places", "other", "Point")
    main = town.geo.feature("main")
    assert (main.layer, main.kind) == ("routes", "trail")
    assert town.geo.frame.units == "km"
    assert town.warnings
    land = from_view(_view(text, "all"))
    assert any("salt" in w for w in land.warnings)
    letters = set(land.geo.terrain)
    assert letters == {"p", "s"}  # salt is plains; marsh is swamp


def test_a_dsl_point_converts_to_km_as_its_features_do():
    greyhawk = GREYHAWK.geo.feature("greyhawk").geometry["coordinates"]
    assert list(GREYHAWK.km((500, 500))) == pytest.approx(greyhawk)


def test_greyhawk_to_hardby_is_about_80_miles_on_the_settings_region_map():
    (source,) = GreyhawkSetting().world_maps()
    geo = from_view(compile_view(parse(source.dsl))).geo
    a = geo.feature("greyhawk").geometry["coordinates"]
    b = geo.feature("hardby").geometry["coordinates"]
    miles = math.dist(a, b) / MILE
    assert 70 <= miles <= 90
