"""SRD 3.5's treasure by encounter level (DEL-389 part 3): the line carries the level ("EL 5, double standard"), or
the source monster's CR does; coins, goods and items from Table: Treasure; gems, art and mundane items from their
tables; magic items from the random magic item tables the RTFs give (`data/magic_tables.json`)."""

from __future__ import annotations

import itertools
import json
import os
import re
import sys
from pathlib import Path

import pytest
from delve_srd35 import treasure as srd35_treasure
from delve_srd35.data import load
from delve_srd35.ruleset import Srd35Ruleset
from delve_srd35.treasure import TREASURE, _Roller, magic_item, parse_spec, plain_name, treasure_tables

from delve.dice import Dice, MemoryRollLog, ScriptedRng, SeededRng
from delve.rules.classic.treasure import ArtObject, Check, Gem, MagicItem, TreasureTypeError

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from srd35_extract import magic


def scripted(*values: int) -> tuple[Dice, ScriptedRng]:
    rng = ScriptedRng(values)
    return Dice(rng, MemoryRollLog(), "cmp_1", "beat-1"), rng


def seeded(n: int = 1) -> Dice:
    return Dice(SeededRng(n), MemoryRollLog(), "cmp_1", "beat-1")


def roller(*values: int) -> tuple[_Roller, ScriptedRng]:
    dice, rng = scripted(*values)
    return _Roller(dice, "test", "hoard"), rng


# The table


def test_the_treasure_table_by_level():
    """Table: Treasure's 5th level: coins 39–95 1d8 x 100 gp, goods 61–95 1d4 gems, items 68–100 1d3 minor; the 6th's
    "100 | 1 medium", printed under Goods by the conversion, is an Items band."""
    levels = treasure_tables()["levels"]
    assert sorted(levels) == list(range(1, 21))
    fifth = levels[5]
    assert {"from": 39, "to": 95, "value": "1d8 x 100 gp"} in fifth["coins"]
    assert {"from": 61, "to": 95, "value": "1d4 gems"} in fifth["goods"]
    assert {"from": 68, "to": 100, "value": "1d3 minor"} in fifth["items"]
    assert levels[6]["items"][-1] == {"from": 100, "to": 100, "value": "1 medium"}
    assert levels[13]["items"][-1] == {"from": 96, "to": 100, "value": "1 major"}
    for level, row in levels.items():
        for column, bands in row.items():
            assert bands[0]["from"] == 1 and bands[-1]["to"] == 100, (level, column)
            assert all(a["to"] + 1 == b["from"] for a, b in itertools.pairwise(bands)), (level, column)
    assert treasure_tables()["above"][21] == 1 and treasure_tables()["above"][30] == 42


def test_the_mundane_items_nest():
    mundane = treasure_tables()["mundane"]
    assert [(r["from"], r["to"]) for r in mundane] == [(1, 17), (18, 50), (51, 83), (84, 100)]
    armor = mundane[1]["sub"]
    assert armor[6]["item"] == "Darkwood" and [r["item"] for r in armor[6]["sub"]] == ["Buckler (205 gp)",
                                                                                       "Shield (257 gp)"]  # fmt: skip
    assert armor[7]["item"] == "Masterwork shield" and len(armor[7]["sub"]) == 5
    assert mundane[3]["sub"][-1]["item"] == "Thieves' tools, masterwork (50 gp)"


# The line


def test_the_line_carries_the_level():
    double = parse_spec("EL 5, double standard")
    assert double.level == 5 and {c: s.times for c, s in double.shares.items()} == {"coins": 2, "goods": 2,
                                                                                    "items": 2}  # fmt: skip
    half = parse_spec("EL 3, half standard")
    assert (half.shares["coins"].divide, half.shares["goods"].chance, half.shares["items"].chance) == (2, 50, 50)
    assert all(s.times == 0 for s in parse_spec("EL 7, none").shares.values())
    assert parse_spec("standard").level is None
    monster = parse_spec("1/10th coins; 50% goods; standard items")
    assert (monster.shares["coins"].divide, monster.shares["goods"].chance, monster.shares["items"].times) == (10,
                                                                                                             50, 1)  # fmt: skip
    plus = parse_spec("EL 9, Standard coins; double goods; standard items, plus +1 vorpal greatsword and +1 flaming whip")
    assert plus.extras == ("+1 vorpal greatsword", "+1 flaming whip") and plus.shares["goods"].times == 2
    assert parse_spec("A") is None


