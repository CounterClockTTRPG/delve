"""The fake DM's fight (`FIGHT` in `tests/e2e/fake_play_server.py`, table voice and fixes Task B2.4) through the tool
host, as the browser's `web/e2e/timeline.spec.ts` plays it through the bridge: the timeline shows
Mirela's Sleep as an ongoing span once initiative is rolled, and the spell interrupted, with why, once the round is
released."""

import pytest

from delve.config import Config
from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.play import seats
from delve.play.timeline import timeline_for
from delve.storage import open_storage
from tests.e2e.fake_play_server import FIGHT
from tests.e2e.scripted import load, start_campaign
from tests.fixtures.rulesets import osric_catalogs

pytestmark = pytest.mark.slow


@pytest.fixture
def played(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    storage = open_storage(config)
    campaign = start_campaign(storage, load("first_session"))
    rng = SeededRng(5)
    host = ToolHost(storage, lambda: rng, catalogs=osric_catalogs())

    def until(tool: str | None) -> None:
        """Every tool step of the fight up to (and not with) `tool`; None for all."""
        while steps and steps[0].get("tool") != tool:
            step = steps.pop(0)
            if "tool" in step:
                result = host.call(campaign.id, "beat-fight", step["tool"], step["args"])
                assert "error" not in result, (step["tool"], result)

    steps = list(FIGHT)
    yield storage, campaign, until
    storage.close()


def mirela(storage, campaign):
    fight = timeline_for(storage, campaign.id, seats.owner_seat(storage, campaign.id))["fight"]
    return fight, next(s for s in fight["slots"] if s["name"] == "Mirela")


def test_the_fight_shows_the_spell_ongoing_then_interrupted(played):
    storage, campaign, until = played
    until("interrupt")
    fight, slot = mirela(storage, campaign)
    assert fight["round"] == 1 and fight["released"] is False
    assert {s["name"] for s in fight["slots"]} == {"Mirela", "Tansy", "Goblin 1", "Goblin 2"}
    assert slot["ongoing"]["what"] == "Sleep" and slot["ongoing"]["state"] == "ongoing"
    assert slot["ongoing"]["to"] == slot["count"]

    until(None)
    _, slot = mirela(storage, campaign)
    assert slot["ongoing"]["state"] == "ongoing", "not before the DM has told the round"
    id = storage.combats.live(campaign.id)[0]
    assert storage.combat_rounds.release(id, 1, "2026-10-25T12:00:00+00:00")
    fight, slot = mirela(storage, campaign)
    assert fight["released"] is True
    assert (slot["ongoing"]["state"], slot["ongoing"]["reason"]) == ("interrupted", "Mirela was hit")

