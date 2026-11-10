"""Dice: notation, its limits, the roll log and the no-re-roll rule within a beat (spec §6.5).

The notation cases that aren't about limits are ttrpg2's `RollTests` (`tests/test_char_dice.py`), with `ScriptedRng`
in place of its `Script`.
"""

import pytest

from delve.dice import (
    BadNotation,
    Dice,
    MemoryRollLog,
    NotationTooLarge,
    Roll,
    RollKey,
    RollLog,
    ScriptedRng,
    ScriptExhausted,
    SeededRng,
    SystemRng,
    parse,
)


def dice(*values: int, beat: str = "beat-1", log: MemoryRollLog | None = None) -> Dice:
    return Dice(ScriptedRng(values), log if log is not None else MemoryRollLog(), "cmp_000000000001", beat)


def test_parse_variants():
    n = parse("2d6")
    assert (n.count, n.sides, n.drop_lowest, n.keep_highest, n.modifier) == (2, 6, 0, 0, 0)
    n = parse("d8+2-1")
    assert (n.count, n.sides, n.modifier) == (1, 8, 1)
    n = parse(" 2D6 + 3 ")
    assert (n.count, n.sides, n.modifier, n.text) == (2, 6, 3, "2D6 + 3")
    assert parse("4d6dl").drop_lowest == 1
    assert parse("4d6dl1").drop_lowest == 1
    assert parse("5d6dl2+1").drop_lowest == 2 and parse("5d6dl2+1").modifier == 1
    assert parse("2d20kh1").keep_highest == 1
    n = parse("d%")
    assert (n.count, n.sides) == (1, 100)
    assert (parse("2d%").count, parse("2d%").sides) == (2, 100)
    assert (parse("0d6+4").count, parse("0d6+4").modifier) == (0, 4)
    for bad in ("2d6*2", "3", "d", "2d", "banana", "1d6+x", "", "1d0", "4d6dl4", "2d6kh3", "4d6dl1kh2"):
        with pytest.raises(BadNotation) as caught:
            parse(bad)
        assert caught.value.hint


def test_ttrpg2_roll_shapes():
    """ttrpg2 `RollTests`: plain rolls, stacked modifiers, the first lowest die dropped, negative totals."""
    roll = dice(3, 4).roll("2d6", purpose="test")
    assert (roll.notation, roll.faces, roll.kept, roll.modifier, roll.total) == ("2d6", (3, 4), (3, 4), 0, 7)
    assert dice(5).roll("d8+2-1", purpose="test").total == 6
    assert dice(2, 3).roll(" 2D6 + 3 ", purpose="test").notation == "2D6 + 3"

    four = dice(5, 2, 6, 2).roll("4d6dl", purpose="test")
    assert (four.faces, four.kept, four.dropped, four.total) == ((5, 2, 6, 2), (5, 6, 2), (2,), 13)
    assert dice(5, 2, 6, 3).roll("4d6dl+1", purpose="test").total == 15
    assert dice(4).roll("1d6dl", purpose="test").dropped == ()
    assert dice(2).roll("1d4-10", purpose="test").total == -8
    assert dice().roll("0d6+4", purpose="test").total == 4


def test_times_and_dice_asked():
    rng = ScriptedRng([6, 6, 6, 1, 2, 3, 4, 4, 4, 4, 1, 1])
    rolls = Dice(rng, MemoryRollLog(), "cmp_000000000001", "beat-1").roll("3d6", purpose="abilities", times=4)
    assert [r.total for r in rolls] == [18, 6, 12, 6]
    assert [r.key.purpose for r in rolls] == ["abilities#1", "abilities#2", "abilities#3", "abilities#4"]
    assert rng.calls == [(1, 6)] * 12
    with pytest.raises(BadNotation):
        dice().roll("1d6", purpose="test", times=0)


def test_keep_highest_and_percentile():
    roll = dice(3, 17).roll("2d20kh1", purpose="advantage")
    assert (roll.kept, roll.total) == ((17,), 17)
    rng = ScriptedRng([42])
    assert Dice(rng, MemoryRollLog(), "cmp_000000000001", "b").roll("d%", purpose="skill").total == 42
    assert rng.calls == [(1, 100)]


def test_limits_refused():
    """Fixes ttrpg2 `test_known_bug_dice_count_has_no_upper_bound`: `roll('999999999d6')` hung the server.

    Rule: spec §6.5, "notation has limits, so 999999999d6 is refused": at most 100 dice of at most 1000 sides,
    repeated at most 20 times."""
    for notation in ("101d6", "1d1001", "999999999d6"):
        with pytest.raises(NotationTooLarge) as caught:
            parse(notation)
        assert caught.value.hint
    assert parse("100d1000").count == 100
    with pytest.raises(NotationTooLarge):
        dice().roll("1d6", purpose="test", times=21)
    assert len(dice(*[1] * 20).roll("1d6", purpose="test", times=20)) == 20


