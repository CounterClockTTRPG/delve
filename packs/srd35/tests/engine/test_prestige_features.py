"""The prestige classes' features that need code (DEL-389 part 4): sneak attack dice from several classes, uncanny dodge
from two classes, evasion, the dragon disciple's natural armour and ability boosts, the duelist's canny defense, grace
and precise strike, damage reduction from two classes, the dwarven defender's defensive stance, the blackguard's smite
good and command undead, the arcane archer's enhance arrow, and the features used so many times a day. Each value is
the SRD's at its level, in the comment beside it."""

from __future__ import annotations

import dataclasses

import pytest
from delve_srd35.engine import Srd35Engine, class_features, defences, features, magic
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.campaigns import Character
from delve.domain.characters import CharacterState, Sheet
from delve.rules.classic import combat as rules
from delve.rules.classic.combat import Combatant
from delve.rules.classic.tables import FightRules

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
SCORES = {"str": 14, "dex": 12, "con": 14, "int": 10, "wis": 12, "cha": 14}


def dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


def sheet(levels: dict[str, int], race: str = "Human", scores: dict | None = None, **d20) -> Sheet:
    cls = "/".join(c.title() for c in levels)
    made = Sheet(label="Ansel", cls=cls, race=race, alignment="", levels=levels, hp_max=30,
                 ability_scores={**TEN, **(scores or {})}, d20=d20)  # fmt: skip
    return ENGINE.fill_derived(made, REF)


def derived(levels: dict[str, int], race: str = "Human", scores: dict | None = None, **d20) -> dict:
    return sheet(levels, race, scores, **d20).d20["derived"]


def hero(levels: dict[str, int], race: str = "Human", scores: dict | None = None, **d20) -> Combatant:
    made = sheet(levels, race, scores, **d20)
    character = Character("pc_1", "c", "Hero", sheet=made)
    return ENGINE.combatant_from_sheet(character, Combatant("pc_1", "Hero", "party", character_id="pc_1", hp=10))


def target(ac: int = 10, **d20) -> Combatant:
    numbers = {"ac": ac, "touch": ac, "flat_footed": ac, "dex": 0, "crit_immune": False, **d20}
    return Combatant("t", "Target", "enemy", hp=40, init=10, d20=numbers)


def swing(attacker: Combatant, defender: Combatant, *faces: int, condition: str = ""):
    rolled, rng = dice(*faces)
    out = ENGINE.swing(dataclasses.replace(attacker, init=30), dataclasses.replace(defender, init=0), condition, rolled,
                       2, FightRules())  # fmt: skip
    rng.assert_done()
    return out


# --- sneak attack, uncanny dodge, evasion --------------------------------------------------------------------------


def test_sneak_attack_dice_from_several_classes_add_up():
    # "If an assassin gets a sneak attack bonus from another source the bonuses on damage stack": rogue 3 (+2d6) and
    # assassin 2 (+1d6) is +3d6; the arcane trickster's and the blackguard's stack the same way.
    assert derived({"rogue": 3, "assassin": 2})["sneak"] == "3d6"
    assert derived({"rogue": 4, "arcane-trickster": 2})["sneak"] == "3d6"
    assert derived({"rogue": 1, "fighter": 6, "blackguard": 4})["sneak"] == "2d6"
    assert derived({"rogue": 5})["sneak"] == "3d6"


def test_uncanny_dodge_from_two_classes_is_improved_uncanny_dodge():
    # "If a character gains uncanny dodge from a second class, the character automatically gains improved uncanny
    # dodge, and the levels from those classes stack to determine the minimum rogue level required to flank": a
    # barbarian 2 / rogue 4 has it at 6, a rogue must be 10th to flank him.
    found = derived({"barbarian": 2, "rogue": 4})
    assert found["uncanny_dodge"] is True and found["improved_uncanny_dodge"] == 6
    assert "improved_uncanny_dodge" not in derived({"rogue": 4})
    # A rogue's own at 8th: "a rogue at least four levels higher than the rogue can flank him".
    assert derived({"rogue": 8})["improved_uncanny_dodge"] == 8


