"""The 3.5 engine's progression (DEL-388): levels and XP by Unearthed Arcana's level-independent tables, hit points
by the hit die, energy drain as negative levels, and natural healing. Each worked example is checked by hand in its
comment."""

from __future__ import annotations

import pytest
from delve_srd35.engine import Srd35Engine, progress
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import CharacterState, Sheet
from delve.rules.classic.combat import Combatant
from delve.rules.classic.life import DEAD_AT
from delve.rules.d20 import Progress

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


def sheet(cls: str, levels: dict[str, int], race: str = "Human", hp_max: int = 10, **abilities: int) -> Sheet:
    return Sheet(label="Hero", cls=cls, race=race, levels=levels, hp_max=hp_max, ability_scores={**TEN, **abilities},
                 d20={"feats": [{"id": "power-attack"}]})  # fmt: skip


def test_cr_awards():
    assert [progress.cr_award(c) for c in ("1", "1/2", "1/3", "1/8", "5", "20", "22")] == [300, 150, 100, 37, 1800,
                                                                                          310000, 620000]  # fmt: skip


def test_cr_awards_read_any_way_the_data_writes_a_cr():
    # 0.5 is how the zombie rows write 1/2; 21 is twice CR 19's 230,000; 24 is twice CR 22's 620,000.
    assert [progress.cr_award(c) for c in ("0.5", "½", " 3 ", "21", "24")] == [150, 150, 900, 460000, 1240000]
    for wrong in ("None", "—", "", "0", "1.5"):
        with pytest.raises(ValueError):
            progress.cr_award(wrong)


def test_level_for():
    assert [progress.level_for(x) for x in (0, 999, 1000, 10000, 16000)] == [1, 1, 2, 5, 6]
    assert progress.level_for(2_600_000) == 20 and progress.level_for(99_000_000) == 20


def test_level_up_rolls_the_hit_die_plus_con():  # seeded dice
    # Fighter 1 → 2: d10 rolls 7, Con 14 is +2, so 9 more hit points.
    d, rng = dice(7)
    raised = ENGINE.level_up(sheet("Fighter", {"fighter": 1}, con=14), "fighter", REF, d)
    assert raised.levels == {"fighter": 2} and raised.hp_max == 19
    assert rng.calls == [(1, 10)]
    assert raised.d20["level_up"]["hit_points"] == 9


def test_level_up_gives_at_least_one_hit_point():
    # Wizard 1 → 2: d4 rolls 1, Con 6 is -2: 1 - 2 is -1, raised to the minimum of 1.
    d, _ = dice(1)
    raised = ENGINE.level_up(sheet("Wizard", {"wizard": 1}, con=6), "wizard", REF, d)
    assert raised.hp_max == 11


def test_level_up_refills_the_numbers_for_the_new_level_and_scores():
    # Core's update calls only level_up on a patch that raises a level and changes the scores, so level_up refills.
    # Fighter 2: BAB +2, Fort +3. The patch also raised Con to 16 (+3): Fort 3 + 3 = 6.
    old = ENGINE.fill_derived(sheet("Fighter", {"fighter": 1}, con=10), REF)
    assert old.d20["derived"]["fort"] == 2
    patched = Sheet.from_dict({**old.to_dict(), "ability_scores": {**TEN, "con": 16}})
    d, _ = dice(5)
    raised = ENGINE.level_up(patched, "fighter", REF, d)
    assert (raised.d20["derived"]["bab"], raised.d20["derived"]["fort"]) == (2, 6)
    assert raised.d20["feats"] == [{"id": "power-attack"}]


def test_level_up_refills_a_casters_slots():
    # Wizard 3: 2 zero-level, 2 first, 1 second; Int 16 (+3) adds a bonus 1st and 2nd: {0: 4, 1: 3, 2: 2}.
    wizard = ENGINE.fill_derived(sheet("Wizard", {"wizard": 2}, int=16), REF)
    d, _ = dice(3)
    raised = ENGINE.level_up(wizard, "wizard", REF, d)
    assert raised.spell_slots == {0: 4, 1: 3, 2: 2}
    assert raised.d20["derived"]["slots"] == {"0": 4, "1": 3, "2": 2}


