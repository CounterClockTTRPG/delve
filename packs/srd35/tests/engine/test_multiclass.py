"""Multiclassing by the book (DEL-389): ECL, the multiclass XP penalty and the favoured class. The SRD: −20% XP for
each class not within one level of the highest-level class, the favoured class not counting (a human's or half-elf's
"Any" is the highest-level class). Each worked example is checked by hand in its comment."""

from __future__ import annotations

from delve_srd35.engine import Srd35Engine, numbers, progress
from delve_srd35.reference import Srd35Reference

from delve.domain.characters import CharacterState, Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
SCORES = {"str": 12, "dex": 14, "con": 12, "int": 14, "wis": 10, "cha": 8}


def sheet(race: str, levels: dict[str, int], **build) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    return Sheet(label="Hero", cls=cls, race=race, levels=levels, hp_max=20, ability_scores=TEN, d20=build)


def test_human_fighter_2_rogue_2_no_penalty():
    assert progress.xp_penalty(sheet("Human", {"fighter": 2, "rogue": 2}), REF) == 0


def test_human_fighter_3_rogue_1_no_penalty_highest_is_favoured():
    # "Any": the fighter, the highest, doesn't count; the rogue alone is left.
    assert progress.xp_penalty(sheet("Human", {"fighter": 3, "rogue": 1}), REF) == 0


def test_dwarf_fighter_1_rogue_3_no_penalty():
    # The fighter is the dwarf's favoured class, exempt; the rogue is the highest.
    assert progress.xp_penalty(sheet("Dwarf", {"fighter": 1, "rogue": 3}), REF) == 0


def test_dwarf_rogue_3_wizard_1_minus_20():
    # Neither is a dwarf's favoured class: the wizard is two below the rogue.
    assert progress.xp_penalty(sheet("Dwarf", {"rogue": 3, "wizard": 1}), REF) == 20


def test_dwarf_fighter_3_rogue_1_no_penalty_favoured_does_not_count():
    # The favoured fighter counts for nothing, also as the highest: the rogue alone is left.
    assert progress.xp_penalty(sheet("Dwarf", {"fighter": 3, "rogue": 1}), REF) == 0


def test_half_elf_three_classes_minus_20():
    # Wizard 3 is the highest, "Any" takes it out; rogue 1 and fighter 1 are within one of each other: no penalty.
    assert progress.xp_penalty(sheet("Half-elf", {"wizard": 3, "rogue": 1, "fighter": 1}), REF) == 0
    # A halfling (favoured rogue): wizard 3 is the highest left, fighter 1 is two below: −20%.
    assert progress.xp_penalty(sheet("Halfling", {"wizard": 3, "rogue": 1, "fighter": 1}), REF) == 20


def test_two_classes_behind_minus_40():
    # A gnome (favoured bard) fighter 3/rogue 1/wizard 1: rogue and wizard each two below the fighter.
    assert progress.xp_penalty(sheet("Gnome", {"fighter": 3, "rogue": 1, "wizard": 1}), REF) == 40


def test_the_build_favoured_class_comes_before_the_race():
    # A human whose build names the wizard: the fighter 3 and rogue 1 count, the rogue two below.
    assert progress.xp_penalty(sheet("Human", {"fighter": 3, "rogue": 1}, favoured_class="wizard"), REF) == 20
    # A dwarf whose build says rogue: the wizard counts against nothing.
    assert progress.xp_penalty(sheet("Dwarf", {"rogue": 3, "wizard": 1}, favoured_class="wizard"), REF) == 0


def test_npc_classes_count_like_any():
    # A dwarf warrior 3/expert 1: neither favoured, expert two below.
    assert progress.xp_penalty(sheet("Dwarf", {"warrior": 3, "expert": 1}), REF) == 20


def test_single_class_and_companion_no_penalty():
    assert progress.xp_penalty(sheet("Dwarf", {"rogue": 5}), REF) == 0
    companion = Sheet(label="Wolf", levels={}, d20={"companion_of": "chr_1", "animal": "wolf"})
    assert progress.xp_penalty(companion, REF) == 0
    assert numbers.ecl(companion, REF) == 0  # a companion has no ECL: it takes no XP


def test_ecl_is_the_class_levels():
    # No racial Hit Dice or level adjustment in the slice's races yet (Task 7): ECL is the levels' total.
    assert numbers.ecl(sheet("Dwarf", {"rogue": 3, "wizard": 1}), REF) == 4


def test_derived_has_ecl_and_the_penalty():
    found = ENGINE.fill_derived(sheet("Dwarf", {"rogue": 3, "wizard": 1}), REF).d20["derived"]
    assert (found["ecl"], found["xp_penalty"]) == (4, 20)


