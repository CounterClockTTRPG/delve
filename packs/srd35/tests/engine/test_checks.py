"""The 3.5 engine's saves, skill checks and ability checks (DEL-388): d20 + the total + the modifier against a DC, by the
SRD's rules. Each worked example is checked by hand in its comment."""

from __future__ import annotations

import pytest
from delve_srd35.engine import Srd35Engine
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import Sheet
from delve.rules.classic.checks import CheckError, CheckResult, SaveResult
from delve.rules.classic.combat import Combatant

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def dice(*faces: int) -> Dice:
    return Dice(ScriptedRng(faces), MemoryRollLog(), "c", "beat")


def filled(cls: str, race: str, levels: dict[str, int], abilities: dict[str, int], d20: dict) -> Sheet:
    return ENGINE.fill_derived(
        Sheet(cls=cls, race=race, levels=levels, ability_scores={**TEN, **abilities}, d20=d20), REF
    )


def dwarf_fighter_3(**d20) -> Sheet:
    # Fort 3 + Con 3 = 6, Ref 1 + Dex 1 = 2, Will 1 + Wis 0 = 1; scale mail and a heavy steel shield, ACP -6.
    return filled("Fighter", "Dwarf", {"fighter": 3}, {"str": 16, "dex": 12, "con": 16},
                  {"armor": "scale mail", "shield": "shield, heavy steel", **d20})  # fmt: skip


def orc() -> Combatant:
    return Combatant("mon_1", "Orc 1", "enemy", d20={"saves": {"fort": 3, "ref": 0, "will": -2}})


def test_will_save_against_sleep_dc():
    # A 1st-level wizard with Int 16 casts sleep at DC 10 + 1 + 3 = 14. The orc's Will is -2: a 15 is 13, and fails.
    wizard = filled("Wizard", "Human", {"wizard": 1}, {"int": 16}, {})
    dc = wizard.d20["derived"]["dc"]["1"]
    assert dc == 14
    out = ENGINE.save(orc(), "will", dc, 0, dice(15), actor="mon_1")
    assert isinstance(out, SaveResult)
    assert (out.success, out.roll.total, out.base, out.total, out.needed, out.name) == (False, 15, -2, 13, 16, "Will")
    assert ENGINE.save(orc(), "Will", dc, 0, dice(16), actor="mon_1").success  # 16 - 2 = 14 meets 14


def test_a_sheets_save_and_its_names():
    # The dwarf's Fort is 6: 9 + 6 + 1 = 16 against 16 succeeds; "fortitude" and "Reflex" name the saves too.
    out = ENGINE.save(dwarf_fighter_3(), "fortitude", 16, 1, dice(9), actor="pc_1", combat_round=2)
    assert (out.success, out.save_type, out.base, out.modifier, out.total) == (True, "fort", 6, 1, 16)
    assert out.roll.key.purpose == "save:fort" and out.roll.key.combat_round == 2
    assert ENGINE.save(dwarf_fighter_3(), "Reflex", None, 0, dice(10), actor="pc_1").base == 2
    with pytest.raises(CheckError, match="Unknown save"):
        ENGINE.save(dwarf_fighter_3(), "breath", 10, 0, dice(10), actor="pc_1")


def test_natural_one_fails_any_save():
    # The dwarf's Fort 6 + 20 = 27 on a 1 is 7 + 20 = 27 against DC 2, and still fails; a 20 against DC 40 succeeds.
    assert not ENGINE.save(dwarf_fighter_3(), "fort", 2, 20, dice(1), actor="pc_1").success
    assert ENGINE.save(orc(), "will", 40, 0, dice(20), actor="mon_1").success


def test_a_save_without_a_dc_answers_the_total():
    out = ENGINE.save(dwarf_fighter_3(), "will", None, 2, dice(12), actor="pc_1")
    assert (out.success, out.total, out.needed, out.dc) == (False, 15, None, None)  # 12 + Will 1 + 2