def test_improved_uncanny_dodge_denies_flanking_to_a_lower_rogue():
    # The barbarian 2 / rogue 4 (flank level 6) flanked by a rogue 9: no +2 and no sneak dice; by a rogue 10, both.
    defender = hero({"barbarian": 2, "rogue": 4})
    assert defender.d20["improved_uncanny_dodge"] == 6
    defender = dataclasses.replace(defender, conditions=("flanked",))
    nine = hero({"rogue": 9}, scores={"str": 10})
    out = swing(nine, defender, 10, 3)  # 10 + 6 (BAB) hits AC 10; an unarmed strike, 1d3
    assert "improved uncanny dodge: can't be flanked (rogue level 9, needs 10)" in out.notes
    assert "+2 to hit (flanking)." not in out.notes and not any("sneak attack" in n for n in out.notes)
    ten = hero({"rogue": 10}, scores={"str": 10})
    rolled = swing(ten, defender, 10, 3, 1, 1, 1, 1, 1)
    assert "+2 to hit (flanking)." in rolled.notes and "sneak attack +5d6" in rolled.notes



def test_the_attackers_rogue_level_is_its_rogue_levels_only():
    # "a rogue at least four levels higher than the [target] can flank him": the levels stack on the target's side
    # only. A rogue 2 / blackguard 10 has sneak attack from both, but is a 2nd-level rogue: it can't flank the
    # barbarian 2 / rogue 4 (needs 10).
    defender = dataclasses.replace(hero({"barbarian": 2, "rogue": 4}), conditions=("flanked",))
    mixed = hero({"rogue": 2, "blackguard": 10}, scores={"str": 10})
    out = swing(mixed, defender, 10, 3)
    assert "improved uncanny dodge: can't be flanked (rogue level 2, needs 10)" in out.notes

def test_evasion_in_light_or_no_armour():
    # Evasion from the rogue's 2nd, the monk's, the shadowdancer's; improved evasion from the monk's 9th and the
    # shadowdancer's 10th. "The evasion ability can only be used if the shadowdancer is wearing light armor or no
    # armor."
    assert derived({"rogue": 2})["evasion"] == "evasion"
    assert derived({"rogue": 2}, armor="leather")["evasion"] == "evasion"
    assert "evasion" not in derived({"rogue": 2}, armor="chainmail")
    assert derived({"rogue": 5, "shadowdancer": 10})["evasion"] == "improved evasion"
    assert derived({"monk": 9})["evasion"] == "improved evasion"
    assert "evasion" not in derived({"fighter": 2})


# --- the dragon disciple -----------------------------------------------------------------------------------------


def test_dragon_disciple_natural_armour_and_ability_boosts():
    # Dragon disciple 2: natural armor increase +1 (Table: The Dragon Disciple, 1st), ability boost Str +2 (2nd). Str
    # 10 → 12 (+1); the natural armour counts in AC and flat-footed AC, not touch.
    plain = derived({"sorcerer": 5})
    two = sheet({"sorcerer": 5, "dragon-disciple": 2})
    found = two.d20["derived"]
    assert (found["ac"], found["touch"], found["flat_footed"]) == (plain["ac"] + 1, plain["touch"],
                                                                   plain["flat_footed"] + 1)  # fmt: skip
    assert found["abilities"] == {"str": 12}
    # 8th: Str +4, Con +2, Int +2 in all, natural armour +3 (from 7th).
    eight = derived({"sorcerer": 5, "dragon-disciple": 8})
    assert eight["abilities"] == {"str": 14, "con": 12, "int": 12}
    assert eight["ac"] == plain["ac"] + 3
    # 10th, dragon apotheosis: "he gains +4 to Strength and +2 to Charisma. His natural armor bonus increases to +4".
    ten = derived({"sorcerer": 5, "dragon-disciple": 10})
    assert ten["abilities"] == {"str": 18, "con": 12, "int": 12, "cha": 12}
    assert ten["ac"] == plain["ac"] + 4
    # The boosts are "gained as if through level advancement": they count for skill points too.
    from delve_srd35.engine import numbers

    assert numbers.skill_point_score(two, "str") == 12


# --- the duelist -------------------------------------------------------------------------------------------------


