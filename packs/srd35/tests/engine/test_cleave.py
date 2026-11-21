"""Cleave and Great Cleave in the round, and `resolve_attack`'s late attack (DEL-431): each worked by hand in its
comment, through core's round with the 3.5 engine."""

from __future__ import annotations

from dataclasses import replace

import pytest
from delve_srd35 import data
from delve_srd35.engine.combat import CHARGED
from test_class_features import Fight
from test_combat import ENGINE, REF, dice, hero, row, wielding

from delve.rules.classic.combat import AttackBlock, Combat, Combatant, CombatError, attack, run_round
from delve.rules.classic.tables import FightRules

FOE = {"ac": 10, "touch": 10, "flat_footed": 10, "dex": 0, "crit_immune": False}


def einkil(feat: str | None = "cleave", bab: int = 4, **form) -> Combatant:
    """Einkil, a dwarf of BAB `bab` with a waraxe (1d10), Cleave or Great Cleave (`feat`)."""
    made = wielding("waraxe", bab, "1d10", **FOE, **({"cleave": feat} if feat else {}))
    if form:
        made = replace(made, d20={**made.d20, "attacks": [{**made.d20["attacks"][0], **form}]},
                       attacks=(AttackBlock("waraxe", "1d10", "1d10", rate=form.get("count", 1)),))  # fmt: skip
    return replace(made, id="einkil", name="Einkil", side="party", hp=30, init=20)


def archer(n: int, hp: int = 5) -> Combatant:
    c = wielding("shortbow", 0, "1d6", **FOE)
    return replace(c, id=f"archer_{n}", name=f"Archer {n}", side="enemy", hp=hp, hp_max=hp, init=10 - n)


def fight(*them: Combatant) -> Combat:
    return Combat(phase="round", round=1, order=tuple(c.id for c in them), rules=FightRules(initiative_once=True),
                  combatants={c.id: c for c in them})  # fmt: skip


def play(f: Combat, actions: list[dict], *faces: int) -> tuple[Combat, list[dict]]:
    rolled, rng = dice(*faces)
    f, out = run_round(f, rolled, REF, actions, "combatant", None, d20=ENGINE)
    rng.assert_done()
    return f, [a for a in out.actions if a.get("attacker") == "Einkil"]


def test_cleave_swings_at_the_next_target_in_the_round():
    # Einkil (+4) rolls 15: 19 hits archer 1 (AC 10, flat-footed 10, hp 5) for 8, which drops it. Cleave: one more
    # swing at archer 2, his fallback, at the same +4: 15 hits for 8. His attacks this round stay at 1.
    f = fight(einkil(), archer(1), archer(2), archer(3, hp=50))
    f, swings = play(f, [{"attacker": "Einkil", "target": "Archer 1", "targets": ["Archer 2"]}], 15, 8, 15, 8)
    assert [(s["target"], s["hit"], s.get("extra")) for s in swings] == [("Archer 1", True, None),
                                                                         ("Archer 2", True, "cleave")]  # fmt: skip
    assert f.combatants["archer_2"].hp <= 0 and f.combatants["einkil"].d20["cleaved"] == 1
    # Round 2: he attacks archer 3 as usual (no "already made this round's attacks"): 15 hits for 3.
    f, swings = play(f, [{"attacker": "Einkil", "target": "Archer 3"}], 15, 3)
    assert [(s["target"], s.get("skipped"), s["damage"]) for s in swings] == [("Archer 3", None, 3)]
    assert f.combatants["archer_3"].hp == 47


@pytest.mark.parametrize(("feat", "extra"), [("cleave", ["cleave"]), ("great cleave", ["great cleave"] * 2)])
def test_cleave_is_once_a_round_and_great_cleave_is_not(feat, extra):
    # Three archers of 5 hp; every 15 hits and every 8 drops one. Cleave takes archer 2 and stops; Great Cleave goes
    # on to archer 3.
    f = fight(einkil(feat), archer(1), archer(2), archer(3))
    faces = (15, 8) * (1 + len(extra))
    f, swings = play(f, [{"attacker": "Einkil", "target": "Archer 1", "targets": ["Archer 2", "Archer 3"]}], *faces)
    assert [s.get("extra") for s in swings] == [None, *extra]
    assert (f.combatants["archer_3"].hp <= 0) is (feat == "great cleave")


