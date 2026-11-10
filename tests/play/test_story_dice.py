"""The dice a tool row shows to each seat (DEL-270, `delve.play.story_dice`), and how the beat runner puts the ids of
a call's rolls on its row (`feed_entry_for`, with the dice the tool host left for it)."""

import pytest

from delve.dice import Dice, ScriptedRng
from delve.dm.provider import ToolCall, ToolResult
from delve.dm.tools import all_specs
from delve.play import table
from delve.play.story_dice import SeatDice, bookkeeping

SPECS = {spec.name: spec for spec in all_specs()}


@pytest.fixture
def garrek(storage, campaign):
    return storage.characters.create(campaign.id, "Garrek")


@pytest.fixture
def grik(storage, campaign):
    return storage.characters.create(campaign.id, "Grik", kind="npc")


@pytest.fixture
def roll(storage, campaign):
    """`roll(notation, purpose, actor=None, faces=(…))`: a roll logged for the campaign, with the faces given."""

    def make(notation, purpose, actor=None, faces=(10,), beat="beat-1"):
        return Dice(ScriptedRng(faces), storage.rolls, campaign.id, beat).roll(notation, purpose=purpose, actor=actor)

    return make


def view(storage, campaign, role, payload, enemy_dice="screen"):
    return SeatDice(storage, campaign.id, role, enemy_dice).row(payload)


def test_the_host_reads_every_roll_without_its_modifier(storage, campaign, garrek, roll):
    attack = roll("1d20+3", "attack#1", garrek.id, faces=(14,))
    hp = roll("2d8", "hp", "mon_1", faces=(3, 5))
    row = {"name": "resolve_attack", "rolls": [attack.id, hp.id], "call_id": "toolu_1"}
    shown = view(storage, campaign, "host", row)
    assert shown == {
        "name": "resolve_attack",
        "dice": [
            {"who": "Garrek", "side": None, "what": "attack", "detail": None, "dice": "d20", "faces": [14], "total": 14},
            {"who": None, "side": "enemy", "what": "hp", "detail": None, "dice": "2d8", "faces": [3, 5], "total": 8},
        ],
    }, "no modifier, no id, no call id; a monster of no fight is an enemy"


def test_others_read_the_partys_dice_and_never_the_bookkeeping(storage, campaign, garrek, grik, roll):
    ours = roll("1d20", "ability:str#the door", garrek.id)
    side = roll("1d10", "initiative", "side:party")
    theirs = roll("1d20", "attack#1", "mon_2")
    npc = roll("2d10", "reaction", grik.id, faces=(4, 9))
    free = roll("3d20", "Reggi wrestling, three falls", None, faces=(14, 7, 18))
    garreks_hp = roll("1d10", "hp", garrek.id)
    weather = roll("1d100", "weather:temperate:day 3", None)
    row = {"name": "roll", "rolls": [ours.id, side.id, theirs.id, npc.id, free.id, garreks_hp.id, weather.id]}
    for role in ("cohost", "player", "observer"):
        lines = view(storage, campaign, role, row)["dice"]
        assert [(line["who"], line["side"], line["what"]) for line in lines] == [
            ("Garrek", None, None),
            (None, "party", None),
        ], role
    opened = view(storage, campaign, "player", row, "open")["dice"]
    assert [line["detail"] for line in opened] == [
        "ability:str#the door",
        "initiative",
        "attack#1",
        "reaction",
        "Reggi wrestling, three falls",
    ], "the free roll's purposes are the DM's words; the enemies' and the DM's own dice in the open"
    assert opened[-1]["faces"] == [14, 7, 18] and opened[-1]["total"] == 39 and opened[-1]["dice"] == "3d20"
    assert len(view(storage, campaign, "host", row)["dice"]) == 7


def test_delves_purposes_read_as_words(storage, campaign, garrek, roll):
    rolls = [
        roll("1d20", "attack#2", garrek.id),
        roll("1d8", "damage#2", garrek.id, faces=(6,)),
        roll("1d20", "save:paralysis_poison_death", garrek.id),
        roll("1d100", "skill:move_silently#the hall", garrek.id),
        roll("1d10", "surprise:party"),
        roll("1d10", "surprise:enemies"),
        roll("4d6dl1", "something else", garrek.id, faces=(1, 4, 5, 6)),
    ]
    lines = view(storage, campaign, "host", {"name": "resolve_attack", "rolls": [r.id for r in rolls]})["dice"]
    assert [(line["side"], line["what"], line["detail"]) for line in lines] == [
        (None, "attack", None),
        (None, "damage", None),
        (None, "save", "paralysis poison death"),
        (None, "skill", "move silently"),
        ("party", "surprise", None),
        ("enemies", "surprise", None),
        (None, None, "something else"),
    ]
    assert (lines[-1]["dice"], lines[-1]["faces"], lines[-1]["total"]) == ("4d6dl1", [1, 4, 5, 6], 15)


