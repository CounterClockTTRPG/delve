"""Entering a prestige class (DEL-389 part 4): its first level checks the class's requirements (`numbers.
requirement_problems`), and a refusal names every unmet one in the class's order. A later level isn't checked again
(the SRD: the requirements are to qualify). A special requirement the engine can't check holds once the DM confirms it
(`set_build(choices={"requirements": …})`)."""

from __future__ import annotations

import pytest
from delve_srd35.engine import Srd35Engine, features, numbers
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def dice() -> Dice:
    return Dice(ScriptedRng([4] * 10), MemoryRollLog(), "c", "beat")


def sheet(levels: dict[str, int], race: str = "Human", alignment: str = "", **d20) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    made = Sheet(label="Ansel", cls=cls, race=race, alignment=alignment, levels=levels, hp_max=30,
                 ability_scores={**TEN, "int": 16, "wis": 14, "cha": 14, "str": 13}, d20=d20)  # fmt: skip
    return ENGINE.fill_derived(made, REF)


def test_eldritch_knight_refused_naming_only_the_unmet():
    # A wizard 5 (Int 16) casts 3rd-level arcane spells, but a wizard is proficient with five weapons, not all martial.
    wizard = sheet({"wizard": 5})
    assert numbers.requirement_problems(wizard, "eldritch-knight", REF) == ["proficiency with all martial weapons"]
    with pytest.raises(ValueError, match=r"Ansel can't enter the eldritch knight: it needs proficiency with all "
                                         r"martial weapons\."):  # fmt: skip
        ENGINE.level_up(wizard, "eldritch-knight", REF, dice())
    # A fighter level gives all martial weapons; the 3rd-level arcane spells are the wizard 5's.
    both = sheet({"wizard": 5, "fighter": 1})
    assert numbers.requirement_problems(both, "eldritch-knight", REF) == []
    entered = ENGINE.level_up(both, "eldritch-knight", REF, dice())
    assert entered.levels == {"wizard": 5, "fighter": 1, "eldritch-knight": 1}
    # The requirement rows are no features of the sheet.
    assert not [f for f in entered.d20["derived"]["features"] if f["kind"] == "requirement"]


def test_a_wizard_without_the_spells_fails_the_casting_too():
    # A wizard 3 (Int 16) casts up to 2nd-level spells.
    assert numbers.requirement_problems(sheet({"wizard": 3, "fighter": 1}), "eldritch-knight", REF) == [
        "the ability to cast 3rd-level arcane spells (it casts arcane spells up to 2nd level)"
    ]
    assert numbers.requirement_problems(sheet({"fighter": 6}), "eldritch-knight", REF) == [
        "the ability to cast 3rd-level arcane spells (it casts no arcane spells)"
    ]


def test_a_second_prestige_level_isnt_checked_again():
    # The wizard took its first eldritch knight level with a fighter's proficiencies; with the levels as they are now
    # it would not qualify, but the 2nd level isn't checked (and its casting row, from 2nd, reads).
    knight = sheet({"wizard": 5, "eldritch-knight": 1})
    assert numbers.requirement_problems(knight, "eldritch-knight", REF)
    raised = ENGINE.level_up(knight, "eldritch-knight", REF, dice())
    assert raised.levels["eldritch-knight"] == 2
    assert "eldritch-knight" not in features.casters(raised)


def test_arcane_archer_weapon_focus_either_bow():
    feats = [{"id": "point-blank-shot"}, {"id": "precise-shot"}, {"id": "weapon-focus", "choice": "shortbow"}]
    archer = sheet({"fighter": 6, "wizard": 1}, race="Elf", feats=feats)
    assert numbers.requirement_problems(archer, "arcane-archer", REF) == []
    longbow = [*feats[:2], {"id": "weapon-focus", "choice": "longbow-composite"}]
    assert numbers.requirement_problems(sheet({"fighter": 6, "wizard": 1}, race="Half-Elf", feats=longbow),
                                        "arcane-archer", REF) == []  # fmt: skip
    sword = [*feats[:2], {"id": "weapon-focus", "choice": "longsword"}]
    assert numbers.requirement_problems(sheet({"fighter": 6, "wizard": 1}, race="Elf", feats=sword),
                                        "arcane-archer", REF) == ["Weapon Focus (longbow or shortbow)"]  # fmt: skip


