"""OSRIC's treasure, merchants and encounters (DEL-306): its loot classes rolled line by line, its magic-item tables,
a merchant's catalogue priced from them, and its dungeon, outdoor and town encounters."""

import json
import re
from importlib import resources

import pytest
from delve_osric.encounters import ENCOUNTERS
from delve_osric.ruleset import OsricRuleset
from delve_osric.tables import TABLES
from delve_osric.treasure import TREASURE, _Roller, magic_item

from delve.dice import Dice, MemoryRollLog, ScriptedRng, SeededRng
from delve.rules.classic import checks

REF = OsricRuleset().reference


def seeded(n: int = 1) -> Dice:
    return Dice(SeededRng(n), MemoryRollLog(), "cmp_1", "beat-1")


def test_a_loot_line_as_the_bestiary_prints_it():
    groups = TREASURE.parse_types("Individual 1, 2, 3, 4 (each); in lair, Hoard 2")["groups"]
    assert groups == [
        {"label": "individual", "codes": ["individual 1", "individual 2", "individual 3", "individual 4"]},
        {"label": "lair", "codes": ["hoard 2"]},
    ]
    assert TREASURE.lair_codes(["hoard 2", "cache 3", "individual 1"]) == ["hoard 2"]
    assert TREASURE.parse_types("Nil") == {"groups": []}


def test_an_individuals_coins_are_always_there():
    """Individual 1 is 3d8 copper, no chance to roll."""
    result = TREASURE.generate(Dice(ScriptedRng([2, 3, 4]), MemoryRollLog(), "c", "b"), "Individual 1")
    assert (result.coins["cp"], result.checks) == (9, ())


def test_a_hoards_lines_are_each_a_chance():
    result = TREASURE.generate(seeded(3), "Hoard 1", source="the troll's cave")
    assert len(result.checks) == 8 and all(c.success == (c.roll <= c.chance) for c in result.checks)
    assert len(result.gems) == 0 or all(g.value_gp > 0 for g in result.gems)
    assert {roll.key.target for roll in result.rolls} == {"the troll's cave"}


@pytest.mark.parametrize(
    "kind", ["any", "potion", "ring", "rod_staff_wand", "armour_shield", "misc_weapon", "sword", "misc_magic", "scroll"]
)
def test_every_kind_of_magic_item_rolls_an_item(kind):
    for n in range(6):
        for item in magic_item(_Roller(seeded(n), "x", "s", []), kind):
            assert item.name and not re.search(r"[⁰-⁹]|\bsee\b|\bProceed\b", item.name), item


def test_a_merchant_stocks_osrics_priced_items():
    shelf = OsricRuleset().merchant_catalogue()
    assert len(shelf) > 200 and all(item.value_gp > 0 and item.price_source == "osric" for item in shelf)
    assert any(item.name == "Ring of Feather Falling" for item in shelf)


def test_a_dungeon_encounter_by_the_matrix_and_the_monster_levels():
    met = ENCOUNTERS.determine(seeded(5), terrain="dungeon", party_level=3, dungeon_level=2, occasion="")
    assert met.tier.startswith("dungeon level 2, monster level") and met.result and len(met.rolls) >= 2


@pytest.mark.parametrize("terrain", ["forest", "hills", "swamp", "ocean", "road", "desert", "mountain"])
def test_an_outdoor_encounter_by_the_terrains_kinds(terrain):
    met = ENCOUNTERS.determine(seeded(2), terrain=terrain, party_level=1, dungeon_level=0, occasion="")
    assert met is not None and met.result and ":" in met.tier


def test_a_town_encounter_by_day_or_night_and_its_choices():
    night = ENCOUNTERS.determine(Dice(ScriptedRng([36, 2]), MemoryRollLog(), "c", "b"), terrain="urban",
                                 party_level=1, dungeon_level=0, occasion="day 1 23:00")  # fmt: skip
    assert (night.result, night.number, night.tier) == ("Ghasts", "2d4", "town by night")
    assert ENCOUNTERS.determine(seeded(), terrain="nowhere", party_level=1, dungeon_level=0, occasion="") is None


def test_the_check_comes_from_the_engine_the_encounter_from_osric():
    result = checks.encounter_check(Dice(ScriptedRng([1, 1, 50]), MemoryRollLog(), "c", "b"), REF, terrain="dungeon",
                                    dungeon_level=1, rules=TABLES, encounters=ENCOUNTERS)  # fmt: skip
    assert result.triggered and result.tier.startswith("dungeon level 1") and len(result.all_rolls) == 3


def test_town_entries_keep_no_prose():
    tables = json.loads(resources.files("delve_osric").joinpath("data", "encounters.json").read_text("utf-8"))
    for when in ("daytime", "nighttime"):
        for entry in tables["urban"][when]:
            assert len(entry["result"]) < 40 and "." not in entry["result"], entry