def test_a_cleave_is_at_the_bonus_of_the_attack_that_dropped():
    # BAB 6: +6 and then +1 (iterative -5). Archer 1 has 11 hp: the first swing (15 + 6) hits for 3, the second
    # (15 + 1) for 8 drops it, and the cleave at archer 2 is at +1 too, the same attack of the round: 15 + 1 hits.
    f = fight(einkil(bab=6, count=2, iterative=True), archer(1, hp=11), archer(2), archer(3))
    actions = [{"attacker": "Einkil", "target": "Archer 1", "targets": ["Archer 2", "Archer 3"]}]
    _, swings = play(f, actions, 15, 3, 15, 8, 15, 8)
    assert [(s["target"], s.get("extra")) for s in swings] == [("Archer 1", None), ("Archer 1", None),
                                                               ("Archer 2", "cleave")]  # fmt: skip
    assert "iterative attack (-5)" in swings[2]["notes"]


def test_a_cleave_isnt_one_of_the_rounds_attacks():
    # The first swing (+6) drops archer 1; the cleave at archer 2 is at +6, with no iterative penalty; his second
    # attack (+1) still comes, at archer 3: 15 + 1 hits for 3.
    f = fight(einkil(bab=6, count=2, iterative=True), archer(1), archer(2), archer(3))
    actions = [{"attacker": "Einkil", "target": "Archer 1", "targets": ["Archer 2", "Archer 3"]}]
    _, swings = play(f, actions, 15, 8, 15, 8, 15, 3)
    assert [(s["target"], s.get("extra")) for s in swings] == [("Archer 1", None), ("Archer 2", "cleave"),
                                                               ("Archer 3", None)]  # fmt: skip
    assert "iterative attack (-5)" not in swings[1]["notes"] and "iterative attack (-5)" in swings[2]["notes"]
    assert swings[2]["follow_up"] is True and "extra_attack" not in swings[2]


def test_a_cleave_with_no_target_left_is_said_due_and_not_spent():
    # Archer 2 stands but isn't in his targets: the cleave is due and not spent (no `cleaved`). After the round a late
    # resolve_attack with condition cleave makes it (15 hits for 3) and spends it; a second is refused.
    f = fight(einkil(), archer(1), archer(2))
    f, (swing,) = play(f, [{"attacker": "Einkil", "target": "Archer 1"}], 15, 8)
    assert "cleave: an extra attack is due; name an adjacent foe in targets" in swing["notes"]
    assert "cleaved" not in f.combatants["einkil"].d20
    rolled, rng = dice(15, 3)
    f, out = attack(f, rolled, "einkil", "archer_2", condition="cleave", late=True, d20=ENGINE)
    rng.assert_done()
    assert out["hit"] and "cleave: the extra attack" in out["notes"] and f.combatants["einkil"].d20["cleaved"] == 1
    with pytest.raises(CombatError, match="once a round"):
        attack(f, dice(15)[0], "einkil", "archer_2", condition="cleave", late=True, d20=ENGINE)


def test_with_no_foe_left_nothing_is_due():
    f = fight(einkil(), archer(1))
    _, (swing,) = play(f, [{"attacker": "Einkil", "target": "Archer 1"}], 15, 8)
    assert not any("cleave" in note for note in swing["notes"])


def test_a_charging_cleave_has_no_charge_bonus():
    # Einkil charges archer 1: 6 + 4 + 2 = 12 hits AC 10, and 8 drops it. The cleave at archer 2 is no charge:
    # 6 + 4 = 10 still hits, with no "+2 (charging)" in its notes.
    f = fight(einkil(), archer(1), archer(2))
    actions = [{"attacker": "Einkil", "target": "Archer 1", "targets": ["Archer 2"], "condition": "charging"}]
    _, swings = play(f, actions, 6, 8, 6, 8)
    assert "+2 to hit (charging); -2 AC until its next turn." in swings[0]["notes"]
    assert swings[1]["extra"] == "cleave" and "cleave: the extra attack" in swings[1]["notes"]
    assert not any("charging" in note for note in swings[1]["notes"])
    # 5 + 4 = 9 with no +2 misses AC 10: the cleave's to-hit is its own.
    _, swings = play(fight(einkil(), archer(1), archer(2)), actions, 6, 8, 5)
    assert swings[1]["hit"] is False


def test_a_resolve_attack_drop_names_great_cleave():
    f = fight(einkil("great cleave"), archer(1), archer(2))
    rolled, _ = dice(15, 8)
    _, out = attack(f, rolled, "einkil", "archer_1", d20=ENGINE)
    assert "Archer 1 dropped: Einkil has an extra attack (great cleave) at a foe within reach: resolve_attack with " \
           "condition cleave." in out["notes"]  # fmt: skip