def test_a_line_that_is_no_treasure_is_refused():
    with pytest.raises(TreasureTypeError, match="EL 5, standard"):
        TREASURE.generate(seeded(), "A")


def test_parse_types_is_one_group():
    assert TREASURE.parse_types("EL 5, double standard") == {
        "groups": [{"label": "EL 5", "codes": ["coins", "coins", "goods", "goods", "items", "items"]}]
    }
    assert TREASURE.parse_types("EL 7, none") == {"groups": []}
    assert TREASURE.lair_codes(["coins", "goods"]) == []


# The hoard, by seeded dice


def test_el_5_standard_by_seeded_dice():
    """5th level (SRD Table: Treasure): coins d% 50 is 39–95, 1d8 x 100 gp, a 3: 300 gp. Goods d% 70 is 61–95, 1d4
    gems, a 2: a gem at d% 30 (26–50, 2d4 x 10 gp: 3 + 4 = 70 gp; the first of its 14 examples, bloodstone) and one at
    d% 100 (2d4 x 1,000 gp: 4 + 4 = 8,000 gp; the third of three, jacinth). Items d% 80 is 68–100, 1d3 minor, a 1:
    Table: Random Magic Item Generation's minor 45 is a ring, Table: Rings' minor 10 Protection +1."""
    dice, rng = scripted(50, 3, 70, 2, 30, 3, 4, 1, 100, 4, 4, 3, 80, 1, 45, 10)
    result = TREASURE.generate(dice, "EL 5, standard", source="the ogre's cave")
    rng.assert_done()
    assert result.types == ("EL 5", "coins", "goods", "items")
    assert result.coins == {"pp": 0, "gp": 300, "ep": 0, "sp": 0, "cp": 0}
    assert result.gems == (Gem("bloodstone", 70, "50 gp gem"), Gem("jacinth", 8000, "5,000 gp gem"))
    assert result.art == ()
    assert result.magic == (MagicItem("minor ring", "Ring of protection +1"),)
    assert {roll.key.target for roll in result.rolls} == {"the ogre's cave"}
    assert result.rolls[0].key.purpose == "treasure:EL5.1"


def test_double_standard_rolls_twice():
    """1st level, each column twice: coins d% 60 (53–95, 2d8 x 10 gp: 1 + 2 = 30 gp) then 10 (none); goods 50 (none)
    then 96 (1 art: d% 5 is 01–10, 1d10 x 10 gp, a 7: 70 gp, the first example, a silver ewer); items 10 and 20
    (none)."""
    dice, rng = scripted(60, 1, 2, 10, 50, 96, 5, 7, 1, 10, 20)
    result = TREASURE.generate(dice, "EL 1, double standard")
    rng.assert_done()
    assert result.types == ("EL 1", "coins", "coins", "goods", "goods", "items", "items")
    assert (result.coins["gp"], result.art, result.gems, result.magic) == (30, (ArtObject("silver ewer", 70),), (), ())


def test_half_standard_halves_the_coins_and_gives_even_odds():
    """3rd level: coins d% 50 (42–95, 1d4 x 100 gp, a 3: 300, halved 150); goods at 50%: a 60, none; items at 50%: a
    50, so the items roll, d% 10 (01–49, none)."""
    dice, rng = scripted(50, 3, 60, 50, 10)
    result = TREASURE.generate(dice, "EL 3, half standard")
    rng.assert_done()
    assert result.coins["gp"] == 150
    assert result.checks == (Check("EL3", "goods", 50, 60, False), Check("EL3", "items", 50, 50, True))


def test_none_rolls_nothing():
    result = TREASURE.generate(seeded(), "EL 7, none")
    assert (result.types, result.rolls, sum(result.coins.values()), result.magic) == (("EL 7",), (), 0, ())


def test_standard_alone_uses_the_cr():
    """No level in the line: the source monster's CR is the level, and the result says so."""
    result = TREASURE.generate(seeded(3), "standard", source="Ogre")
    assert result.types[0] == "EL 3 (Ogre's CR 3)"
    assert {roll.key.purpose.split(".")[0] for roll in result.rolls} == {"treasure:EL3"}
    goblin = TREASURE.generate(seeded(3), "Standard", source="goblins")  # CR 1/3: the 1st level
    assert goblin.types[0] == "EL 1 (Goblin's CR 1/3)"
    with pytest.raises(TreasureTypeError, match="no encounter level"):
        TREASURE.generate(seeded(), "standard", source="the vault")


