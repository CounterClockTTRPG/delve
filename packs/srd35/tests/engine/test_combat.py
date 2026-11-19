"""The 3.5 engine's combat (DEL-388): combatants from sheets and monster rows, initiative, and the swing with critical
hits, sneak attack and flat-footed targets. Each worked example is checked by hand in its comment."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest
from delve_srd35 import data
from delve_srd35.engine import Srd35Engine, combat
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.campaigns import Character
from delve.domain.characters import Effect, Sheet
from delve.rules.classic.combat import AttackBlock, Combatant
from delve.rules.classic.tables import FightRules
from delve.rules.d20 import Initiative, Swing

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


def row(id: str) -> dict:
    return next(r for r in data.load("monsters") if r["id"] == id)


def monster(id: str, **over) -> Combatant:
    core = Combatant(f"mon_{id}", id.title(), "enemy", hp=10, hp_max=10, attacks=(AttackBlock("", "1d6", "1d6"),))
    return ENGINE.combatant_from_monster(row(id), core, over)


def hero(cls: str, levels: dict[str, int], abilities: dict[str, int], race: str = "Human", **d20) -> Combatant:
    sheet = ENGINE.fill_derived(
        Sheet(label="Hero", cls=cls, race=race, levels=levels, ability_scores={**TEN, **abilities}, d20=d20), REF
    )
    character = Character("pc_1", "c", "Hero", sheet=sheet)
    return ENGINE.combatant_from_sheet(character, Combatant("pc_1", "Hero", "party", character_id="pc_1", hp=10))


def wielding(name: str, bonus: int, damage: str, threat: int = 20, mult: int = 2, hands: int = 1, **d20) -> Combatant:
    """An attacker with one form, as `attack_line` makes them."""
    form = {"name": name, "bonus": bonus, "damage": damage, "threat": threat, "mult": mult, "count": 1, "touch": False,
            "hands": hands, "ranged": False}  # fmt: skip
    numbers = {"bab": bonus, "attacks": [form], "stance": {"power_attack": 0, "defensive": False}, **d20}
    return Combatant("a", "Attacker", "enemy", attacks=(AttackBlock(name, damage, damage),), init=12, d20=numbers)


def target(ac: int = 15, **d20) -> Combatant:
    numbers = {"ac": ac, "touch": 11, "flat_footed": ac - 1, "dex": 1, "crit_immune": False, **d20}
    return Combatant("t", "Target", "party", hp=40, init=10, d20=numbers)


def swing(attacker: Combatant, defender: Combatant, *faces: int, condition: str = "", round: int = 2) -> Swing:
    rolled, rng = dice(*faces)
    out = ENGINE.swing(attacker, defender, condition, rolled, round, FightRules())
    rng.assert_done()
    return out


def test_touch_from_breakdown():
    assert combat.touch_from_breakdown("15 (+1 size, +1 Dex, +2 leather armor, +1 light shield)") == 12
    # Typographic and plain signs; deflection and dodge count, armour and natural armour don't.
    assert combat.touch_from_breakdown("15 (–1 size, +1 Dex, +5 natural)") == 10
    assert combat.touch_from_breakdown("4 (-1 size, -5 Dex)") == 4
    assert combat.touch_from_breakdown("18 (+2 Dex, +2 deflection, +1 dodge, +3 natural)") == 15


def test_confirmed_critical_triples_a_greataxe():
    # 20 threatens; the confirmation 12 + 5 = 17 meets AC 15; the damage is three rolls of 1d12+3: 7 + 10 + 13 = 30.
    out = swing(wielding("greataxe", 5, "1d12+3", mult=3, hands=2), target(15), 20, 12, 4, 7, 10)
    assert (out.hit, out.roll, out.damage, out.damage_die) == (True, 20, 30, "1d12+3")
    assert out.notes == ("critical threat", "confirmed ×3")
    assert [r.key.purpose for r in out.rolls] == ["attack#1", "confirm#1", "damage#1#1", "damage#1#2", "damage#1#3"]
    assert out.attacker.attacks_used == 1


def test_threat_unconfirmed_is_normal_damage():
    # 19 threatens on a falchion's 18–20; the confirmation 2 + 4 = 6 misses AC 15; 2d4+4 is 3 + 2 + 4 = 9.
    out = swing(wielding("falchion", 4, "2d4+4", threat=18, hands=2), target(15), 19, 2, 3, 2)
    assert (out.hit, out.damage, out.notes) == (True, 9, ("critical threat",))


def test_natural_twenty_confirmation_confirms_and_natural_one_does_not():
    # The confirmation faces alone decide: 20 confirms against AC 40, 1 never does against AC 5.
    assert "confirmed ×2" in swing(wielding("sword", 4, "1d8"), target(40), 20, 20, 5, 5).notes
    assert swing(wielding("sword", 30, "1d8"), target(5), 20, 1, 5).damage == 5


def test_skeleton_ignores_criticals_and_sneak():
    # Review Focus 4. The human warrior skeleton is undead: a rogue's natural 20 on it in round 1 (it hasn't acted, so
    # it's flat-footed) is a threat but no critical, and no sneak dice: 1d6 rolls 4, once; no confirmation is rolled.
    skeleton = monster("human-warrior-skeleton")
    assert (skeleton.d20["type"], skeleton.d20["crit_immune"], skeleton.d20["cr"]) == ("undead", True, "1/3")
    rogue = wielding("short sword", 3, "1d6", threat=19, sneak="1d6")
    out = swing(rogue, replace(skeleton, init=None), 20, 4, round=1)
    assert (out.hit, out.damage) == (True, 4)
    assert out.notes == ("flat-footed", "critical threat", "immune to critical hits", "immune to sneak attack")
    # The gelatinous cube, an ooze, is immune too.
    assert monster("gelatinous-cube").d20["crit_immune"] is True


def test_round_one_target_that_hasnt_acted_is_flat_footed():
    # The goblin: AC 15, flat-footed 14. A +2 attack rolling 12 makes 14: a hit on it flat-footed in round 1 (the
    # attacker's initiative 12 beats its 5), a miss in round 2, and a hit in any round while it is `flat-footed`.
    goblin = replace(monster("goblin"), init=5)
    attacker = wielding("club", 2, "1d6")
    first = swing(attacker, goblin, 12, 3, round=1)
    assert (first.hit, first.damage, first.notes) == (True, 3, ("flat-footed",))
    assert swing(attacker, goblin, 12, round=2).hit is False
    assert swing(attacker, replace(goblin, init=20), 12, round=1).hit is False  # it acted first
    assert swing(attacker, replace(goblin, conditions=("flat-footed",)), 12, 3, round=3).hit is True


def test_flat_footed_touch_takes_off_dex():
    # A touch attack on a flat-footed target is against its touch AC less its Dex bonus: 11 - 1 = 10.
    touch = replace(wielding("touch", 0, "0"), d20={**wielding("touch", 0, "0").d20, "attacks": [
        {"name": "touch", "bonus": 0, "damage": "0", "threat": 20, "mult": 2, "count": 1, "touch": True, "hands": 1,
         "ranged": False}]})  # fmt: skip
    assert swing(touch, target(), 10, round=2).hit is False  # 10 against touch 11
    out = swing(touch, replace(target(), init=None), 10, round=1)
    assert (out.hit, out.damage) == (True, 0)  # a spell's touch deals no damage of its own


def test_sneak_attack_when_flanked():
    # A human rogue 3 with Dex 16 and a short sword: BAB 2 + Str 0 = +2, 1d6 threatening 19–20, sneak 2d6. The orc's
    # AC is 13: 15 + 2 hits; flanked, 1d6 (4) + 2d6 (3 + 5) = 12.
    rogue = hero("Rogue", {"rogue": 3}, {"dex": 16}, weapon="short sword")
    assert rogue.d20["attacks"][0] == {"name": "short sword", "bonus": 2, "damage": "1d6", "threat": 19, "mult": 2,
                                       "count": 1, "touch": False, "hands": 1, "ranged": False}  # fmt: skip
    assert rogue.d20["sneak"] == "2d6"
    out = swing(rogue, monster("orc"), 15, 4, 3, 5, condition="flanked")
    assert (out.hit, out.damage, out.notes) == (True, 12, ("+2 to hit (flanking).", "sneak attack +2d6"))
    assert swing(rogue, replace(monster("orc"), conditions=("flanked",)), 15, 4, 3, 5).damage == 12
    assert swing(rogue, monster("orc"), 15, 4).damage == 4  # not flanked, not flat-footed


def test_power_attack_two_handed_doubles():
    # A human fighter 1 with Str 16 and a greataxe: BAB 1 + Str 3 = +4, 1d12 + 4 (Str ×1.5), ×3. Power Attack 1 makes it
    # +3 to hit: 10 + 3 = 13 meets the orc's AC 13; the damage is 6 + 4 + 2 × 1 = 12.
    fighter = hero("Fighter", {"fighter": 1}, {"str": 16}, weapon="greataxe", feats=[{"id": "power-attack"}])
    assert fighter.d20["attacks"][0] == {"name": "greataxe", "bonus": 4, "damage": "1d12+4", "threat": 20, "mult": 3,
                                         "count": 1, "touch": False, "hands": 2, "ranged": False}  # fmt: skip
    powered = replace(fighter, d20={**fighter.d20, "stance": {"power_attack": 1, "defensive": False}})
    assert swing(powered, monster("orc"), 10, 6).damage == 12
    assert swing(powered, monster("orc"), 9).hit is False  # 9 + 3 = 12
    # A confirmed critical multiplies Power Attack's bonus too: (6 + 4) + (1 + 4) + (2 + 4) + 2 × 1 × 3 = 27.
    assert swing(powered, monster("orc"), 20, 15, 6, 1, 2).damage == 27
    # One-handed, the bonus is added once: a warhammer at BAB 1 + Str 3 = +4, 1d8 + 3, 5 + 3 + 1 = 9.
    hammer = hero("Fighter", {"fighter": 1}, {"str": 16}, weapon="warhammer", feats=[{"id": "power-attack"}])
    hammer = replace(hammer, d20={**hammer.d20, "stance": {"power_attack": 1, "defensive": False}})
    assert swing(hammer, monster("orc"), 10, 5).damage == 9


def test_natural_one_misses_even_against_ac_5():
    out = swing(wielding("sword", 10, "1d8"), target(5), 1)
    assert (out.hit, out.damage, out.damage_die, out.roll) == (False, 0, None, 1)
    assert swing(wielding("sword", -5, "1d8"), target(40), 20, 2, 3).hit is True  # a natural 20 hits


def test_minimum_damage_and_defensive_fighting():
    # 1d4-3 rolling 1 is -2: a hit deals 1. Fighting defensively costs 4 to hit (14 + 3 - 4 = 13 misses 15); a target
    # fighting defensively has +2 AC (13 + 3 = 16 misses 17).
    assert swing(wielding("dagger", 3, "1d4-3"), target(15), 14, 1).damage == 1
    careful = wielding("dagger", 3, "1d4", stance={"power_attack": 0, "defensive": True})
    assert swing(careful, target(15), 14).hit is False
    assert swing(wielding("dagger", 3, "1d4"), target(15, stance={"defensive": True}), 13).hit is False


def test_negative_levels_take_one_off_attacks_and_saves():
    # A drained fighter: two negative levels. Fort 2 + Con 0 = 2 is 0; the warhammer's +4 swings at +2: 11 + 2 = 13
    # meets the orc's 13, 10 + 2 = 12 misses.
    sheet = ENGINE.fill_derived(Sheet(label="Hero", cls="Fighter", race="Human", levels={"fighter": 1},
                                      ability_scores={**TEN, "str": 16},
                                      d20={"weapon": "warhammer", "negative_levels": 2}), REF)  # fmt: skip
    drained = ENGINE.combatant_from_sheet(
        Character("pc_1", "c", "Hero", sheet=sheet), Combatant("pc_1", "Hero", "party")
    )
    assert (drained.d20["negative_levels"], drained.d20["saves"]) == (2, {"fort": 0, "ref": -2, "will": -2})
    assert ENGINE.save(drained, "fort", 10, 0, dice(10)[0], actor="pc_1").base == 0
    assert swing(drained, monster("orc"), 11, 5).hit is True
    assert swing(drained, monster("orc"), 10).hit is False
    assert "negative_levels" not in hero("Fighter", {"fighter": 1}, {"str": 16}).d20


def test_effects_add_to_hit_and_damage():
    # Bless's +1 to hit makes 12 + 2 + 1 = 15 a hit on AC 15; a +2 damage effect makes 1d6 (3) deal 5.
    blessed = replace(wielding("club", 2, "1d6"), effects=(Effect("bless", 3, to_hit=1, dmg=2),))
    assert swing(blessed, target(15), 12, 3).damage == 5


def test_sheet_forms_by_the_srd():
    # A human wizard 1 (Str 8, Dex 14) with a longsword, which wizards aren't proficient with: BAB 0 - 1 - 4 = -5,
    # 1d8 - 1. A wizard also gets touch (BAB + Str) and ranged touch (BAB + Dex) forms for its spells.
    wizard = hero("Wizard", {"wizard": 1}, {"str": 8, "dex": 14, "int": 16}, weapon="longsword")
    assert [(f["name"], f["bonus"], f["damage"], f["touch"]) for f in wizard.d20["attacks"]] == [
        ("longsword", -5, "1d8-1", False), ("touch", -1, "0", True), ("ranged touch", 2, "0", True)]  # fmt: skip
    assert [b.name for b in wizard.attacks] == ["longsword", "touch", "ranged touch"]
    # A dagger it is proficient with: -1, 1d4 - 1, 19–20.
    dagger = hero("Wizard", {"wizard": 1}, {"str": 8}, weapon="dagger").d20["attacks"][0]
    assert (dagger["bonus"], dagger["damage"], dagger["threat"]) == (-1, "1d4-1", 19)
    # An elf wizard is proficient with the longsword (the elves' Weapon Proficiency).
    assert hero("Wizard", {"wizard": 1}, {"str": 8}, race="Elf", weapon="longsword").d20["attacks"][0]["bonus"] == -1
    # A halfling rogue with Weapon Finesse and a rapier: BAB 0 + Dex 3 + size 1 = +4; the Small damage 1d4; Weapon
    # Focus (rapier) +1. A longbow is Dex too, and no Str on the damage: 1d6 for Small, ×3.
    halfling = hero("Rogue", {"rogue": 1}, {"str": 12, "dex": 16}, race="Halfling", weapon="rapier",
                    feats=[{"id": "weapon-finesse"}, {"id": "weapon-focus", "choice": "rapier"}])  # fmt: skip
    rapier = halfling.d20["attacks"][0]
    assert (rapier["bonus"], rapier["damage"], rapier["threat"], halfling.size) == (5, "1d4+1", 18, "S")
    bow = hero("Fighter", {"fighter": 1}, {"str": 14, "dex": 14}, weapon="longbow").d20["attacks"][0]
    assert (bow["bonus"], bow["damage"], bow["mult"], bow["ranged"]) == (3, "1d8", 3, True)
    # Improved Critical doubles the threat range: a longsword's 19–20 becomes 17–20.
    keen = hero("Fighter", {"fighter": 5}, {"str": 14}, weapon="longsword",
                feats=[{"id": "improved-critical", "choice": "longsword"}])  # fmt: skip
    assert keen.d20["attacks"][0]["threat"] == 17


def test_a_sheets_combatant_carries_its_numbers():
    fighter = hero("Fighter", {"fighter": 3}, {"str": 16, "dex": 12, "con": 14}, race="Dwarf", weapon="warhammer",
                   armor="scale mail", shield="shield, heavy steel")  # fmt: skip
    d = fighter.d20
    # BAB 3; AC 10 + 4 + 2 + 1 = 17, touch 11, flat-footed 16; Fort 3 + 2 + 2 racial vs. … (numbers' own tests).
    assert (d["bab"], d["ac"], d["touch"], d["flat_footed"], d["init_bonus"], d["dex"]) == (3, 17, 11, 16, 1, 1)
    assert (d["type"], d["crit_immune"], d["sneak"], fighter.ac) == ("humanoid", False, "", 17)
    assert d["stance"] == {"power_attack": 0, "defensive": False} and d["aoo"] == {"round": 0, "used": 0}
    assert "cr" not in d
    # Made again mid-fight (core's rearm), a wizard keeps its stance and the form it holds, by name.
    sheet = ENGINE.fill_derived(Sheet(label="Hero", cls="Wizard", race="Human", levels={"wizard": 1},
                                      ability_scores=TEN, d20={"weapon": "dagger"}), REF)  # fmt: skip
    character = Character("pc_2", "c", "Hero", sheet=sheet)
    wizard = ENGINE.combatant_from_sheet(character, Combatant("pc_2", "Hero", "party"))
    holding = replace(wizard, weapon=2, d20={**wizard.d20, "stance": {"power_attack": 0, "defensive": True}})
    again = ENGINE.combatant_from_sheet(character, holding)
    assert again.attacks[again.weapon].name == "ranged touch" and again.d20["stance"]["defensive"] is True


def test_mangled_goblin_row_reads_its_size_and_type():
    # The conversion's goblin row: size "Goblin", type "1st-Level", "Small" and "Humanoid" in its subtypes (the
    # extraction repairs it since DEL-394; this is the row as it came). Its size comes from the AC's "+1 size", its
    # type from the subtypes; AC 15, touch 12 by the breakdown, flat-footed 14.
    goblin_row = {**row("goblin"), "size": "Goblin", "type": "1st-Level",
                  "subtypes": ["Warrior", "Small", "Humanoid", "Goblinoid"]}  # fmt: skip
    core = Combatant("mon_goblin", "Goblin", "enemy", hp=10, hp_max=10, attacks=(AttackBlock("", "1d6", "1d6"),))
    goblin = ENGINE.combatant_from_monster(goblin_row, core, {})
    d = goblin.d20
    assert (goblin.size, d["type"], d["crit_immune"], d["cr"]) == ("S", "humanoid", False, "1/3")
    assert (d["ac"], d["touch"], d["flat_footed"], d["bab"], d["init_bonus"], d["dex"]) == (15, 12, 14, 1, 1, 1)
    assert d["saves"] == {"fort": 3, "ref": 1, "will": -1}
    assert [(f["name"], f["bonus"]) for f in d["attacks"]] == [("morningstar", 2), ("javelin", 3)]
    assert [(b.name, b.damage_sm) for b in goblin.attacks] == [("morningstar", "1d6"), ("javelin", "1d4")]
    # The kobold is mangled the same way; the owlbear's full attack gives its two claws and its bite.
    assert (monster("kobold").size, monster("kobold").d20["type"]) == ("S", "humanoid")
    owlbear = monster("owlbear")
    assert [(b.name, b.rate) for b in owlbear.attacks] == [("claw", 2.0), ("bite", 1.0)]
    assert (owlbear.size, owlbear.d20["type"]) == ("L", "magical beast")
    # The orc's typographic saves ("+3", "–2") and an AC override.
    assert monster("orc").d20["saves"] == {"fort": 3, "ref": 0, "will": -2}
    assert monster("orc", ac=18).d20["ac"] == 18


def test_swinging_the_held_form():
    # The goblin holds its javelin (core's `weapon`): the swing is +3, 1d4.
    goblin = replace(monster("goblin"), weapon=1)
    out = swing(goblin, target(15), 12, 2)
    assert (out.hit, out.damage, out.damage_die) == (True, 2, "1d4")


def test_effects_ac_keeps_its_classic_sign():
    # Ruling R10. Held ("ac 4") is 4 easier to hit: AC 15 is 11, so 9 + 2 hits; a ring of protection's ac -1 is 1
    # harder: AC 16, so 13 + 2 misses. Touch and flat-footed AC move alike.
    attacker = wielding("club", 2, "1d6")
    held = replace(target(15), effects=(Effect("held", 2, ac=4),))
    out = swing(attacker, held, 9, 3)
    assert (out.hit, out.notes) == (True, ("+4 AC modifier on Target (active effects).",))
    assert swing(attacker, target(15), 9).hit is False
    ringed = replace(target(15), effects=(Effect("ring of protection", 0, ac=-1),))
    assert swing(attacker, ringed, 13).hit is False
    assert swing(attacker, ringed, 14, 3).hit is True
    assert swing(attacker, replace(held, init=None), 8, 3, round=1).hit is True  # flat-footed 14 - 4 = 10


def test_the_war_domain_gives_its_weapon():
    # The shared shape's cleric: a warhammer, war and good domains. A cleric 3 with Str 14: BAB 2 + Str 2 + Weapon Focus
    # 1 = +5, proficient by the War domain; without it the martial warhammer is nonproficient: 2 + 2 - 4 = 0.
    war = hero("Cleric", {"cleric": 3}, {"str": 14, "wis": 14}, weapon="warhammer", domains=["war", "good"])
    assert war.d20["attacks"][0]["bonus"] == 5
    plain = hero("Cleric", {"cleric": 3}, {"str": 14, "wis": 14}, weapon="warhammer", domains=["good", "law"])
    assert plain.d20["attacks"][0]["bonus"] == 0


def test_flanking_and_charging_give_two_to_hit():
    # Ruling R11. 11 + 2 misses AC 15; flanked (the swing's condition or the target's) it is 15 and hits.
    attacker = wielding("club", 2, "1d6")
    assert swing(attacker, target(15), 11).hit is False
    assert swing(attacker, target(15), 11, 3, condition="flanking").hit is True
    assert swing(attacker, replace(target(15), conditions=("flanked",)), 11, 3).hit is True
    # Charging: +2, and the charger is marked; a swing at it then has its AC 15 - 2 = 13 (11 + 2 hits).
    charge = swing(attacker, target(15), 11, 3, condition="charging")
    assert charge.hit is True and "charging_ac_penalty" in charge.attacker.conditions
    assert charge.notes == ("+2 to hit (charging); -2 AC until its next turn.",)
    charger = target(15, stance=charge.attacker.d20["stance"])
    charger = replace(charger, conditions=charge.attacker.conditions)
    assert swing(attacker, charger, 11, 3).hit is True


def test_a_charges_penalty_lasts_only_its_round():
    # Ruling R12: the charge in round 2 is kept as stance["charged"] = 2; core's mark stays on the charger, but in
    # round 3 its AC is 15 again (11 + 2 = 13 misses) while in round 2 it is 13 (13 hits).
    charge = swing(wielding("club", 2, "1d6"), target(15), 11, 3, condition="charging", round=2)
    assert charge.attacker.d20["stance"] == {"power_attack": 0, "defensive": False, "charged": 2}
    charger = replace(target(15, stance=charge.attacker.d20["stance"]), conditions=charge.attacker.conditions)
    attacker = wielding("club", 2, "1d6")
    assert swing(attacker, charger, 11, 3, round=2).hit is True
    assert swing(attacker, charger, 11, round=3).hit is False


def test_an_attack_of_opportunity_rolls_under_its_own_purposes():
    attacker = wielding("club", 2, "1d6", aoo={"round": 2, "used": 0, "swinging": True})
    out = swing(attacker, target(15), 15, 3)
    assert [r.key.purpose for r in out.rolls] == ["attack#aoo", "damage#aoo"]


def test_set_against_a_charge_doubles_with_the_critical_on_top():
    # 1d6 twice: 3 + 4 = 7. With a confirmed ×3 critical as well it is rolled four times (×3 and ×2 is ×4): 1+2+3+4.
    attacker = wielding("spear", 2, "1d6", mult=3)
    out = swing(attacker, target(15), 15, 3, 4, condition="set_vs_charge")
    assert (out.damage, out.notes) == (7, ("set vs. charge: double damage",))
    crit = swing(attacker, target(15), 20, 15, 1, 2, 3, 4, condition="set_vs_charge")
    assert (crit.damage, crit.notes) == (10, ("critical threat", "confirmed ×3", "set vs. charge: double damage"))


def test_rear_and_fleeing_give_no_bonus_and_say_why():
    attacker = wielding("club", 2, "1d6")
    rear = swing(attacker, target(15), 12, condition="rear")
    assert (rear.hit, rear.notes) == (False, ("3.5: no rear bonus — flanking needs an ally opposite",))
    fleeing = swing(attacker, target(15), 12, condition="fleeing")
    assert (fleeing.hit, fleeing.notes) == (False, ("3.5: a fleeing foe provokes — use provoke",))


def test_an_unreadable_attack_is_left_out_with_a_warning():
    # The centaur's composite longbow keeps "(+4 Str bonus)" in its name and swings at +5; a piece with no bonus is
    # not swung (no auto-hit) and the combatant says so.
    centaur = monster("centaur")
    bow = next(f for f in centaur.d20["attacks"] if "longbow" in f["name"])
    assert bow["name"] == "composite longbow (+4 str bonus)"
    assert (bow["bonus"], bow["damage"], bow["mult"]) == (5, "2d6+4", 3)
    assert "warnings" not in centaur.d20
    core = Combatant("mon_x", "Gazer", "enemy")
    gazer = ENGINE.combatant_from_monster({"name": "Gazer", "full_attack": "Bite +3 melee (1d6) or gaze (DC 15)"},
                                          core, {})  # fmt: skip
    assert [f["name"] for f in gazer.d20["attacks"]] == ["bite"]
    assert gazer.d20["warnings"] == ["Unreadable attack 'gaze (DC 15)': left out; the DM rolls it."]


def test_a_swarm_hits_without_a_roll():
    # The spider swarm's "Swarm (1d6 plus poison)": no d20, 1d6 rolls 3, and the poison is the DM's.
    out = swing(monster("spider-swarm"), target(30), 3)
    assert (out.hit, out.roll, out.damage, out.notes) == (True, 0, 3, ("plus poison",))


def test_initiative_is_d20_plus_dex_and_improved_initiative():
    # Dex 14 (+2) and Improved Initiative (+4): 11 + 6 = 17.
    quick = hero("Fighter", {"fighter": 1}, {"dex": 14}, feats=[{"id": "improved-initiative"}])
    rolled, _ = dice(11)
    out = ENGINE.initiative(quick, rolled, 1)
    assert isinstance(out, Initiative)
    assert (out.roll, out.total, out.rolls[0].key.purpose) == (11, 17, "initiative")
    rolled, _ = dice(11)
    assert ENGINE.initiative(monster("goblin"), rolled, 1).total == 12


def test_a_combatant_the_engine_didnt_make_is_refused():
    with pytest.raises(ValueError, match="no 3.5 numbers"):
        ENGINE.initiative(Combatant("x", "X", "enemy"), dice(10)[0], 1)


def _touching(**over) -> Combatant:
    form = {"name": "touch", "bonus": 0, "damage": "0", "threat": 20, "mult": 2, "count": 1, "touch": True, "hands": 1,
            "ranged": False}  # fmt: skip
    base = wielding("touch", 0, "0")
    return replace(base, d20={**base.d20, "attacks": [form], **over})


def test_flat_footed_touch_takes_off_dodge_too():
    # AC 17 with Dex 2 and Dodge 1: touch 13, flat-footed 14. Flat-footed, the touch AC loses both: 13 - 2 - 1 = 10,
    # which a 10 + 0 hits; not flat-footed, touch 13 isn't.
    dodger = replace(target(17, touch=13, flat_footed=14, dex=2), init=None)
    assert swing(_touching(), dodger, 10, round=1).hit is True
    assert swing(_touching(), replace(dodger, init=1), 10, round=2).hit is False


def test_an_effects_damage_is_multiplied_by_a_critical_and_not_added_to_a_touch():
    # A club +2 (1d6) with +2 damage from an effect: 20 threatens, 13 + 2 confirms on AC 15, ×2: 3 + 4 + 2 × 2 = 11.
    blessed = replace(wielding("club", 2, "1d6"), effects=(Effect("bless", 3, dmg=2),))
    assert swing(blessed, target(15), 20, 13, 3, 4).damage == 11
    # A spell's touch deals none of its own, with an effect's damage or Power Attack: 10 + 0 hits touch 11 for 0.
    toucher = replace(_touching(stance={"power_attack": 1, "defensive": False}), effects=(Effect("x", 3, dmg=2),))
    out = swing(toucher, target(15, touch=9), 10)
    assert (out.hit, out.damage) == (True, 0)


def test_only_melee_flanks():
    # A ranged attack gets no flanking +2: 12 + 2 = 14 misses AC 15, with a note why.
    bow = wielding("shortbow", 2, "1d6")
    bow = replace(bow, d20={**bow.d20, "attacks": [{**bow.d20["attacks"][0], "ranged": True}], "sneak": "1d6"})
    out = swing(bow, target(15), 12, condition="flanked")
    assert out.hit is False and "3.5: only a melee attack flanks" in out.notes
    # Sneak attack at range on a flat-footed target stays: 12 + 2 = 14 hits flat-footed 14; 1d6 (3) + 1d6 (4) = 7.
    out = swing(bow, replace(target(15), init=None), 12, 3, 4, round=1)
    assert (out.hit, out.damage) == (True, 7)


def test_a_halfling_throws_and_slings_better():
    # The halflings' +1 with thrown weapons and slings: a halfling rogue 1 with Dex 16 and a sling, BAB 0 + Dex 3 +
    # size 1 + 1 = +5; with a shortbow, no thrown bonus, +4.
    sling = hero("Rogue", {"rogue": 1}, {"dex": 16}, race="Halfling", weapon="sling").d20["attacks"][0]
    assert sling["bonus"] == 5
    assert hero("Rogue", {"rogue": 1}, {"dex": 16}, race="Halfling", weapon="shortbow").d20["attacks"][0]["bonus"] == 4
    # A human's sling is BAB 0 + Dex 3.
    assert hero("Rogue", {"rogue": 1}, {"dex": 16}, weapon="sling").d20["attacks"][0]["bonus"] == 3


def test_power_attack_isnt_used_with_a_light_weapon():
    # A human fighter 1 with Str 16 and a short sword (light): +4, 1d6+3. Power Attack 1 is ignored, with a note:
    # 9 + 4 = 13 still hits the orc's AC 13, for 5 + 3 = 8.
    fighter = hero("Fighter", {"fighter": 1}, {"str": 16}, weapon="short sword", feats=[{"id": "power-attack"}])
    powered = replace(fighter, d20={**fighter.d20, "stance": {"power_attack": 1, "defensive": False}})
    out = swing(powered, monster("orc"), 9, 5)
    assert (out.hit, out.damage) == (True, 8)
    assert "Power Attack: not with a light weapon" in out.notes


@pytest.mark.parametrize(
    ("line", "parts"),
    [
        # The SRD's own lines (`data/monsters.json`) that are not one "NdS±M": a template on a base creature...
        ("4d8+19 plus 4d12+16", ((4, 8, 19, 1), (4, 12, 16, 1))),  # 4th-level Barbarian Ogre
        ("1d8+1 plus 2d8+6", ((1, 8, 1, 1), (2, 8, 6, 1))),  # Human Form Werewolf
        ("12d8+51 plus 7d8+49", ((12, 8, 51, 1), (7, 8, 49, 1))),  # Hill Giant Dire Wereboar
        ("6d8+6d8+72", ((6, 8, 0, 1), (6, 8, 72, 1))),  # 6th-level Ranger Troll Hunter
        ("8d10 + 7d8 + 75", ((8, 10, 0, 1), (7, 8, 75, 1))),  # 7th-level Cleric Celestial Charger
        # ... and a fraction of one Hit Die.
        ("1/2 d8", ((1, 8, 0, Fraction(1, 2)),)),  # Cat
        ("1/4 d8", ((1, 8, 0, Fraction(1, 4)),)),  # Bat
        ("1/2 d6+1", ((1, 6, 1, Fraction(1, 2)),)),  # Grig
        ("1/2 d8+2", ((1, 8, 2, Fraction(1, 2)),)),  # Tiny Monstrous Scorpion
        ("1/2 d10", ((1, 10, 0, Fraction(1, 2)),)),  # Tiny Animated Object
        # The plain lines read as R18 has them.
        ("1d8+1", ((1, 8, 1, 1),)),
        ("9d8–9", ((9, 8, -9, 1),)),
        ("4d10 + 20", ((4, 10, 20, 1),)),
    ],
)
def test_a_hit_dice_line_reads_as_its_parts(line, parts):  # DEL-402
    read = ENGINE.read_hit_dice(line)
    assert read is not None
    assert [(p.count, p.sides, p.mod, p.share) for p in read] == list(parts)


@pytest.mark.parametrize("line", ["", "Varies", "1d8+1 plus a template", "8, 12, or 16", "2 hp"])
def test_a_line_that_isnt_all_dice_is_left_to_core(line):  # DEL-402
    assert ENGINE.read_hit_dice(line) is None


def test_every_hit_dice_line_in_the_srd_reads():  # DEL-402
    # Only the template and family rows, which have no Hit Dice of their own ("Vampire", "Red Dragon"), are left.
    unread = [r["name"] for r in data.load("monsters") if r["hit_dice"] and ENGINE.read_hit_dice(r["hit_dice"]) is None]
    assert unread == []


def test_uncanny_dodge_keeps_dex_and_shuts_out_flat_footed_sneak():
    # DEL-396. A rogue 4 with Dex 16 and leather: AC 15, flat-footed 15. In round 1 before it acts, a +2 club rolling
    # 11 makes 13 and misses (a rogue 3's flat-footed 12 is hit); a rogue's sneak dice don't come for it being
    # flat-footed: 15 + 2 = 17 hits for 1d6 (4) alone.
    four = replace(hero("Rogue", {"rogue": 4}, {"dex": 16}, armor="leather"), init=None)
    assert (four.d20["ac"], four.d20["flat_footed"], four.d20["uncanny_dodge"]) == (15, 15, True)
    out = swing(wielding("club", 2, "1d6"), four, 11, round=1)
    assert (out.hit, out.notes) == (False, ("flat-footed", "uncanny dodge: keeps Dex to AC"))
    three = replace(hero("Rogue", {"rogue": 3}, {"dex": 16}, armor="leather"), init=None)
    assert swing(wielding("club", 2, "1d6"), three, 11, 3, round=1).hit is True
    sneaky = wielding("club", 2, "1d6", sneak="2d6")
    out = swing(sneaky, four, 15, 4, round=1)
    assert (out.hit, out.damage) == (True, 4)
    # Flanked, the sneak dice still come: 15 + 2 + 2 hits; 4 + 3 + 5 = 12.
    assert swing(sneaky, four, 15, 4, 3, 5, condition="flanked", round=1).damage == 12


def test_uncanny_dodge_is_lost_when_immobilized():
    # A held (or helpless, paralyzed ...) rogue 4 loses its Dex anyway: flat-footed AC 15 - 3 = 12, which 10 + 2 hits,
    # and the sneak dice come: 1d6 (3) + 2d6 (1 + 2) = 6.
    four = replace(hero("Rogue", {"rogue": 4}, {"dex": 16}, armor="leather"), init=None, conditions=("held",))
    out = swing(wielding("club", 2, "1d6", sneak="2d6"), four, 10, 3, 1, 2, round=1)
    assert (out.hit, out.damage) == (True, 6)
    # Its flat-footed touch AC loses Dex too: touch 13 - 3 = 10, which a 10 + 0 hits; not held, it keeps 13.
    assert swing(_touching(), four, 10, round=1).hit is True
    assert swing(_touching(), replace(four, conditions=()), 10, round=1).hit is False


def test_a_monster_with_uncanny_dodge_keeps_dex():
    # A row whose special qualities name uncanny dodge keeps its Dex flat-footed too: 12 + 2 = 14 misses AC 15.
    row = {"name": "Dodger", "armor_class": "15 (+3 Dex, +2 leather)", "touch": "13", "flat_footed": "12",
           "abilities": {"dex": "16"}, "full_attack": "Club +2 melee (1d6)",
           "special_qualities": " trap sense +1 uncanny dodge"}  # fmt: skip
    dodger = ENGINE.combatant_from_monster(row, Combatant("mon_d", "Dodger", "enemy"), {})
    assert dodger.d20["uncanny_dodge"] is True
    assert swing(wielding("club", 2, "1d6"), replace(dodger, init=None), 12, round=1).hit is False
    assert "uncanny_dodge" not in monster("orc").d20


def _shooting(**d20) -> Combatant:
    bow = wielding("shortbow", 2, "1d6", **d20)
    return replace(bow, d20={**bow.d20, "attacks": [{**bow.d20["attacks"][0], "ranged": True}]})


def test_shooting_into_melee_is_minus_four_and_precise_shot_removes_it():
    # DEL-397. A +2 shortbow at a foe engaged in melee: 13 + 2 - 4 = 11 misses AC 15, with a note; 13 + 2 hits it
    # otherwise, and with Precise Shot (told so).
    shot = swing(_shooting(), target(15), 13, condition="into_melee")
    assert (shot.hit, shot.notes) == (False, ("-4 to hit (shooting into melee).",))
    assert swing(_shooting(), target(15), 13, 3).hit is True
    precise = swing(_shooting(precise_shot=True), target(15), 13, 3, condition="into_melee")
    assert (precise.hit, precise.notes) == (True, ("Precise Shot: no -4 into melee.",))
    # A melee attack takes nothing for it: 13 + 2 hits, with a note why.
    melee = swing(wielding("club", 2, "1d6"), target(15), 13, 3, condition="into_melee")
    assert (melee.hit, melee.notes) == (True, ("3.5: into_melee is for a ranged attack",))


def test_precise_shot_comes_from_the_sheet_and_the_row():
    # A human fighter 1 with Point Blank Shot and Precise Shot, and a javelin (thrown, ranged): Dex 14, +3.
    feats = [{"id": "point-blank-shot"}, {"id": "precise-shot"}]
    thrower = hero("Fighter", {"fighter": 1}, {"dex": 14}, weapon="javelin", feats=feats)
    assert thrower.d20["precise_shot"] is True and thrower.d20["attacks"][0]["ranged"] is True
    assert swing(thrower, target(15), 12, 3, condition="into_melee").hit is True  # 12 + 3 = 15
    plain = hero("Fighter", {"fighter": 1}, {"dex": 14}, weapon="javelin")
    assert "precise_shot" not in plain.d20
    assert swing(plain, target(15), 12, condition="into_melee").hit is False  # 12 + 3 - 4 = 11
    row = {"name": "Archer", "armor_class": "12 (+2 Dex)", "abilities": {"dex": "14"},
           "full_attack": "Shortbow +3 ranged (1d6)", "feats": "Point Blank Shot, Precise Shot"}  # fmt: skip
    assert ENGINE.combatant_from_monster(row, Combatant("mon_a", "Archer", "enemy"), {}).d20["precise_shot"] is True