@pytest.mark.parametrize(
    ("cls", "levels", "race", "intelligence", "hints"),
    [
        # Fighter 1 → 2: 2 + 0 skill points, +1 for a human; a fighter bonus feat at fighter 2.
        ("fighter", {"fighter": 1}, "Human", 10, ["3 skill points", "a fighter bonus feat"]),
        # Fighter 2 → 3: 2 + 1 (Int 12); a feat at 3rd level.
        ("fighter", {"fighter": 2}, "Dwarf", 12, ["3 skill points", "a feat"]),
        # Fighter 3 → 4: 2 - 1 (Int 8); a fighter bonus feat at fighter 4 and an ability increase at 4th level.
        ("fighter", {"fighter": 3}, "Dwarf", 8, ["1 skill point", "a fighter bonus feat", "an ability increase"]),
        # Rogue 4 → 5: 8 + 0.
        ("rogue", {"rogue": 4}, "Halfling", 10, ["8 skill points"]),
        # Wizard 4 → 5: 2 + 3 (Int 16); a wizard bonus feat at wizard 5.
        ("wizard", {"wizard": 4}, "Elf", 16, ["5 skill points", "a wizard bonus feat"]),
        # Fighter 5 → 6: a feat at 6th level, and the class table's bonus feat at fighter 6.
        ("fighter", {"fighter": 5}, "Dwarf", 10, ["2 skill points", "a feat", "a fighter bonus feat"]),
        # Rogue 2 / wizard 3 → wizard 4: character level 6 gives the feat; Int 6 (-2) still gets the minimum 1.
        ("wizard", {"rogue": 2, "wizard": 3}, "Elf", 6, ["1 skill point", "a feat"]),
    ],
)
def test_level_up_hints(cls, levels, race, intelligence, hints):
    d, _ = dice(1)
    raised = ENGINE.level_up(sheet(cls.title(), levels, race=race, int=intelligence), cls, REF, d)
    said = raised.d20["level_up"]
    assert said["class"] == cls and said["level"] == levels[cls] + 1
    assert said["hints"] == hints


def test_the_first_level_has_four_times_the_skill_points_and_a_feat():
    # A human's first level: (2 + 0) × 4 + 4 extra = 12, a feat, the human's extra feat, a fighter bonus feat; the
    # hit die is the maximum (the SRD's first level), so nothing is rolled.
    raised = ENGINE.level_up(sheet("Fighter", {}, hp_max=0, con=12), "fighter", REF, dice()[0])
    assert raised.hp_max == 11  # d10 at its maximum, + 1 for Con 12
    assert raised.d20["level_up"]["hints"] == [
        "12 skill points",
        "a feat",
        "a racial bonus feat",
        "a fighter bonus feat",
    ]


def test_an_unknown_class_cannot_take_a_level():
    with pytest.raises(ValueError, match="Unknown class"):
        ENGINE.level_up(sheet("Bard", {"psion": 1}), "psion", REF, dice(3)[0])


def test_award_xp_adds_to_the_total():
    state = ENGINE.award_xp(Sheet(), CharacterState(hp=5, xp=700), 450)
    assert (state.xp, state.hp) == (1150, 5)


def test_progress_by_the_one_total():
    fighter = sheet("Fighter", {"fighter": 1})
    assert ENGINE.progress(fighter, CharacterState(xp=999), REF) == Progress(1, 999, 1000, ())
    assert ENGINE.progress(fighter, CharacterState(xp=3000), REF) == Progress(3, 3000, 1000, ("fighter",))


