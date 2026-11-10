"""A campaign's world maps on the geo model (plan 7 Task 9, Review Focus 4): a plateau 6 `.map` is converted once, on
its first read, and its seats keep seeing what they saw; a new campaign's copies start with nothing known; the setting's
own ready map replaces the built-in one, and changes no campaign made before it; a map in review is never copied or
listed to a seat; and the DM's world tools reveal, hide and add places, areas and roads."""

import json
from dataclasses import replace

import pytest

from delve.domain.world import CampaignWorldMap, WorldKnowledge, WorldMapSource, WorldPosition
from delve.maps.geo.geojson import from_geojson, to_geojson
from delve.maps.geo.grid import cell_at
from delve.maps.geo.model import Frame, GeoFeature, GeoMap, GeoMapError, Grid
from delve.play import characters, travel, world_maps
from delve.play.context import NotFound, PlayError, context_for
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import osric, over
from tests.fixtures.settings import GreyhawkSetting
from tests.play.test_travel import VALE, VALE_MAP, clear_days, make_campaign

TRAVEL = osric().tables.travel
"""A ruleset's travel rates: OSRIC's, installed as a pack."""

SECRET = "SECRET-XYZZY"

REGION = GreyhawkSetting().world_maps()[0]
"""The setting's region map, `.map` text: Greyhawk, Hardby, and two places tagged hidden."""


def ctx_of(storage, campaign, *dice, beat="beat-1"):
    from delve.dice import ScriptedRng

    return context_for(storage, campaign.id, beat, ScriptedRng(dice), catalogs=over(PlayReference()))


def _point(id_, name, x, y, **kw):
    return GeoFeature(id_, "places", kw.pop("kind", "town"), name, {"type": "Point", "coordinates": [x, y]}, **kw)


def _area(id_, layer, kind, name, ring, **kw):
    return GeoFeature(id_, layer, kind, name, {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}, **kw)


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


MARCH = GeoMap(
    Frame(100.0, 100.0),
    Grid("square", 10.0, 10, 10),
    "p" * 100,
    (
        _point("ashford", "Ashford", 15, 15),
        _point("brindle", "Brindle", 85, 85),
        GeoFeature(
            "old-road", "routes", "road", "The Old Road", {"type": "LineString", "coordinates": [[15, 15], [85, 85]]}
        ),
        _area("mere", "water", "lake", "The Mere", square(40, 40, 60, 60)),
        _area("the-march", "regions", "kingdom", "The March", square(0, 0, 30, 30)),
    ),
)
"""100 × 100 km in cells of 10 km: Ashford in the March (the top-left 3 × 3 cells), a road to Brindle past the Mere."""


@pytest.fixture
def march(storage):
    """A campaign without a module map or a setting, with the March saved as its own geo map."""
    campaign = make_campaign(storage, worldmaps=[])
    ctx = ctx_of(storage, campaign)
    world_maps.save_geo(ctx, "march", to_geojson(MARCH), "The March")
    return ctx


def seat_names(view):
    return {f["name"] for f in view["features"]}


# --- old maps and old campaigns (Review Focus 4) ---------------------------------------------------------------------


def plateau_6_campaign(storage, *, at="greyhawk", x=500.0, y=500.0):
    """A campaign as plateau 6 left it: the region map as `.map` text, `clan-temple` revealed, the party at Greyhawk
    (a point in the `.map`'s own units)."""
    campaign = make_campaign(storage, worldmaps=[])
    storage.world_maps.put(
        CampaignWorldMap(campaign.id, REGION.name, REGION.title, "setting", REGION.dsl, revealed=("clan-temple",))
    )
    state = storage.campaign_states.get(campaign.id)
    storage.campaign_states.put(replace(state, world=WorldPosition(REGION.name, x, y, at)))
    return campaign


def test_a_plateau_6_campaign_converts_on_its_first_read_and_keeps_what_its_seats_saw(storage):
    campaign = plateau_6_campaign(storage)
    ctx = ctx_of(storage, campaign)
    (region,) = world_maps.maps(ctx)
    assert region.geo is not None and region.knowledge == WorldKnowledge(everything=True, features=("clan-temple",))
    # Only geo and knowledge were written: plateau 6's readers keep the text, what was revealed and the position.
    assert (region.dsl, region.revealed) == (REGION.dsl, ("clan-temple",))
    assert world_maps.position(ctx) == WorldPosition(REGION.name, 500.0, 500.0, "greyhawk")
    greyhawk = world_maps.geo(ctx, REGION.name).feature("greyhawk")
    assert world_maps.party_point(ctx, REGION.name) == tuple(greyhawk.geometry["coordinates"])
    view = world_maps.seat_view(ctx, REGION.name)
    assert view["known"]["all"] and {"Greyhawk", "Hardby", "Clan Temple"} <= seat_names(view)
    assert "Ambush Site" not in seat_names(view), "a hidden place never revealed stays hidden"
    assert world_maps.seat_maps(ctx) == [world_maps.get(ctx, REGION.name)]
    # A second read converts nothing again.
    assert world_maps.maps(ctx)[0].updated_at == region.updated_at