def test_every_unmet_requirement_in_the_classes_order():
    # The arcane archer's text: Race, Base Attack Bonus, Feats (Point Blank Shot, Precise Shot, Weapon Focus), Spells.
    assert numbers.requirement_problems(sheet({"fighter": 3}), "arcane-archer", REF) == [
        "Elf or half-elf (it is human)",
        "base attack bonus +6 (it is +3)",
        "Point Blank Shot",
        "Precise Shot",
        "Weapon Focus (longbow or shortbow)",
        "the ability to cast 1st-level arcane spells (it casts no arcane spells)",
    ]
    with pytest.raises(ValueError, match=r"it needs Elf or half-elf \(it is human\); base attack bonus"):
        ENGINE.level_up(sheet({"fighter": 3}), "arcane-archer", REF, dice())


def test_dwarven_defender_alignment_and_race():
    feats = [{"id": "dodge"}, {"id": "endurance"}, {"id": "toughness"}]
    assert numbers.requirement_problems(sheet({"fighter": 7}, race="Dwarf", alignment="LN", feats=feats),
                                        "dwarven-defender", REF) == []  # fmt: skip
    assert numbers.requirement_problems(sheet({"fighter": 7}, alignment="Chaotic Good", feats=feats),
                                        "dwarven-defender", REF) == [
        "Dwarf (it is human)", "Any lawful (it is chaotic good)"]  # fmt: skip
    assert numbers.requirement_problems(sheet({"fighter": 7}, race="Dwarf", feats=feats), "dwarven-defender", REF) == [
        "Any lawful (it has no alignment)"
    ]


def test_skills_ranks_sneak_attack_and_a_named_spell():
    # The arcane trickster: nonlawful, Decipher Script, Disable Device and Escape Artist 7 and Knowledge (arcana) 4
    # ranks, mage hand and a 3rd-level arcane spell, sneak attack +2d6. A rogue 3 (+2d6) / wizard 5 has them all.
    skills = {"decipher-script": 7, "disable-device": 7, "escape-artist": 7, "knowledge-arcana": 4}
    trickster = sheet({"rogue": 3, "wizard": 5}, alignment="CN", skills=skills)
    assert numbers.requirement_problems(trickster, "arcane-trickster", REF) == []
    short = sheet({"rogue": 1, "wizard": 5}, alignment="LN", skills={**skills, "escape-artist": 6})
    assert numbers.requirement_problems(short, "arcane-trickster", REF) == [
        "Any nonlawful (it is lawful neutral)",
        "Escape Artist 7 ranks (it has 6)",
        "sneak attack +2d6 (it has +1d6)",
    ]
    # A cleric 7 (Wis 14) casts lesser planar ally (cleric 4th); a cleric 5 casts up to 3rd.
    focus = [{"id": "spell-focus", "choice": "conjuration"}]
    assert numbers.requirement_problems(sheet({"cleric": 7}, feats=focus), "thaumaturgist", REF) == []
    assert numbers.requirement_problems(sheet({"cleric": 5}), "thaumaturgist", REF) == [
        "Spell Focus (conjuration)",
        "the ability to cast lesser planar ally",
    ]


def test_spontaneous_arcane_casting_for_the_dragon_disciple():
    # "Ability to cast arcane spells without preparation": a sorcerer's or bard's, not a wizard's. Its two special
    # requirements (Draconic, a dragon variety) wait for the DM.
    sorcerer = sheet({"sorcerer": 1}, skills={"knowledge-arcana": 8})
    wizard = sheet({"wizard": 1}, skills={"knowledge-arcana": 8})
    draconic, variety = "the DM's confirmation: speaks Draconic", "the DM's confirmation: a dragon variety chosen"
    assert numbers.requirement_problems(sorcerer, "dragon-disciple", REF) == [draconic, variety]
    assert numbers.requirement_problems(wizard, "dragon-disciple", REF) == [
        draconic, "the ability to cast arcane spells without preparation", variety]  # fmt: skip


def test_feats_counted_and_the_skills_any():
    # The loremaster: two Knowledge skills at 10 ranks, three metamagic or item creation feats, Skill Focus in a
    # Knowledge skill, and seven divination spells (the DM's).
    skills = {"knowledge-history": 10, "knowledge-local": 10}
    feats = [{"id": "scribe-scroll"}, {"id": "empower-spell"}, {"id": "craft-wand"},
             {"id": "skill-focus", "choice": "knowledge-history"}]  # fmt: skip
    sage = sheet({"wizard": 7}, skills=skills, feats=feats, choices={"requirements": {"loremaster": [
        "can cast seven divination spells, one of 3rd level or higher"]}})  # fmt: skip
    assert numbers.requirement_problems(sage, "loremaster", REF) == []
    thin = sheet({"wizard": 7}, skills={"knowledge-history": 10}, feats=feats[:2])
    assert numbers.requirement_problems(thin, "loremaster", REF) == [
        "Knowledge (any two) 10 ranks in each (it has 1)",
        "Any three metamagic or item creation feats (it has 2)",
        "Skill Focus (Knowledge [any individual Knowledge skill])",
        "the DM's confirmation: can cast seven divination spells, one of 3rd level or higher",
    ]


