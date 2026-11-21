"""Iterative attacks (DEL-389 part 2): a character's manufactured weapon gives one attack per round at BAB +1 to +5,
two at +6, three at +11, four at +16, each after the first 5 lower in the order taken; natural attacks, spell touch
forms and monsters' forms keep their counts; the monk's flurry at 9th (no penalty) and 11th (greater flurry: a
second extra attack), with her iterative attacks on top. Each number is worked by hand in its comment."""

from __future__ import annotations

import dataclasses

import pytest
from delve_srd35.engine import Srd35Engine
from delve_srd35.engine.combat import attack_bonuses, iterations
from delve_srd35.reference import Srd35Reference
from test_class_features import Fight, dice
from test_combat import row, target
from test_high_levels import live_party  # noqa: F401 (a fixture)

from delve.domain.campaigns import Character
from delve.rules.classic.combat import AttackBlock, Combatant
from delve.rules.classic.tables import FightRules

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)


@pytest.fixture
def fight(srd35_call, srd35_storage, srd35_campaign):
    return Fight(srd35_call, srd35_storage, srd35_campaign)


def _swings(attacker: Combatant, target: Combatant, *faces: tuple[int, ...]):
    """The attacker's attacks this round, one after the other (its `attacks_used` carried), each with its faces (the
    d20's, then the damage's on a hit)."""
    out = []
    target = dataclasses.replace(target, init=0)
    attacker = dataclasses.replace(attacker, init=30)
    for rolls in faces:
        rolled, rng = dice(*rolls)
        swing = ENGINE.swing(attacker, target, "", rolled, 2, FightRules())
        rng.assert_done()
        out.append(swing)
        attacker = swing.attacker
    return out


def _core(name: str) -> Combatant:
    return Combatant("mon_1", name, "enemy", hp=10, hp_max=10, attacks=(AttackBlock("", "1d6", "1d6"),))


def test_iterations_by_bab():
    assert [iterations(b) for b in (-1, 0, 1, 5, 6, 10, 11, 15, 16, 20, 25)] == [1, 1, 1, 1, 2, 2, 3, 3, 4, 4, 4]


def test_fighter_6_attacks_twice_at_plus_6_and_plus_1(fight):
    # Fighter 6, BAB +6, Str 16 (+3), longsword: +9 then +4, two attacks a round (the block's rate).
    fight.character("Bors", "Fighter", 6, scores={"str": 16}, weapon="longsword")
    fight.enemies("orc")
    bors = fight.combatant("Bors")
    form = bors.d20["attacks"][0]
    assert (form["bonus"], form["count"], form["iterative"]) == (9, 2, True)
    assert bors.attacks[bors.weapon].rate == 2
    assert attack_bonuses(form) == [9, 4]
    # The orc's AC 13: 4 + 9 = 13 hits the first; 9 + 4 = 13 hits the second, 8 + 4 misses it.
    first, second = _swings(bors, fight.combatant("Orc"), (4, 1), (9, 1))
    assert first.hit and second.hit
    assert "iterative attack (-5)" in second.notes and not any("iterative" in n for n in first.notes)
    _, missed = _swings(bors, fight.combatant("Orc"), (4, 1), (8,))
    assert not missed.hit


def test_fighter_16_attacks_four_times(fight):
    # Fighter 16, BAB +16/+11/+6/+1, Str 14 (+2), longsword: +18/+13/+8/+3.
    fight.character("Bors", "Fighter", 16, weapon="longsword")
    fight.character("Cora", "Fighter", 11, weapon="longsword")
    fight.enemies("orc")
    form = fight.combatant("Bors").d20["attacks"][0]
    assert (form["count"], attack_bonuses(form)) == (4, [18, 13, 8, 3])
    # Fighter 11: three, +13/+8/+3.
    assert attack_bonuses(fight.combatant("Cora").d20["attacks"][0]) == [13, 8, 3]


def test_a_natural_attack_doesnt_iterate(fight):
    # A dire bear (BAB +9): its full attack line's 2 claws and 1 bite, none iterative.
    fight.character("Elowen", "Wizard", 12, weapon="quarterstaff")
    fight.enemies("dire bear")
    bear = fight.combatant("Dire Bear")
    assert [(f["count"], bool(f.get("iterative"))) for f in bear.d20["attacks"]] == [(2, False), (1, False)]
    # A wizard 12 (BAB +6): the quarterstaff iterates, the spell touch forms don't.
    forms = {f["name"]: f for f in fight.combatant("Elowen").d20["attacks"]}
    assert forms["quarterstaff"]["count"] == 2 and forms["quarterstaff"]["iterative"]
    assert (forms["touch"]["count"], forms["ranged touch"]["count"]) == (1, 1)
    assert not forms["touch"].get("iterative") and not forms["ranged touch"].get("iterative")