def test_a_plateau_6_point_without_a_place_is_converted_through_the_maps_units(storage):
    campaign = plateau_6_campaign(storage, at=None)
    ctx = ctx_of(storage, campaign)
    x, y = world_maps.party_point(ctx, REGION.name)
    gx, gy = world_maps.geo(ctx, REGION.name).feature("greyhawk").geometry["coordinates"]
    assert abs(x - gx) < 1e-6 and abs(y - gy) < 1e-6


def test_the_converted_campaign_still_travels_with_plateau_6s_travel(storage):
    campaign = make_campaign(storage)
    world_maps.maps(ctx_of(storage, campaign))
    ctx = ctx_of(storage, campaign, *clear_days(5))
    characters.create(ctx, name="Garrek", sheet={"hp_max": 10})
    world_maps.place_party(ctx, "oakton")
    travelled = travel.travel(ctx, "millbrook")
    assert travelled["arrived"] and world_maps.position(ctx).at == "millbrook"


def test_a_new_campaigns_copy_of_the_settings_map_knows_nothing(storage):
    campaign = make_campaign(storage, worldmaps=[], setting="greyhawk")
    ctx = ctx_of(storage, campaign)
    (region,) = world_maps.maps(ctx)
    assert (region.source, region.dsl) == ("setting", REGION.dsl)
    assert region.geo is not None and region.knowledge == WorldKnowledge()
    assert world_maps.seat_maps(ctx) == [], "a seat isn't shown a map the party knows nothing of"
    assert world_maps.seat_view(ctx, REGION.name)["features"] == []


def test_a_module_map_is_copied_with_its_geo_and_nothing_known(storage):
    campaign = make_campaign(storage)
    (vale,) = world_maps.maps(ctx_of(storage, campaign))
    assert (vale.source, vale.dsl, vale.knowledge) == ("module", VALE, WorldKnowledge())
    assert from_geojson(vale.geo).geo.feature("millbrook") is not None


# A fragment the vale's map includes: it is no map of its own.
TOWNS = "city northby { at 0,50 }\n"
WITH_TOWNS = VALE.replace("road kings-road", "!include towns.map\n        road kings-road")


def test_an_include_fragment_is_not_converted_or_listed_and_its_map_has_its_features(storage):
    maps = [WorldMapSource("vale", "The Vale", WITH_TOWNS), WorldMapSource("towns", "", TOWNS)]
    campaign = make_campaign(storage, worldmaps=maps)
    ctx = ctx_of(storage, campaign)
    listed = {m.name: m for m in world_maps.maps(ctx)}
    assert listed["towns"].geo is None and listed["towns"].knowledge is None
    assert world_maps.geo(ctx, "vale").feature("northby") is not None
    world_maps.place_party(ctx, "northby")
    assert [m.name for m in world_maps.seat_maps(ctx)] == ["vale"]


def test_an_old_campaigns_fragment_is_skipped_and_the_map_that_includes_it_converts(storage):
    campaign = make_campaign(storage, worldmaps=[])
    for name, text in (("vale", WITH_TOWNS), ("towns", TOWNS)):
        storage.world_maps.put(CampaignWorldMap(campaign.id, name, name, "module", text))
    listed = {m.name: m for m in world_maps.maps(ctx_of(storage, campaign))}
    assert listed["towns"].geo is None and listed["vale"].knowledge == WorldKnowledge(everything=True)
    assert from_geojson(listed["vale"].geo).geo.feature("northby") is not None


def flanaess_of_greyhawk(storage, status="ready"):
    """The install's own Greyhawk map, "flanaess", a geo document."""
    flanaess = WorldMapSource("flanaess", "The Flanaess", "", geo=to_geojson(MARCH), status=status)
    return storage.setting_maps.put("greyhawk", flanaess)


def test_a_new_campaign_copies_the_settings_ready_map(storage):
    flanaess_of_greyhawk(storage)
    campaign = make_campaign(storage, worldmaps=[], setting="greyhawk")
    (only,) = world_maps.maps(ctx_of(storage, campaign))
    assert (only.name, only.title, only.source, only.dsl) == ("flanaess", "The Flanaess", "setting", "")
    assert only.knowledge == WorldKnowledge() and from_geojson(only.geo).geo.feature("ashford") is not None


def test_the_modules_map_still_wins_a_name_clash_with_the_settings_map(storage):
    flanaess_of_greyhawk(storage)
    ours = WorldMapSource("flanaess", "Our Flanaess", VALE)
    campaign = make_campaign(storage, worldmaps=[ours], setting="greyhawk")
    (only,) = world_maps.maps(ctx_of(storage, campaign))
    assert (only.title, only.source) == ("Our Flanaess", "module")