def test_a_class_features_bonus_feat_meets_a_requirement():
    # "A ranger gains Endurance as a bonus feat at 3rd level": a ranger 5 with Knowledge (geography) 8 ranks enters the
    # horizon walker without taking Endurance itself; a ranger 2 hasn't it yet. A wizard's Scribe Scroll is one of the
    # loremaster's three metamagic or item creation feats.
    geography = {"knowledge-geography": 8}
    assert numbers.requirement_problems(sheet({"ranger": 5}, skills=geography), "horizon-walker", REF) == []
    assert numbers.requirement_problems(sheet({"ranger": 2}, skills=geography), "horizon-walker", REF) == ["Endurance"]
    skills = {"knowledge-history": 10, "knowledge-local": 10}
    two = [{"id": "empower-spell"}, {"id": "craft-wand"}, {"id": "skill-focus", "choice": "knowledge-history"}]
    confirmed = {"requirements": {"loremaster": ["can cast seven divination spells, one of 3rd level or higher"]}}
    sage = sheet({"wizard": 7}, skills=skills, feats=two, choices=confirmed)
    assert numbers.requirement_problems(sage, "loremaster", REF) == []
    fighter = sheet({"fighter": 7}, skills=skills, feats=two, choices=confirmed)
    assert "Any three metamagic or item creation feats (it has 2)" in numbers.requirement_problems(
        fighter, "loremaster", REF)  # fmt: skip


def _rogue(srd35_call):
    sheet = {"cls": "Rogue", "level": 5, "race": "Human", "alignment": "Neutral Evil", "hp_max": 25,
             "ability_scores": {**TEN, "int": 14, "dex": 16}}  # fmt: skip
    assert "error" not in (made := srd35_call("create_character", name="Vex", sheet=sheet)), made
    built = srd35_call("set_build", character="Vex", skills={"disguise": 4, "hide": 8, "move silently": 8})
    assert "error" not in built, built


def test_assassin_needs_the_dms_confirmation_of_its_special(srd35_call):
    _rogue(srd35_call)
    patch = {"cls": "Rogue/Assassin", "levels": {"rogue": 5, "assassin": 1}}
    refused = srd35_call("update_character", ref="Vex", patch=patch, reason="joins the guild")
    assert "Vex can't enter the assassin: it needs the DM's confirmation: kill someone for no other reason than to " \
           "join." in refused["error"]  # fmt: skip
    wrong = srd35_call("set_build", character="Vex", choices={"requirements": {"assassin": ["paid the dues"]}})
    assert "'paid the dues' is no special requirement of the assassin: kill someone for no other reason than to " \
           "join." in wrong["error"]  # fmt: skip
    not_prestige = srd35_call("set_build", character="Vex", choices={"requirements": {"fighter": ["anything"]}})
    assert "The fighter has no special requirements" in not_prestige["error"]
    said = srd35_call(
        "set_build",
        character="Vex",
        choices={"requirements": {"Assassin": ["Kill someone, for no other reason than to join!"]}},
    )
    assert said["build"]["choices"]["requirements"] == {
        "assassin": ["kill someone for no other reason than to join"]}  # fmt: skip
    entered = srd35_call("update_character", ref="Vex", patch=patch, reason="joins the guild")
    assert "error" not in entered, entered


def test_an_items_enhanced_score_counts_for_a_feat_and_is_noted(srd35_call):
    # A Str 12 fighter 7 with gauntlets of ogre power +2 has Str 14 while they are worn: Power Attack's Str 13 holds,
    # so the blackguard's Power Attack, Cleave and Improved Sunder count, and the entry notes the item.
    sheet = {"cls": "Fighter", "level": 7, "race": "Human", "alignment": "LE", "hp_max": 50,
             "ability_scores": {**TEN, "str": 12, "int": 13}}  # fmt: skip
    assert "error" not in srd35_call("create_character", name="Mord", sheet=sheet)
    built = srd35_call(
        "set_build",
        character="Mord",
        items=["gauntlets of ogre power"],
        skills={"hide": 5, "knowledge religion": 2},
        feats=["power attack", "cleave", "combat expertise", "improved sunder"],
        choices={"requirements": {"blackguard": ["peaceful contact with a summoned evil outsider"]}},
    )
    assert "error" not in built, built
    assert any("Power Attack" in w and "worn" in w for w in built["warnings"]), built
    patch = {"cls": "Fighter/Blackguard", "levels": {"fighter": 7, "blackguard": 1}}
    entered = srd35_call("update_character", ref="Mord", patch=patch, reason="the pact")
    assert "error" not in entered, entered
    assert any("Power Attack" in n and "worn" in n for n in entered["notes"]), entered


