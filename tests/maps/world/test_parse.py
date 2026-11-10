"""Parsing and compiling ttrpg2's world-map DSL: the four real maps, includes, styles, and errors that name their line."""

import pytest

from delve.maps.world import WorldMapError, compile_view, is_workspace, parse
from tests.maps.world import INCLUDES, read

SAMPLE = """\
workspace sheldomar {
    styles {
        terrain.biome=marsh  { color #4a6b3a; fill-opacity 0.4 }
        city                 { marker circle; color #222; marker-size 6 }
        [walled]             { stroke #444; stroke-width 2 }
    }
    model {
        kingdom geoff { color #6b7c4a; capital hochoch }
        city hochoch { at 412,308; pop 2400; in geoff; tags [walled, trade]; description "Frontier town."
                       doc locations/hochoch.md }
        city orlane {
            at 398,224
            contains {
                building golden-grain-inn { at 12,8;  size 6,4;  type inn }
                street  main-road         { points 0,10 30,10 }
            }
        }
        road south-trade-track { from hochoch; to orlane; via 410,260 405,240; surface dirt }
        terrain rushmoors { polygon 350,200 380,180 390,260 360,280; biome marsh }
        poi crocodile-attack { at 372,250; kind event }
        dungeon temple-cellars {
            in orlane.golden-grain-inn
            room antechamber { at 0,0 size 4,4 }
            room pit-chamber { at 4,0 size 6,6 }
            passage          { from antechamber; to pit-chamber }
        }
    }
    views {
        view world { scope sheldomar; include kingdoms, cities, roads, terrain, poi; units miles; scale 2
                     styles { terrain.biome=marsh { color #f0c070 } } }
        view orlane-city    { scope orlane;         include buildings, streets; units feet }
        view temple-cellars { scope temple-cellars; include rooms, passages;    units feet }
    }
}
"""


@pytest.mark.parametrize(
    ("name", "views"),
    [
        ("greyhawk-region.map", ["world"]),
        ("wastes-of-cynidicea.map", ["world", "sulm-akar-city"]),
        ("cantona.map", ["region", "city"]),
    ],
)
def test_the_ttrpg2_maps_parse_and_compile(name, views):
    model = parse(read(name), INCLUDES)
    assert [v.name for v in model.views] == views
    for view in views:
        compiled = compile_view(model, view)
        assert compiled.features, view
        assert all(f.coords for f in compiled.features)


def test_the_included_fragment_lands_in_its_city():
    assert not is_workspace(read("sulm-akar-buildings.map"))
    assert is_workspace(read("wastes-of-cynidicea.map"))
    city = compile_view(parse(read("wastes-of-cynidicea.map"), INCLUDES), "sulm-akar-city")
    names = {f.name for f in city.features if f.kind == "building"}
    assert {"rerds-yard", "sand-crow"} <= names
    assert city.units == "feet"


def test_greyhawk_region():
    view = compile_view(parse(read("greyhawk-region.map")))
    assert (view.name, view.workspace, view.units, view.scale) == ("world", "greyhawk-region", "miles", 1.0)
    greyhawk = view.feature("greyhawk")
    assert (greyhawk.kind, greyhawk.geometry, greyhawk.coords) == ("city", "Point", ((500.0, 500.0),))
    assert greyhawk.tags == ("walled", "capital", "freecity")
    assert greyhawk.label == "Greyhawk"
    assert view.feature("castle-greyhawk").label == "Castle Greyhawk"
    assert view.feature("gnarley-forest").properties["biome"] == "forest"
    road = view.feature("south-coast")
    assert road.geometry == "LineString"
    assert road.coords == ((500.0, 500.0), (640.0, 385.0))
    assert (road.properties["from"], road.properties["to"], road.properties["surface"]) == (
        "greyhawk",
        "hardby",
        "dirt",
    )


