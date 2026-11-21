"""The 3.5 engine's numbers (DEL-388): BAB, saves, AC, skills, slots and DCs from the class, race and armour tables.
Each worked example is checked by hand against the SRD in its comment."""

from __future__ import annotations

import pytest
from delve_srd35.engine import Srd35Engine, numbers
from delve_srd35.reference import Srd35Reference

from delve.domain.characters import Sheet

REF = Srd35Reference()
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def sheet(cls: str, race: str, levels: dict[str, int], abilities: dict[str, int], d20: dict) -> Sheet:
    return Sheet(cls=cls, race=race, levels=levels, ability_scores={**TEN, **abilities}, d20=d20)


def dwarf_fighter_3(**d20) -> Sheet:
    return sheet("Fighter", "Dwarf", {"fighter": 3}, {"str": 16, "dex": 12, "con": 16},
                 {"armor": "scale mail", "shield": "shield, heavy steel", "feats": [{"id": "power-attack"}], **d20})  # fmt: skip


def test_modifier_is_half_the_distance_from_ten():
    assert [numbers.modifier(s) for s in (1, 8, 9, 10, 11, 12, 15, 16, 18)] == [-5, -1, -1, 0, 0, 1, 2, 3, 4]


def test_signed_reads_typographic_and_plain_signs():
    texts = ("+3", "3", "–2", "−2", "-1", "+6/+1", "18–20", "+4^3^")
    assert [numbers.signed(t) for t in texts] == [3, 3, -2, -2, -1, 6, 18, 4]
    assert numbers.signed("—") is None and numbers.signed("") is None


def test_class_row_reads_the_level():
    row = numbers.class_row(REF, "Fighter", 3)
    assert (row["bab"], row["fort"], row["ref"], row["will"]) == (3, 3, 1, 1)
    with pytest.raises(ValueError, match="level 21"):
        numbers.class_row(REF, "fighter", 21)


def test_the_armour_table_is_the_srds():
    table = numbers.armour_table()
    assert table["scale-mail"] == {"name": "Scale mail", "bonus": 4, "max_dex": 3, "acp": -4, "failure": 25,
                                   "category": "medium", "speed": {30: 20, 20: 15}}  # fmt: skip
    assert table["studded-leather"]["acp"] == -1 and table["full-plate"]["bonus"] == 8
    assert table["shield-heavy-steel"] == {"name": "Shield, heavy steel", "bonus": 2, "max_dex": None, "acp": -2,
                                           "failure": 15, "category": "shield", "speed": {}}  # fmt: skip
    assert table["shield-tower"]["max_dex"] == 2 and table["shield-light-wooden"]["failure"] == 5
    assert len(table) == 18  # 12 armours, the buckler and five shields


def test_dwarf_fighter_3():
    # Fighter 3: BAB +3, Fort +3, Ref +1, Will +1. Con 16 (+3), Dex 12 (+1), Wis 10 (+0).
    # Fort 3+3 = 6, Ref 1+1 = 2, Will 1+0 = 1.
    # Scale mail +4 (max Dex +3, ACP -4), heavy steel shield +2 (ACP -2).
    # AC 10+4+2+1 = 17; touch 10+1 = 11; flat-footed 17-1 = 16; ACP -4-2 = -6. Initiative +1.
    d = numbers.derived(dwarf_fighter_3(), REF)
    assert (d["bab"], d["fort"], d["ref"], d["will"]) == (3, 6, 2, 1)
    assert (d["ac"], d["touch"], d["flat_footed"], d["acp"]) == (17, 11, 16, -6)
    assert (d["init"], d["max_dex"], d["spell_failure"]) == (1, 3, 0)
    assert (d["slots"], d["dc"], d["sneak"], d["turning_per_day"]) == ({}, {}, "", 0)