def test_duelist_canny_defense():
    # "When not wearing armor or using a shield, a duelist adds 1 point of Intelligence bonus (if any) per duelist
    # class level to her Dexterity bonus to modify Armor Class while wielding a melee weapon"; lost when flat-footed.
    # Int 16 (+3): duelist 1 is +1, duelist 3 +3.
    base = {"fighter": 6}
    plain = derived(base, scores={"int": 16}, weapon="rapier")
    one = derived({**base, "duelist": 1}, scores={"int": 16}, weapon="rapier")
    three = derived({**base, "duelist": 3}, scores={"int": 16}, weapon="rapier")
    assert (one["ac"], one["touch"], one["flat_footed"]) == (plain["ac"] + 1, plain["touch"] + 1, plain["flat_footed"])
    assert three["ac"] == plain["ac"] + 3
    # Not in armour, not with a shield, not without a melee weapon.
    assert (
        derived({**base, "duelist": 3}, scores={"int": 16}, weapon="rapier", armor="leather")["ac"] == plain["ac"] + 2
    )
    assert (
        derived({**base, "duelist": 3}, scores={"int": 16}, weapon="rapier", shield="buckler")["ac"] == plain["ac"] + 1
    )
    assert derived({**base, "duelist": 3}, scores={"int": 16}, weapon="longbow")["ac"] == plain["ac"]


def test_duelist_improved_reaction_and_grace():
    # Improved reaction +2 on initiative at 2nd; grace, "+2 competence bonus on all Reflex saving throws" at 4th,
    # "only when she is wearing no armor and not using a shield".
    base = derived({"fighter": 6})
    four = derived({"fighter": 6, "duelist": 4})
    assert four["init"] == base["init"] + 2
    assert four["ref"] == base["ref"] + 4 + 2  # the duelist's own Ref +4 at 4th, and grace
    assert derived({"fighter": 6, "duelist": 4}, armor="leather")["ref"] == base["ref"] + 4


def test_duelist_precise_strike():
    # Precise strike at 5th: +1d6 "with a light or one-handed piercing weapon"; "Any creature that is immune to
    # critical hits is not vulnerable to a precise strike". Fighter 6 / duelist 5, BAB +11, Str 10: a rapier 1d6.
    duelist = hero({"fighter": 6, "duelist": 5}, weapon="rapier")
    assert duelist.d20["attacks"][0]["precise"] == "1d6"
    out = swing(duelist, target(), 10, 3, 4)
    assert out.damage == 3 + 4 and "precise strike +1d6" in out.notes
    immune = swing(duelist, target(crit_immune=True), 10, 3)
    assert immune.damage == 3 and "immune to precise strike" in immune.notes
    # A longsword slashes; with a shield she can't.
    assert "precise" not in hero({"fighter": 6, "duelist": 5}, weapon="longsword").d20["attacks"][0]
    assert "precise" not in hero({"fighter": 6, "duelist": 5}, weapon="rapier", shield="buckler").d20["attacks"][0]
    assert hero({"fighter": 6, "duelist": 10}, weapon="dagger").d20["attacks"][0]["precise"] == "2d6"


# --- damage reduction, the blackguard's undead ---------------------------------------------------------------------


def test_damage_reduction_from_two_classes_is_the_highest():
    # The SRD's Damage Reduction: "If a creature has damage reduction from more than one source, the two forms of
    # damage reduction do not stack"; neither class's text says otherwise. Barbarian 10 (2/—) and dwarven defender 6
    # (3/—): 3/—.
    assert derived({"barbarian": 10, "dwarven-defender": 6}, race="Dwarf")["dr"] == "3/—"
    assert derived({"barbarian": 13, "dwarven-defender": 6}, race="Dwarf")["dr"] == "3/—"
    assert derived({"fighter": 7, "dwarven-defender": 10}, race="Dwarf")["dr"] == "6/—"


def test_dwarven_defender_ac_bonus_is_a_dodge_bonus():
    # "The dwarven defender receives a dodge bonus to Armor Class", +1 at 1st: in AC and touch AC, not flat-footed.
    plain = derived({"fighter": 6}, race="Dwarf")
    one = derived({"fighter": 6, "dwarven-defender": 1}, race="Dwarf")
    assert (one["ac"], one["touch"], one["flat_footed"]) == (plain["ac"] + 1, plain["touch"] + 1, plain["flat_footed"])