def test_a_ranged_or_non_dropping_hit_gives_no_cleave():
    # 3 doesn't drop archer 1 (hp 5); a bow's hit that drops one isn't a melee attack.
    f = fight(einkil(), archer(1), archer(2))
    _, swings = play(f, [{"attacker": "Einkil", "target": "Archer 1", "targets": ["Archer 2"]}], 15, 3)
    assert len(swings) == 1
    bow = einkil(ranged=True)
    _, swings = play(fight(bow, archer(1), archer(2)), [{"attacker": "Einkil", "target": "Archer 1",
                                                         "targets": ["Archer 2"]}], 15, 8)  # fmt: skip
    assert len(swings) == 1


def test_cleave_comes_from_the_sheet_and_the_row():
    assert hero("Fighter", {"fighter": 4}, {"str": 16}, feats=["power-attack", "cleave"]).d20["cleave"] == "cleave"
    assert hero("Fighter", {"fighter": 4}, {"str": 16},
                feats=["power-attack", "cleave", "great-cleave"]).d20["cleave"] == "great cleave"  # fmt: skip
    assert "cleave" not in hero("Fighter", {"fighter": 1}, {"str": 16}).d20
    cleavers = [r for r in data.load("monsters") if "cleave" in str(r.get("feats") or "").lower()]
    assert cleavers
    core = Combatant("mon_1", "M", "enemy", hp=10, hp_max=10, attacks=(AttackBlock("", "1d6", "1d6"),))
    assert ENGINE.combatant_from_monster(cleavers[0], core, {}).d20["cleave"] in ("cleave", "great cleave")
    assert "cleave" not in ENGINE.combatant_from_monster(row("goblin"), core, {}).d20


def test_a_late_attack_leaves_the_next_round_and_the_charge_alone():
    # Review Focus 4. Einkil (+4, one attack) and an orc of 50 hp; two rounds of Einkil attacking (15s hit for 3, the
    # orc's 2s miss). Then a late charge after round 2: it is round 2's, keyed and logged so, and spends nothing of
    # round 3 and leaves no charge mark. Round 3 he attacks as usual.
    orc = replace(archer(1, hp=50), id="orc", name="Orc")
    f = fight(einkil(None), orc)
    attacks = [{"attacker": "Einkil", "target": "Orc"}, {"attacker": "Orc", "target": "Einkil"}]
    rolled, _ = dice(15, 3)
    with pytest.raises(CombatError, match="round 1"):
        attack(f, rolled, "einkil", "orc", late=True, d20=ENGINE)
    for _ in range(2):
        f, _ = play(f, attacks, 15, 3, 2)
    assert f.round == 3
    rolled, rng = dice(15, 3)
    f, out = attack(f, rolled, "einkil", "orc", condition="charging", late=True, d20=ENGINE)
    rng.assert_done()
    assert out["hit"] and {r["combat_round"] for r in out["rolls"]} == {2}
    assert f.log[-1]["round"] == 2 and f.log[-1]["late"] is True
    einkil_now = f.combatants["einkil"]
    assert einkil_now.attacks_used == 0 and CHARGED not in einkil_now.conditions
    f, swings = play(f, attacks, 15, 3, 2)
    assert [s.get("skipped") for s in swings] == [None]
    # Without late, an attack between rounds is the coming round's: round 4's is then spent.
    rolled, _ = dice(15, 3)
    f, _ = attack(f, rolled, "einkil", "orc", d20=ENGINE)
    f, swings = play(f, attacks, 2)
    assert [s.get("skipped") for s in swings] == ["already made this round's attacks"]


def test_a_charger_left_out_of_a_round_loses_the_mark_at_its_slot():
    # Ledger P1. Einkil charges in round 1 (15 + 4 + 2 hits for 3). In round 2 he declares nothing: at his slot the
    # mark comes off, so the orc after him swings at his full AC.
    orc = replace(archer(1, hp=50), id="orc", name="Orc")
    f = fight(einkil(None), orc)
    f, _ = play(f, [{"attacker": "Einkil", "target": "Orc", "condition": "charging"}], 15, 3)
    assert CHARGED in f.combatants["einkil"].conditions
    f, _ = play(f, [])
    assert CHARGED not in f.combatants["einkil"].conditions