def test_armour_check_penalty_doubles_for_swim():
    # Climb: 3 ranks + Str 3 - 6 = 0. Swim: 2 ranks + Str 3 - 6x2 = -7. Intimidate takes no ACP: 1 + Cha 0 = 1.
    d = numbers.derived(dwarf_fighter_3(skills={"climb": 3, "swim": 2, "intimidate": 1}), REF)
    assert d["skills"] == {"climb": 0, "swim": -7, "intimidate": 1}


def test_feats_add_to_saves_ac_and_initiative():
    # Great Fortitude, Lightning Reflexes, Iron Will +2 each; Dodge +1 AC and touch, not flat-footed;
    # Improved Initiative +4: Dex 1 + 4 = 5.
    feats = [{"id": i} for i in ("great-fortitude", "lightning-reflexes", "iron-will", "dodge", "improved-initiative")]
    d = numbers.derived(dwarf_fighter_3(feats=feats), REF)
    assert (d["fort"], d["ref"], d["will"]) == (8, 4, 3)
    assert (d["ac"], d["touch"], d["flat_footed"], d["init"]) == (18, 12, 16, 5)


def test_halfling_rogue_1_is_small_and_sneaks():
    # Rogue 1: BAB +0, Fort +0, Ref +2, Will +0. Halfling: Small, +1 racial bonus on all saving throws,
    # +2 racial bonus on Climb, Jump, Move Silently and Listen. Dex 17 (+3), Con 12 (+1).
    # Fort 0+1+1 = 2, Ref 2+3+1 = 6, Will 0+0+1 = 1.
    # Leather +2 (max Dex +6, ACP 0). AC 10+2+3+1 (size) = 16; touch 10+3+1 = 14; flat-footed 16-3 = 13.
    # Hide: 4 ranks + Dex 3 + ACP 0 + 4 (Small size modifier on Hide) = 11.
    # Move Silently: 4 + 3 + 0 + 2 racial = 9. Listen: 4 + Wis 0 + 2 racial = 6.
    s = sheet("Rogue", "Halfling", {"rogue": 1}, {"str": 8, "dex": 17, "con": 12},
              {"armor": "leather", "skills": {"hide": 4, "move-silently": 4, "listen": 4}})  # fmt: skip
    d = numbers.derived(s, REF)
    assert (d["bab"], d["fort"], d["ref"], d["will"]) == (0, 2, 6, 1)
    assert (d["ac"], d["touch"], d["flat_footed"], d["acp"]) == (16, 14, 13, 0)
    assert d["skills"] == {"hide": 11, "move-silently": 9, "listen": 6}
    assert d["sneak"] == "1d6"


@pytest.mark.parametrize(("level", "dice"), [(1, "1d6"), (2, "1d6"), (3, "2d6"), (4, "2d6"), (5, "3d6")])
def test_sneak_attack_by_rogue_level(level, dice):
    s = sheet("Rogue", "Human", {"rogue": level}, {}, {})
    assert numbers.derived(s, REF)["sneak"] == dice


def test_a_rogue_of_4th_level_keeps_dex_when_flat_footed():
    # Uncanny dodge (rogue 4): flat-footed AC is the full AC, Dex and Dodge kept. Leather +2, Dex 16 (+3), Dodge:
    # AC 10+2+3+1 = 16, touch 14, flat-footed 16 (a rogue 3 has 12).
    build = {"armor": "leather", "feats": [{"id": "dodge"}]}
    d = numbers.derived(sheet("Rogue", "Human", {"rogue": 4}, {"dex": 16}, build), REF)
    assert (d["ac"], d["touch"], d["flat_footed"], d["uncanny_dodge"]) == (16, 14, 16, True)
    d = numbers.derived(sheet("Rogue", "Human", {"rogue": 3}, {"dex": 16}, build), REF)
    assert (d["ac"], d["flat_footed"], "uncanny_dodge" in d) == (16, 12, False)