def test_blackguard_commands_undead_as_a_cleric_two_levels_lower():
    # Command undead at 3rd: "He commands undead as would a cleric of two levels lower": blackguard 5 at turning
    # level 3, 3 + Cha (14: +2) = 5 a day; none before 3rd.
    five = sheet({"fighter": 6, "blackguard": 5}, scores={"cha": 14})
    assert magic.turning_level(five) == 3
    assert five.d20["derived"]["turning_per_day"] == 5
    assert magic.turning_level(sheet({"fighter": 6, "blackguard": 2})) == 0
    # It rebukes: check 13 + 2 = 15, Table: Turning Undead level + 1 = 4 HD; damage 2d6 (3 + 4) + 3 + 2 = 12.
    roll, rng = dice(13, 3, 4)
    said = ENGINE.turn_undead(five, 0, "ghoul", 0, roll, actor="pc_1", state=CharacterState(hp=20))
    rng.assert_done()
    assert (said["max_hd"], said["total_hd"], said["rebukes"]) == (4, 12, True)


def test_shadowdancer_summon_shadow_is_one_shadow_growing():
    # "Every third level gained by the shadowdancer adds +2 HD ... to her shadow companion": one shadow, +2 HD at 6th
    # and +4 at 9th, not two or three shadows.
    def shadow(level: int):
        made = sheet({"rogue": 5, "shadowdancer": level})
        return next(f["value"] for f in made.d20["derived"]["features"] if f["id"] == "summon-shadow")

    assert (shadow(3), shadow(6), shadow(9)) == ("+0 HD", "+2 HD", "+4 HD")


# --- the arcane archer -----------------------------------------------------------------------------------------------


def test_enhance_arrow_makes_the_arrows_magic():
    # "every nonmagical arrow an arcane archer nocks and lets fly becomes magical, gaining a +1 enhancement bonus ...
    # (+1 at 1st level, +2 at 3rd level ...)". Fighter 6 / arcane archer 1, BAB +7, Dex 10: a longbow +7 + 1, 1d8 + 1,
    # magic against DR.
    archer = hero({"fighter": 6, "arcane-archer": 1}, race="Elf", weapon="longbow")
    form = archer.d20["attacks"][0]
    plain = hero({"fighter": 7}, race="Elf", weapon="longbow").d20["attacks"][0]
    assert (form["bonus"], form["damage"], form["enhancement"]) == (plain["bonus"] + 1, "1d8+1", 1)
    assert "magic" in defences.overcomes(archer, form)
    # A +2 longbow's arrows are +2 already: the higher counts, they don't stack. At 3rd the arrows are +2 and a +1 bow
    # adds nothing more.
    assert (
        hero({"fighter": 6, "arcane-archer": 1}, race="Elf", weapon="+2 longbow").d20["attacks"][0]["enhancement"] == 2
    )
    three = hero({"fighter": 6, "arcane-archer": 3}, race="Elf", weapon="+1 longbow").d20["attacks"][0]
    assert three["enhancement"] == 2 and three["damage"] == "1d8+2"
    # Not a crossbow's bolts, not a sword.
    assert "enhancement" not in hero({"fighter": 6, "arcane-archer": 1}, race="Elf",
                                     weapon="crossbow, light").d20["attacks"][0]  # fmt: skip


def test_the_arcane_archers_once_a_day_arrows_are_uses():
    # Seeker arrow at 4th and phase arrow at 6th, each "once per day"; hail of arrows at 8th "once per day".
    found = {f["id"]: f for f in derived({"fighter": 6, "arcane-archer": 8}, race="Elf")["features"]}
    assert [found[i]["per_day"] for i in ("seeker-arrow", "phase-arrow", "hail-of-arrows")] == [1, 1, 1]


# --- use_feature -----------------------------------------------------------------------------------------------------