def test_progress_is_ready_no_further_than_the_slices_last_level():
    # 16,000 XP is 6th level, but the slice stops at 5th: a 5th-level character isn't ready, and has no next level.
    fifth = sheet("Fighter", {"fighter": 3, "rogue": 2})
    assert ENGINE.progress(fifth, CharacterState(xp=16000), REF) == Progress(6, 16000, None, ())
    fourth = sheet("Fighter", {"fighter": 2, "rogue": 2})
    assert ENGINE.progress(fourth, CharacterState(xp=16000), REF).ready == ("fighter", "rogue")


def test_rest_heals_level_per_day_and_refills_turning():
    # Cleric 3, two days: 3 × 2 = 6; with complete bed rest 12, capped at hp_max 20.
    cleric = sheet("Cleric", {"cleric": 3}, hp_max=20)
    hurt = CharacterState(hp=5, d20={"turning_used": 2})
    state, report = ENGINE.rest(cleric, hurt, 2)
    assert state.hp == 11 and state.d20 == {"turning_used": 0}
    assert report == {"healed": 6, "basis": "level × days (×2 complete bed rest)"}
    state, report = ENGINE.rest(cleric, hurt, 2, bed_rest=True)
    assert state.hp == 17 and report["healed"] == 12
    state, _ = ENGINE.rest(cleric, hurt, 7, bed_rest=True)
    assert state.hp == 20


def test_rest_counts_every_class_level():
    # Rogue 2 / wizard 1 is 3rd level: one day heals 3.
    state, _ = ENGINE.rest(sheet("Rogue/Wizard", {"rogue": 2, "wizard": 1}, hp_max=15), CharacterState(hp=4), 1)
    assert state.hp == 7 and state.d20 == {"turning_used": 0}


def test_drain_gives_negative_levels_and_takes_five_hit_points_each():
    # Fighter 3 at 20/25 drained twice: two negative levels, 10 hp off both the maximum and the current hit points.
    fighter = ENGINE.fill_derived(sheet("Fighter", {"fighter": 3}, hp_max=25), REF)
    after, state, said = ENGINE.drain(fighter, CharacterState(hp=20, xp=3500), 2, REF, dice()[0])
    assert after.levels == {"fighter": 3} and after.d20["negative_levels"] == 2
    assert (after.hp_max, state.hp, state.xp) == (15, 10, 3500)
    assert said == {"slain": False, "levels": 2, "negative_levels": 2, "hp_lost": 10}
    assert after.d20["feats"] == [{"id": "power-attack"}] and "derived" in after.d20
    # A third drain adds to the two.
    again, _, said = ENGINE.drain(after, state, 1, REF, dice()[0])
    assert again.d20["negative_levels"] == 3 and said["slain"] is True


def test_drain_to_zero_kills():
    # Wizard 2 drained twice: two negative levels on a 2nd-level character, so he dies.
    wizard = sheet("Wizard", {"wizard": 2}, hp_max=9)
    after, state, said = ENGINE.drain(wizard, CharacterState(hp=9), 2, REF, dice()[0])
    assert said["slain"] is True and state.hp == DEAD_AT
    assert after.d20["negative_levels"] == 2


def test_drain_leaves_at_least_one_hit_point_of_maximum():
    after, state, _ = ENGINE.drain(sheet("Fighter", {"fighter": 4}, hp_max=7), CharacterState(hp=7), 1, REF, dice()[0])
    assert (after.hp_max, state.hp) == (2, 2)
    after, state, _ = ENGINE.drain(after, state, 1, REF, dice()[0])
    assert (after.hp_max, state.hp) == (1, -3)


def test_drain_keeps_the_maximum_it_took():
    # Fighter 4 with hp_max 7: the first drain takes 5 (7 → 2), the second only 1 (2 → 1, the floor): 6 in all.
    after, state, _ = ENGINE.drain(sheet("Fighter", {"fighter": 4}, hp_max=7), CharacterState(hp=7), 1, REF, dice()[0])
    assert after.d20["drain_hp"] == 5
    after, _, _ = ENGINE.drain(after, state, 1, REF, dice()[0])
    assert after.d20["drain_hp"] == 6