def test_elf_wizard_1_slots_and_dc():
    # Wizard 1: 3 cantrips, one 1st; Int 16 (+3) gives one bonus 1st-level spell, none on level 0.
    # Slots {0: 3, 1: 2}; DC 10+0+3 = 13, 10+1+3 = 14. Unarmoured: no failure, no max Dex.
    # Spellcraft: 4 ranks + Int 3 + Skill Focus 3 = 10. Search: 1 + 3 + 2 elven racial = 6.
    s = sheet("Wizard", "Elf", {"wizard": 1}, {"dex": 14, "int": 16},
              {"skills": {"spellcraft": 4, "search": 1}, "feats": [{"id": "skill-focus", "choice": "spellcraft"}]})  # fmt: skip
    d = numbers.derived(s, REF)
    assert d["slots"] == {"0": 3, "1": 2} and d["dc"] == {"0": 13, "1": 14}
    assert (d["spell_failure"], d["max_dex"], d["ac"], d["init"]) == (0, None, 12, 2)
    assert d["skills"] == {"spellcraft": 10, "search": 6}


def test_a_wizard_in_armour_risks_failure_and_others_dont():
    # Leather 10% + light wooden shield 5% = 15%; ACP 0 + -1 = -1.
    gear = {"armor": "Leather", "shield": "shield-light-wooden"}
    wizard = numbers.derived(sheet("Wizard", "Human", {"wizard": 1}, {"int": 15}, gear), REF)
    assert (wizard["spell_failure"], wizard["acp"]) == (15, -1)
    assert numbers.derived(sheet("Cleric", "Human", {"cleric": 1}, {"wis": 15}, gear), REF)["spell_failure"] == 0


def test_too_low_a_key_ability_casts_no_spells_of_that_level():
    # The SRD: a caster needs a key ability of 10 + the spell level to cast spells of that level. Int 10: cantrips only.
    d = numbers.derived(sheet("Wizard", "Human", {"wizard": 1}, {"int": 10}, {}), REF)
    assert d["slots"] == {"0": 3} and d["dc"] == {"0": 10}


def test_human_cleric_1_domain_slot():
    # Cleric 1: 3 orisons, one 1st + one domain slot; Wis 15 (+2) gives one bonus 1st: {0: 3, 1: 1+1+1 = 3}.
    # DC 10+0+2 = 12, 10+1+2 = 13. Turning 3 + Cha 12 (+1) = 4. Fort 2+0, Will 2+2 = 4.
    s = sheet("Cleric", "Human", {"cleric": 1}, {"wis": 15, "cha": 12}, {"domains": ["war", "good"]})
    d = numbers.derived(s, REF)
    assert d["slots"] == {"0": 3, "1": 3} and d["dc"] == {"0": 12, "1": 13}
    assert (d["turning_per_day"], d["fort"], d["will"]) == (4, 2, 4)


def test_extra_turning_gives_four_more():
    # The SRD's Extra Turning: four more turning attempts a day. 3 + Cha 0 + 4 = 7.
    s = sheet("Cleric", "Human", {"cleric": 1}, {"wis": 12}, {"feats": [{"id": "extra-turning"}]})
    assert numbers.derived(s, REF)["turning_per_day"] == 7


def test_an_unknown_armour_warns_and_counts_nothing():
    d = numbers.derived(sheet("Fighter", "Human", {"fighter": 1}, {}, {"armor": "mithral pyjamas"}), REF)
    assert d["ac"] == 10 and d["warnings"] == ["Unknown armour 'mithral pyjamas'."]


def test_the_fake_tripwire_isnt_needed_here():
    # The numbers come from a reference alone: no ruleset, no `Ruleset.tables`, no storage.
    d = numbers.derived(dwarf_fighter_3(), Srd35Reference())
    assert d["ac"] == 17 and "warnings" not in d