def test_a_map_in_review_is_not_copied(storage):
    review = WorldMapSource("draft", "Draft", "", geo=to_geojson(MARCH), status="review")
    campaign = make_campaign(storage, worldmaps=[review, VALE_MAP])
    assert [m.name for m in world_maps.maps(ctx_of(storage, campaign))] == ["vale"]


def test_a_setting_map_in_review_leaves_the_built_in_one(storage):
    flanaess_of_greyhawk(storage, status="review")
    of_greyhawk = make_campaign(storage, worldmaps=[], setting="greyhawk")
    assert [m.name for m in world_maps.maps(ctx_of(storage, of_greyhawk))] == [REGION.name]


def test_existing_campaigns_keep_their_copies(storage):
    campaign = make_campaign(storage, worldmaps=[], setting="greyhawk")
    ctx = ctx_of(storage, campaign)
    (region,) = world_maps.maps(ctx)
    flanaess_of_greyhawk(storage)
    assert world_maps.maps(ctx) == [region], "a setting map added later changes nothing of the campaign"


def test_a_campaign_map_in_review_is_not_listed_played_on_or_placed_on(march):
    world_maps.set_start(march, "march", "everything")
    world_maps.save_geo(march, "march", to_geojson(MARCH), status="review")
    assert world_maps.seat_maps(march) == []
    with pytest.raises(PlayError, match="still in review"):
        world_maps.current_map(march, "march")
    with pytest.raises(PlayError, match="still in review"):
        world_maps.place_party(march, "ashford", "march")
    world_maps.accept(march, "march")
    assert [m.name for m in world_maps.seat_maps(march)] == ["march"]


# --- saving a geo map ------------------------------------------------------------------------------------------------


def test_save_geo_refuses_a_document_that_doesnt_hold_together(march):
    broken = to_geojson(MARCH)
    broken["delve"]["terrain"] = "p"
    with pytest.raises(GeoMapError):
        world_maps.save_geo(march, "march", broken)


def test_save_geo_of_a_reshaped_lake_moves_its_cells(march):
    geo = world_maps.geo(march, "march")
    old = cell_at(geo.grid, 45, 45)
    assert geo.terrain_of(old) == "lake"
    moved = [
        _area("mere", "water", "lake", "The Mere", square(70, 10, 90, 30)) if f.id == "mere" else f
        for f in MARCH.features
    ]
    world_maps.save_geo(march, "march", to_geojson(replace(MARCH, features=tuple(moved))))
    geo = world_maps.geo(march, "march")
    assert geo.terrain_of(old) == "plains" and geo.terrain_of(cell_at(geo.grid, 75, 15)) == "lake"


def test_a_new_campaign_map_starts_with_nothing_known_and_a_save_keeps_what_is_known(march):
    assert world_maps.knowledge(march, "march") == WorldKnowledge()
    world_maps.set_start(march, "march", "regions", regions=["The March"])
    world_maps.save_geo(march, "march", to_geojson(MARCH), "The March again")
    assert world_maps.knowledge(march, "march").cells == tuple(sorted({0, 1, 2, 10, 11, 12, 20, 21, 22}))
    assert world_maps.get(march, "march").title == "The March again"


# --- the party and what it knows -------------------------------------------------------------------------------------


def test_place_party_reveals_10_km_around(march):
    placed = world_maps.place_party(march, "ashford")
    assert placed["position"] == {"map": "march", "x": 15.0, "y": 15.0, "at": "ashford", "km": True}
    known = set(world_maps.knowledge(march, "march").cells)
    assert {1, 10, 11, 12, 21} <= known and cell_at(MARCH.grid, 85, 85) not in known
    assert world_maps.party_point(march, "march") == (15.0, 15.0)
    assert "Ashford" in seat_names(world_maps.seat_view(march, "march"))
    assert [m.name for m in world_maps.seat_maps(march)] == ["march"]


def test_place_party_on_a_dsl_map_writes_its_point_in_km(storage):
    """Plan 7 Task 10: every position is written in km on the geo map, a `.map` one's too."""
    campaign = make_campaign(storage)
    ctx = ctx_of(storage, campaign)
    placed = world_maps.place_party(ctx, "oakton")
    x, y = world_maps.geo(ctx, "vale").feature("oakton").geometry["coordinates"]
    assert placed["position"] == {"map": "vale", "x": x, "y": y, "at": "oakton", "km": True}
    assert world_maps.knowledge(ctx, "vale").cells, "the land around Oakton became known"
    assert "Oakton" in seat_names(world_maps.seat_view(ctx, "vale"))