def test_a_wild_shaped_druid_bites_once(srd35_call, fight):
    # Druid 8 (BAB +6) as a wolf: the bite at her BAB, one a round.
    fight.character("Ash", "Druid", 8, scores={"wis": 14})
    fight.enemies("orc")
    out = srd35_call("use_feature", character="Ash", feature="wild shape", target="wolf")
    assert "error" not in out, out
    forms = fight.combatant("Ash").d20["attacks"]
    assert [(f["name"], f["count"], bool(f.get("iterative"))) for f in forms] == [("bite", 1, False)]


def test_monk_11_greater_flurry(fight):
    # Monk 11, BAB +8/+3, Str 14 (+2): unarmed, +10/+5. Flurrying (no penalty from 9th, a second extra attack at
    # 11th): +10/+10/+10/+5.
    fight.character("Monk", "Monk", 11)
    fight.enemies("orc")
    form = fight.combatant("Monk").d20["attacks"][0]
    assert (form["count"], attack_bonuses(form)) == (2, [10, 5])
    c = fight.stance("Monk", flurry=True)
    assert [a["bonus"] for a in c["attacks_this_round"]] == [10, 10, 10, 5]
    monk = fight.combatant("Monk")
    assert monk.attacks[monk.weapon].rate == 4
    # The fourth swing is the one at -5: faces 3, 3, 3 (+10 = 13) hit the orc's AC 13, and 8 + 5 = 13 the fourth.
    swings = _swings(monk, fight.combatant("Orc"), (3, 1), (3, 1), (3, 1), (8, 1))
    assert all(s.hit for s in swings)
    assert [any("iterative" in n for n in s.notes) for s in swings] == [False, False, False, True]
    assert "flurry of blows (+0)" in swings[0].notes


def test_monk_9_flurries_without_penalty(fight):
    # Monk 9, BAB +6/+1, Str 14 (+2): flurry +8/+8/+3 (no penalty, one extra attack).
    fight.character("Monk", "Monk", 9)
    fight.enemies("orc")
    c = fight.stance("Monk", flurry=True)
    assert [a["bonus"] for a in c["attacks_this_round"]] == [8, 8, 3]


def test_an_attack_of_opportunity_is_at_the_full_bonus(fight):
    # Fighter 6's attack of opportunity after his first swing: +9, not +4 (it isn't one of his attacks this round).
    fight.character("Bors", "Fighter", 6, scores={"str": 16}, weapon="longsword")
    fight.enemies("orc")
    bors = fight.combatant("Bors")
    (first,) = _swings(bors, fight.combatant("Orc"), (10, 1))
    after = first.attacker
    swinging = dataclasses.replace(after, d20={**after.d20, "aoo": {"round": 2, "used": 0, "swinging": True}})
    (aoo,) = _swings(swinging, fight.combatant("Orc"), (4, 1))
    assert aoo.hit and not any("iterative" in n for n in aoo.notes)


def test_the_live_party_fighter_swings_twice(live_party, fight):  # noqa: F811
    # Bram, the live fighter 6: BAB +6, Str 17 (+3), Weapon Focus (longsword) +1: +10/+5 (Phase 2's engine gave him
    # one attack a round, the number that was wrong). The cleric 6 and rogue 6 (BAB +4) and the wizard 6 (+3) keep one.
    made = []
    for i, (sheet, _) in enumerate(live_party):
        character = Character(f"pc_{i}", "c", sheet.cls, sheet=sheet)
        made.append(ENGINE.combatant_from_sheet(character, Combatant(f"pc_{i}", sheet.cls, "party", hp=10)))
    bram = made[0]
    form = bram.d20["attacks"][0]
    assert (form["name"], form["count"], form["iterative"], attack_bonuses(form)) == ("longsword", 2, True, [10, 5])
    assert bram.attacks[bram.weapon].rate == 2
    assert [c.d20["attacks"][0]["count"] for c in made[1:]] == [1, 1, 1]


def _bors_swings(out) -> list[dict]:
    return [a for a in out["actions"] if a.get("attacker") == "Bors" and "skipped" not in a]


def _iterated(swing: dict) -> bool:
    return any("iterative" in n for n in swing["notes"])


@pytest.fixture
def bors(fight, srd35_call):
    # Fighter 6, BAB +6, Str 16 (+3), longsword: +9/+4, against an orc of 500 hp (none of the swings fells it).
    fight.character("Bors", "Fighter", 6, scores={"str": 16}, weapon="longsword")
    out = srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1, "hp": 500}], surprise=False)
    assert "error" not in out, out
    return srd35_call


