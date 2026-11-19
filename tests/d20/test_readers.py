"""The readers of a sheet's numbers under a d20 engine (DEL-387): each shows the engine's, not AC and THAC0."""

import pytest

from delve.dm.tools import party as party_tool
from delve.play import characters, sessions
from delve.play.context import context_for
from delve.web.routes import play as play_route
from tests.fixtures.d20 import d20_catalogs, fake_engine
from tests.fixtures.rulesets import osric_catalogs

NUMBERS = {"defence": 11, "attack": 1, "save": 2}


@pytest.fixture
def ctx(d20_storage, d20_campaign):
    fake_engine().called.clear()
    return context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())


@pytest.fixture
def fighter(ctx):
    return characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": 1, "hp_max": 12})


def test_party_status_shows_the_engines_numbers(ctx, fighter, d20_call):
    (entry,) = d20_call("party_status")["party"]
    assert entry["d20"] == NUMBERS
    assert "thac0" not in entry and "ac" not in entry
    assert "sheet_numbers" in fake_engine().called


def test_get_character_brief_shows_the_engines_numbers(ctx, fighter, d20_call):
    entry = d20_call("get_character", ref="Bram", brief=True)
    assert entry["d20"] == NUMBERS and "thac0" not in entry and "ac" not in entry


def test_the_session_summary_shows_the_engines_numbers(ctx, fighter):
    (entry,) = sessions.primer(ctx, roll_weather=False)["party"]
    assert entry["d20"] == NUMBERS
    assert "thac0" not in entry and "ac" not in entry


def test_the_play_routes_sheet_shows_the_engines_numbers(ctx, fighter, d20_web, d20_campaign):
    state = d20_web.get(f"/api/campaigns/{d20_campaign.id}/play/state").json()
    (entry,) = state["party"]
    assert entry["d20"] == NUMBERS and "ac" not in entry and "thac0" not in entry
    assert play_route._digest(ctx, fighter)["d20"] == NUMBERS
    assert "ac" not in play_route._digest(ctx, fighter)


def test_the_characters_route_shows_the_engines_numbers(ctx, fighter, d20_web, d20_campaign):
    (listed,) = d20_web.get(f"/api/campaigns/{d20_campaign.id}/characters").json()
    assert listed["d20"] == NUMBERS
    assert listed["xp_progress"]["xp_next"] is not None and "per_class" not in listed["xp_progress"]
    assert all("thac0_worked" not in a for a in listed["sheet"]["attacks"])


def test_osric_readers_still_show_thac0(d20_storage):
    from delve.domain.modules import ModuleMap
    from tests.dm.tools.conftest import CRYPT

    module = d20_storage.modules.create("The Crypt")
    d20_storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    number = d20_storage.revisions.snapshot(module.id).number
    campaign = d20_storage.campaigns.create("Old", module.id, number, ruleset="osric", setting="greyhawk")
    ctx = context_for(d20_storage, campaign.id, "beat-1", catalogs=osric_catalogs())
    pc = characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": 1, "hp_max": 12})
    (entry,) = sessions.primer(ctx, roll_weather=False)["party"]
    assert "thac0" in entry and "ac" in entry and "d20" not in entry
    assert "ac" in play_route._digest(ctx, pc) and "d20" not in play_route._digest(ctx, pc)
    assert "thac0" in party_tool._brief(ctx, pc) and "d20" not in party_tool._brief(ctx, pc)
