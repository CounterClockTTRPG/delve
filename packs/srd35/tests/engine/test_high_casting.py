"""Prepared casting to 9th-level spells (DEL-389 part 2): the class tables' spells per day to 9th, bonus spells by the
key ability to 9th (the SRD's Table: Ability Modifiers and Bonus Spells), a cleric's domain slot at every level from
1st, the paladin's and ranger's to 4th and the adept's to 5th; a level above the caster's highest is refused. Each
worked example is checked by hand against the SRD's tables in its comment."""

from __future__ import annotations

import sys
from pathlib import Path

from delve_srd35 import data
from delve_srd35.engine import Srd35Engine
from delve_srd35.reference import Srd35Reference

from delve.domain.characters import CharacterState, Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def filled(cls: str, level: int, abilities: dict[str, int], **d20) -> Sheet:
    return ENGINE.fill_derived(
        Sheet(label=cls, cls=cls, race="Human", levels={cls.lower(): level}, ability_scores={**TEN, **abilities},
              d20=d20),
        REF,
    )  # fmt: skip


def test_wizard_9_int_18_slots():
    # Table: The Wizard, 9th: 4 / 4 / 4 / 3 / 2 / 1. Int 18 (+4) gives a bonus spell of 1st to 4th; a 5th-level bonus
    # spell needs Int 20. DCs: 10 + level + 4.
    sheet = filled("Wizard", 9, {"int": 18})
    derived = sheet.d20["derived"]
    assert derived["slots"] == {"0": 4, "1": 5, "2": 5, "3": 4, "4": 3, "5": 1}
    assert derived["dc"] == {"0": 14, "1": 15, "2": 16, "3": 17, "4": 18, "5": 19}
    assert sheet.spell_slots == {0: 4, 1: 5, 2: 5, 3: 4, 4: 3, 5: 1}
    assert ENGINE.can_memorize(sheet, [5], ["Cone of Cold"]) is None
    assert ENGINE.can_memorize(sheet, [4, 4, 4], ["Stoneskin", "Ice Storm", "Dimension Door"]) is None
    assert ENGINE.can_memorize(sheet, [6], ["Disintegrate"]) == "Wizard can cast up to 5th-level spells."


def test_wizard_17_and_20_prepare_9th():
    # Table: The Wizard, 17th: 9th-level 1; 20th: 4 of every level. Int 19 reaches 9th (10 + 9); its +4 gives bonus
    # spells of 1st to 4th only.
    sheet = filled("Wizard", 17, {"int": 19})
    assert sheet.d20["derived"]["slots"]["9"] == 1 and sheet.d20["derived"]["dc"]["9"] == 23
    assert ENGINE.can_memorize(sheet, [9], ["Wish"]) is None
    too_many = ENGINE.can_memorize(sheet, [9, 9], ["Wish", "Gate"])
    assert too_many == "Too many level-9 spells: 2 given, 1 slots available."
    top = filled("Wizard", 20, {"int": 19}).d20["derived"]["slots"]
    assert top == {"0": 4, "1": 5, "2": 5, "3": 5, "4": 5, "5": 4, "6": 4, "7": 4, "8": 4, "9": 4}


def test_an_ability_too_low_for_a_level_gives_none_of_it():
    # Int 18 is under 10 + 9: a 17th-level wizard with it has no 9th-level slots (the SRD: "must have an Intelligence
    # score of at least 10 + the spell level"), and casts up to 8th.
    sheet = filled("Wizard", 17, {"int": 18})
    assert "9" not in sheet.d20["derived"]["slots"] and sheet.d20["derived"]["slots"]["8"] == 2
    assert ENGINE.can_memorize(sheet, [9], ["Wish"]) == "Wizard can cast up to 8th-level spells."


def test_cleric_17_ninth_level_slot_and_domain():
    # Table: The Cleric, 17th: 6 / 5+1 / 5+1 / 5+1 / 5+1 / 4+1 / 4+1 / 3+1 / 2+1 / 1+1. Wis 19 (+4): a bonus spell of
    # 1st to 4th. The domain slot is one of each level 1st to 9th.
    sheet = filled("Cleric", 17, {"wis": 19}, domains=["luck", "destruction"])
    derived = sheet.d20["derived"]
    assert derived["slots"] == {"0": 6, "1": 7, "2": 7, "3": 7, "4": 7, "5": 5, "6": 5, "7": 4, "8": 3, "9": 2}
    assert derived["dc"]["9"] == 23
    # Miracle is cleric 9 (and luck's); implosion is destruction's 9th and cleric 9; gate is cleric 9.
    assert ENGINE.can_memorize(sheet, [9, 9], ["Miracle", "Gate"]) is None
    # Storm of vengeance is cleric 9 too: one 9th-level slot is the domain slot, for luck's or destruction's ninth,
    # so two spells that are neither leave it unfilled.
    assert ENGINE.can_memorize(sheet, [9, 9], ["Miracle", "Implosion"]) is None
    refusal = ENGINE.can_memorize(sheet, [9, 9], ["Gate", "Storm of Vengeance"])
    assert refusal and "domain slot" in refusal and "Miracle" in refusal and "Implosion" in refusal
    assert ENGINE.spell_level(sheet, "Miracle") == 9


