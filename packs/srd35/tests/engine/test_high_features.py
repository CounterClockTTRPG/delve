"""The class features above 5th level (DEL-389 part 2): rage's numbers by level (greater, tireless and mighty rage,
indomitable will), damage reduction with its bypass, the monk's high levels (AC bonus, unarmed dice, fast movement,
ki strike), wild shape's sizes and plants and its elemental uses apart, smite evil to 5 a day, the companions'
tables to 20th, and the bard's music. Each number is worked by hand in its comment from the SRD's class tables
(`features.json`)."""

from __future__ import annotations

import pytest
from delve_srd35.engine import companions, numbers
from delve_srd35.reference import Srd35Reference
from test_class_features import Fight

from delve.domain.characters import Sheet

REF = Srd35Reference()
SCORES = {"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 12, "cha": 10}


@pytest.fixture
def fight(srd35_call, srd35_storage, srd35_campaign):
    return Fight(srd35_call, srd35_storage, srd35_campaign)


def derived(cls: str, level: int, race: str = "Human", **build) -> dict:
    sheet = Sheet(cls=cls.capitalize(), levels={cls: level}, race=race, ability_scores=dict(SCORES), d20=build)
    return numbers.derived(sheet, REF)


def feature(found: dict, fid: str) -> dict | None:
    return next((f for f in found["features"] if f["id"] == fid), None)


# --- rage --------------------------------------------------------------------------------------------------------


def test_rage_numbers_are_the_rows():
    # The SRD: rage +4 Str and Con, +2 Will; greater rage (11th) +6, +6, +3; mighty rage (20th) +8, +8, +4.
    from delve_srd35.engine.class_features import rage_numbers

    for level, expected in ((1, (4, 4, 2)), (10, (4, 4, 2)), (11, (6, 6, 3)), (19, (6, 6, 3)), (20, (8, 8, 4))):
        sheet = Sheet(cls="Barbarian", levels={"barbarian": level}, race="Human", ability_scores=dict(SCORES))
        got = rage_numbers(sheet)
        assert (got["str"], got["con"], got["will"]) == expected, level


def test_barbarian_11_greater_rage(fight):
    # Barbarian 11, Str 14, Con 12 (+1), greataxe. Greater rage: Str 20 (+5, 3 more) is +3 to hit, +4 damage two-handed
    # (3 × 1.5 = 4.5, rounded down); Con 18 (+4): 3 + 4 = 7 rounds, +3 hp per Hit Die (11) = 33; +3 Will (morale),
    # +3 Fort (the Con's +3 more).
    fight.character("Krug", "Barbarian", 11, weapon="greataxe")
    fight.enemies("orc")
    before = fight.combatant("Krug")
    out = fight.call("use_feature", character="Krug", feature="rage")
    assert "error" not in out, out
    assert (out["rounds"], out["hp_gained"]) == (7, 33)
    assert "+3 on Fortitude and Will saves while raging" in out["notes"][0]
    assert "+3 on melee attack rolls, +3 damage in melee and thrown (+4 two-handed)" in out["notes"][0]
    raging = fight.combatant("Krug")
    assert raging.hp_max == before.hp_max + 33
    # BAB +11/+6, Str +2, greataxe: +13, + rage 3; the face 2 hits the orc's AC 13. 1d12 face 6 + Str 3 + rage 4 = 13.
    swing = fight.swing("Krug", "Orc", 2, 6)
    assert swing.hit and swing.damage == 6 + 3 + 4 and "rage: +3 to hit, +4 damage" in swing.notes
    will = fight.call("saving_throw", character="Krug", save_type="will", dc=10)
    fort = fight.call("saving_throw", character="Krug", save_type="fort", dc=10)
    ref = fight.call("saving_throw", character="Krug", save_type="ref", dc=10)
    assert (will["modifier"], fort["modifier"], ref["modifier"]) == (3, 3, 0)
    # Out of the fight, the character's own save reads the rage by the sheet's level too.
    fight.call("end_combat")
    will = fight.call("saving_throw", character="Krug", save_type="will", dc=10)
    assert will["modifier"] == 3
    # Ended: the 33 hp come off and, below 17th, Krug is fatigued.
    ended = fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    assert ended["fatigued"] is True
    assert fight.state("Krug").sheet.hp_max == before.hp_max


def test_barbarian_20_mighty_and_tireless_rage(fight):
    # Barbarian 20, Str 14, Con 12, greataxe. Mighty rage: Str 22 (+6, 4 more): +4 to hit, +6 damage two-handed; Con 20
    # (+5): 3 + 5 = 8 rounds, +4 hp per Hit Die (20) = 80; +4 Will and Fort. Tireless rage: not fatigued at its end.
    fight.character("Krug", "Barbarian", 20, weapon="greataxe")
    fight.enemies("orc")
    out = fight.call("use_feature", character="Krug", feature="rage")
    assert (out["rounds"], out["hp_gained"]) == (8, 80)
    assert "fatigued" not in " ".join(out["notes"])
    swing = fight.swing("Krug", "Orc", 2, 6)
    assert swing.hit and swing.damage == 6 + 3 + 6 and "rage: +4 to hit, +6 damage" in swing.notes
    assert fight.call("saving_throw", character="Krug", save_type="will", dc=10)["modifier"] == 4
    assert fight.call("saving_throw", character="Krug", save_type="fort", dc=10)["modifier"] == 4
    ended = fight.call("use_feature", character="Krug", feature="rage", amount=-1)
    assert ended["fatigued"] is False and "fatigued" not in fight.combatant("Krug").conditions


def test_tireless_rage_from_17th(fight):
    # Barbarian 16: fatigued at the rage's end; 17: tireless.
    for name, level, tired in (("Krug", 16, True), ("Brak", 17, False)):
        fight.character(name, "Barbarian", level)
        fight.call("use_feature", character=name, feature="rage")
        assert fight.call("use_feature", character=name, feature="rage", amount=-1)["fatigued"] is tired, level


def test_rage_hit_points_are_per_hit_die(fight):
    # A gnoll barbarian 1: 2 racial Hit Dice and 1 class level, 3 Hit Dice: rage's Con +4 (+2) is 6 hp, not 2.
    out = fight.call("create_character", name="Grak", sheet={"cls": "Barbarian", "level": 1, "race": "Gnoll",
                                                             "hp_max": 20, "ability_scores": dict(SCORES)})  # fmt: skip
    assert "error" not in out, out
    rage = fight.call("use_feature", character="Grak", feature="rage")
    assert "error" not in rage, rage
    assert rage["hp_gained"] == 6
    assert fight.state("Grak").sheet.hp_max == 26


def test_indomitable_will_from_14th(fight):
    # Indomitable will (14th): +4 on Will saves against enchantment while raging, said in the rage's notes; the
    # engine doesn't add it (the save doesn't know an enchantment).
    fight.character("Krug", "Barbarian", 14)
    out = fight.call("use_feature", character="Krug", feature="rage")
    assert any("+4 on Will saves against enchantment spells" in note for note in out["notes"])
    assert fight.call("saving_throw", character="Krug", save_type="will", dc=10)["modifier"] == 3
    fight.character("Brak", "Barbarian", 13)
    out = fight.call("use_feature", character="Brak", feature="rage")
    assert not any("enchantment" in note for note in out["notes"])
    found = feature(derived("barbarian", 14), "indomitable-will")
    assert found is not None and found["value"] == 4


# --- damage reduction --------------------------------------------------------------------------------------------


def test_damage_reduction_carries_its_bypass():
    # The barbarian's DR: 1/— at 7th, 2/— at 10th (so at 11th), 5/— at 19th; the row's bypass "—" (none bypasses it).
    from delve_srd35.engine import features

    row = next(r for r in features.rows("barbarian") if r["id"] == "damage-reduction")
    assert row["bypass"] == "—"
    assert derived("barbarian", 11)["dr"] == "2/—"
    assert derived("barbarian", 19)["dr"] == "5/—"
    assert derived("barbarian", 20)["dr"] == "5/—"


# --- the monk ----------------------------------------------------------------------------------------------------


def test_monk_ac_bonus_to_4():
    # Monk, Dex 12 (+1), Wis 12 (+1), unarmoured: 10 + 1 + 1 + the class bonus (+2 at 10th, +3 at 15th, +4 at 20th).
    assert [derived("monk", level)["ac"] for level in (10, 15, 20)] == [14, 15, 16]


def test_monk_fast_movement_to_60():
    # A human's 30 ft. + the monk's +60 ft. at 18th; +50 at 15th.
    assert derived("monk", 15)["speed"] == 80
    assert derived("monk", 18)["speed"] == 90


def test_monk_unarmed_dice_by_size(fight):
    # The monk's unarmed damage: Medium 2d8 at 16th, 2d10 at 20th; Small 2d6 at 16th, 2d8 at 20th. Str 14 (+2) on each
    # (the sheet's scores are as given).
    fight.character("Mei", "Monk", 20)
    fight.character("Lin", "Monk", 16)
    out = fight.call("create_character", name="Pip", sheet={"cls": "Monk", "level": 20, "race": "Halfling",
                                                            "hp_max": 100, "ability_scores": dict(SCORES)})  # fmt: skip
    assert "error" not in out, out
    fight.enemies("orc")
    assert fight.combatant("Mei").d20["attacks"][0]["damage"] == "2d10+2"
    assert fight.combatant("Lin").d20["attacks"][0]["damage"] == "2d8+2"
    assert fight.combatant("Pip").d20["attacks"][0]["damage"] == "2d8+2"


def test_ki_strike_on_the_unarmed_form(fight):
    # Ki strike: magic at 4th, lawful too at 10th, adamantine too at 16th; none at 3rd.
    for name, level in (("A", 3), ("B", 4), ("C", 10), ("D", 16)):
        fight.character(name, "Monk", level)
    fight.enemies("orc")
    assert "bypasses" not in fight.combatant("A").d20["attacks"][0]
    assert fight.combatant("B").d20["attacks"][0]["bypasses"] == ["magic"]
    assert fight.combatant("C").d20["attacks"][0]["bypasses"] == ["magic", "lawful"]
    assert fight.combatant("D").d20["attacks"][0]["bypasses"] == ["magic", "lawful", "adamantine"]
    # A monk with a weapon in hand: no ki strike on it.
    fight.character("E", "Monk", 10, weapon="quarterstaff")
    fight.call("end_combat")
    fight.enemies("orc")
    assert "bypasses" not in fight.combatant("E").d20["attacks"][0]


def test_monk_notes_and_their_uses():
    # Diamond body (11th) is a note; abundant step (12th) 1 a day; quivering palm (15th) 1 a week.
    found = derived("monk", 15)
    assert feature(found, "diamond-body")["kind"] == "note"
    step, palm = feature(found, "abundant-step"), feature(found, "quivering-palm")
    assert (step["kind"], step["per_day"]) == ("uses", 1)
    assert (palm["kind"], palm["per_day"], palm["per"]) == ("uses", 1, "week")
    assert feature(derived("monk", 14), "quivering-palm") is None


# --- wild shape --------------------------------------------------------------------------------------------------


def test_wild_shape_tiny_at_11_and_plants_at_12(srd35_call, fight):
    # Tiny animals from 11th (a cat), plants from 12th (a shrieker).
    fight.character("Ash", "Druid", 10)
    assert "error" in srd35_call("use_feature", character="Ash", feature="wild-shape", target="cat")
    fight.character("Bryn", "Druid", 11)
    assert "error" not in srd35_call("use_feature", character="Bryn", feature="wild-shape", target="cat")
    assert "error" in srd35_call("use_feature", character="Bryn", feature="wild-shape", target="shrieker")
    fight.character("Cael", "Druid", 12)
    assert "error" not in srd35_call("use_feature", character="Cael", feature="wild-shape", target="shrieker")


def test_wild_shape_huge_at_15(srd35_call, fight):
    # Huge from 15th: a treant (Huge plant, 7 HD).
    fight.character("Ash", "Druid", 14)
    assert "Huge" in srd35_call("use_feature", character="Ash", feature="wild-shape", target="treant")["error"]
    fight.character("Bryn", "Druid", 15)
    assert "error" not in srd35_call("use_feature", character="Bryn", feature="wild-shape", target="treant")


def test_wild_shape_elementals_have_their_own_uses(srd35_call, fight):
    # Druid 16: wild shape 5 a day and an elemental once a day "in addition to her normal wild shape usage". The
    # elemental spends its own use; the second is refused, while her ordinary uses are all left.
    fight.character("Ash", "Druid", 16)
    found = feature(fight.state("Ash").sheet.d20["derived"], "wild-shape")
    assert (found["per_day"], found["elemental_per_day"]) == (5, 1)
    out = srd35_call("use_feature", character="Ash", feature="wild-shape", target="medium earth elemental")
    assert "error" not in out, out
    assert out["uses_left"] == 0
    used = fight.state("Ash").state.d20["used"]
    assert used == {"wild-shape-elemental": 1}
    srd35_call("use_feature", character="Ash", feature="wild-shape", target="")
    refused = srd35_call("use_feature", character="Ash", feature="wild-shape", target="small fire elemental")
    assert "Elemental wild shape: 1 a day at this level, used 1." in refused["error"]
    out = srd35_call("use_feature", character="Ash", feature="wild-shape", target="wolf")
    assert "error" not in out and out["uses_left"] == 4
    # Huge elementals only at 20th, with 3 a day.
    assert "Huge" in srd35_call("use_feature", character="Ash", feature="wild-shape",
                                target="huge air elemental")["error"]  # fmt: skip
    fight.character("Bryn", "Druid", 20)
    assert feature(fight.state("Bryn").sheet.d20["derived"], "wild-shape")["elemental_per_day"] == 3
    assert "error" not in srd35_call("use_feature", character="Bryn", feature="wild-shape", target="huge air elemental")


def test_a_druid_below_16_has_no_elemental_uses():
    assert "elemental_per_day" not in feature(derived("druid", 15), "wild-shape")


# --- the paladin and the companions ------------------------------------------------------------------------------


def test_smite_evil_to_5_a_day(fight):
    # Smite evil 4 a day at 15th, 5 at 20th; +20 damage at 20th (the paladin level).
    assert feature(derived("paladin", 15), "smite-evil")["per_day"] == 4
    assert feature(derived("paladin", 20), "smite-evil")["per_day"] == 5
    fight.character("Aldra", "Paladin", 20, scores={"cha": 14})
    fight.enemies("orc")
    out = fight.call("use_feature", character="Aldra", feature="smite evil")
    assert out["smite"] == {"to_hit": 2, "damage": 20} and out["uses_left"] == 4


def test_the_companion_tables_to_20():
    # The special mount at 15th-20th: +8 HD, +10 natural armour, +4 Str, Int 9, spell resistance; the animal
    # companion at 18th-20th: +12 HD, +12 natural armour, +6 Str and Dex, 7 tricks.
    mount = companions.block("special-mount", 20)
    assert (mount["bonus_hd"], mount["natural_armour"], mount["str"], mount["int"]) == (8, 10, 4, 9)
    assert "spell resistance" in mount["special"]
    animal = companions.block("animal-companion", 20)
    assert (animal["bonus_hd"], animal["natural_armour"], animal["str"], animal["dex"], animal["tricks"]) == \
        (12, 12, 6, 6, 7)  # fmt: skip


# --- the bard ----------------------------------------------------------------------------------------------------


def test_inspire_courage_by_level(fight):
    # Inspire courage +2 at 8th, +3 at 14th, +4 at 20th.
    assert [feature(derived("bard", level), "inspire-courage")["value"] for level in (7, 8, 14, 20)] == [1, 2, 3, 4]
    fight.character("Lyra", "Bard", 14, skills={"perform": 17})
    fight.enemies("orc")
    out = fight.call("use_feature", character="Lyra", feature="inspire courage")
    assert out["effect"] == "Inspire Courage +3"
    effect = next(e for e in fight.combatant("Lyra").effects if e.name == "Inspire Courage +3")
    assert (effect.to_hit, effect.dmg) == (3, 3)


def test_the_bards_high_music_as_notes_with_their_uses():
    # Inspire greatness (9th: one ally, one more per three levels past 9th), song of freedom (12th), inspire heroics
    # (15th: one ally, one more per three levels past 15th), mass suggestion (18th): each spends a bardic music use.
    # The lower songs too: every bardic music performance spends one of its uses a day.
    found = derived("bard", 18)
    for fid in ("countersong", "fascinate", "inspire-courage", "inspire-competence", "suggestion"):
        assert feature(found, fid)["spends"] == "bardic-music", fid
    for fid in ("inspire-greatness", "song-of-freedom", "inspire-heroics", "mass-suggestion"):
        assert feature(found, fid)["kind"] == "note" and feature(found, fid)["spends"] == "bardic-music", fid
    assert feature(found, "inspire-greatness")["value"] == 4  # 9th, 12th, 15th, 18th
    assert feature(found, "inspire-heroics")["value"] == 2  # 15th, 18th
    assert feature(found, "bardic-music")["per_day"] == 18
    assert feature(derived("bard", 17), "mass-suggestion") is None


def test_a_low_song_spends_bardic_music_by_its_row(fight):
    # Inspire courage spends bardic music by its row's `spends` (no list in the engine): a bard 1 has 1 a day.
    fight.character("Lyra", "Bard", 1, skills={"perform": 4})
    fight.enemies("orc")
    assert "error" not in fight.call("use_feature", character="Lyra", feature="inspire courage")
    assert fight.state("Lyra").state.d20["used"] == {"bardic-music": 1}
    refused = fight.call("use_feature", character="Lyra", feature="inspire courage")
    assert "Bardic music: 1 a day at this level, used 1." in refused["error"]