def test_a_monster_is_named_from_its_fight(storage, campaign, roll):
    fight = storage.combats.create(campaign.id, "active", {"combatants": {"mon_1": {"name": "Goblin 1"}}})
    attack = roll("1d20", "attack#1", "mon_1", beat=f"beat-1/{fight}")
    gone = roll("1d20", "attack#1", "mon_1", beat="beat-1/cmb_000000000000")
    lines = view(storage, campaign, "host", {"name": "resolve_attack", "rolls": [attack.id, gone.id]})["dice"]
    assert [(line["who"], line["side"]) for line in lines] == [("Goblin 1", None), (None, "enemy")]


def test_a_secret_checks_dice_are_the_hosts(storage, campaign, garrek, roll):
    check = roll("1d100", "skill:hide_in_shadows", garrek.id)
    row = {"name": "skill_check", "rolls": [check.id], "secret": True}
    assert view(storage, campaign, "host", row)["dice"][0]["what"] == "skill"
    assert view(storage, campaign, "cohost", row, "open") == {"name": "skill_check"}
    assert view(storage, campaign, "player", row, "open") is None, "a player sees no row without dice for them"


def test_with_the_dice_hidden_only_the_host_reads_any(storage, campaign, garrek, roll):
    """DEL-280: the host's `show_dice` off, the story is in words alone for every other seat, the enemies' dice in the
    open or not; a co-host still sees the row, a player or an observer no row at all."""
    ours = roll("1d20", "attack#1", garrek.id, faces=(17,))
    theirs = roll("1d20", "attack#1", "mon_1")
    row = {"name": "resolve_attack", "rolls": [ours.id, theirs.id]}
    hidden = {"show_dice": False}
    assert len(SeatDice(storage, campaign.id, "host", **hidden).row(row)["dice"]) == 2
    assert SeatDice(storage, campaign.id, "cohost", "open", **hidden).row(row) == {"name": "resolve_attack"}
    for role in ("player", "observer"):
        assert SeatDice(storage, campaign.id, role, "open", **hidden).row(row) is None, role
    assert len(view(storage, campaign, "player", row)["dice"]) == 1, "shown, the party's own"


def test_a_batchs_steps_show_their_own_dice(storage, campaign, garrek, roll):
    ours = roll("1d20", "ability:dex", garrek.id)
    theirs = roll("1d20", "save:spell", "mon_1")
    row = {
        "name": "batch",
        "steps": [
            {"step": 0, "name": "ability_check", "rolls": [ours.id]},
            {"step": 1, "name": "get_character"},
            {"step": 2, "name": "saving_throw", "rolls": [theirs.id], "failed": True},
        ],
    }
    host = view(storage, campaign, "host", row)
    assert [len(step.get("dice", [])) for step in host["steps"]] == [1, 0, 1]
    assert host["steps"][2]["failed"] is True and "rolls" not in str(host)
    cohost = view(storage, campaign, "cohost", row)
    assert [len(step.get("dice", [])) for step in cohost["steps"]] == [1, 0, 0]
    player = view(storage, campaign, "player", row)
    assert player == {"name": "batch", "steps": [{"step": 0, "name": "ability_check", "dice": host["steps"][0]["dice"]}]}


def test_a_refused_row_and_a_row_from_before(storage, campaign, garrek, roll):
    ours = roll("1d20", "ability:dex", garrek.id)
    refused = {"name": "ability_check", "failed": True, "rolls": [ours.id]}
    assert view(storage, campaign, "host", refused)["failed"] is True
    assert view(storage, campaign, "cohost", refused) is None and view(storage, campaign, "player", refused) is None
    assert view(storage, campaign, "host", {"name": "roll"}) == {"name": "roll"}
    assert view(storage, campaign, "cohost", {"name": "roll"}) == {"name": "roll"}
    assert view(storage, campaign, "player", {"name": "roll"}) is None


def test_a_reused_roll_shows_on_each_row(storage, campaign, garrek, roll):
    """The same key again in the beat is the stored roll (a Retry): each row that got it shows it."""
    first = roll("1d20", "ability:str", garrek.id, faces=(9,))
    again = roll("1d20", "ability:str", garrek.id, faces=())
    assert again.id == first.id
    for row in ({"name": "ability_check", "rolls": [first.id]}, {"name": "ability_check", "rolls": [again.id]}):
        assert view(storage, campaign, "player", row)["dice"][0]["faces"] == [9]


