"""Nonlethal damage under 3.5 (DEL-421, DEL-455): tracked in `d20["nonlethal"]` apart from hit points, staggered when
it equals the current hit points and unconscious above them; a regenerating creature's wounds are nonlethal but for
its stoppers, and its regeneration lowers them each round; `apply_damage` deals it (`nonlethal: true`), `apply_heal`
heals it by as much, `end_combat` keeps it on the character, and a rest of a day or more clears it."""

from __future__ import annotations

from delve_srd35 import data
from delve_srd35.engine import Srd35Engine
from delve_srd35.reference import Srd35Reference
from delve_srd35.tables import TABLES

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.rules.classic import combat as rules
from delve.rules.classic.combat import AttackBlock, Combatant

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
SCORES = {"str": 14, "dex": 12, "con": 12, "int": 10, "wis": 10, "cha": 10}


def _dice(*faces: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(faces)
    return Dice(rng, MemoryRollLog(), "c", "beat"), rng


def _troll(hp: int = 63) -> Combatant:
    row = next(r for r in data.load("monsters") if r["id"] == "troll")
    core = Combatant("mon_troll", "Troll", "enemy", hp=hp, hp_max=63, attacks=(AttackBlock("", "1d6", "1d6"),), init=0)
    return ENGINE.combatant_from_monster(row, core, {})


def _swordsman() -> Combatant:
    form = {"name": "longsword", "bonus": 10, "damage": "1d8+6", "threat": 20, "mult": 2, "count": 1, "touch": False,
            "hands": 1, "ranged": False}  # fmt: skip
    return Combatant("a", "Attacker", "party", attacks=(AttackBlock("longsword", "1d8+6", "1d8+6"),), init=30,
                     d20={"bab": 10, "attacks": [form], "stance": {}})  # fmt: skip


def _fight(storage, campaign) -> rules.Combat:
    return rules.from_json(storage.combats.live(campaign.id)[1])


def _combatant(storage, campaign, name: str) -> Combatant:
    return next(c for c in _fight(storage, campaign).combatants.values() if c.name == name)


def _state(storage, campaign, name: str):
    return next(c for c in storage.characters.list(campaign.id) if c.name == name).state


def _oryn(srd35_call, level: int = 1) -> None:
    sheet = {"cls": "Fighter", "level": level, "race": "Human", "hp_max": 10 * level, "ability_scores": SCORES}
    assert "error" not in srd35_call("create_character", name="Oryn", sheet=sheet)


def test_a_trolls_sword_wounds_are_nonlethal(srd35_call, srd35_storage, srd35_campaign):
    # Bram's +1 longsword (+10 against AC 16: 15 hits; 1d8+6: [6] + 6 = 12). Its hp stays 63; the 12 is nonlethal.
    swordsman = _swordsman()
    rolled, rng = _dice(15, 6)
    swing = ENGINE.swing(swordsman, _troll(), "", rolled, 2, TABLES.fight)
    rng.assert_done()
    assert (swing.hit, swing.damage, swing.nonlethal) == (True, 0, 12)
    assert "regeneration 5: nonlethal damage (fire or acid deals lethal)" in swing.notes
    # Landed by core: the troll keeps its 63 hp and has 12 nonlethal.
    troll = _troll()
    combat = rules.Combat(phase="round", round=2, order=("a", troll.id), rules=TABLES.fight,
                          combatants={"a": swordsman, troll.id: troll})  # fmt: skip
    rolled, rng = _dice(15, 6)
    combat, hit = rules.attack(combat, rolled, "a", troll.id, d20=ENGINE)
    landed = combat.combatants[troll.id]
    assert (hit["damage"], hit["nonlethal"], landed.hp, landed.d20["nonlethal"]) == (0, 12, 63, 12)
    # Through the tools: 12 nonlethal on a troll at 63, and the round's regeneration 5 leaves 7.
    srd35_call("setup_combat", enemies=[{"name": "troll", "count": 1, "hp": 63}], surprise=False)
    dealt = srd35_call("apply_damage", character="Troll", amount=12, nonlethal=True)
    assert (dealt["nonlethal"], dealt["hp"]) == (12, 63), dealt
    said = srd35_call("combat_round", actions=[])
    assert "error" not in said, said
    troll = _combatant(srd35_storage, srd35_campaign, "Troll")
    assert (troll.hp, troll.d20["nonlethal"]) == (63, 7)
    assert "Troll: regeneration 5 (fire or acid deals lethal damage): nonlethal 12 → 7." in said["defences"]


def test_a_troll_knocked_out_by_nonlethal_is_defeated(srd35_call, srd35_storage, srd35_campaign):  # Review Focus 3
    _oryn(srd35_call)
    srd35_call("setup_combat", enemies=[{"name": "troll", "count": 1, "hp": 15}], surprise=False)
    # 16 nonlethal at 15 hp: unconscious. Its attack is skipped; the round's regeneration takes it to 11, below its 15
    # hp, so it wakes, and acts in the next round.
    out = srd35_call("apply_damage", character="Troll", amount=16, nonlethal=True)
    assert (out["nonlethal"], out["state"]) == (16, "unconscious"), out
    said = srd35_call("combat_round", actions=[{"attacker": "Troll", "target": "Oryn"}])
    (skipped,) = [a for a in said["actions"] if a.get("attacker") == "Troll"]
    assert skipped["skipped"] == "unconscious — cannot act"
    assert _combatant(srd35_storage, srd35_campaign, "Troll").d20["nonlethal"] == 11
    said = srd35_call("combat_round", beat="beat-2", actions=[{"attacker": "Troll", "target": "Oryn"}])
    assert not any("skipped" in a for a in said["actions"] if a.get("attacker") == "Troll"), said["actions"]
    # Knocked out again (6 → 16 more than 15), the fight ends: the troll is down, defeated, worth its CR 5's XP.
    srd35_call("apply_damage", character="Troll", amount=10, nonlethal=True)
    ended = srd35_call("end_combat")
    (troll,) = ended["enemies"]
    assert troll["fate"] == "down" and ended["defeated"] == {"troll": 1}
    assert ended["groups"][0]["xp_earned"] > 0
    # Fire still kills it at 0 hp: 19 fire at hp 15, lethal.
    srd35_call("setup_combat", enemies=[{"name": "troll", "count": 1, "hp": 15}], surprise=False)
    srd35_call("apply_damage", character="Troll", amount=16, nonlethal=True)
    burnt = srd35_call("apply_damage", character="Troll", amount=19)
    assert burnt["dead"] is True and burnt["hp_after"] == -4
    assert srd35_call("end_combat")["enemies"][0]["fate"] == "slain"


def test_apply_damage_nonlethal_staggers_then_drops(srd35_call, srd35_storage, srd35_campaign):  # DEL-455
    _oryn(srd35_call, level=6)
    srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1, "hp": 200}], surprise=False)
    srd35_call("update_character", ref="Oryn", patch={"hp": 10})
    # 10 nonlethal at 10 hp: staggered, one attack though a fighter 6 has two (+6/+1).
    out = srd35_call("apply_damage", character="Oryn", amount=10, nonlethal=True)
    assert (out["nonlethal"], out["state"], out["hp"]) == (10, "staggered", 10), out
    said = srd35_call("combat_round", actions=[{"attacker": "Oryn", "target": "Orc"}])
    swings = [a for a in said["actions"] if a.get("attacker") == "Oryn"]
    assert len(swings) == 1 and "skipped" not in swings[0], swings
    status = {e["name"]: e for e in said["status"]["combatants"]}
    assert (status["Oryn"]["status"], status["Oryn"]["nonlethal"]) == ("staggered", 10)
    # One more: unconscious, skipped.
    out = srd35_call("apply_damage", character="Oryn", amount=1, nonlethal=True)
    assert (out["nonlethal"], out["state"]) == (11, "unconscious"), out
    said = srd35_call("combat_round", beat="beat-2", actions=[{"attacker": "Oryn", "target": "Orc"}])
    assert [a["skipped"] for a in said["actions"] if a.get("attacker") == "Oryn"] == ["unconscious — cannot act"]
    # Healing 5 heals 5 of each ("the nonlethal damage is healed by the same amount"): hp 15, nonlethal 6. She acts.
    healed = srd35_call("apply_heal", character="Oryn", amount=5)
    assert (healed["hp_after"], healed["nonlethal"]) == (15, 6), healed
    said = srd35_call("combat_round", beat="beat-3", actions=[{"attacker": "Oryn", "target": "Orc"}])
    oryn = [a for a in said["actions"] if a.get("attacker") == "Oryn"]
    assert len(oryn) == 2 and not any("skipped" in a for a in oryn), oryn


