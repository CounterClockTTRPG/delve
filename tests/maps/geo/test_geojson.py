"""GeoJSON in and out: the Delve document reads back exactly, a foreign file is scaled and mapped, and Azgaar's export
maps itself."""

import itertools
import math

import pytest

from delve.maps.geo.geojson import (
    AZGAAR_BIOME_NAMES,
    AZGAAR_BIOMES,
    PropertyMapping,
    Scale,
    from_geojson,
    is_azgaar,
    to_geojson,
)
from delve.maps.geo.grid import cell_at
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, GeoMapError, Grid, PictureRef
from tests.maps.geo import fixture

HAND_MAPPING = PropertyMapping(
    kind="type", name="label", values={"settlement": "town", "highway": "road", "woods": "forest", "mere": "lake"}
)


def _delve_map() -> GeoMap:
    return GeoMap(
        Frame(60.0, 40.0, "miles"),
        Grid("hex", 10.0, 6, 4, origin=(1.5, 0.0), orientation="flat"),
        "pfhm" * 5 + "ww" + "." + "l",
        (
            GeoFeature(
                "keep",
                "places",
                "castle",
                "The Keep",
                {"type": "Point", "coordinates": [12.5, 8.25]},
                description="A grey keep.",
                dm_notes="SECRET-XYZZY: the lord is a doppelganger.",
                tags=("walled",),
            ),
            GeoFeature(
                "cave", "places", "dungeon", "Cave", {"type": "Point", "coordinates": [30.0, 20.0]}, hidden=True
            ),
            GeoFeature(
                "track",
                "routes",
                "track",
                "Hill Track",
                {"type": "LineString", "coordinates": [[12.5, 8.25], [30.0, 20.0]]},
                props={"surface": "dirt"},
            ),
            GeoFeature(
                "brook",
                "water",
                "river",
                "Brook",
                {"type": "LineString", "coordinates": [[1.0, 1.0], [50.0, 30.0]]},
                props={"navigable_km": 12.5, "barrier": True},
            ),
            GeoFeature(
                "march",
                "regions",
                "kingdom",
                "The March",
                {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 0]]]},
            ),
        ),
        PictureRef("ab" * 32, 1200, 800, 0.05, asset="worldmap-test"),
    )


def test_a_delve_document_reads_back_exactly():
    geo = _delve_map()
    doc = to_geojson(geo)
    assert doc["type"] == "FeatureCollection"
    assert doc["delve"]["version"] == 1
    assert doc["delve"]["terrain"] == geo.terrain
    cave = next(f for f in doc["features"] if f["id"] == "cave")
    assert cave["properties"]["hidden"] is True
    imported = from_geojson(doc)
    assert imported.geo == geo
    assert imported.needs_scale is False
    assert imported.warnings == []
    assert to_geojson(imported.geo) == doc
    assert imported.geo.feature("keep").dm_notes.startswith("SECRET-XYZZY")


def test_the_qgis_export_adds_a_polygon_per_cell_and_reading_it_ignores_them():
    geo = _delve_map()
    doc = to_geojson(geo, terrain_cells=True)
    cells = [f for f in doc["features"] if f["properties"]["layer"] == "terrain"]
    assert len(cells) == len(geo.terrain) - geo.terrain.count(".")  # a cell outside the map has no polygon
    assert cells[1]["properties"]["terrain"] == "forest"
    assert cells[1]["geometry"]["type"] == "Polygon"
    assert from_geojson(doc).geo == geo


def test_a_delve_document_that_doesnt_hold_together_names_its_problems():
    doc = to_geojson(_delve_map())
    doc["delve"]["terrain"] = "pp"
    point = {"type": "Point", "coordinates": [0, 0]}
    doc["features"] += [
        {"type": "Feature", "id": "port", "geometry": point, "properties": {"layer": "places", "kind": "spaceport"}},
        {"type": "Feature", "id": "keep", "geometry": point, "properties": {"layer": "places", "kind": "town"}},
    ]
    with pytest.raises(GeoMapError) as raised:
        from_geojson(doc)
    problems = " | ".join(raised.value.problems)
    assert "terrain" in problems
    assert "spaceport" in problems
    assert "keep" in problems  # the duplicate id


def test_not_a_feature_collection_is_refused():
    with pytest.raises(GeoMapError):
        from_geojson({"type": "Feature"})


def test_a_foreign_file_without_a_scale_asks_for_one_with_its_properties_and_kinds():
    imported = from_geojson(fixture("hand.geojson"), mapping=HAND_MAPPING)
    assert imported.geo is None
    assert imported.needs_scale is True
    assert imported.properties == ["description", "label", "type"]
    assert imported.kinds == ["beacon", "highway", "mere", "settlement", "woods"]


