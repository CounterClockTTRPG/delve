"""A campaign's own maps (campaign maps, 2026-10-23): played beside its revision's maps, moved on, reached by an exit
from a module map, and listed for the DM as the campaign's own, never the module's."""

from dataclasses import replace

import pytest

from delve.dice import ScriptedRng
from delve.domain.modules import ModuleMap
from delve.play import campaign_maps, characters, moves, sessions
from delve.play.context import context_for
from tests.fixtures import SAMPLES
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

CRYPT = (SAMPLES / "crypt.dmap").read_text() + '\nexit at 20,12 { to "slums" at 2,2 }\n'
COTTAGE = (SAMPLES / "cottage.dmap").read_text()


@pytest.fixture
def ctx(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    storage.campaign_maps.put(campaign.id, "slums", COTTAGE)
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng(()), catalogs=over(PlayReference()))
    characters.create(ctx, name="Garrek", sheet={"hp_max": 8})
    return ctx


def test_the_played_revision_holds_the_campaigns_own_maps_after_the_modules(ctx):
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    revision = campaign_maps.played_revision(ctx.storage, campaign)
    assert [m.name for m in revision.maps] == ["crypt", "slums"]
    assert campaign_maps.own_names(ctx.storage, campaign.id) == {"slums"}


def test_a_campaign_map_is_moved_on_like_a_module_map(ctx):
    out = moves.move(ctx, to="kitchen", map="slums")
    assert out["map"] == "slums"
    raw = ctx.storage.map_states.get(ctx.campaign_id, "slums")
    assert raw["characters"][characters.get(ctx, "Garrek").id]["location"] == "room.kitchen"


def test_the_dm_sees_a_campaign_map_marked_as_the_campaigns_own(ctx):
    block = sessions._module(ctx)
    entries = {m["name"]: m for m in block["maps"]}
    assert entries["slums"]["own"] is True
    assert "own" not in entries["crypt"]


def test_a_module_map_of_the_same_name_gives_way_to_the_campaigns(ctx, storage):
    """A module upgraded with a map named like a campaign's own: the campaign keeps playing its own."""
    campaign = storage.campaigns.get(ctx.campaign_id)
    module_revision = storage.revisions.get(campaign.module_id, campaign.revision)
    upgraded = replace(module_revision, maps=(*module_revision.maps, ModuleMap("slums", "map", CRYPT, False)))
    clash = campaign_maps.with_own_maps(upgraded, storage.campaign_maps.list(campaign.id))
    assert [m.source for m in clash.maps if m.name == "slums"] == [COTTAGE]