def test_above_20th_level_adds_major_items():
    result = TREASURE.generate(seeded(5), "EL 22, standard")
    assert "+2 major (above 20th level)" in result.types
    assert sum(item.category.startswith("major") for item in result.magic) >= 2


def test_the_entrys_named_items_come_with_the_hoard():
    result = TREASURE.generate(seeded(2), "EL 9, standard coins; double goods; standard items, plus +1 vorpal greatsword")
    assert MagicItem("named in the entry", "+1 vorpal greatsword") in result.magic


def test_the_same_source_in_the_same_beat_is_the_same_hoard():
    log = MemoryRollLog()
    first = TREASURE.generate(Dice(SeededRng(1), log, "c", "b"), "EL 8, standard", source="crypt")
    again = TREASURE.generate(Dice(SeededRng(99), log, "c", "b"), "EL 8, standard", source="crypt")
    assert (first.coins, first.gems, first.art, first.magic) == (again.coins, again.gems, again.art, again.magic)


@pytest.mark.parametrize("level", range(1, 26))
def test_every_level_rolls(level):
    for seed in range(15):
        result = TREASURE.generate(seeded(seed), f"EL {level}, triple standard", source=f"hoard {seed}")
        assert all(g.value_gp > 0 for g in result.gems) and all(a.value_gp > 0 for a in result.art)
        assert all(item.name for item in result.magic)


# Magic items


def _row(table: list[dict], face: int) -> dict:
    return next(r for r in table if r["from"] <= face <= r["to"])


def test_a_medium_item_names_an_items_json_entry():
    """Table: Rings' medium 10 is Protection +2: the ring of protection of `items.json`, at +2."""
    r, rng = roller(10)
    assert magic_item(r, "medium", "rings") == MagicItem("medium ring", "Ring of protection +2")
    rng.assert_done()
    row = _row(load("magic_tables")["rings"]["medium"], 10)
    entry = next(i for i in load("items") if i["id"] == row["item"])
    assert (row["ref"], row["bonus"], entry["name"], entry["item_type"]) == ("items", 2, "Protection", "ring")
    amulet = _row(load("magic_tables")["wondrous"]["medium"], 3)
    assert (amulet["name"], amulet["item"], amulet["bonus"]) == ("Amulet of natural armor +2",
                                                                 "amulet-of-natural-armor", 2)  # fmt: skip


def test_a_medium_weapon_names_a_weapons_json_base():
    """Table: Weapons' medium 20 is +2; Table: Weapon Type Determination's 50 a common melee weapon; Table: Common
    Melee Weapons' 30 the longsword."""
    r, rng = roller(20, 50, 30)
    assert magic_item(r, "medium", "weapons") == MagicItem("medium weapon", "+2 longsword")
    rng.assert_done()
    assert _row(load("magic_tables")["common_melee"], 30)["item"] in {w["id"] for w in load("weapons")}


def test_a_special_ability_and_roll_again():
    """Table: Weapons' minor 95 is a special ability and roll again: 10 is +1, the weapon a common melee one (50), a
    longsword (30), and Table: Melee Weapon Special Abilities' minor 20 flaming."""
    r, rng = roller(95, 10, 50, 30, 20)
    assert magic_item(r, "minor", "weapons") == MagicItem("minor weapon", "+1 longsword (flaming)")
    rng.assert_done()


def test_keen_is_rerolled_on_a_bludgeoning_weapon():
    """Keen (minor 57–67) only on a piercing or slashing weapon: on a heavy mace (46–50) it is rolled again."""
    r, _ = roller(95, 10, 50, 48, 60, 20)
    assert magic_item(r, "minor", "weapons").name == "+1 heavy mace (flaming)"