def test_award_xp_takes_the_penalty_rounded_down():
    # 1,001 × 80 / 100 = 800.8, rounded down to 800.
    multi = sheet("Dwarf", {"rogue": 3, "wizard": 1})
    assert ENGINE.award_xp(multi, CharacterState(hp=5, xp=6000), 1001).xp == 6800
    assert ENGINE.award_xp(sheet("Dwarf", {"rogue": 4}), CharacterState(hp=5, xp=6000), 1001).xp == 7001


def test_progress_uses_ecl():
    # Rogue 3/wizard 1 is ECL 4: 10,000 XP reaches 5th, the next (5th) needs 10,000 by Table 6-13.
    found = ENGINE.progress(sheet("Dwarf", {"rogue": 3, "wizard": 1}), CharacterState(hp=5, xp=10000), REF)
    assert found.xp_next == 10000 and found.ready == ("rogue", "wizard")
    # A gnoll fighter 1 is ECL 4 (2 racial HD + 1 + LA 1) on a class total of 1: 3,000 XP reaches 3rd, below its ECL,
    # so nothing is ready, and its next level (5th) needs 10,000; by the class total 2nd would be ready at 1,000.
    gnoll = Sheet(label="Grak", cls="Fighter", race="Gnoll", levels={"fighter": 1}, hp_max=20, ability_scores=TEN)
    assert numbers.ecl(gnoll, REF) == 4 and sum(gnoll.levels.values()) == 1
    found = ENGINE.progress(gnoll, CharacterState(hp=5, xp=3000), REF)
    assert found.xp_next == 10000 and found.ready == ()


def test_level_up_says_a_new_penalty():
    from delve.dice import Dice, MemoryRollLog, ScriptedRng

    dice = Dice(ScriptedRng([3]), MemoryRollLog(), "c", "beat")
    raised = ENGINE.level_up(sheet("Dwarf", {"rogue": 3}), "wizard", REF, dice)
    assert raised.d20["level_up"]["xp_penalty"] == 20
    dice = Dice(ScriptedRng([3]), MemoryRollLog(), "c", "beat")
    assert "xp_penalty" not in ENGINE.level_up(sheet("Dwarf", {"rogue": 3}), "rogue", REF, dice).d20["level_up"]


def _dwarf(srd35_call, levels):
    cls = "/".join(c.title() for c in levels)
    made = srd35_call("create_character", name="Durin",
                      sheet={"cls": cls, "levels": levels, "race": "Dwarf", "hp_max": 20, "ability_scores": SCORES})  # fmt: skip
    assert "error" not in made, made
    return made


def test_award_with_penalty(srd35_call):
    # 1,000 XP to the dwarf rogue 3/wizard 1 adds 800, on 4th level's floor of 6,000 (made with no XP, DEL-389).
    _dwarf(srd35_call, {"rogue": 3, "wizard": 1})
    out = srd35_call("award_xp", character="Durin", amount=1000)
    assert out["xp_gained"] == 800 and out["xp_total"] == 6800
    assert out["xp_note"] == "0 XP was below 4th level's 6,000: raised to 6,000 before the award."
    assert out["xp_awarded"] == 1000 and out["xp_penalty"] == "−20% (multiclass)"


def test_award_without_penalty_says_none(srd35_call):
    _dwarf(srd35_call, {"fighter": 1, "rogue": 3})
    out = srd35_call("award_xp", character="Durin", amount=1000)
    assert out["xp_gained"] == 1000 and "xp_penalty" not in out and "xp_awarded" not in out


def test_bab_and_saves_sum_across_classes():
    # Fighter 2: BAB +2, Fort +3, Ref +0, Will +0. Rogue 2: BAB +1, Fort +0, Ref +3, Will +0. Scores all 10.
    found = ENGINE.fill_derived(sheet("Human", {"fighter": 2, "rogue": 2}), REF).d20["derived"]
    assert (found["bab"], found["fort"], found["ref"], found["will"]) == (3, 3, 3, 0)


def test_a_companion_takes_no_xp():
    # A companion grows with its master's level, not by XP: an award leaves its XP as it was.
    companion = Sheet(label="Wolf", levels={}, d20={"companion_of": "chr_1", "animal": "wolf"})
    assert ENGINE.award_xp(companion, CharacterState(hp=13, xp=0), 1000).xp == 0


