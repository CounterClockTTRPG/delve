"""A monster's attack line as attack forms (DEL-388), with the typographic and the plain number formats."""

from __future__ import annotations

from delve_srd35 import data
from delve_srd35.engine import attack_line, combat

from delve.rules.classic.combat import Combatant


def test_parse_or_and_count():
    assert [(a["name"], a["bonus"], a["damage"], a["threat"], a["count"]) for a in attack_line.parse(
        "Morningstar +2 melee (1d6) or javelin +3 ranged (1d4)")] == [("morningstar", 2, "1d6", 20, 1), ("javelin", 3, "1d4", 20, 1)]  # fmt: skip
    assert attack_line.parse("2 claws +3 melee (1d4)")[0]["count"] == 2
    assert attack_line.parse("Falchion +4 melee (2d4+4/18–20)")[0]["threat"] == 18
    assert attack_line.parse("Greataxe +5 melee (1d12+3/×3)")[0]["mult"] == 3


def test_several_attacks_give_one_form_each_named_in_the_singular():
    # Review Focus 2: "2 claws" is one form "claw" with count 2; "and" forms of a full attack are forms too.
    forms = attack_line.parse("2 claws +9 melee (1d6+5) and bite +4 melee (1d8+2)")
    assert [(f["name"], f["bonus"], f["damage"], f["count"]) for f in forms] == [("claw", 9, "1d6+5", 2),
                                                                                 ("bite", 4, "1d8+2", 1)]  # fmt: skip
    assert [f["name"] for f in attack_line.parse("Bite +19 (2d6), 2 Claws +17/+17 (2d6/2d6), 2 Wings +17/+17 (1d6/1d6)")] == [
        "bite", "claw", "wing"]  # fmt: skip
    assert attack_line.parse("2 hooves +14 melee (1d4+3)")[0]["name"] == "hoof"


def test_plain_and_typographic_formats_read_alike():
    typographic = attack_line.parse("Spear +1 melee (1d6–1/×3) or sling –2 ranged (1d3)")
    plain = attack_line.parse("Spear +1 melee (1d6-1/x3) or sling -2 ranged (1d3)")
    assert typographic == plain
    assert [(f["damage"], f["mult"], f["bonus"], f["ranged"]) for f in plain] == [("1d6-1", 3, 1, False),
                                                                                  ("1d3", 2, -2, True)]  # fmt: skip
    assert attack_line.parse("Scimitar +1 melee (1d6+1/18-20)")[0]["threat"] == 18


def test_iteratives_extras_touch_and_two_hands():
    # The first of "+16/+11" is the bonus; "plus 1d6 cold" is the DM's; a ray is a ranged touch attack; a greataxe two-
    # handed (the SRD's table), a longsword not.
    axe = attack_line.parse("+2 Huge frost greataxe +30/+25/+20 melee (3d6+18/×3 plus 1d6 cold)")[0]
    assert (axe["name"], axe["bonus"], axe["damage"], axe["mult"], axe["hands"]) == ("+2 huge frost greataxe", 30,
                                                                                    "3d6+18", 3, 2)  # fmt: skip
    assert axe["plus"] == "1d6 cold"
    ray = attack_line.parse("Electricity ray +12 ranged touch (2d8)")[0]
    assert (ray["touch"], ray["ranged"], ray["damage"]) == (True, True, "2d8")
    drain = attack_line.parse("Incorporeal touch +3 melee (1d4 Wisdom drain)")[0]
    assert (drain["touch"], drain["damage"], drain["plus"]) == (True, "0", "1d4 Wisdom drain")
    assert attack_line.parse("Longsword +2 melee (1d8+1/19-20)")[0]["hands"] == 1
    # Mangled spacing from the RTFs, an asterisk, a swarm that hits without a roll, and a line with no form.
    assert attack_line.parse("Slam+2 melee, (1d6+1)")[0]["bonus"] == 2
    assert attack_line.parse("Bite +0 melee* (1d4+2*)")[0]["damage"] == "1d4+2"
    assert attack_line.parse("Swarm (1d6 plus poison)")[0]["bonus"] is None
    assert attack_line.parse("—") == []


def test_a_monsters_iterative_attacks_are_its_count():
    # The SRD hill giant's full attack, "Greatclub +16/+11 melee (2d8+10)": two greatclub attacks a round, the second
    # 5 lower (an iterative form, as a character's: `combat.attack_bonuses`). A frost giant jarl's four; a dragon's
    # "2 Claws +17/+17" are two at the same bonus, counted by the 2, not iterative.
    club = attack_line.parse("Greatclub +16/+11 melee (2d8+10) or 2 slams +15 melee (1d4+7)")
    assert [(f["name"], f["bonus"], f["count"], bool(f.get("iterative"))) for f in club] == [
        ("greatclub", 16, 2, True), ("slam", 15, 2, False)]  # fmt: skip
    assert combat.attack_bonuses(club[0]) == [16, 11]
    axe = attack_line.parse("+2 Huge frost greataxe +30/+25/+20/+15 melee (3d6+18/×3 plus 1d6 cold)")[0]
    assert (axe["count"], combat.attack_bonuses(axe)) == (4, [30, 25, 20, 15])
    claws = attack_line.parse("2 Claws +17/+17 (2d6/2d6)")[0]
    assert (claws["count"], combat.attack_bonuses(claws)) == (2, [17, 17])
    # The hill giant as a combatant swings twice: its greatclub block's rate.
    row = next(r for r in data.load("monsters") if r["id"] == "hill-giant")
    giant = combat.combatant_from_monster(row, Combatant("m", "Hill Giant", "enemy"), {})
    assert giant.attacks[0].rate == 2


def test_a_bonus_in_the_name_and_a_spaced_sign():
    # The centaur's line: the "(+4 Str bonus)" stays in the name, the bonus is +5; Cornugon's "bite + 22".
    centaur = next(r for r in data.load("monsters") if r["id"] == "centaur")
    bow = attack_line.parse(centaur["full_attack"])[-1]
    assert (bow["name"], bow["bonus"], bow["damage"], bow["ranged"]) == ("composite longbow (+4 str bonus)", 5,
                                                                         "2d6+4", True)  # fmt: skip
    assert "plus" not in bow
    assert attack_line.parse("bite + 22 melee (2d4+5)")[0]["bonus"] == 22


def test_only_a_swarm_hits_without_a_bonus():
    # Every monster row's lines: no form but a swarm's lacks a bonus; what can't be read is a warning instead.
    for row in data.load("monsters"):
        for line in (row.get("full_attack"), row.get("attack")):
            forms, _ = attack_line.read(line or "")
            assert [f["name"] for f in forms if f["bonus"] is None] in ([], ["swarm"]), (row["id"], line)
    forms, warnings = attack_line.read("Bite +3 melee (1d6) or tail (2d6)")
    assert [f["name"] for f in forms] == ["bite"]
    assert warnings == ["Unreadable attack 'tail (2d6)': left out; the DM rolls it."]
    assert attack_line.read("—") == ([], [])