class Fight:
    def __init__(self, call, storage, campaign):
        self.call, self.storage, self.campaign = call, storage, campaign

    def character(self, name: str, levels: dict[str, int], race: str = "Human", **build) -> None:
        made = self.call("create_character", name=name,
                         sheet={"cls": "/".join(levels), "levels": levels, "race": race, "hp_max": 40,
                                "ability_scores": SCORES})  # fmt: skip
        assert "error" not in made, made
        if build:
            out = self.call("set_build", character=name, **build)
            assert "error" not in out, out

    def enemies(self, *names: str) -> None:
        out = self.call("setup_combat", enemies=[{"name": n, "count": 1, "hp": 30} for n in names], surprise=False)
        assert "error" not in out, out

    def combatant(self, name: str) -> Combatant:
        fight = rules.from_json(self.storage.combats.live(self.campaign.id)[1])
        return next(c for c in fight.combatants.values() if c.name == name)

    def swing(self, attacker: str, defender: str, *faces: int):
        return swing(self.combatant(attacker), self.combatant(defender), *faces)


@pytest.fixture
def fight(srd35_call, srd35_storage, srd35_campaign):
    return Fight(srd35_call, srd35_storage, srd35_campaign)


def test_defensive_stance(fight):
    # Dwarven defender 1, Con 14: "+2 to Strength, +4 to Constitution, a +2 resistance bonus on all saves, and a +4
    # dodge bonus to AC"; it "lasts for a number of rounds equal to 3 + the character's (newly improved) Constitution
    # modifier": Con 18, 3 + 4 = 7; "increases the defender's hit points by 2 points per level": 2. 1 a day at 1st.
    fight.character("Brom", {"dwarven-defender": 1}, race="Dwarf", weapon="warhammer")
    fight.enemies("orc")
    before = fight.combatant("Brom")
    out = fight.call("use_feature", character="Brom", feature="defensive stance")
    assert "error" not in out, out
    effect = out["effect"]
    assert (effect["name"], effect["duration"], effect.get("ac")) == ("Defensive Stance", 7, -4)
    assert out["hp_gained"] == 2 and out["uses_left"] == 0
    standing = fight.combatant("Brom")
    assert (standing.hp, standing.hp_max) == (before.hp + 2, before.hp_max + 2)
    # +4 on Fortitude (+2 resistance, +2 of the Con), +2 on Reflex and Will.
    saves = [
        fight.call("saving_throw", character="Brom", save_type=s, dc=10)["modifier"] for s in ("fort", "ref", "will")
    ]
    assert saves == [4, 2, 2]
    # Str 16 (+3): +1 to hit and +1 damage in melee. The warhammer 1d8: 15 hits; 4 + 2 + 1.
    hit = fight.swing("Brom", "Orc", 15, 4)
    assert hit.damage == 4 + 2 + 1 and "defensive stance: +1 to hit, +1 damage" in hit.notes
    assert fight.call("use_feature", character="Brom", feature="defensive-stance")["error"].startswith(
        "Brom is already in a defensive stance"
    )
    # Ended: the hit points go, and "the defender is winded and takes a –2 penalty to Strength for the duration of
    # that encounter": Str 14 → 12, one less to hit.
    ended = fight.call("use_feature", character="Brom", feature="defensive stance", amount=-1)
    assert "error" not in ended, ended
    after = fight.combatant("Brom")
    assert (after.hp, after.hp_max) == (before.hp, before.hp_max)
    assert "winded" in after.conditions and not any(e.name == "Defensive Stance" for e in after.effects)
    assert after.d20["attacks"][0]["bonus"] == before.d20["attacks"][0]["bonus"] - 1
    refused = fight.call("use_feature", character="Brom", feature="defensive stance")
    assert "Defensive stance: 1 a day at this level, used 1." in refused["error"]



def test_defensive_stance_dodge_is_lost_flat_footed(fight):
    # The stance's "+4 dodge bonus to AC" goes with the Dex bonus when the defender is flat-footed (SRD: a dodge
    # bonus is lost whenever the character loses its Dex bonus to AC).
    fight.character("Brom", {"dwarven-defender": 1}, race="Dwarf", weapon="warhammer")
    fight.enemies("orc")
    assert "error" not in fight.call("use_feature", character="Brom", feature="defensive stance")
    brom = fight.combatant("Brom")
    standing = fight.swing("Orc", "Brom", 2)  # a miss: no damage rolled
    assert "-4 AC modifier on Brom (active effects)." in standing.notes
    caught = swing(fight.combatant("Orc"), dataclasses.replace(brom, conditions=("flat-footed",)), 2)
    assert "flat-footed" in caught.notes and not any("AC modifier" in n for n in caught.notes)

