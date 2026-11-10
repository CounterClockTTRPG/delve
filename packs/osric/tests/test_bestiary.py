"""OSRIC's bestiary (DEL-301): the Gamemaster Guide's monsters read out of its PDF by `scripts/osric_bestiary.py`,
their lookups, and a fight against them in the classic engine."""

import re

from delve_osric.data import load
from delve_osric.reference import OsricReference, attacks, hit_dice_number, monster_thac0

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.campaigns import Character
from delve.domain.characters import Sheet
from delve.rules.classic import combat as cb

MONSTERS = load("monsters")["monsters"]
REF = OsricReference()
ROWS = ("frequency", "no_encountered", "size", "armour_class", "hit_dice", "attacks", "morale", "loot", "experience")


def named(name: str) -> dict:
    """The monster the guide indexes as `name` (DEL-325 names it as players say it)."""
    return next(m for m in MONSTERS if m.get("index_name", m["name"]) == name)


def test_every_monster_of_the_guide_with_its_stat_block_and_text():
    assert len(MONSTERS) == 438
    assert len({m["slug"] for m in MONSTERS}) == len(MONSTERS)
    for m in MONSTERS:
        assert m["description"], m["name"]
        assert sum(1 for row in ROWS if not m[row]) == 0, m["name"]
    assert "Gamemaster Guide, Part Two: Monsters" in load("monsters")["_source"]


def test_a_stat_block_as_the_guide_prints_it():
    bugbear = named("Bugbear")
    assert (bugbear["armour_class"], bugbear["hit_dice"], bugbear["attacks"]) == (
        "5 [15]",
        "3+1",
        "1 (2d4 or by weapon)",
    )
    assert bugbear["loot"] == "Individual 1, 2, 3, 4 (each); in lair, Hoard 2"  # set on lines above and below its label
    assert bugbear["description"].startswith("Bugbears are related to goblins")
    assert bugbear["sections"]["Surprise and Initiative"] == "Surprise. Bugbears surprise opponents on a 1–3 on 1d6."


def test_a_table_of_variants_is_a_monster_each():
    assert (named("Badger, ordinary")["hit_dice"], named("Badger, giant")["hit_dice"]) == ("1+2", "3")
    assert named("Badger, giant")["family"] == "Badger"
    sauropods = [m["index_name"] for m in MONSTERS if m.get("index_name", "").startswith("Sauropods")]
    assert sauropods[1] == "Sauropods, argentinosaurus"
    assert named("Hadrosaurids, telmatosaurus")["armour_class"] == "9 [11]"  # a table as wide as the page


def test_no_running_headers_footers_or_index_in_the_text():
    for m in MONSTERS:
        text = m["description"] + " ".join(m["sections"].values())
        assert not re.search(r"PART TWO: MONSTERS|CHAPTER [A-Z]+:|\.{8,}", text), m["name"]
    assert named("Sahuagin, normal")["description"].startswith("Sahuagin are humanoid fish-people")


def test_monster_lookups():
    assert [m["name"] for m in REF.monster("Bugbear")] == ["Bugbear"]
    assert {m["name"] for m in REF.monster("badger")} == {"Badger", "Giant badger"}
    assert REF.monster("Bear, greater, polar")[0]["name"] == "Polar bear"  # the guide's own name (DEL-325)
    assert [m["name"] for m in REF.monster("bear")][:4] == ["Cave bear", "Black bear", "Brown bear", "Polar bear"]
    assert REF.monster("red dragon")[0]["name"] == "Red dragon"
    assert REF.monster("") == [] and REF.monster("no such beast") == []


def test_a_monster_row_carries_the_engines_columns():
    (bugbear,) = REF.monster("bugbear")
    assert (bugbear["armor_class"], bugbear["hit_dice"], bugbear["thac0"]) == ("5 [15]", "3+1", 16)
    assert (bugbear["no_of_attacks"], bugbear["damage_attack"]) == ("1", "2d4 or by weapon")
    assert bugbear["source"] == "OSRIC 3.0 Gamemaster Guide, p. 108"


def test_attack_lines():
    assert attacks("3 (1d8/1d8/3d10)") == ("3", "1d8/1d8/3d10")
    assert attacks("2 claws (1d3), 1 bite (1d6)") == ("3", "1d3/1d3/1d6")
    assert attacks("1 bite (1d6) and tail lash (2d8)") == ("2", "1d6/2d8")
    assert attacks("1d12 or by weapon") == ("1", "1d12 or by weapon")


def test_monster_thac0_by_hit_dice():
    assert [hit_dice_number(h) for h in ("1d4 hp", "1-1", "3+1", "9 to 11")] == [0.5, 0.9, 3.5, 9.0]
    assert [monster_thac0(h) for h in ("1d4 hp", "1-1", "1", "1+1", "3+1", "9 to 11", "16")] == [
        21,
        20,
        19,
        18,
        16,
        12,
        7,
    ]


def test_a_fight_against_osric_monsters():
    garrek = Character(id="chr_garrek", campaign_id="cmp_1", name="Garrek", kind="pc", sheet=Sheet(cls="Fighter"))
    fight, _ = cb.start([garrek])
    dice = Dice(ScriptedRng([3, 4, 5, 6, 2, 1]), MemoryRollLog(), "cmp_1", "beat-1")
    fight, _ = cb.add_monsters(fight, dice, REF, "bugbear", 2)
    bugbears = [c for c in fight.combatants.values() if c.side == "enemy"]
    assert [(c.name, c.ac, c.thac0, c.hp) for c in bugbears] == [("Bugbear 1", 5, 16, 13), ("Bugbear 2", 5, 16, 10)]
