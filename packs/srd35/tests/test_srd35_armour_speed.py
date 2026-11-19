"""Medium and heavy armour slow a 3.5 character, a dwarf excepted (DEL-407): Table: Armor and Shields' speed columns
(30 ft. → 20 ft., 20 ft. → 15 ft.) are the sheet's speed in that armour, a load slows no more than the armour already
does (Encumbrance by Armor: "use the worse figure ... Do not stack the penalties"), and heavy armour runs at ×3."""

from __future__ import annotations

import pytest

FIGHTER = {"str": 10, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8}


def _made(srd35_call, name, race, **build):
    made = srd35_call("create_character", name=name, sheet={"cls": "Fighter", "level": 1, "race": race, "hp_max": 10,
                                                             "ability_scores": FIGHTER})  # fmt: skip
    assert "error" not in made, made
    if build:
        made = srd35_call("set_build", character=name, **build)
        assert "error" not in made, made
    return made


def _sheet(srd35_call, name):
    found = srd35_call("get_character", ref=name)
    assert "error" not in found, found
    return found["sheet"]


@pytest.mark.parametrize(
    ("race", "build", "speed"),
    [
        ("Human", {"armor": "chain shirt"}, 30),  # light armour doesn't slow
        ("Human", {"armor": "chainmail"}, 20),  # medium
        ("Human", {"armor": "full plate"}, 20),  # heavy
        ("Elf", {"armor": "hide"}, 20),
        ("Halfling", {"armor": "scale mail"}, 15),  # the 20 ft. column
        ("Gnome", {"armor": "banded mail"}, 15),
        ("Dwarf", {"armor": "full plate"}, 20),  # "even when wearing medium or heavy armor"
        ("Human", {"shield": "heavy steel shield"}, 30),  # "Shields do not affect a character's speed."
        ("Human", {"shield": "tower shield"}, 30),
    ],
)
def test_armour_sets_the_sheets_speed(srd35_call, race, build, speed):
    _made(srd35_call, "Bram", race, **build)
    sheet = _sheet(srd35_call, "Bram")
    assert sheet["movement_rate"] == speed
    assert sheet["d20"]["derived"]["speed"] == speed


def test_taking_the_armour_off_gives_the_races_speed_back(srd35_call):
    _made(srd35_call, "Bram", "Human", armor="scale mail")
    assert _sheet(srd35_call, "Bram")["movement_rate"] == 20
    assert "error" not in srd35_call("set_build", character="Bram", armor="")
    assert _sheet(srd35_call, "Bram")["movement_rate"] == 30


def test_a_speed_the_dm_set_stays_in_armour(srd35_call):
    _made(srd35_call, "Bram", "Human")
    assert srd35_call("update_character", ref="Bram", patch={"movement_rate": 40})["sheet"]["movement_rate"] == 40
    assert "error" not in srd35_call("set_build", character="Bram", armor="full plate")
    assert _sheet(srd35_call, "Bram")["movement_rate"] == 40


def test_heavy_armour_runs_at_three_times_the_speed(srd35_call):
    # Table: Armor and Shields, note 2: "When running in heavy armor, you move only triple your speed, not quadruple."
    _made(srd35_call, "Bram", "Human", armor="half-plate")
    _made(srd35_call, "Dorna", "Human", armor="breastplate")
    assert _sheet(srd35_call, "Bram")["d20"]["derived"]["run_multiplier"] == 3
    assert "run_multiplier" not in _sheet(srd35_call, "Dorna")["d20"]["derived"]


@pytest.mark.parametrize(
    ("carried", "band", "movement"),
    # Str 10: light 33 lb., medium 66, heavy 100. The worn scale mail (30 lb.) is a light load; padded armour adds 10,
    # a chainmail 40.
    [
        ((), "light", 20),
        (("Padded",), "moderate", 20),
        (("Chainmail",), "heavy", 20),
        (("Chainmail", "Chainmail"), "severe", 5),
    ],
)
def test_armour_and_a_load_dont_stack(srd35_call, carried, band, movement):
    # A human in scale mail moves 20 ft.; a medium or heavy load (30 ft. → 20 ft.) slows it no more. Lifting more
    # than a heavy load still staggers at 5 ft.
    _made(srd35_call, "Bram", "Human", armor="scale mail")
    assert "error" not in srd35_call("add_item", character="Bram", item="Scale mail")
    for item in carried:
        assert "error" not in srd35_call("add_item", character="Bram", item=item)
    weighed = srd35_call("encumbrance", character="Bram")
    assert (weighed["band"], weighed["movement"]) == (band, movement), weighed


def test_a_load_slows_a_character_in_light_armour_from_its_speed(srd35_call):
    _made(srd35_call, "Bram", "Human", armor="leather")
    srd35_call("add_item", character="Bram", item="Chainmail")  # 40 lb., a medium load
    weighed = srd35_call("encumbrance", character="Bram")
    assert (weighed["band"], weighed["movement"], weighed["penalty"]) == ("moderate", 20, -10)


def test_a_party_in_heavy_armour_walks_slower(srd35_call, srd35_storage, srd35_campaign):
    # 20 ft. walks 16 miles a day (Table: Movement and Distance).
    from delve.dice import SeededRng
    from delve.play import travel
    from delve.play.context import context_for
    from tests.fixtures.rulesets import srd35_catalogs

    _made(srd35_call, "Bram", "Human", armor="full plate")
    ctx = context_for(srd35_storage, srd35_campaign.id, "beat-t", SeededRng(1), catalogs=srd35_catalogs())
    assert travel._pace(ctx, "foot", [], 0).miles == 16


def test_the_armour_table_has_each_pieces_category_and_speeds():
    from delve_srd35.engine.numbers import armour_table

    table = armour_table()
    assert (table["padded"]["category"], table["padded"]["speed"]) == ("light", {30: 30, 20: 20})
    assert (table["hide"]["category"], table["hide"]["speed"]) == ("medium", {30: 20, 20: 15})
    assert (table["full-plate"]["category"], table["full-plate"]["speed"]) == ("heavy", {30: 20, 20: 15})
    assert (table["shield-tower"]["category"], table["shield-tower"]["speed"]) == ("shield", {})
    categories = [piece["category"] for piece in table.values()]
    assert [categories.count(c) for c in ("light", "medium", "heavy", "shield")] == [4, 4, 4, 6]


def test_the_engine_gives_the_worse_of_armour_and_load():
    from dataclasses import replace

    from delve_srd35.engine import Srd35Engine
    from delve_srd35.reference import Srd35Reference

    from delve.domain.characters import Sheet

    engine = Srd35Engine(Srd35Reference())
    human = engine.fill_derived(Sheet(label="", race="Human", d20={"armor": "full plate"}), engine.reference)
    assert human.movement_rate == 20
    bands = ("light", "moderate", "heavy", "severe", "overloaded")
    assert [engine.loaded_speed(human, band, 20) for band in bands] == [20, 20, 20, 5, 0]
    # A speed the DM set is the ruleset's to slow.
    assert engine.loaded_speed(replace(human, movement_rate=40), "heavy", 40) is None