def test_compile_geometry_styles_and_scopes():
    model = parse(SAMPLE)
    world = compile_view(model, "world")
    assert world.scale == 2.0
    by = {f.name: f for f in world.features}
    assert "geoff" not in by  # a kingdom without a polygon has nothing to draw
    assert by["south-trade-track"].coords == ((412, 308), (410, 260), (405, 240), (398, 224))
    ring = by["rushmoors"].coords
    assert by["rushmoors"].geometry == "Polygon" and ring[0] == ring[-1]
    assert by["rushmoors"].style["color"] == "#f0c070"  # the view's rule wins over the workspace's
    hochoch = by["hochoch"]
    assert (hochoch.style["marker"], hochoch.style["stroke"], hochoch.style["stroke-width"]) == ("circle", "#444", 2)
    assert hochoch.properties["doc"] == "locations/hochoch.md"
    assert hochoch.properties["description"] == "Frontier town."
    assert by["crocodile-attack"].properties["category"] == "event"

    city = compile_view(model, "orlane-city")
    inn = city.feature("golden-grain-inn")
    assert inn.coords == ((12, 8), (18, 8), (18, 12), (12, 12), (12, 8))
    assert {f.kind for f in city.features} == {"building", "street"}

    cellars = compile_view(model, "temple-cellars")
    passage = next(f for f in cellars.features if f.kind == "passage")
    assert passage.coords == ((2, 2), (7, 3))


def test_the_first_view_is_the_default_and_a_map_without_views_shows_everything():
    assert compile_view(parse(SAMPLE)).name == "world"
    bare = compile_view(parse("workspace w { model { city a { at 1,2 } } }"))
    assert (bare.name, bare.units, bare.scale, [f.name for f in bare.features]) == ("w", "miles", 1.0, ["a"])


def test_an_unknown_view_is_refused():
    with pytest.raises(WorldMapError, match="no view 'nope'"):
        compile_view(parse(SAMPLE), "nope")


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        (
            "workspace w {\n  model {\n    city a { at 1,2 }\n    road r { from a; to nowhere }\n  }\n}\n",
            4,
            "unresolved reference 'nowhere'",
        ),
        ("workspace w {\n  model {\n    castle a { at 1,2 }\n  }\n}\n", 3, "unknown feature kind 'castle'"),
        (
            "workspace w {\n  model {\n    city a { at 1,2 }\n\n    city a { at 3,4 }\n  }\n}\n",
            5,
            "duplicate identifier 'a'",
        ),
        ("workspace w {\n  model {\n    river r { points 1,2 3 }\n  }\n}\n", 3, "expects coord pairs"),
        ("workspace w {\n  model {\n    city a { at 1,2 \n", 3, "end of text"),
        ("workspace w { model { city a { at 1,2 } } }\nmodel { }\n", 2, "after the workspace"),
        (
            "workspace w {\n  model { city a { at 1,2 } }\n  views { view v { scope elsewhere } }\n}\n",
            3,
            "scope 'elsewhere'",
        ),
        ("workspace w {\n  model {\n    city a { at 1,2 } @\n  }\n}\n", 3, "unexpected character '@'"),
    ],
)
def test_a_parse_error_names_its_line(text, line, message):
    with pytest.raises(WorldMapError) as caught:
        parse(text)
    assert caught.value.line == line
    assert message in caught.value.message
    assert str(caught.value).startswith(f"line {line}: ")


def test_an_error_in_an_include_names_the_include_line_and_the_file():
    text = "workspace w {\n  model {\n    city a { at 0,0; contains {\n      !include bad.map\n    } }\n  }\n}\n"
    with pytest.raises(WorldMapError) as caught:
        parse(text, {"bad.map": "building b { at 1,2 }\nbuilding c { at oops }\nbuilding d { at 1 2 3 }\n"})
    assert caught.value.line == 4
    assert "bad.map, line 3" in caught.value.message


def test_includes_must_exist_and_must_not_loop():
    text = "workspace w {\n  model {\n    !include a.map\n  }\n}\n"
    with pytest.raises(WorldMapError, match="not found") as caught:
        parse(text)
    assert caught.value.line == 3
    with pytest.raises(WorldMapError, match="cycle"):
        parse(text, {"a.map": "!include b.map\n", "b.map": "!include a.map\n"})


def test_strings_hex_colours_and_comments():
    model = parse(
        'workspace w { # a comment\n model { city a { at 1,2; description "a # not a comment \\"x\\"" color #AbC } } }'
    )
    city = compile_view(model).feature("a")
    assert city.properties["description"] == 'a # not a comment "x"'
    assert city.properties["color"] == "#abc"