def test_nonlethal_survives_the_fight_and_a_rest_clears_it(srd35_call, srd35_storage, srd35_campaign):
    _oryn(srd35_call)
    srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1}], surprise=False)
    srd35_call("apply_damage", character="Oryn", amount=3, nonlethal=True)
    assert "error" not in srd35_call("end_combat")
    assert _state(srd35_storage, srd35_campaign, "Oryn").d20["nonlethal"] == 3
    # Into the next fight with it, and out again.
    srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1}], surprise=False)
    assert _combatant(srd35_storage, srd35_campaign, "Oryn").d20["nonlethal"] == 3
    srd35_call("end_combat")
    # Out of a fight: 2 more, and healing 1 heals 1 of it.
    out = srd35_call("apply_damage", character="Oryn", amount=2, nonlethal=True)
    assert out["nonlethal"] == 5, out
    assert srd35_call("apply_heal", character="Oryn", amount=1)["nonlethal"] == 4
    # A rest of no days keeps it; of a day clears it.
    srd35_call("rest", days=0)
    assert _state(srd35_storage, srd35_campaign, "Oryn").d20["nonlethal"] == 4
    rested = srd35_call("rest", days=1)
    assert "nonlethal" not in (_state(srd35_storage, srd35_campaign, "Oryn").d20 or {})
    assert rested["healing"]["Oryn"]["d20"]["nonlethal_cleared"] == 4