def test_resolve_attack_takes_late_in_3_5_only(srd35_call, srd35_storage, srd35_campaign):
    # The scoped tool has `late`, core's doesn't; through the host a late attack after round 1 is round 1's, and one
    # before it is refused.
    from delve.dm.tools.host import all_specs

    (core,) = [s for s in all_specs() if s.name == "resolve_attack"]
    (scoped,) = [s for s in ENGINE.tools() if s.name == "resolve_attack"]
    assert "late" not in core.params["properties"] and "late" in scoped.params["properties"]
    Fight(srd35_call, srd35_storage, srd35_campaign).character("Bors", "Fighter", 1)
    assert "error" not in srd35_call("setup_combat", enemies=[{"name": "orc", "count": 1, "hp": 99}], surprise=False)
    early = srd35_call("resolve_attack", attacker="Bors", target="Orc", late=True)
    assert "round 1 hasn't been resolved" in early["error"]
    assert "error" not in srd35_call("combat_round", actions=[])
    out = srd35_call("resolve_attack", attacker="Bors", target="Orc", late=True)
    assert "error" not in out, out
    assert {r["combat_round"] for r in out["rolls"]} == {1}


def _late(f: Combat, *faces: int) -> tuple[Combat, dict]:
    rolled, rng = dice(*faces)
    f, out = attack(f, rolled, "einkil", "orc", late=True, d20=ENGINE)
    rng.assert_done()
    return f, out


def test_late_attacks_follow_on_from_the_rounds():
    # BAB 6: +6/+1. Round 1 Einkil declares nothing; two late attacks after it are its first and second of round 1:
    # attack#1 at +6 (15 + 6 hits for 3), attack#2 at +1, the iterative -5 (15 + 1 hits for 4), each its own roll.
    orc = replace(archer(1, hp=99), id="orc", name="Orc")
    full = einkil(None, bab=6, count=2, iterative=True)
    f, _ = play(fight(full, orc), [])
    f, first = _late(f, 15, 3)
    f, second = _late(f, 15, 4)
    assert [r["purpose"] for r in first["rolls"]] == ["attack#1", "damage#1"]
    assert [r["purpose"] for r in second["rolls"]] == ["attack#2", "damage#2"]
    assert "iterative attack (-5)" in second["notes"] and "iterative attack (-5)" not in first["notes"]
    assert f.combatants["orc"].hp == 99 - 3 - 4 and f.combatants["einkil"].attacks_used == 0
    # After a round in which he made both his attacks, a late one is his third: attack#3 (at -10).
    f, _ = play(f, [{"attacker": "Einkil", "target": "Orc"}], 15, 3, 15, 3)
    assert f.log[-2]["attacks"] == {"einkil": 2}
    f, third = _late(f, 15, 3)
    assert third["rolls"][0]["purpose"] == "attack#3" and "iterative attack (-10)" in third["notes"]


def test_a_staggered_attackers_late_attack_leaves_the_next_round_its_attack():  # final review, DEL-421 x DEL-431
    # Einkil at hp 10 with 10 nonlethal is staggered: one attack a round. Round 1 he declares nothing (the orc's 2
    # misses); his late attack after it (15 hits for 3) is round 1's, and round 2 he still attacks (15 hits for 3).
    orc = replace(archer(1, hp=99), id="orc", name="Orc")
    staggered = einkil(None)
    staggered = replace(staggered, hp=10, d20={**staggered.d20, "nonlethal": 10})
    f, _ = play(fight(staggered, orc), [{"attacker": "Orc", "target": "Einkil"}], 2)
    f, out = _late(f, 15, 3)
    assert out["hit"] and out["attacks_remaining_this_round"] == 0
    assert f.combatants["einkil"].attacks_used == 0
    f, swings = play(f, [{"attacker": "Einkil", "target": "Orc"}], 15, 3)
    assert [(s.get("skipped"), s["damage"]) for s in swings] == [(None, 3)]