def test_negative_levels_take_one_each_from_saves_skills_and_abilities():
    # Two negative levels: Will 1 - 2, Climb 3 ranks + Str 3 - ACP 6 - 2, Str 3 - 2.
    drained = dwarf_fighter_3(skills={"climb": 3}, negative_levels=2)
    save = ENGINE.save(drained, "will", None, 0, dice(10), actor="pc_1")
    assert (save.base, save.modifier, save.total) == (1, -2, 9)
    climb = ENGINE.skill_check(drained, "climb", None, 0, dice(10), actor="pc_1", occasion="")
    assert (climb.bonus, climb.modifier, climb.total) == (0, -2, 8)
    strength = ENGINE.ability_check(drained, "str", None, 0, dice(10), actor="pc_1", occasion="")
    assert (strength.bonus, strength.modifier, strength.total) == (3, -2, 11)


def test_trained_only_without_ranks_refuses():
    out = ENGINE.skill_check(dwarf_fighter_3(), "open-lock", 15, 0, dice(), actor="pc_1", occasion="the door")
    assert isinstance(out, CheckResult)
    assert (out.success, out.roll, out.total, out.all_rolls) == (False, None, None, ())
    assert "trained" in out.note and "Open Lock" in out.note
    # With ranks it rolls: 2 ranks + Dex 1 - no ACP (Open Lock has none) = 3; 12 + 3 = 15 meets 15.
    trained = ENGINE.skill_check(dwarf_fighter_3(skills={"open-lock": 2}), "Open Lock", 15, 0, dice(12),
                                 actor="pc_1", occasion="the door")  # fmt: skip
    assert (trained.success, trained.bonus, trained.total, trained.note) == (True, 3, 15, "")
    assert trained.roll.key.purpose == "skill:open-lock#the door"


def test_armour_check_penalty_in_climb():
    # Climb: 3 ranks + Str 3 - ACP 6 = 0. Untrained, Climb is Str 3 - ACP 6 = -3: the armour weighs on it all the same.
    out = ENGINE.skill_check(dwarf_fighter_3(skills={"climb": 3}), "climb", 10, 0, dice(10), actor="pc_1", occasion="")
    assert (out.bonus, out.total, out.success, out.name) == (0, 10, True, "Climb")
    untrained = ENGINE.skill_check(dwarf_fighter_3(), "climb", 10, 2, dice(10), actor="pc_1", occasion="")
    assert (untrained.bonus, untrained.modifier, untrained.total, untrained.success) == (-3, 2, 9, False)


def test_natural_one_and_twenty_are_not_special_on_skills():
    # Intimidate 10 ranks + Cha 0 = 10: a 1 is 11, meeting DC 11; a 20 is 30, short of DC 31.
    sheet = dwarf_fighter_3(skills={"intimidate": 10})
    assert ENGINE.skill_check(sheet, "intimidate", 11, 0, dice(1), actor="pc_1", occasion="").success
    assert not ENGINE.skill_check(sheet, "intimidate", 31, 0, dice(20), actor="pc_1", occasion="").success
    with pytest.raises(CheckError, match="Unknown skill"):
        ENGINE.skill_check(sheet, "basket weaving", 10, 0, dice(10), actor="pc_1", occasion="")


def test_an_ability_check_is_the_modifier_and_the_modifier_given():
    # Str 16 is +3: 8 + 3 - 1 = 10 against DC 10 succeeds; Wis 10 is +0.
    out = ENGINE.ability_check(dwarf_fighter_3(), "str", 10, -1, dice(8), actor="pc_1", occasion="the gate")
    assert (out.success, out.bonus, out.modifier, out.total, out.name) == (True, 3, -1, 10, "str")
    assert out.roll.key.purpose == "ability:str#the gate"
    assert ENGINE.ability_check(dwarf_fighter_3(), "wis", None, 0, dice(8), actor="pc_1", occasion="").total == 8
    with pytest.raises(CheckError, match="Unknown ability"):
        ENGINE.ability_check(dwarf_fighter_3(), "luck", 10, 0, dice(8), actor="pc_1", occasion="")


def test_a_combatant_without_saves_is_refused():
    with pytest.raises(CheckError, match="no saves"):
        ENGINE.save(Combatant("mon_2", "Rat", "enemy"), "fort", 10, 0, dice(10), actor="mon_2")
