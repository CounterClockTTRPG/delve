"""`play.quests` (plan 6 Task 5, Decisions 6 and 7): quests, seeded from the module as `available` and not yet known,
known once they turn `active`. Their log notes may be the DM's alone. ttrpg2's scope warnings come over: regional
under an average party level of 4, continental under 8. The primer holds the active quests and the nearest
countdowns."""

import json

import pytest

from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.dm.tools.redact import player_view
from delve.play import characters, factions, quests, sessions
from delve.play.context import NotFound, PlayError
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.play.test_factions import SECRET, SOURCE


@pytest.fixture
def host(storage):
    return ToolHost(storage, lambda: SeededRng(1), catalogs=over(PlayReference()))


@pytest.fixture
def call(host, campaign):
    """`call(tool, **args)`: a tool call on the campaign, in one beat."""
    return lambda tool, /, **args: host.call(campaign.id, "beat-1", tool, args)


@pytest.fixture
def seeded(ctx):
    factions.seed(ctx, SOURCE)
    return ctx


def test_a_quest_becomes_known_when_it_turns_active(seeded):
    ctx = seeded
    out = quests.update_quest(ctx, "find-the-relic", status="active")["quest"]
    assert (out["status"], out["known"], out["started_day"]) == ("active", True, 1)
    paused = quests.update_quest(ctx, "find-the-relic", status="paused", known=False)["quest"]
    assert paused["known"] is False  # the DM may hide it again


def test_a_quest_note_marked_not_known(seeded):
    ctx = seeded
    quests.update_quest(ctx, "find-the-relic", note="The abbot gave them the map.")
    quests.update_quest(ctx, "find-the-relic", note=f"{SECRET}: the map is false.", note_known=False)
    log = ctx.storage.quests.get(ctx.campaign_id, "find-the-relic").log
    assert [(n.day, n.known) for n in log] == [(1, True), (1, False)]
    assert SECRET in log[1].text


def test_a_quest_ends_on_its_day(seeded):
    ctx = seeded
    quests.update_quest(ctx, "find-the-relic", status="active")
    sessions.advance_days(ctx, 3)
    out = quests.update_quest(ctx, "find-the-relic", status="complete", note="The relic is home.")["quest"]
    assert (out["status"], out["ended_day"]) == ("complete", 4)
    with pytest.raises(PlayError):
        quests.update_quest(ctx, "find-the-relic", status="lost")
    with pytest.raises(NotFound) as unknown:
        quests.update_quest(ctx, "the relic", status="active")
    assert unknown.value.candidates == [{"id": "find-the-relic", "name": "Find the relic"}]


def test_add_quest_is_active_and_known_and_warns_on_scope(seeded, call):
    ctx = seeded
    characters.create(ctx, name="Garrek", sheet={"hp_max": 10, "levels": {"fighter": 2}})
    characters.create(ctx, name="Pippa", sheet={"hp_max": 6, "levels": {"thief": 3}})
    added = call("add_quest", id="Rescue Henrik", title="Rescue old Henrik", giver="Tira", stakes="He hangs.")
    assert added["quest"]["id"] == "rescue-henrik"
    assert (added["quest"]["status"], added["quest"]["known"]) == ("active", True)
    assert "warning" not in added
    regional = call("add_quest", id="the-pass", title="Hold the pass", scope="regional")
    assert "regional" in regional["warning"].lower() and "2.5" in regional["warning"]
    continental = call("add_quest", id="iuz", title="Stop Iuz", scope="continental")
    assert "continental" in continental["warning"].lower()
    assert "error" in call("add_quest", id="iuz", title="Again")
    assert "error" in call("add_quest", id="x", title="X", scope="planar")


def test_quests_lists_by_status_with_scope_warnings(seeded, call):
    call("add_quest", id="the-pass", title="Hold the pass", scope="regional")
    listed = call("quests")
    assert [q["id"] for q in listed["quests"]] == ["find-the-relic", "the-pass"]
    assert listed["avg_party_level"] == 1.0
    assert "scope_warning" in listed["quests"][1] and "scope_warning" not in listed["quests"][0]
    assert [q["id"] for q in call("quests", status="available")["quests"]] == ["find-the-relic"]
    assert SECRET in json.dumps(call("quests"))  # the DM's own notes


def test_the_quest_tools_show_the_players_nothing_but_their_names(seeded, call, host):
    """The players may see that a quest changed; what they know of it is the World panel's (Task 12)."""
    assert host.spec("add_quest").player_visible and host.spec("update_quest").player_visible
    assert not host.spec("quests").player_visible
    for name, args in (
        ("update_quest", {"id": "find-the-relic", "note": SECRET, "note_known": False}),
        ("add_quest", {"id": "q", "title": "Q", "stakes": "S"}),
    ):
        result = call(name, **args)
        assert "error" not in result
        assert player_view(host.spec(name), args, result) == {}


def test_the_primer_holds_active_quests_and_the_nearest_countdowns(seeded, call):
    ctx = seeded
    for n in range(6):
        call("add_clock", label=f"clock {n}", days=20 - n)
    call("add_clock", label="the siege", segments=4)
    quests.update_quest(ctx, "find-the-relic", status="active")
    call("add_quest", id="paused", title="Paused one")
    quests.update_quest(ctx, "paused", status="paused")
    primer = call("session_primer")
    assert [q["id"] for q in primer["quests"]] == ["find-the-relic"]
    assert [c["label"] for c in primer["clocks"]] == ["The eye wakes", "clock 5", "clock 4", "clock 3", "clock 2"]


def test_ended_quests_are_short_in_the_whole_list(seeded, call):
    """DEL-79: the whole list was 25 KB in a long campaign. Without a status an ended quest is its id, title, status
    and the day it ended; asked for by status it comes whole, log and notes."""
    call("add_quest", id="the-mill", title="Save the mill", stakes="The village starves.")
    call("update_quest", id="the-mill", note="The miller paid them.", status="complete")
    call("add_quest", id="the-pass", title="Hold the pass")
    listed = {quest["id"]: quest for quest in call("quests")["quests"]}
    assert listed["the-mill"] == {"id": "the-mill", "title": "Save the mill", "status": "complete", "ended_day": 1}
    assert "log" in listed["the-pass"] and "stakes" in listed["the-pass"]
    done = call("quests", status="complete")["quests"]
    assert [q["id"] for q in done] == ["the-mill"] and done[0]["stakes"] == "The village starves." and done[0]["log"]