def test_armour_and_shields():
    """Table: Armor and Shields' minor 70 is +1 armor; Table: Random Armor Type's 20 a chain shirt. Minor 10 is +1
    shield, 40 on Table: Random Shield Type a heavy steel shield. Minor 89 a specific armor: 10 the mithral shirt."""
    r, _ = roller(70, 20)
    assert magic_item(r, "minor", "armor") == MagicItem("minor armor", "+1 chain shirt")
    r, _ = roller(10, 40)
    assert magic_item(r, "minor", "armor") == MagicItem("minor shield", "+1 heavy steel shield")
    r, _ = roller(89, 10)
    assert magic_item(r, "minor", "armor") == MagicItem("minor armor", "Mithral shirt")


def test_potions_wands_and_scrolls_name_spells():
    """Table: Potions and Oils' minor 5 is cure light wounds; Table: Wands' medium 1 magic missile (5th). A minor
    scroll: arcane (d% 10), one spell (1d3: 1), 1st level (d% 20), Table: Arcane Spell Scrolls' 1st-level 06 burning
    hands."""
    spells = {s["id"] for s in load("spells")}
    r, _ = roller(5)
    assert magic_item(r, "minor", "potions") == MagicItem("minor potion", "Potion of cure light wounds")
    assert _row(load("magic_tables")["potions"]["minor"], 5)["item"] in spells
    r, _ = roller(1)
    assert magic_item(r, "medium", "wands") == MagicItem("medium wand", "Wand of magic missile (5th)")
    r, rng = roller(10, 1, 20, 6)
    assert magic_item(r, "minor", "scrolls") == MagicItem("minor scroll", "Scroll (arcane): burning hands")
    rng.assert_done()
    assert _row(load("magic_tables")["scroll_spells"]["arcane"]["1"], 6)["item"] in spells


def test_a_mundane_item():
    """Table: Mundane Items' 5 is an alchemical item, 5 again alchemist's fire, 1d4 flasks: 3."""
    r, rng = roller(5, 5, 3)
    assert srd35_treasure._mundane(r) == MagicItem("mundane", "Alchemist's fire (3 flasks, 20 gp each)")
    rng.assert_done()
    r, _ = roller(30, 5, 85, 30)  # armor, Small (5), darkwood (85), a shield (30 is the buckler)
    assert srd35_treasure._mundane(r) == MagicItem("mundane", "Darkwood buckler (Small, 205 gp)")


def test_the_tables_names_said_plainly():
    assert plain_name("Sword, bastard") == "bastard sword"
    assert plain_name("Shield, heavy, steel") == "heavy steel shield"
    assert plain_name("Longbow, composite (+1 Str bonus)") == "composite longbow (+1 Str bonus)"


# The extracted tables


def _bands(rows: list[dict]) -> list[tuple[int, int]]:
    return [(r["from"], r["to"]) for r in rows]


def _tables(tables: dict) -> dict[str, list[dict]]:
    """Every d% list of `magic_tables.json`, by a dotted name."""
    found: dict[str, list[dict]] = {}

    def walk(name: str, value) -> None:
        if isinstance(value, list):
            found[name] = value
            for row in value:
                if "sub" in row:
                    walk(f"{name}/{row['name']}", row["sub"])
        elif isinstance(value, dict):
            for key, inner in value.items():
                walk(f"{name}.{key}" if name else key, inner)

    walk("", {k: v for k, v in tables.items() if k != "scroll_counts"})
    return found


def test_magic_tables_deterministic_and_complete():
    """Every table runs 01–100 without a gap, but where the SRD's own rows overlap (Table: Rings' medium 47–51 and
    50–56, Table: Scroll Spell Levels' major 86–95 and 95–100: the first printed wins); every row's `ref` names an
    entry of its file."""
    tables = load("magic_tables")
    lists = _tables(tables)
    overlaps = []
    for name, rows in lists.items():
        bands = _bands(rows)
        assert bands[0][0] == 1 and bands[-1][1] == 100, name
        overlaps += [(name, a, b) for a, b in itertools.pairwise(bands) if a[1] + 1 != b[0]]
    assert overlaps == [("rings.medium", (47, 51), (50, 56)), ("scroll_levels.major", (86, 95), (95, 100))]
    ids = {f: {row["id"] for row in load(f)} for f in ("items", "spells", "weapons")}
    for name, rows in lists.items():
        for row in rows:
            if "ref" in row:
                assert row["item"] in ids[row["ref"]], (name, row)
    assert set(tables["generation"]) == {"minor", "medium", "major"} and len(tables["generation"]["medium"]) == 9
    assert {g: len(rows) for g, rows in tables["wondrous"].items()} == {"minor": 100, "medium": 100, "major": 100}
    assert all(sorted(tables["scroll_spells"][kind]) == [str(n) for n in range(10)] for kind in ("arcane", "divine"))
    assert tables["scroll_counts"] == {"minor": "1d3", "medium": "1d4", "major": "1d6"}
    named = sum("ref" in row for rows in lists.values() for row in rows)
    assert named >= 1300


