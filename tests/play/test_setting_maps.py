"""A setting's own world maps (settings plan Task 9, Review Focus 4): a module's ready map copied into the setting as a
Delve document, the install's old pointers copied once at start and then gone, and a seat's whole-map view that never
holds a hidden feature or the DM's notes."""

import json

import pytest

from delve.domain.world import WorldMapSource
from delve.maps.geo.geojson import from_geojson, to_geojson
from delve.maps.geo.model import GeoMap
from delve.modules.source import ModuleSource
from delve.play import setting_maps
from delve.play.setting_maps import SettingMapTaken
from tests.fixtures.rulesets import osric_catalogs
from tests.play.test_travel import VALE_MAP
from tests.play.test_world_maps import MARCH, SECRET, _point

SETTINGS = osric_catalogs().settings
"""The tests' settings: Greyhawk is a pack's (its double)."""


def module_with(storage, *worldmaps):
    module = storage.modules.create("The Flanaess")
    storage.module_sources.put(module.id, ModuleSource(worldmaps=tuple(worldmaps)))
    return module.id


FLANAESS = WorldMapSource("flanaess", "The Flanaess", "", geo=to_geojson(MARCH))


def test_copy_a_module_map(storage):
    module_id = module_with(storage, FLANAESS, VALE_MAP)
    copied = setting_maps.copy_module_map(storage, "greyhawk", module_id, "flanaess", settings=SETTINGS)
    assert (copied.name, copied.title, copied.status, copied.dsl) == ("flanaess", "The Flanaess", "ready", "")
    assert storage.setting_maps.get("greyhawk", "flanaess").geo == FLANAESS.geo
    # A `.map` one becomes a Delve document, under the name asked for.
    vale = setting_maps.copy_module_map(storage, "greyhawk", module_id, "vale", as_name="the-vale", settings=SETTINGS)
    assert vale.name == "the-vale" and from_geojson(vale.geo).geo.feature("millbrook") is not None
    assert [m.name for m in storage.setting_maps.list("greyhawk")] == ["flanaess", "the-vale"]


def test_copy_refuses_a_taken_name_and_a_map_in_review(storage):
    review = WorldMapSource("draft", "Draft", "", geo=to_geojson(MARCH), status="review")
    module_id = module_with(storage, FLANAESS, review)
    setting_maps.copy_module_map(storage, "greyhawk", module_id, "flanaess", settings=SETTINGS)
    with pytest.raises(SettingMapTaken):
        setting_maps.copy_module_map(storage, "greyhawk", module_id, "flanaess", settings=SETTINGS)
    with pytest.raises(ValueError):
        setting_maps.copy_module_map(storage, "greyhawk", module_id, "draft", settings=SETTINGS)
    with pytest.raises(KeyError):
        setting_maps.copy_module_map(storage, "greyhawk", module_id, "nowhere", settings=SETTINGS)
    with pytest.raises(KeyError):
        setting_maps.copy_module_map(storage, "greyhawk", "mod_nope", "flanaess", settings=SETTINGS)
    with pytest.raises(KeyError):
        setting_maps.copy_module_map(storage, "atlantis", module_id, "flanaess", settings=SETTINGS)
    assert [m.name for m in storage.setting_maps.list("greyhawk")] == ["flanaess"]


def test_seat_view_has_no_hidden_feature(storage):
    lair = _point("lair", SECRET, 50, 50, hidden=True, dm_notes=SECRET)
    ashford = _point("ashford", "Ashford", 15, 15, dm_notes=f"{SECRET}: the reeve is a doppelganger.")
    marked = GeoMap(MARCH.frame, MARCH.grid, MARCH.terrain, (ashford, lair, *MARCH.features[1:]))
    world_map = WorldMapSource("march", "The March", "", geo=to_geojson(marked))
    view = setting_maps.seat_view(storage, world_map, [world_map])
    assert SECRET not in json.dumps(view)
    assert "Ashford" in {f["name"] for f in view["features"]}
    assert (view["name"], view["title"], view["known"]["all"], view["party"], view["journey"]) == (
        "march",
        "The March",
        True,
        None,
        None,
    )
    assert view["picture"] is None and view["tiles_version"] == ""