def test_drain_that_takes_the_hp_past_dead_says_slain():
    # Fighter 5 at hp 2 drained 3 levels: 3 negative levels of 5 don't kill, but 2 - 15 = -13 is at or below -10.
    _, state, said = ENGINE.drain(sheet("Fighter", {"fighter": 5}, hp_max=30), CharacterState(hp=2), 3, REF, dice()[0])
    assert said["slain"] is True and state.hp == DEAD_AT


@pytest.mark.parametrize("levels", [0, -1])
def test_drain_refuses_fewer_than_one_level(levels):
    with pytest.raises(ValueError, match="at least 1"):
        ENGINE.drain(sheet("Fighter", {"fighter": 3}), CharacterState(hp=10), levels, REF, dice()[0])


def test_xp_for_an_orc_is_150():
    orc = next(row for row in REF.monster("orc") if row["id"] == "orc")
    assert orc["cr"] == "1/2"
    combatant = Combatant(id="orc-1", name="Orc", side="enemy", hp=5, hp_max=5, d20={"cr": progress.cr_for(orc)})
    assert ENGINE.xp_for_defeated(combatant, [1, 1, 1, 1]) == 150
    assert ENGINE.xp_for_defeated(combatant, [5]) == 150  # the same award whatever the party's levels


def test_no_cr_no_xp():
    plain = Combatant(id="x", name="X", side="enemy", hp=5, hp_max=5)
    assert ENGINE.xp_for_defeated(plain, [1]) is None
    unknown = Combatant(id="y", name="Y", side="enemy", hp=5, hp_max=5, d20={"cr": "None"})
    assert ENGINE.xp_for_defeated(unknown, [1]) is None


def test_a_skeleton_without_a_cr_takes_the_templates():
    skeleton = next(row for row in REF.monster("human warrior skeleton") if row["id"] == "human-warrior-skeleton")
    assert skeleton["cr"] == "None"
    assert progress.cr_for(skeleton) == "1/3"
    assert progress.cr_award(progress.cr_for(skeleton)) == 100


@pytest.mark.parametrize(
    ("monster", "cr"),
    [
        # The SRD's own skeleton and zombie statistics give these CRs; the template's table by Hit Dice agrees.
        ("wolf-skeleton", "1"),  # 2 HD
        ("owlbear-skeleton", "2"),  # 5 HD
        ("troll-skeleton", "3"),  # 6 HD
        ("chimera-skeleton", "4"),  # 9 HD
        ("ettin-skeleton", "5"),  # 10 HD
        ("advanced-megaraptor-skeleton", "6"),  # 12 HD
        ("cloud-giant-skeleton", "7"),  # 17 HD
        ("young-adult-red-dragon-skeleton", "8"),  # 19 HD
        ("human-commoner-zombie", "1/2"),  # its own CR, written 0.5
        ("ogre-zombie", "3"),
    ],
)
def test_cr_for_template_undead(monster, cr):
    row = next(r for r in REF.monster(monster.replace("-", " ")) if r["id"] == monster)
    assert progress.cr_for(row) == cr


def test_cr_for_the_zombie_table_and_other_rows():
    # A zombie row without a CR: 2 HD is 1/2, 3 HD falls between rows and takes the lower (1/2), 16 HD is 5.
    assert [progress.cr_for({"id": "x-zombie", "cr": "", "hit_dice": f"{hd}d12+3"}) for hd in (2, 3, 16)] == ["1/2",
                                                                                                          "1/2", "5"]  # fmt: skip
    assert progress.cr_for({"id": "orc", "cr": "1/2"}) == "1/2"
    assert progress.cr_for({"id": "thing", "cr": "None", "hit_dice": "3d8"}) is None
    assert progress.cr_for({"id": "big-skeleton", "cr": "None", "hit_dice": "24d12"}) is None