def test_a_cleave_by_hand_is_at_the_dropping_attacks_bonus():  # final review, DEL-431
    # BAB 6: +6/+1. Round 2 (round 1 passed with nothing declared): resolve_attack's first swing at archer 1 (15 + 6
    # hits for 8) drops it. The cleave by hand at archer 2 is at the same +6, no iterative penalty, under a roll of
    # its own (attack#1:cleave), and isn't one of his attacks: one is left, his second (+1, the -5) at archer 3.
    f = fight(einkil(bab=6, count=2, iterative=True), archer(1), archer(2), replace(archer(3, hp=99), id="a3"))
    f, _ = play(f, [])
    rolled, _ = dice(15, 8)
    f, _ = attack(f, rolled, "einkil", "archer_1", d20=ENGINE)
    rolled, rng = dice(15, 8)
    f, out = attack(f, rolled, "einkil", "archer_2", condition="cleave", d20=ENGINE)
    rng.assert_done()
    assert out["hit"] and not any("iterative" in n for n in out["notes"])
    assert [r["purpose"] for r in out["rolls"]] == ["attack#1:cleave", "damage#1:cleave"]
    assert f.combatants["einkil"].attacks_used == 1 and out["attacks_remaining_this_round"] == 1
    assert "Einkil has 1 more attack(s) this round (2/round)." in out["notes"]
    rolled, _ = dice(15, 3)
    f, out = attack(f, rolled, "einkil", "a3", d20=ENGINE)
    assert out["rolls"][0]["purpose"] == "attack#2" and "iterative attack (-5)" in out["notes"]


def test_a_late_cleave_is_at_the_bonus_of_the_rounds_dropping_attack():  # final review, DEL-431
    # Round 1: +6 (15 hits archer 1, hp 11, for 3) and +1 (15 + 1 hits for 8: it drops), no foe in his targets, so
    # the cleave is due. Made late, it is at that second attack's +1 (the -5), not a third's -10, under its own roll.
    f = fight(einkil(bab=6, count=2, iterative=True), archer(1, hp=11), archer(2))
    f, _ = play(f, [{"attacker": "Einkil", "target": "Archer 1"}], 15, 3, 15, 8)
    rolled, rng = dice(15, 8)
    f, out = attack(f, rolled, "einkil", "archer_2", condition="cleave", late=True, d20=ENGINE)
    rng.assert_done()
    assert "iterative attack (-5)" in out["notes"] and out["rolls"][0]["purpose"] == "attack#2:cleave"
    assert f.combatants["einkil"].attacks_used == 0


def test_a_late_drop_says_the_cleave_is_late_too():  # final review, DEL-431
    # Round 1 Einkil declares nothing; a late attack after it (15 hits archer 1 for 8) drops archer 1: the cleave due
    # is round 1's, so the note says to make it late.
    f, _ = play(fight(einkil(), archer(1), archer(2)), [])
    rolled, _ = dice(15, 8)
    _, out = attack(f, rolled, "einkil", "archer_1", late=True, d20=ENGINE)
    assert "Archer 1 dropped: Einkil has an extra attack (cleave) at a foe within reach: resolve_attack with " \
           "condition cleave and late: true." in out["notes"]  # fmt: skip


def _hurt_archer(hp: int, nonlethal: int) -> Combatant:
    a = archer(1, hp=hp)
    return replace(a, d20={**a.d20, "nonlethal": nonlethal})


def test_a_lethal_hit_under_the_nonlethal_knocks_out_and_earns_a_cleave():  # final review, DEL-421 x DEL-431
    # Archer 1 at hp 20 with 18 nonlethal. Einkil's 15 hits for 3: hp 17, below the 18, so it is knocked out, said so,
    # and the drop earns his Cleave at archer 2 (15 hits for 8).
    f = fight(einkil(), _hurt_archer(20, 18), archer(2))
    f, swings = play(f, [{"attacker": "Einkil", "target": "Archer 1", "targets": ["Archer 2"]}], 15, 3, 15, 8)
    assert swings[0]["unconscious"] is True and "Archer 1 is unconscious (nonlethal 18, hp 17)!" in swings[0]["notes"]
    assert [(s["target"], s.get("extra")) for s in swings] == [("Archer 1", None), ("Archer 2", "cleave")]


def test_a_lethal_hit_to_the_nonlethal_staggers_and_says_so():  # final review, DEL-421
    # hp 20, 17 nonlethal: a hit for 3 leaves hp 17, equal to it: staggered, said so, and no Cleave (it still stands).
    rolled, _ = dice(15, 3)
    _, out = attack(fight(einkil(), _hurt_archer(20, 17), archer(2)), rolled, "einkil", "archer_1", d20=ENGINE)
    assert out["staggered"] is True and "Archer 1 is staggered (nonlethal 17, hp 17): one attack or action a round." \
        in out["notes"]  # fmt: skip
    assert not any("dropped" in n for n in out["notes"])