def test_a_hidden_added_place_stays_out_of_the_seats_view(march):
    world_maps.set_start(march, "march", "everything")
    added = world_maps.add_place(
        march, "Lich Tower", "ruin", "50,20", description=SECRET, notes=f"{SECRET}: the lich", hidden=True
    )
    assert added["id"] == "lich-tower" and SECRET not in json.dumps(added)
    assert SECRET not in json.dumps(world_maps.seat_view(march, "march"))
    dm = {f["id"]: f for f in world_maps.dm_view(march, "march")["features"]}
    assert dm["lich-tower"]["hidden"] and dm["lich-tower"]["dm_notes"] == f"{SECRET}: the lich"
    again = world_maps.add_place(march, "Lich Tower", "ruin", "ashford")
    assert again["id"] == "lich-tower-2" and "Lich Tower" in seat_names(world_maps.seat_view(march, "march"))
    world_maps.reveal(march, "lich-tower")
    assert SECRET in json.dumps(world_maps.seat_view(march, "march")), "a revealed place shows its description"


def test_add_place_refuses_an_unknown_kind_and_a_point_off_the_map(march):
    with pytest.raises(PlayError):
        world_maps.add_place(march, "Inn", "tavern", "ashford")
    with pytest.raises(PlayError):
        world_maps.add_place(march, "Inn", "village", "500,500")


def test_hide_place_takes_a_known_place_out_and_a_road(march):
    world_maps.set_start(march, "march", "everything")
    world_maps.hide(march, "Ashford")
    world_maps.hide(march, "old-road")
    names = seat_names(world_maps.seat_view(march, "march"))
    assert "Ashford" not in names and "The Old Road" not in names and "Brindle" in names
    world_maps.reveal(march, "ashford")
    assert "Ashford" in seat_names(world_maps.seat_view(march, "march"))
    with pytest.raises(NotFound):
        world_maps.hide(march, "nowhere")


def test_reveal_area_and_forget_it(march):
    world_maps.reveal_area(march, "brindle", 10)
    assert "Brindle" in seat_names(world_maps.seat_view(march, "march"))
    world_maps.set_start(march, "march", "everything")
    world_maps.reveal_area(march, "brindle", 10, forget=True)
    view = world_maps.seat_view(march, "march")
    assert "Brindle" not in seat_names(view) and "Ashford" in seat_names(view)
    assert cell_at(MARCH.grid, 85, 85) not in set(world_maps.knowledge(march, "march").cells)


def test_reveal_place_on_a_region_knows_its_cells(march):
    revealed = world_maps.reveal(march, "The March")
    assert revealed["revealed"] == "the-march"
    assert set(world_maps.knowledge(march, "march").cells) == {0, 1, 2, 10, 11, 12, 20, 21, 22}
    assert "Ashford" in seat_names(world_maps.seat_view(march, "march"))


def test_reveal_any_feature_names_the_candidates_of_an_unknown_one(march):
    world_maps.reveal(march, "brindle")
    assert "Brindle" in seat_names(world_maps.seat_view(march, "march"))
    with pytest.raises(NotFound) as refused:
        world_maps.reveal(march, "Brindel")
    assert "brindle" in [c["id"] for c in refused.value.candidates]


def test_the_routing_graph_is_kept_until_the_map_changes(march):
    from delve.rules.classic.overland import mode_rules

    rules = mode_rules("foot", TRAVEL)
    graph = world_maps.graph(march, "march", rules)
    world_maps.place_party(march, "ashford")  # knowledge changes; the map doesn't
    assert world_maps.graph(march, "march", rules) is graph
    world_maps.save_geo(march, "march", to_geojson(replace(MARCH, terrain="f" * 100)))
    assert world_maps.graph(march, "march", rules) is not graph


def test_once_converted_the_geo_document_is_the_map(storage):
    """Plan 7 Task 11: plateau 6's DSL save is gone; a converted map's text is never read as the map again."""
    campaign = make_campaign(storage)
    ctx = ctx_of(storage, campaign)
    world_maps.add_place(ctx, "Lich Tower", "ruin", "oakton", map="vale")
    stored = storage.world_maps.get(campaign.id, "vale")
    storage.world_maps.put(replace(stored, dsl=VALE.replace("city distant", "city faraway")))
    geo_map = world_maps.geo(ctx, "vale")
    assert geo_map.feature("lich-tower") is not None and geo_map.feature("faraway") is None
    assert world_maps.knowledge(ctx, "vale") == WorldKnowledge(), "what the party knew is kept"


def test_without_a_map_the_refusal_names_advance_days(storage):
    ctx = ctx_of(storage, make_campaign(storage, worldmaps=[]))
    with pytest.raises(PlayError) as refused:
        world_maps.current_map(ctx)
    assert "advance_days" in refused.value.hint and "the campaign's page" in refused.value.hint
