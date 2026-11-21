"""Monsters as characters (DEL-389): a monster whose level adjustment is a plain "+N" is a race, with its racial Hit
Dice (their base attack and saves), natural armour, size, speed and level adjustment. Its ECL is racial Hit Dice +
class levels + level adjustment; its character level for feats, ability increases and skill points is its Hit Dice
(racial + class), without the adjustment. A monster of 1 Hit Die or less trades it for its class levels (the SRD's
"exchange the features of their humanoid Hit Die for the class features of a PC or NPC class"). Each worked example
is checked by hand in its comment."""

from __future__ import annotations

from delve_srd35 import data
from delve_srd35.engine import Srd35Engine, numbers, progress
from delve_srd35.reference import Srd35Reference

from delve.domain.characters import CharacterState, Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
SCORES = {"str": 16, "dex": 12, "con": 14, "int": 13, "wis": 10, "cha": 8}


def sheet(race: str, levels: dict[str, int], scores: dict[str, int] = TEN) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    return Sheet(label="Hero", cls=cls, race=race, levels=levels, hp_max=20, ability_scores=scores, d20={})


def test_gnoll_fighter_1():
    # monsters.json's gnoll: Humanoid, Medium, 30 ft., hit_dice "2d8+2" (2 racial HD, d8), base attack/grapple
    # "+1/+3" (BAB +1), saves Fort +4 Ref +0 Will +0 with Con 13 (+1), Dex 10, Wis 10 and no save feat (Power Attack):
    # base Fort +3, Ref +0, Will +0. AC "15 (+1 natural, +2 leather armor, +2 heavy steel shield)": natural armour +1.
    # Level adjustment "+1". ECL = 2 HD + 1 fighter level + 1 LA = 4.
    race = numbers.monster_race(REF, "gnoll")
    assert race["racial_hd"] == {"levels": 2, "die": "d8"}
    assert race["racial_bab"] == 1
    assert race["racial_saves"] == {"fort": 3, "ref": 0, "will": 0}
    assert (race["natural_armour"], race["level_adjustment"]) == (1, 1)
    assert (race["size"], race["speed"]) == ("Medium", 30)
    found = numbers.derived(sheet("Gnoll", {"fighter": 1}), REF)
    # Fighter 1: BAB +1, Fort +2, Ref +0, Will +0, on the racial +1 and +3/+0/+0; all scores 10. AC 10 + 1 natural.
    assert (found["bab"], found["fort"], found["ref"], found["will"]) == (2, 5, 0, 0)
    assert (found["ac"], found["touch"], found["flat_footed"]) == (11, 10, 11)
    assert found["ecl"] == 4
    assert found["speed"] == 30
    assert "warnings" not in found


def test_azer_by_its_racial_hit_dice_line():
    # "Racial Hit Dice: An azer begins with two levels of outsider, which provide 2d8 Hit Dice, a base attack bonus of
    # +2, and base saving throw bonuses of Fort +3, Ref +3, and Will +3." "+6 natural armor bonus." "Favored Class:
    # Fighter." "Level adjustment +4." Racial Skills: "5 x (8 + Int modifier)"; Racial Feats: "one feat".
    race = numbers.monster_race(REF, "Azer")
    assert race["racial_hd"] == {"levels": 2, "die": "d8"}
    assert race["racial_bab"] == 2
    assert race["racial_saves"] == {"fort": 3, "ref": 3, "will": 3}
    assert (race["natural_armour"], race["level_adjustment"], race["favoured_class"]) == (6, 4, "fighter")
    assert race["racial_skill_points"] == {"per_hd": 8, "times": 5}
    assert race["racial_feats"] == 1
    assert "climb" in race["racial_class_skills"]
    # Azer rogue 1: ECL 2 + 1 + 4 = 7; the favoured class from the trait.
    azer = sheet("Azer", {"rogue": 1})
    assert numbers.ecl(azer, REF) == 7
    assert numbers.favoured_class(azer, REF) == "fighter"


def test_one_hit_die_humanoids_trade_it_for_class_levels():
    # Goblin "1d8+1" LA +0: no racial HD, ECL = class levels. Hobgoblin "1d8+2" LA +1: ECL = class levels + 1.
    goblin = numbers.monster_race(REF, "goblin")
    assert goblin["racial_hd"]["levels"] == 0 and goblin["racial_bab"] == 0
    assert goblin["racial_saves"] == {"fort": 0, "ref": 0, "will": 0}
    assert numbers.ecl(sheet("Goblin", {"rogue": 1}), REF) == 1
    assert numbers.ecl(sheet("Hobgoblin", {"fighter": 1}), REF) == 2
    # The goblin rogue 1: the rogue's numbers alone (BAB +0, Ref +2), Small (+1 AC).
    found = numbers.derived(sheet("Goblin", {"rogue": 1}), REF)
    assert (found["bab"], found["ref"], found["ac"]) == (0, 2, 11)


def test_cohort_only_is_refused():
    # Air Mephit's level adjustment reads "+3 (cohort)": not a race.
    assert numbers.monster_race(REF, "Air Mephit") is None
    assert numbers.race_named(REF, "Air Mephit") is None
    found = numbers.derived(sheet("Air Mephit", {"fighter": 1}), REF)
    assert "Air Mephit can't be a character race: its level adjustment is '+3 (cohort)'." in found["warnings"]