def test_the_table_reader_on_lines():
    names = magic.Names([{"id": "protection", "name": "Protection", "item_type": "ring"}], [], [])
    lines = ["Table: Rings", "Minor\tMedium\tMajor\tRing\tMarket Price", "01–18\t—\t—\tProtection +1\t2,000 gp",
             "19–100\t01–100\t01–100\tFeather falling\t2,200 gp", "1 A footnote."]  # fmt: skip
    found = magic.table(lines, "Rings", "items:ring", names)
    assert found["minor"][0] == {"from": 1, "to": 18, "name": "Protection +1", "item": "protection", "ref": "items",
                                 "bonus": 1, "price": "2,000 gp"}  # fmt: skip
    assert found["minor"][1]["item"] == "Feather falling" and "ref" not in found["minor"][1]
    assert _bands(found["medium"]) == [(1, 100)]


def test_the_extraction_from_the_rtfs_is_stable():
    """The RTFs aren't in the repository: set DELVE_SRD35_RTF to their folder to run this. Two runs give the
    committed bytes."""
    folder = os.environ.get("DELVE_SRD35_RTF", "")
    if not folder or not (Path(folder) / "MagicItemsI.rtf").is_file():
        pytest.skip("DELVE_SRD35_RTF isn't set to the SRD's RTFs")
    import extract_rtf

    data = Path(srd35_treasure.__file__).parent / "data"
    runs = [extract_rtf.magic(Path(folder), data, load("weapons"))[0] for _ in range(2)]
    text = json.dumps(runs[0], ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    assert runs[0] == runs[1] and text == (data / "magic_tables.json").read_text(encoding="utf-8")


def test_the_ruleset_has_the_treasure():
    assert Srd35Ruleset.treasure is TREASURE


def test_rolled_abilities_stay_within_plus_10_and_agree():
    # Table: Melee Weapon Special Abilities: "Reroll if you get a duplicate special ability, an ability incompatible
    # with an ability that you've already rolled, or if the extra ability puts you over the +10 limit." Over 300
    # major hoards no weapon, armour or shield is over +10, holy and unholy, axiomatic and anarchic, or flaming and
    # flaming burst.
    from delve_srd35.engine.tools import _parens

    effects = load("item_effects")
    for n in range(300):
        for item in TREASURE.generate(seeded(n), "EL 20, double standard").magic:
            head, groups = _parens(item.name.lower())
            plus = re.match(r"^\+(\d+) ", head)
            named = [w for g in groups if not re.match(r"^\+?\d+( str bonus)?$", g) for w in g.split("; ")]
            if not plus or not named or item.category.split()[-1] not in ("weapon", "armor", "shield"):
                continue
            on = "weapon" if item.category.endswith("weapon") else "armor"
            rows = []
            for words in named:
                key = re.sub(r"[^a-z]+", "-", re.sub(r" \(\d+\)|, (?:light|moderate|heavy)$", "", words)).strip("-")
                rows.append(effects.get(f"{key}-{on}") or effects[key])
            assert int(plus.group(1)) + sum(row["price"] for row in rows) <= 10, item.name
            aligned = {a for row in rows for a in row.get("aligned", ())}
            assert not {"good", "evil"} <= aligned and not {"lawful", "chaotic"} <= aligned, item.name
            energies = [row["energy"] for row in rows if row.get("energy")]
            assert len(energies) == len(set(energies)), item.name


def test_a_fraction_cr_is_the_first_level():
    # "CR 1/2, standard": a CR below 1 is the 1st level, as a monster's is (the SRD rounds a group's EL); the rolled
    # entry says how it was read.
    assert parse_spec("CR 1/2, standard").level == 1
    assert parse_spec("EL 3, 1/10 coins; standard goods").shares["coins"].divide == 10
    result = TREASURE.generate(seeded(3), "CR 1/2, standard", source="kobolds")
    assert result.types[0] == "EL 1 (CR 1/2)"