def test_table_die_past_the_notation_limit():
    """An encounter table of 27136 lines is one exact die, logged once per key; notation stays capped."""
    log = MemoryRollLog()
    rng = ScriptedRng([20000])
    roll = Dice(rng, log, "cmp_000000000001", "beat-1").table(27136, purpose="encounter:table")
    again = Dice(ScriptedRng([]), log, "cmp_000000000001", "beat-1").table(27136, purpose="encounter:table")
    assert (roll.notation, roll.total, again) == ("1d27136", 20000, roll)
    assert rng.calls == [(1, 27136)] and len(log.rolls) == 1
    with pytest.raises(NotationTooLarge):
        dice().table(1_000_001, purpose="encounter:table")
    with pytest.raises(NotationTooLarge):
        dice().roll("1d27136", purpose="encounter:table")


def test_drop_lowest_keeps_faces():
    roll = dice(1, 5, 1, 6, 3).roll("5d6dl2", purpose="test")
    assert roll.faces == (1, 5, 1, 6, 3)
    assert roll.kept == (5, 6, 3) and roll.dropped == (1, 1) and roll.total == 14


def test_same_key_same_beat_returns_stored_roll():
    """Fixes ttrpg2 `test_known_bug_roll_is_not_logged_and_can_be_repeated_freely`.

    Rule: spec §6.5 (ttrpg2's Hard Constraint #3, no re-rolls): every roll is logged, and a repeat of the same roll
    (same actor, purpose, target and combat round) within the same beat returns the stored result."""
    log = MemoryRollLog()
    first = dice(1, log=log).roll("1d20", purpose="save:spell", actor="chr_aaaaaaaaaaaa", target="chr_bbbbbbbbbbbb")
    again = dice(20, log=log).roll("1d20", purpose="save:spell", actor="chr_aaaaaaaaaaaa", target="chr_bbbbbbbbbbbb")
    assert again == first and again.total == 1
    assert len(log.rolls) == 1
    other_target = dice(20, log=log).roll("1d20", purpose="save:spell", actor="chr_aaaaaaaaaaaa", target="mon_1")
    assert other_target.total == 20 and len(log.rolls) == 2


def test_new_round_rolls_fresh():
    log = MemoryRollLog()
    one = dice(4, log=log).roll("1d20", purpose="save:spell", actor="mon_1", combat_round=1)
    two = dice(15, log=log).roll("1d20", purpose="save:spell", actor="mon_1", combat_round=2)
    assert (one.total, two.total) == (4, 15)
    assert (one.key.combat_round, two.key.combat_round) == (1, 2)
    assert len(log.rolls) == 2


def test_new_beat_rolls_fresh():
    log = MemoryRollLog()
    one = dice(4, beat="beat-1", log=log).roll("1d20", purpose="attack", actor="chr_aaaaaaaaaaaa")
    two = dice(15, beat="beat-2", log=log).roll("1d20", purpose="attack", actor="chr_aaaaaaaaaaaa")
    assert (one.total, two.total) == (4, 15)
    assert (one.key.beat, two.key.beat) == ("beat-1", "beat-2")


def test_every_roll_is_logged_with_its_key():
    log = MemoryRollLog()
    roll = dice(7, log=log).d(8, purpose="damage", actor="chr_aaaaaaaaaaaa", target="mon_2", combat_round=3)
    [(campaign_id, logged)] = log.rolls
    assert campaign_id == "cmp_000000000001" and logged == roll
    assert roll.key == RollKey(
        beat="beat-1", actor="chr_aaaaaaaaaaaa", purpose="damage", target="mon_2", combat_round=3
    )
    assert (roll.notation, roll.faces, roll.total) == ("1d8", (7,), 7)
    assert roll.id.startswith("roll_") and roll.at
    assert isinstance(log, RollLog)


def test_roll_is_frozen():
    roll = dice(3).d(6, purpose="test")
    assert isinstance(roll, Roll)
    with pytest.raises(AttributeError):
        roll.total = 6  # type: ignore[misc]


def test_seeded_is_deterministic():
    def totals(seed: int) -> list[int]:
        d = Dice(SeededRng(seed), MemoryRollLog(), "cmp_000000000001", "b")
        return [r.total for r in d.roll("3d6", purpose="abilities", times=6)]

    assert totals(7) == totals(7)
    assert totals(7) != totals(8)


def test_system_rng_in_range():
    rng = SystemRng()
    values = {rng.randint(1, 4) for _ in range(200)}
    assert values == {1, 2, 3, 4}


def test_scripted_exhaustion_raises():
    rng = ScriptedRng([3])
    assert rng.randint(1, 6) == 3
    with pytest.raises(ScriptExhausted):
        rng.randint(1, 6)
    with pytest.raises(ScriptExhausted):
        ScriptedRng([7]).randint(1, 6)  # a value that doesn't fit the die
    rng = ScriptedRng([2, 5])
    rng.randint(1, 6)
    with pytest.raises(ScriptExhausted):
        rng.assert_done()