def test_winded_ends_with_the_encounter(fight):
    # "winded ... for the duration of that encounter": the fight's end takes it off; the next fight's Str is whole.
    fight.character("Brom", {"dwarven-defender": 1}, race="Dwarf", weapon="warhammer")
    fight.enemies("orc")
    before = fight.combatant("Brom").d20["attacks"][0]["bonus"]
    fight.call("use_feature", character="Brom", feature="defensive stance")
    fight.call("use_feature", character="Brom", feature="defensive stance", amount=-1)
    ended = fight.call("end_combat")
    assert "error" not in ended, ended
    assert "winded" not in next(iter(ended["characters"].values()))["conditions"]
    (brom,) = fight.storage.characters.list(fight.campaign.id)
    assert "winded" not in brom.state.conditions
    fight.enemies("orc")
    again = fight.combatant("Brom")
    assert "winded" not in again.conditions and again.d20["attacks"][0]["bonus"] == before


def test_a_rest_ends_a_defensive_stance_left_on(fight):
    fight.character("Brom", {"dwarven-defender": 1}, race="Dwarf")
    fight.call("use_feature", character="Brom", feature="defensive stance")
    out = fight.call("rest", character="Brom", days=1)
    assert [e["feature"] for e in out["rage_ended"]] == ["defensive-stance"]
    assert "defending" not in (fight.storage.characters.get(out["rage_ended"][0]["character_id"]).state.d20 or {})


def test_smite_good(fight):
    # Blackguard 2 (fighter 6), Cha 14: "adds his Charisma modifier (if positive) to his attack roll and deals 1 extra
    # point of damage per class level": +2 to hit, +2 damage on a good target; "If a blackguard accidentally smites a
    # creature that is not good, the smite has no effect but it is still used up".
    fight.character("Mord", {"fighter": 6, "blackguard": 2}, weapon="longsword")
    fight.enemies("aasimar", "orc")
    out = fight.call("use_feature", character="Mord", feature="smite good")
    assert "error" not in out, out
    smitten = fight.swing("Mord", "Aasimar", 15, 4)
    assert "smite good: +2 to hit, +2 damage" in smitten.notes
    assert smitten.damage == 4 + 2 + 2 and "smite" not in smitten.attacker.d20
    fight.call("rest", character="Mord", days=1)
    fight.call("use_feature", character="Mord", feature="smite good")
    missed = fight.swing("Mord", "Orc", 15, 4)
    assert any("isn't good" in note for note in missed.notes) and missed.damage == 4 + 2


def test_a_feature_used_once_a_day(fight):
    # The arcane archer's seeker arrow, once a day: spent, then refused until a rest.
    fight.character("Ilsa", {"fighter": 6, "arcane-archer": 4}, race="Elf")
    out = fight.call("use_feature", character="Ilsa", feature="seeker arrow")
    assert "error" not in out and out["uses_left"] == 0, out
    assert "Seeker arrow: 1 a day at this level, used 1." in fight.call("use_feature", character="Ilsa",
                                                                         feature="seeker-arrow")["error"]  # fmt: skip


def test_breath_weapon_says_its_dice_and_dc(fight):
    # Dragon disciple 3: breath weapon 2d8, once a day, "The DC of the breath weapon is 10 + class level + Con
    # modifier": 10 + 3 + 2 = 15.
    fight.character("Vey", {"sorcerer": 5, "dragon-disciple": 3})
    out = fight.call("use_feature", character="Vey", feature="breath weapon")
    assert "error" not in out, out
    assert (out["dice"], out["dc"], out["uses_left"]) == ("2d8", 15, 0)


def test_features_rows_have_the_prestige_uses():
    rows = {r["id"]: r for r in features.rows("shadowdancer")}
    assert rows["shadow-illusion"]["kind"] == "uses" and rows["defensive-roll"]["kind"] == "uses"
    assert class_features.USES.keys() >= {"defensive-stance", "smite-good", "seeker-arrow", "breath-weapon"}