def test_cleric_with_wis_18_has_no_9th():
    sheet = filled("Cleric", 17, {"wis": 18}, domains=["luck", "destruction"])
    assert "9" not in sheet.d20["derived"]["slots"]
    assert ENGINE.can_memorize(sheet, [9], ["Miracle"]) == "Cleric can cast up to 8th-level spells."


def test_druid_17_prepares_9th():
    # Table: The Druid, 17th: 9th-level 1. Wis 19.
    sheet = filled("Druid", 17, {"wis": 19})
    assert sheet.d20["derived"]["slots"]["9"] == 1
    assert ENGINE.can_memorize(sheet, [9], ["Shapechange"]) is None


def test_a_7th_level_cleric_prepares_4th_and_not_5th():
    # A 7th-level cleric (Wis 15): 4th-level 1+1, no 5th.
    sheet = filled("Cleric", 7, {"wis": 15}, domains=["war", "good"])
    assert sheet.d20["derived"]["slots"]["4"] == 2 and "5" not in sheet.d20["derived"]["slots"]
    assert ENGINE.can_memorize(sheet, [4, 4], ["Divine Power", "Divine Power"]) is None
    assert ENGINE.can_memorize(sheet, [5], ["Flame Strike"]) == "Cleric can cast up to 4th-level spells."


def test_wizard_6_cant_memorize_cone_of_cold(srd35_call):
    # Table: The Wizard, 6th: 3rd-level 2 and nothing higher; cone of cold is Sor/Wiz 5.
    sheet = {"cls": "Wizard", "level": 6, "race": "Elf", "hp_max": 20, "ability_scores": {**TEN, "int": 16}}
    srd35_call("create_character", name="Elowen", sheet=sheet)
    out = srd35_call("memorize_spells", character="Elowen", spells=["Cone of Cold"])
    assert out["error"] == "Elowen can cast up to 3rd-level spells.", out
    out = srd35_call("memorize_spells", character="Elowen", spells=["Fireball", "Fireball"])
    assert out["by_level"] == {"3": ["Fireball", "Fireball"]}, out


def test_paladin_and_ranger_to_4th_at_half_caster_level():
    # Table: The Paladin, 14th: 2 / 1 / 1 / 0. Wis 18 (+4) gives a bonus spell of 1st to 4th, so the 4th-level "0"
    # is 1: 3 / 2 / 2 / 1. No 0-level spells. Caster level 7.
    sheet = filled("Paladin", 14, {"wis": 18})
    assert sheet.d20["derived"]["slots"] == {"1": 3, "2": 2, "3": 2, "4": 1}
    assert ENGINE.can_memorize(sheet, [4], ["Holy Sword"]) is None
    assert ENGINE.can_memorize(sheet, [0], ["Light"]) == "Too many level-0 spells: 1 given, 0 slots available."
    _, said = ENGINE.cast(sheet, CharacterState(hp=90), "Holy Sword", 4, None)
    assert said["caster_level"] == 7
    # Wis 14 (+2): a bonus of 1st and 2nd only; the 4th-level "0" stays none, and a 4th-level spell is refused.
    low = filled("Paladin", 14, {"wis": 14})
    assert low.d20["derived"]["slots"] == {"1": 3, "2": 2, "3": 1}
    assert ENGINE.can_memorize(low, [4], ["Holy Sword"]) == "Paladin can cast up to 3rd-level spells."
    # Table: The Ranger, 20th: 3 / 3 / 3 / 3; Wis 14 (+2): 4 / 4 / 3 / 3.
    ranger = filled("Ranger", 20, {"wis": 14})
    assert ranger.d20["derived"]["slots"] == {"1": 4, "2": 4, "3": 3, "4": 3}
    assert ENGINE.can_memorize(ranger, [4], ["Tree Stride"]) is None


def test_the_adept_prepares_to_5th():
    # Table: The Adept, 20th: 3 / 3 / 3 / 3 / 3 / 2. Wis 15 (+2): a bonus of 1st and 2nd: 3 / 4 / 4 / 3 / 3 / 2.
    sheet = filled("Adept", 20, {"wis": 15})
    assert sheet.d20["derived"]["slots"] == {"0": 3, "1": 4, "2": 4, "3": 3, "4": 3, "5": 2}
    fifth = next(row["name"] for row in data.load("spells") if row["levels"].get("adept") == 5)
    assert ENGINE.can_memorize(sheet, [5], [fifth]) is None


def test_the_wiz_keys_are_wizard():
    # The SRD's Level lines of Mage's Lucubration and Mnemonic Enhancer read "Wiz 6" and "Wiz 4": wizard only (the
    # spell lists: "Wizard only").
    sys.path.insert(0, str(SCRIPTS))
    from srd35_extract import kinds

    assert kinds._spell_levels("Wiz 6") == {"wizard": 6}
    spells = {row["id"]: row for row in data.load("spells")}
    assert spells["mages-lucubration"]["levels"] == {"wizard": 6}
    assert spells["mnemonic-enhancer"]["levels"] == {"wizard": 4}
    assert not any("wiz" in row["levels"] for row in spells.values())