def _wizard(srd35_call, level: int, name: str = "Ansel"):
    sheet = {"cls": "Wizard/Fighter", "levels": {"wizard": level, "fighter": 1}, "race": "Human", "hp_max": 30,
             "ability_scores": {**TEN, "int": 16}}  # fmt: skip
    assert "error" not in (made := srd35_call("create_character", name=name, sheet=sheet)), made


def test_a_class_by_its_spaced_name_enters_with_its_features(srd35_call, srd35_storage, srd35_campaign):
    # "Eldritch Knight" is the eldritch-knight: the sheet keeps its levels under the id, with its features.
    _wizard(srd35_call, 5)
    patch = {"cls": "Wizard/Fighter/Eldritch Knight", "levels": {"wizard": 5, "fighter": 1, "eldritch knight": 1}}
    entered = srd35_call("update_character", ref="Ansel", patch=patch, reason="the order")
    assert "error" not in entered, entered
    (ansel,) = srd35_storage.characters.list(srd35_campaign.id)
    assert ansel.sheet.levels == {"wizard": 5, "fighter": 1, "eldritch-knight": 1}
    assert {"bonus-feat", "proficiency"} <= {f["id"] for f in ansel.sheet.d20["derived"]["features"]
                                             if f["class"] == "eldritch-knight"}  # fmt: skip
    patch = {"cls": "Wizard/Fighter/Eldritch Knight", "levels": {"wizard": 5, "fighter": 1, "eldritch knight": 2}}
    second = srd35_call("update_character", ref="Ansel", patch=patch, reason="2nd level")
    assert "error" not in second, second
    (ansel,) = srd35_storage.characters.list(srd35_campaign.id)
    assert ansel.sheet.levels["eldritch-knight"] == 2
    assert "casting" in {f["id"] for f in ansel.sheet.d20["derived"]["features"] if f["class"] == "eldritch-knight"}


def test_features_by_a_class_name():
    assert features.rows("Eldritch Knight") == features.rows("eldritch-knight") != []


def test_one_patch_raises_the_wizard_and_enters(srd35_call):
    # A wizard 4 (Int 16) casts 2nd-level spells; the same patch makes it a wizard 5, which casts 3rd-level ones.
    _wizard(srd35_call, 4)
    patch = {"cls": "Wizard/Fighter/Eldritch-Knight", "levels": {"wizard": 5, "fighter": 1, "eldritch-knight": 1}}
    entered = srd35_call("update_character", ref="Ansel", patch=patch, reason="5th and the order")
    assert "error" not in entered, entered


def test_a_level_that_is_no_number_is_refused(srd35_call):
    # The tool's schema refuses it before the check runs; a patch core's sheet refuses is left to core (`_entering`).
    _wizard(srd35_call, 3)
    patch = {"cls": "Wizard/Fighter/Eldritch-Knight", "levels": {"wizard": 3, "fighter": 1, "eldritch-knight": "1"}}
    refused = srd35_call("update_character", ref="Ansel", patch=patch, reason="the order")
    assert "is not of type 'integer'" in refused["error"]


def test_a_prestige_class_made_at_creation_is_warned_not_refused(srd35_call):
    # A high-level NPC made a wizard 5 / eldritch knight 1 without a fighter's martial weapons: made, with a warning.
    sheet = {"cls": "Wizard/Eldritch-Knight", "levels": {"wizard": 5, "eldritch-knight": 1}, "race": "Human",
             "hp_max": 30, "ability_scores": {**TEN, "int": 16}}  # fmt: skip
    made = srd35_call("create_character", name="Ansel", sheet=sheet)
    assert "error" not in made, made
    assert "entered eldritch knight without: proficiency with all martial weapons." in \
        made["sheet"]["d20"]["derived"]["warnings"]  # fmt: skip
    # Met (a fighter level), no warning.
    sheet = {**sheet, "cls": "Wizard/Fighter/Eldritch-Knight", "levels": {"wizard": 5, "fighter": 1,
                                                                          "eldritch-knight": 1}}  # fmt: skip
    made = srd35_call("create_character", name="Brin", sheet=sheet)
    assert not [w for w in made["sheet"]["d20"]["derived"].get("warnings", ()) if w.startswith("entered")]