@pytest.mark.parametrize(
    "scale", [Scale(width_km=200.0), Scale(known=("oakvale", "RIVERMOUTH", 180.0))], ids=["width", "known"]
)
def test_a_foreign_file_with_a_mapping_and_a_scale(scale):
    imported = from_geojson(fixture("hand.geojson"), mapping=HAND_MAPPING, scale=scale)
    geo = imported.geo
    assert geo is not None
    assert (geo.frame.width_km, geo.frame.height_km) == pytest.approx((200.0, 160.0))
    oakvale, rivermouth = geo.feature("Oakvale"), geo.feature("rivermouth")
    assert (oakvale.layer, oakvale.kind) == ("places", "town")
    assert oakvale.geometry["coordinates"] == pytest.approx([20.0, 0.0])  # y grows down from the top
    assert rivermouth.geometry["coordinates"] == pytest.approx([200.0, 0.0])
    road = geo.feature("King's Road")
    assert (road.layer, road.kind) == ("routes", "road")
    line = road.geometry["coordinates"]
    assert sum(math.dist(a, b) for a, b in itertools.pairwise(line)) == pytest.approx(180.0)
    assert geo.terrain_of(cell_at(geo.grid, 50.0, 120.0)) == "forest"  # the Old Wood, y flipped
    assert geo.terrain_of(cell_at(geo.grid, 150.0, 110.0)) == "lake"  # the Still Mere's cells
    assert geo.terrain_of(cell_at(geo.grid, 150.0, 20.0)) == "plains"  # under no terrain
    assert geo.feature("Still Mere").layer == "water"
    assert geo.feature("Signal Fire") is None
    assert any("beacon" in w for w in imported.warnings)


def test_a_known_distance_between_places_that_arent_there_is_refused():
    with pytest.raises(GeoMapError):
        from_geojson(fixture("hand.geojson"), mapping=HAND_MAPPING, scale=Scale(known=("Oakvale", "Atlantis", 10.0)))


def test_azgaar_is_recognised_by_its_properties():
    assert is_azgaar(fixture("azgaar-cut.geojson"))
    assert not is_azgaar(fixture("hand.geojson"))


def test_azgaars_biome_table():
    assert AZGAAR_BIOMES[0] == "sea"
    assert [AZGAAR_BIOMES[i] for i in (1, 2, 3, 4, 5, 7, 6, 8, 9, 10, 11, 12)] == [
        "desert", "desert", "plains", "plains", "jungle", "jungle", "forest", "forest", "forest", "arctic", "arctic",
        "swamp",
    ]  # fmt: skip
    assert AZGAAR_BIOME_NAMES["temperate deciduous forest"] == "forest"


def test_an_azgaar_export_maps_itself():
    imported = from_geojson(fixture("azgaar-cut.geojson"), scale=Scale(width_km=600.0))
    geo = imported.geo
    assert geo is not None
    assert (geo.frame.width_km, geo.frame.height_km) == pytest.approx((600.0, 200.0))

    def at(x: float) -> str | None:
        return geo.terrain_of(cell_at(geo.grid, x, 100.0))

    assert at(50.0) == "sea"  # biome 0
    assert at(150.0) == "forest"  # biome 6
    assert at(250.0) == "mountain"  # biome 4, but height 70
    assert at(350.0) == "hills"  # "Grassland" by name, height 55
    assert at(450.0) == "plains"  # biome 3
    assert at(550.0) == "plains"  # biome 42 isn't in the table
    assert any("42" in w for w in imported.warnings)

    kinds = {f.name: (f.layer, f.kind) for f in geo.features}
    assert kinds["Ashford"] == ("places", "city")
    assert "capital" in geo.feature("Ashford").tags
    assert kinds["Brindle"] == ("places", "port")
    assert kinds["Cobb"] == ("places", "village")
    assert kinds["Silverrun"] == ("water", "river")
    assert kinds["Old Road"] == ("routes", "road")
    assert kinds["Deepdelve"] == ("places", "dungeon")
    assert kinds["Old Tower"] == ("places", "ruin")
    assert [f.kind for f in geo.features if f.layer == "routes"] == ["road", "trail"]  # the sea route is dropped
    assert sum(1 for f in geo.features if f.layer == "places" and f.kind == "other") == 1  # the volcano
    river = geo.feature("Silverrun").geometry["coordinates"]
    assert river[0] == pytest.approx([250.0, 20.0])  # from its source, y flipped
    assert river[-1] == pytest.approx([50.0, 100.0])  # to its mouth, in the sea
    assert len({f.id for f in geo.features}) == len(geo.features)