def test_bookkeeping():
    for purpose in ("weather:x:day 1", "encounter:check#day 1", "treasure:A#1.2", "merchant tier #1", "hp"):
        assert bookkeeping(purpose), purpose
    for purpose in ("hp of the rope", "attack#1", "the merchant's dog"):
        assert not bookkeeping(purpose), purpose


def test_the_row_keeps_the_ids_the_host_left_for_its_call():
    taken: list = []

    def dice(name, args):
        taken.append((name, args))
        return {"rolls": ["roll_a"]} if name == "skill_check" else {"steps": {0: ["roll_b"], 1: ["roll_c"]}}

    pending = table.PendingCalls("cmp_1", "beat-1", dice=dice)
    args = {"character": "Pippa", "skill": "hide", "secret": True}
    table.feed_entry_for(ToolCall("t1", "skill_check", args), SPECS.get, pending)
    row = table.feed_entry_for(ToolResult("t1", True, "{}"), SPECS.get, pending)
    assert row.payload == {"name": "skill_check", "call_id": "t1", "rolls": ["roll_a"], "secret": True}
    steps = [
        {"tool": "encounter_check", "args": {"terrain": "dungeon"}},
        {"tool": "ability_check", "args": {"character": "Garrek", "ability": "str"}},
    ]
    table.feed_entry_for(ToolCall("t2", "batch", {"steps": steps}), SPECS.get, pending)
    row = table.feed_entry_for(ToolResult("t2", True, '{"results": []}'), SPECS.get, pending)
    assert row.payload["steps"] == [{"step": 1, "name": "ability_check", "failed": True, "rolls": ["roll_c"]}], (
        "a DM-only step and its dice stay out"
    )
    assert [name for name, _ in taken] == ["skill_check", "batch"]
    # Without the host's dice (a replay of the DM log), a row is as it was.
    plain = table.PendingCalls("cmp_1", "beat-1")
    table.feed_entry_for(ToolCall("t3", "roll", {"notation": "1d6", "purpose": "x"}), SPECS.get, plain)
    assert table.feed_entry_for(ToolResult("t3", True, "{}"), SPECS.get, plain).payload == {
        "name": "roll",
        "call_id": "t3",
    }


def test_scouts_dice_are_secret_unless_the_call_says_otherwise():
    """DEL-273: scout rolls Move Silently, Hide in Shadows and Detect Noise, checks the character can't know the
    result of; its dice showed to every seat. They are secret by default; `secret: false` shows them, in a batch too."""
    pending = table.PendingCalls("cmp_1", "beat-1", dice=lambda name, args: {"rolls": ["roll_a"]})
    table.feed_entry_for(ToolCall("t1", "scout", {"character": "Pippa"}), SPECS.get, pending)
    assert table.feed_entry_for(ToolResult("t1", True, "{}"), SPECS.get, pending).payload["secret"] is True
    table.feed_entry_for(ToolCall("t2", "scout", {"character": "Pippa", "secret": False}), SPECS.get, pending)
    assert "secret" not in table.feed_entry_for(ToolResult("t2", True, "{}"), SPECS.get, pending).payload
    table.feed_entry_for(ToolCall("t3", "roll", {"notation": "1d6", "purpose": "x"}), SPECS.get, pending)
    assert "secret" not in table.feed_entry_for(ToolResult("t3", True, "{}"), SPECS.get, pending).payload

    batched = table.PendingCalls("cmp_1", "beat-1", dice=lambda name, args: {"steps": {0: ["roll_b"]}})
    steps = [{"tool": "scout", "args": {"character": "Pippa"}}]
    table.feed_entry_for(ToolCall("t4", "batch", {"steps": steps}), SPECS.get, batched)
    (step,) = table.feed_entry_for(ToolResult("t4", True, '{"results": []}'), SPECS.get, batched).payload["steps"]
    assert step["secret"] is True


def test_a_pcs_own_roll_shows_to_the_players(storage, campaign, garrek, roll):
    """DEL-274: the free roll had no actor, so a PC's contest ("Reggi wrestling, three falls") stayed behind the
    screen. With the PC as its actor it shows like the party's other dice; the DM's own roll still doesn't."""
    theirs = roll("3d20", "Garrek wrestling, three falls", garrek.id, faces=(14, 7, 18))
    mine = roll("1d6", "the ogre's mood", faces=(3,))
    row = {"name": "roll", "rolls": [theirs.id]}
    (line,) = view(storage, campaign, "player", row)["dice"]
    assert (line["who"], line["faces"], line["total"]) == ("Garrek", [14, 7, 18], 39)
    assert view(storage, campaign, "player", {"name": "roll", "rolls": [mine.id]}) is None, "the DM's own"