def test_apply_damage_nonlethal_refuses_the_dead_and_the_removed_and_logs(srd35_call, srd35_storage, srd35_campaign):
    # final review: logged as the lethal path is, in the fight's log and a character's in the campaign's; a dead
    # troll (19 fire at 15 hp) or a removed one takes none.
    _oryn(srd35_call)
    srd35_call("setup_combat", enemies=[{"name": "troll", "count": 2, "hp": 15}], surprise=False)
    out = srd35_call("apply_damage", character="Troll 1", amount=4, nonlethal=True)
    assert out["nonlethal"] == 4, out
    assert _fight(srd35_storage, srd35_campaign).log[-1] == {"type": "damage", "id": out["id"], "amount": 4,
                                                              "nonlethal": True}  # fmt: skip
    srd35_call("apply_damage", character="Oryn", amount=2, nonlethal=True)
    (logged,) = [e for e in srd35_storage.events.list(srd35_campaign.id) if e.type == "damage"]
    assert {k: logged.data[k] for k in ("name", "amount", "nonlethal", "nonlethal_before", "nonlethal_after")} == {
        "name": "Oryn", "amount": 2, "nonlethal": True, "nonlethal_before": 0, "nonlethal_after": 2}  # fmt: skip
    assert logged.data["in_combat"] is True
    srd35_call("apply_damage", character="Troll 1", amount=19)
    refused = srd35_call("apply_damage", character="Troll 1", amount=4, nonlethal=True)
    assert "dead" in refused["error"], refused
    srd35_call("remove_combatant", id="Troll 2", reason="fled")
    refused = srd35_call("apply_damage", character="Troll 2", amount=4, nonlethal=True)
    assert "removed" in refused["error"], refused


def test_setup_combat_with_an_override_shows_a_staggered_pc(srd35_call, srd35_storage, srd35_campaign):
    # final review: Oryn (hp 10) comes to the fight with 10 nonlethal, staggered; an override on the orcs makes the
    # answer's status anew, and it says so.
    _oryn(srd35_call)
    srd35_call("apply_damage", character="Oryn", amount=10, nonlethal=True)
    out = srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1, "init": 3}], surprise=False)
    assert "error" not in out, out
    (oryn,) = [c for c in out["combat"]["combatants"] if c["name"] == "Oryn"]
    assert oryn["status"] == "staggered", oryn
