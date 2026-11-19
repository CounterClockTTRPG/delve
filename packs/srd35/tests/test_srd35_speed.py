"""A 3.5 character's speed is its race's, in feet (DEL-404): the sheet's `movement_rate` is filled from the race, a
load slows it by the SRD's reduced speeds (a dwarf's not), and travel reads it in feet."""

from __future__ import annotations

import pytest

FIGHTER = {"str": 10, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8}


def _made(srd35_call, name, race, **sheet):
    made = srd35_call("create_character", name=name, sheet={"cls": "Fighter", "level": 1, "race": race, "hp_max": 10,
                                                             "ability_scores": FIGHTER, **sheet})  # fmt: skip
    assert "error" not in made, made
    return made


@pytest.mark.parametrize(
    ("race", "speed"),
    [("Human", 30), ("Elf", 30), ("Half-elf", 30), ("Half-orc", 30), ("Dwarf", 20), ("Gnome", 20), ("Halfling", 20)],
)
def test_a_new_character_moves_at_its_races_speed(srd35_call, race, speed):
    # The SRD's races: "base land speed is 30 feet" for the Medium ones, 20 feet for dwarves and the Small races.
    assert _made(srd35_call, "Bram", race)["sheet"]["movement_rate"] == speed


def test_the_speed_follows_the_race_and_keeps_the_dms(srd35_call):
    _made(srd35_call, "Bram", "Human")
    # The DM's change of race takes the new race's speed.
    changed = srd35_call("update_character", ref="Bram", patch={"race": "Dwarf"})
    assert "error" not in changed, changed
    assert changed["sheet"]["movement_rate"] == 20
    # A speed the DM sets (a barbarian's fast movement) stays, through a level-up as through any change.
    assert srd35_call("update_character", ref="Bram", patch={"movement_rate": 30})["sheet"]["movement_rate"] == 30
    assert srd35_call("update_character", ref="Bram", patch={"level": 2})["sheet"]["movement_rate"] == 30
    # So does one given at creation.
    assert _made(srd35_call, "Pip", "Halfling", movement_rate=15)["sheet"]["movement_rate"] == 15


def test_a_load_slows_the_races_speed(srd35_call):
    # Str 10: light 33 lb., medium 66, heavy 100; 40 lb. of chainmail is a medium load. A human's 30 ft. is 20 ft. under a medium load (Table: Carrying
    # Loads); a halfling's 20 ft. is 15 ft. (Other Base Speeds) under its ×3/4 medium load (25–49 lb.).
    _made(srd35_call, "Bram", "Human")
    _made(srd35_call, "Pip", "Halfling")
    for name in ("Bram", "Pip"):
        added = srd35_call("add_item", character=name, item="Chainmail")  # 40 lb.
        assert "error" not in added, added
    bram, pip = (srd35_call("encumbrance", character=name) for name in ("Bram", "Pip"))
    assert (bram["band"], bram["movement"], bram["penalty"]) == ("moderate", 20, -10)
    assert (pip["band"], pip["movement"], pip["penalty"]) == ("moderate", 15, -5)


def test_a_dwarf_is_not_slowed_by_a_medium_or_heavy_load(srd35_call):
    # "Dwarves can move at this speed even when ... carrying a medium or heavy load." Lifting more (staggering) still
    # takes them to 5 ft. Str 10: a chainmail (40 lb.) is a medium load, two (80) a heavy one, three (120) lifting.
    _made(srd35_call, "Thorin", "Dwarf")
    for band, movement in (("moderate", 20), ("heavy", 20), ("severe", 5)):
        assert "error" not in srd35_call("add_item", character="Thorin", item="Chainmail")
        weighed = srd35_call("encumbrance", character="Thorin")
        assert (weighed["band"], weighed["movement"]) == (band, movement), weighed


def test_the_engine_reads_the_dwarfs_trait_from_the_race():
    from delve_srd35.engine import Srd35Engine
    from delve_srd35.reference import Srd35Reference

    from delve.domain.characters import Sheet

    engine = Srd35Engine(Srd35Reference())
    dwarf, gnome = Sheet(label="", race="Dwarf"), Sheet(label="", race="Gnome")
    # The dwarf keeps its speed under a medium or heavy load; anything else is the pack's reduced speeds (None).
    bands = ("light", "moderate", "heavy", "severe", "overloaded")
    assert [engine.loaded_speed(dwarf, band, 20) for band in bands] == [None, 20, 20, None, None]
    assert [engine.loaded_speed(gnome, band, 20) for band in bands] == [None] * 5
    assert engine.loaded_speed(Sheet(label="", race="Centaur"), "heavy", 30) is None  # not an SRD race


def test_a_party_walks_the_srds_miles_a_day(srd35_call, srd35_storage, srd35_campaign):
    # Table: Movement and Distance: 30 ft. is 24 miles a day, 20 ft. 16; the slowest sets the pace.
    from delve.dice import SeededRng
    from delve.play import travel
    from delve.play.context import context_for
    from tests.fixtures.rulesets import srd35_catalogs

    def miles() -> float:
        ctx = context_for(srd35_storage, srd35_campaign.id, "beat-t", SeededRng(1), catalogs=srd35_catalogs())
        return travel._pace(ctx, "foot", [], 0).miles

    _made(srd35_call, "Bram", "Human")
    assert miles() == 24
    _made(srd35_call, "Thorin", "Dwarf")
    assert miles() == 16