def test_fill_derived_writes_derived_and_slots_and_keeps_the_build():
    build = {"skills": {"concentration": 4}, "feats": [{"id": "combat-casting"}], "domains": ["war", "good"],
             "weapon": "warhammer", "armor": "scale mail", "shield": "shield, heavy steel"}  # fmt: skip
    s = sheet("Cleric", "Human", {"cleric": 1}, {"wis": 15, "cha": 12}, build)
    filled = Srd35Engine(REF).fill_derived(s, REF)
    assert {k: v for k, v in filled.d20.items() if k != "derived"} == build
    assert filled.d20["derived"] == numbers.derived(s, REF)
    assert filled.spell_slots == {0: 3, 1: 3}


def test_sheet_numbers_and_prompt_terms():
    engine = Srd35Engine(REF)
    s = engine.fill_derived(sheet("Cleric", "Human", {"cleric": 1}, {"wis": 15}, {"domains": ["war"]}), REF)
    out = engine.sheet_numbers(s)
    assert set(out) == {"bab", "fort", "ref", "will", "ac", "touch", "flat_footed", "init", "skills", "feats",
                        "domains", "slots", "dc", "features"}  # fmt: skip
    assert [(f["id"], f["per_day"]) for f in out["features"]] == [("casting", None), ("proficiency", None),
                                                                   ("turn-undead", 3)]  # fmt: skip
    assert (out["will"], out["slots"], out["domains"], out["feats"]) == (4, {"0": 3, "1": 3}, ["war"], [])
    assert engine.sheet_numbers(Sheet(cls="Fighter", race="Human", levels={"fighter": 1}))["bab"] == 1
    assert engine.prompt_terms() == {"attack_number": "attack bonus against AC",
                                     "saves_list": "Fortitude, Reflex and Will against a DC"}  # fmt: skip


def test_the_ruleset_carries_the_engine():
    from delve_srd35.ruleset import Srd35Ruleset

    ruleset = Srd35Ruleset()
    assert isinstance(ruleset.d20, Srd35Engine) and ruleset.d20.reference is ruleset.reference


def test_a_two_handed_weapon_gets_no_shields_ac():
    # The dwarf fighter 3 in scale mail +4 with a heavy steel shield +2 (Dex 12, +1): AC 17, flat-footed 16, ACP -6.
    # With a greatsword or a longbow both hands are on the weapon: the heavy shield's +2 is lost (AC 15, flat-footed
    # 14), its armour check penalty still on him (carried, -6). A longsword keeps it; so does a hand crossbow.
    for weapon in ("greatsword", "longbow", "light crossbow"):
        d = numbers.derived(dwarf_fighter_3(weapon=weapon), REF)
        assert (d["ac"], d["touch"], d["flat_footed"], d["acp"]) == (15, 11, 14, -6), weapon
    for weapon in ("longsword", "hand crossbow"):
        assert numbers.derived(dwarf_fighter_3(weapon=weapon), REF)["ac"] == 17, weapon
    assert "both hands" in numbers.shield_use(dwarf_fighter_3(weapon="greatsword"), REF)["note"]
    assert numbers.shield_use(dwarf_fighter_3(weapon="longsword"), REF) == {"counts": True, "attack": 0, "note": None}


def test_a_buckler_with_a_two_handed_weapon():
    # A buckler +1: with a greatsword, -1 to attack and no buckler AC (AC 10 + 4 + 1 = 15); with a longbow, "without
    # penalty", its +1 kept (AC 16).
    use = numbers.shield_use(dwarf_fighter_3(shield="buckler", weapon="greatsword"), REF)
    assert (use["counts"], use["attack"]) == (False, -1)
    assert numbers.derived(dwarf_fighter_3(shield="buckler", weapon="greatsword"), REF)["ac"] == 15
    assert numbers.derived(dwarf_fighter_3(shield="buckler", weapon="longbow"), REF)["ac"] == 16
    assert numbers.shield_use(dwarf_fighter_3(shield="buckler", weapon="longbow"), REF)["attack"] == 0
