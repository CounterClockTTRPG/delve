"""The dice each call rolled, for its story row (DEL-270): the tool host watches every `Dice` a call uses, the fight's
own included, and puts the rolls' ids in its `dice_out`, never in the answer the DM reads. A batch's steps each have
their own. A roll asked again in the beat is the stored roll, and is listed again."""

import itertools

import pytest

from delve.dice import Dice, MemoryRollLog, ScriptedRng, SeededRng, watching
from delve.dm.tools import ToolHost
from delve.dm.tools.rolled import Rolled
from tests.dm.tools.conftest import GARREK, PIPPA
from tests.fixtures.rulesets import osric_catalogs


@pytest.fixture
def out():
    return Rolled()


@pytest.fixture
def run(storage, campaign, out):
    seeds = itertools.count(1)
    host = ToolHost(storage, lambda: SeededRng(next(seeds)), dice_out=out, catalogs=osric_catalogs())

    def call(tool, /, beat="beat-1", **args):
        return host.call(campaign.id, beat, tool, args)

    call("create_character", name="Garrek", sheet=GARREK)
    call("create_character", name="Pippa", sheet=PIPPA)
    return call


def taken(out, campaign, tool, beat="beat-1", **args):
    return out.take(campaign.id, beat, tool, args)


def test_watching_lists_new_and_stored_rolls():
    dice = Dice(ScriptedRng([4, 6, 17]), MemoryRollLog(), "cmp_1", "beat-1")
    with watching() as seen:
        first = dice.d(20, purpose="attack#1", actor="chr_1")
        again = dice.d(20, purpose="attack#1", actor="chr_1")
        other = dice.roll("1d8", purpose="damage#1", actor="chr_1")
    assert again == first and [r.id for r in seen] == [first.id, first.id, other.id]
    assert dice.d(20, purpose="later", actor="chr_1").total == 17  # nothing watches outside
    assert len(seen) == 3


def test_a_call_puts_its_rolls_and_answers_without_them(run, out, campaign, storage):
    answer = run("roll", notation="3d20", purpose="Reggi wrestling, three falls")
    assert "rolls" not in answer and "roll_id" not in str(answer)
    (logged,) = [r for r in storage.rolls.list(campaign.id) if r.key.purpose.startswith("Reggi")]
    assert taken(out, campaign, "roll", notation="3d20", purpose="Reggi wrestling, three falls") == {
        "rolls": [logged.id]
    }
    assert taken(out, campaign, "roll", notation="3d20", purpose="Reggi wrestling, three falls") is None


def test_a_reused_roll_is_put_again(run, out, campaign):
    """The same roll again within the beat (a Retry) is the stored one: its row shows it all the same."""
    run("roll", notation="1d6", purpose="the rope")
    run("roll", notation="1d6", purpose="the rope")
    first = taken(out, campaign, "roll", notation="1d6", purpose="the rope")
    second = taken(out, campaign, "roll", notation="1d6", purpose="the rope")
    assert first == second and len(first["rolls"]) == 1


def test_a_fights_own_dice_are_watched(run, out, campaign, storage):
    run("move_party", to="Entry Hall")
    run("setup_combat", enemies=[{"name": "goblin", "count": 2, "hp": 5}])
    set_up = taken(out, campaign, "setup_combat", enemies=[{"name": "goblin", "count": 2, "hp": 5}])
    purposes = {r.key.purpose for r in storage.rolls.get_many(campaign.id, set_up["rolls"]).values()}
    assert {"initiative", "surprise:party", "surprise:enemies"} <= purposes
    run("resolve_attack", attacker="Garrek", target="Goblin 1")
    attack = taken(out, campaign, "resolve_attack", attacker="Garrek", target="Goblin 1")
    rolls = storage.rolls.get_many(campaign.id, attack["rolls"])
    assert {r.key.purpose for r in rolls.values()} >= {"attack#1"}
    assert all(r.key.beat.startswith("beat-1/") for r in rolls.values()), "the fight's dice, keyed by the fight"


def test_a_batchs_steps_have_their_own_dice(run, out, campaign, storage):
    steps = [
        {"tool": "ability_check", "args": {"character": "Garrek", "ability": "str"}},
        {"tool": "get_character", "args": {"ref": "Garrek"}},
        {"tool": "skill_check", "args": {"character": "Pippa", "skill": "move silently", "secret": True}},
    ]
    run("batch", steps=steps)
    dice = taken(out, campaign, "batch", steps=steps)
    assert set(dice["steps"]) == {0, 1, 2} and dice["steps"][1] == []
    by_step = {i: storage.rolls.get_many(campaign.id, ids) for i, ids in dice["steps"].items()}
    assert [r.key.purpose for r in by_step[0].values()] == ["ability:str"]
    assert [r.key.purpose for r in by_step[2].values()] == ["skill:move_silently"]


def test_a_refused_call_puts_no_dice(run, out, campaign):
    run("skill_check", character="Garrek", skill="juggling")
    assert taken(out, campaign, "skill_check", character="Garrek", skill="juggling") == {"rolls": []}
    run("roll", notation="2d", purpose="x")
    assert taken(out, campaign, "roll", notation="2d", purpose="x") == {"rolls": []}


def test_the_secret_flag_is_a_checks_argument(run):
    out = run("ability_check", character="Garrek", ability="dex", secret=True)
    assert "error" not in out and out["ability"] == "dex"
    assert "error" not in run("skill_check", character="Pippa", skill="hide", secret=True)


def test_rolled_is_bounded_and_forgets_a_beat():
    rolled = Rolled(limit=2)
    for n in range(3):
        rolled.put("cmp_1", "beat-1", "roll", {"n": n}, {"rolls": [str(n)]})
    assert rolled.take("cmp_1", "beat-1", "roll", {"n": 0}) is None, "the oldest went first"
    assert rolled.take("cmp_1", "beat-1", "roll", {"n": 2}) == {"rolls": ["2"]}
    rolled.put("cmp_1", "beat-2", "roll", {}, {"rolls": ["x"]})
    rolled.forget("cmp_1", "beat-1")
    assert rolled.take("cmp_1", "beat-1", "roll", {"n": 1}) is None
    assert rolled.take("cmp_1", "beat-2", "roll", {}) == {"rolls": ["x"]}