def test_award_to_a_companion_says_it_takes_none(srd35_call):
    made = srd35_call("create_character", name="Ash",
                      sheet={"cls": "Druid", "level": 1, "race": "Human", "hp_max": 8, "ability_scores": SCORES})  # fmt: skip
    assert "error" not in made, made
    assert "error" not in (added := srd35_call("add_companion", master="Ash", animal="wolf", name="Grey")), added
    out = srd35_call("award_xp", character="Grey", amount=1000)
    assert out["xp_gained"] == 0 and out["xp_total"] == 0 and out["level_up_hints"] == []
    assert out["xp_note"] == "A companion takes no XP: it grows with its master's level."


def _hit_die_faces(srd35_storage, srd35_campaign, cls):
    return [
        r.total for r in srd35_storage.rolls.list(srd35_campaign.id) if r.key.purpose.startswith(f"level_up:hp:{cls}:")
    ]


def test_a_first_level_in_a_new_class_is_a_level_up(srd35_call, srd35_storage, srd35_campaign):  # DEL-457
    # Kell, human rogue 3 (Con 12, Int 12), at 18 of 18, takes his 4th level as a fighter: the d10 is rolled (not its
    # maximum, the character's first Hit Die being the rogue's) and with Con's +1 on the maximum and current hit
    # points; the hints: the fighter's 2 + Int 1 + the human's 1 = 4 skill points, the fighter's 1st-level bonus feat
    # (Table: The Fighter), and an ability increase at 4th character level; no feat (not 3rd, 6th …).
    scores = {"str": 14, "dex": 16, "con": 12, "int": 12, "wis": 10, "cha": 10}
    made = srd35_call("create_character", name="Kell",
                      sheet={"cls": "Rogue", "level": 3, "race": "Human", "hp_max": 18, "ability_scores": scores})  # fmt: skip
    assert "error" not in made, made
    out = srd35_call(
        "update_character", ref="Kell", patch={"cls": "Rogue/Fighter", "levels": {"rogue": 3, "fighter": 1}}
    )
    assert "error" not in out, out
    [face] = _hit_die_faces(srd35_storage, srd35_campaign, "fighter")
    said = out["sheet"]["d20"]["level_up"]
    assert said == {"class": "fighter", "level": 1, "hit_points": face + 1,
                    "hints": ["4 skill points", "a fighter bonus feat", "an ability increase"]}  # fmt: skip
    assert out["sheet"]["hp_max"] == out["state"]["hp"] == 18 + face + 1


def test_a_new_class_and_a_level_in_one_patch_each_roll(srd35_call, srd35_storage, srd35_campaign):  # DEL-457
    # A dwarf rogue 3 (Con 12) to rogue 4/fighter 1: the rogue's d6 first, then the fighter's d10, each + 1; the answer's
    # level-up is the last, the fighter's, at character level 5 (no feat or increase: 5 is neither 3n nor 4n).
    _dwarf(srd35_call, {"rogue": 3})
    out = srd35_call(
        "update_character", ref="Durin", patch={"cls": "Rogue/Fighter", "levels": {"rogue": 4, "fighter": 1}}
    )
    assert "error" not in out, out
    purposes = [r.key.purpose for r in srd35_storage.rolls.list(srd35_campaign.id)]
    assert purposes == ["level_up:hp:rogue:4", "level_up:hp:fighter:1"]
    rogue, fighter = (_hit_die_faces(srd35_storage, srd35_campaign, cls)[0] for cls in ("rogue", "fighter"))
    assert out["sheet"]["hp_max"] == 20 + rogue + 1 + fighter + 1
    assert out["sheet"]["d20"]["level_up"]["class"] == "fighter"
    # The fighter's 2 + Int 14's 2 = 4 skill points, and its bonus feat.
    assert out["sheet"]["d20"]["level_up"]["hints"] == ["4 skill points", "a fighter bonus feat"]


def test_making_a_character_is_no_level_up(srd35_call, srd35_storage, srd35_campaign):  # DEL-457
    made = _dwarf(srd35_call, {"rogue": 3, "wizard": 1})
    assert made["sheet"]["hp_max"] == 20 and "level_up" not in made["sheet"]["d20"]
    assert srd35_storage.rolls.list(srd35_campaign.id) == []


def test_an_eldritch_knights_bonus_feat_takes_an():  # DEL-457: entering gives the hint, "an eldritch-knight"
    # A human wizard 5/fighter 1/eldritch knight 1, Int 10: the eldritch knight's 2 + 0 + the human's 1 = 3 skill
    # points, and Table: The Eldritch Knight's 1st-level bonus feat; 7th character level gives no feat or increase.
    entered = sheet("Human", {"wizard": 5, "fighter": 1, "eldritch-knight": 1})
    assert progress.hints(entered, "eldritch-knight", REF) == ["3 skill points", "an eldritch-knight bonus feat"]