def test_a_dash_or_per_age_adjustment_is_refused():
    for name in ("Black Dragon", "Owlbear"):
        row = next(r for r in data.load("monsters") if r["name"] == name)
        assert numbers.monster_race(REF, name) is None
        warning = f"{name} can't be a character race: its level adjustment is '{row['level_adjustment']}'."
        assert warning in numbers.derived(sheet(name, {"fighter": 1}), REF)["warnings"]


def test_core_races_unchanged():
    dwarves = next(r for r in data.load("races") if r["id"] == "dwarves")
    assert numbers.race_named(REF, "Dwarf") == dwarves
    assert numbers.race_named(REF, "Halfling")["id"] == "halflings"  # the core race, not the monster row
    assert numbers.ecl(sheet("Dwarf", {"fighter": 2}), REF) == 2


def test_hints_count_hit_dice_and_the_racial_ones():
    # A gnoll fighter 1 (Int 10) is character level 3 (2 HD + 1): the fighter's 2 + 0 points (no ×4, the first racial
    # HD took it), a feat at 3rd, the fighter's bonus feat; and the racial Hit Dice's own: (2 + 0) × (2 + 3) = 10
    # humanoid skill points and 1 + 2 // 3 = 1 feat.
    gnoll = sheet("Gnoll", {"fighter": 1})
    assert progress.hints(gnoll, "fighter", REF) == [
        "2 skill points",
        "a feat",
        "a fighter bonus feat",
        "10 skill points from its 2 racial Hit Dice",
        "1 feat from its racial Hit Dice",
    ]
    # An azer rogue 1 (Int 14): 8 + 2 rogue points; the line's 5 × (8 + 2) = 50 racial points and one feat; level 3.
    azer = sheet("Azer", {"rogue": 1}, {**TEN, "int": 14})
    assert progress.hints(azer, "rogue", REF) == [
        "10 skill points",
        "a feat",
        "50 skill points from its 2 racial Hit Dice",
        "1 feat from its racial Hit Dice",
    ]
    # A doppelganger (4 HD) rogue 1 is level 5: no feat, but its racial Hit Dice give an ability increase.
    dopp = sheet("Doppelganger", {"rogue": 1})
    assert "1 ability increase from its racial Hit Dice" in progress.hints(dopp, "rogue", REF)
    assert "a feat" not in progress.hints(dopp, "rogue", REF)


def test_the_first_class_level_after_racial_hit_dice_rolls_its_die():
    from delve.dice import Dice, MemoryRollLog, ScriptedRng

    dice = Dice(ScriptedRng([3]), MemoryRollLog(), "c", "beat")
    raised = ENGINE.level_up(sheet("Gnoll", {}), "fighter", REF, dice)
    assert raised.d20["level_up"]["hit_points"] == 3  # rolled 3 + Con 0, not the d10's 10


def test_progress_counts_racial_hit_dice_and_adjustment():
    # Gnoll fighter 1: ECL 4, so with 0 XP the next level (5th) needs 10,000; the class total (1) would say 1,000.
    found = ENGINE.progress(sheet("Gnoll", {"fighter": 1}), CharacterState(hp=5, xp=0), REF)
    assert found.xp_next == 10000 and found.ready == ()


def _gnoll(srd35_call, race="Gnoll"):
    out = srd35_call("create_character", name="Grak",
                     sheet={"cls": "Fighter", "level": 1, "race": race, "hp_max": 20, "ability_scores": SCORES})  # fmt: skip
    assert "error" not in out, out
    return out


def test_set_build_counts_the_racial_skill_points(srd35_call):
    # Gnoll fighter 1, Int 13 (+1): racial (2 + 1) × 5 = 15, fighter 2 + 1 = 3: 18 points; max ranks 3 HD + 3 = 6.
    # Listen and Spot are the gnoll's (its stat block's skills), Climb the fighter's.
    _gnoll(srd35_call)
    fine = srd35_call("set_build", character="Grak", skills={"listen": 6, "spot": 6, "climb": 6})
    assert fine["skill_points"] == {"spent": 18, "total": 18}
    out = srd35_call("set_build", character="Grak", skills={"listen": 6, "spot": 6, "climb": 7})
    assert "Climb 7 ranks: at most 6 (a class skill, level 3)." in out["error"]


def test_set_build_warns_on_an_unusable_race(srd35_call):
    _gnoll(srd35_call, race="Air Mephit")
    out = srd35_call("set_build", character="Grak", skills={"climb": 1})
    assert "error" not in out, out
    assert out["warnings"] == ["Air Mephit can't be a character race: its level adjustment is '+3 (cohort)'."]


def test_a_blank_level_adjustment_is_worded_as_none():
    # An entry with no level adjustment at all (the Air Elemental's is blank) says so, not "is ''".
    found = numbers.derived(sheet("Air Elemental", {"fighter": 1}), REF)
    assert "Air Elemental can't be a character race: its entry gives no level adjustment." in found["warnings"]
    assert not any("''" in warning for warning in found["warnings"])
