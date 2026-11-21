"""Prestige classes and XP (DEL-389 part 4). The SRD: "Prestige classes ... do not count against a character when
determining multiclass XP penalties"; ECL and the 20th-level cap count every class level, prestige included."""

from __future__ import annotations

import pytest
from delve_srd35.engine import numbers, progress
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import CharacterState, Sheet

REF = Srd35Reference()
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def sheet(race: str, levels: dict[str, int], **build) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    return Sheet(label="Hero", cls=cls, race=race, levels=levels, hp_max=20, ability_scores=TEN, d20=build)


def test_prestige_levels_take_no_xp_penalty():
    # Human fighter 6 / wizard 1 / eldritch knight 3. The eldritch knight is set aside: the classes that count are
    # fighter 6 and wizard 1. A human's favoured class "any" is the highest of them, fighter, and is excluded; the
    # wizard is then alone, so there is nothing two levels below anything: no penalty. (Were the eldritch knight
    # counted, wizard 1 vs EK 3 would cost 20%.) ECL is 10.
    character = sheet("Human", {"fighter": 6, "wizard": 1, "eldritch knight": 3})
    assert progress.xp_penalty(character, REF) == 0
    assert numbers.ecl(character, REF) == 10


def test_prestige_class_is_not_the_highest_either():
    # Dwarf rogue 3 / wizard 1 / arcane trickster 2: the dwarf's favoured class is fighter (none here). Rogue 3 and
    # wizard 1 count: wizard is two below rogue, 20%. The arcane trickster neither adds a penalty of its own nor
    # (at 2) changes the highest; were arcane trickster 5 counted as the highest, wizard and rogue would both be two below it: 40%.
    low = sheet("Dwarf", {"rogue": 3, "wizard": 1, "arcane trickster": 2})
    assert progress.xp_penalty(low, REF) == 20
    high = sheet("Dwarf", {"rogue": 3, "wizard": 1, "arcane trickster": 5})
    assert progress.xp_penalty(high, REF) == 20


def test_rogue_10_assassin_10_is_the_top():
    # 10 + 10 = ECL 20: the last level, no 21st.
    character = sheet("Human", {"rogue": 10, "assassin": 10})
    assert numbers.ecl(character, REF) == 20
    assert progress.top(character, REF)
    assert progress.xp_penalty(character, REF) == 0
    result = progress.progress(character, CharacterState(xp=190_000), REF)
    assert result.xp_next is None


def test_no_21st_level_through_any_class():
    # The top holds for the total: rogue 10 / assassin 10 takes no 11th rogue level, nor an 11th assassin level.
    character = sheet("Human", {"rogue": 10, "assassin": 10})
    for cls in ("rogue", "assassin", "fighter"):
        with pytest.raises(Exception, match="20th level, the top"):
            progress.level_up(character, cls, REF, Dice(ScriptedRng([]), MemoryRollLog(), "c", "beat"))


def test_a_level_past_the_class_table_is_refused_not_raised():
    # An archmage's table ends at 5th: a 6th is the DM's refusal (a CheckError the tool host answers with), not a
    # crash, though the character (wizard 13 / archmage 5, ECL 18) is below the top. So for a 10-level class's 11th.
    from delve.rules.classic.checks import CheckError

    no_dice = Dice(ScriptedRng([]), MemoryRollLog(), "c", "beat")
    for levels, cls, past in (({"wizard": 13, "archmage": 5}, "archmage", 6), ({"rogue": 5, "assassin": 10},
                                                                                 "assassin", 11)):  # fmt: skip
        with pytest.raises(CheckError, match=f"table has no level {past}"):
            progress.level_up(sheet("Human", levels), cls, REF, no_dice)