def test_a_charging_fighter_6_attacks_once(bors):
    # A charge is one attack (at +9 +2), not +11/+6: the round's attacks are spent.
    out = bors("combat_round", actions=[{"attacker": "Bors", "target": "Orc", "condition": "charging"}])
    (swing,) = _bors_swings(out)
    assert not _iterated(swing) and "+2 to hit (charging); -2 AC until its next turn." in swing["notes"]
    assert swing["attacks_remaining_this_round"] == 0
    # The next round's full attack starts the -5 sequence again: +9, then +4.
    out = bors("combat_round", beat="beat-2", actions=[{"attacker": "Bors", "target": "Orc"}])
    assert [_iterated(s) for s in _bors_swings(out)] == [False, True]


def test_a_full_attack_swings_twice(bors):
    out = bors("combat_round", actions=[{"attacker": "Bors", "target": "Orc"}])
    assert [_iterated(s) for s in _bors_swings(out)] == [False, True]


def test_a_single_standard_attack_is_at_the_full_bonus(bors):
    # A move and an attack (`single`): one swing at +9, no iterative.
    out = bors("combat_round", actions=[{"attacker": "Bors", "target": "Orc", "single": True}])
    (swing,) = _bors_swings(out)
    assert not _iterated(swing) and swing["attacks_remaining_this_round"] == 0


def test_a_monsters_full_attack_is_every_form_of_its_line():
    # The SRD gargoyle: "2 claws +6 melee (1d4+2) and bite +4 melee (1d6+1) and gore +4 melee (1d6+1)", one full
    # attack of four: the claw block's rate is 4, and the swings take the line's forms in order.
    gargoyle = ENGINE.combatant_from_monster(row("gargoyle"), _core("Gargoyle"), {})
    assert [b.rate for b in gargoyle.attacks] == [4, 4, 4]
    # Against AC 15: claw 9 + 6 = 15 hits (1d4 [3] + 2 = 5); claw 8 + 6 = 14 misses; bite 11 + 4 = 15 hits (1d6 [4] +
    # 1 = 5); gore 10 + 4 = 14 misses.
    swings = _swings(gargoyle, target(15), (9, 3), (8,), (11, 4), (10,))
    assert [(s.hit, s.damage, s.damage_die) for s in swings] == [
        (True, 5, "1d4+2"), (False, 0, None), (True, 5, "1d6+1"), (False, 0, None)]  # fmt: skip
    assert "full attack: bite" in swings[2].notes and "full attack: gore" in swings[3].notes
    assert not any("full attack" in n for n in swings[0].notes)
    # The ogre's "Greatclub +8 melee (2d8+7) or javelin +1 ranged (1d8+5)" are two full attacks of one each.
    ogre = ENGINE.combatant_from_monster(row("ogre"), _core("Ogre"), {})
    assert [b.rate for b in ogre.attacks] == [1, 1]
    # The drider's "2 daggers +3 melee … and bite +1 melee …; or shortbow +5 ranged": three, or one.
    drider = ENGINE.combatant_from_monster(row("drider"), _core("Drider"), {})
    assert [b.rate for b in drider.attacks] == [3, 3, 1]


def test_a_monster_holding_its_second_form_starts_its_full_attack_with_it():
    # The gargoyle holding its bite: bite first, then the claws and the gore. One attack (a standard action) is the
    # bite: 11 + 4 = 15 hits AC 15, 1d6 [2] + 1 = 3.
    gargoyle = ENGINE.combatant_from_monster(row("gargoyle"), _core("Gargoyle"), {})
    biting = dataclasses.replace(gargoyle, weapon=1)
    (bite,) = _swings(biting, target(15), (11, 2))
    assert (bite.hit, bite.damage, bite.damage_die) == (True, 3, "1d6+1")
    assert not any("full attack" in n for n in bite.notes)


def test_a_monsters_iterative_form_beside_another_counts_its_own_attacks():
    # A hill giant's "Greatclub +16/+11 melee (2d8+10)" alone: two, the second at -5, as before.
    giant = ENGINE.combatant_from_monster(row("hill-giant"), _core("Hill Giant"), {})
    assert giant.attacks[0].rate == 2
    first, second = _swings(giant, target(15), (1,), (4, 1, 1))
    assert not first.hit and "iterative attack (-5)" in second.notes and second.hit


def test_attacks_per_round_lands_on_the_held_form():
    # The ogre's "Greatclub … or javelin …" held at the javelin: `attacks_per_round` 2 makes the javelin's count 2.
    held = dataclasses.replace(_core("Ogre"), attacks=(AttackBlock("javelin", "1d8+5", "1d8+5"),), weapon=0)
    ogre = ENGINE.combatant_from_monster(row("ogre"), held, {"attacks_per_round": 2})
    assert [(f["name"], f["count"]) for f in ogre.d20["attacks"]] == [("greatclub", 1), ("javelin", 2)]
    assert ogre.attacks[ogre.weapon].name == "javelin" and ogre.attacks[ogre.weapon].rate == 2
