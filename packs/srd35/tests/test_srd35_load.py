"""A 3.5 character's load (DEL-388, ruling R20): the SRD's Table: Carrying Capacity, by Strength, in the pack's
encumbrance bands, so the session primer, the character pages and the encumbrance tool read a load."""

from __future__ import annotations

from delve_srd35 import data
from delve_srd35.tables import TABLES

from delve.rules.classic import encumbrance as enc

FIGHTER = {"str": 16, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8}


def test_the_carrying_capacity_rows_are_the_srds():
    # Checked by hand against the SRD's Table: Carrying Capacity: Str 10 carries 33 lb. or less light, 34–66 lb.
    # medium, 67–100 lb. heavy; Str 27's heavy load is 694–1,040 lb.; "+10 ×4" for Tremendous Strength.
    carrying = data.load("carrying")
    rows = {row["strength"]: row for row in carrying["loads"]}
    assert sorted(rows) == list(range(1, 30))
    assert rows[10] == {"strength": 10, "light": 33, "medium": 66, "heavy": 100}
    assert rows[27]["heavy"] == 1040
    assert carrying["tremendous"] == 4


def test_the_bands_are_light_medium_heavy_then_lifting():
    # Str 16: light 76, medium 153, heavy 230; lifting off the ground (staggering) to double the heavy load, 460.
    assert enc.str_band_for(16, rules=TABLES.encumbrance) == (76, 153, 230, 460)
    # Tremendous Strength: Str 32 is Str 22's row (173/346/520) × 4.
    assert enc.str_band_for(32, rules=TABLES.encumbrance) == (692, 1384, 2080, 4160)
    # A heavy load slows a speed of 30 ft. to 20 ft. (Table: Carrying Loads), as a medium one does.
    loaded = enc.compute([("anvil", 1, 200.0)], strength=16, movement_rate=30, rules=TABLES.encumbrance)
    assert (loaded["band"], loaded["movement"]) == ("heavy", 20)


def test_the_primer_and_the_character_page_read_a_load(srd35_tripwire, srd35_call, srd35_storage, srd35_campaign):
    from delve.dice import SeededRng
    from delve.play.context import context_for
    from delve.web.routes.characters import character_json
    from tests.fixtures.rulesets import srd35_catalogs

    made = srd35_call("create_character", name="Bram", sheet={"cls": "Fighter", "level": 1, "race": "Human",
                                                               "hp_max": 12, "ability_scores": FIGHTER})  # fmt: skip
    assert "error" not in made, made
    assert "error" not in srd35_call("set_build", character="Bram", weapon="longsword", armor="chain mail")
    primer = srd35_call("session_primer")
    assert "error" not in primer, primer
    weighed = srd35_call("encumbrance", character="Bram")
    assert "error" not in weighed, weighed
    assert weighed["thresholds"] == {"light": 76, "moderate": 153, "heavy": 230, "severe": 460}
    ctx = context_for(srd35_storage, srd35_campaign.id, "beat-web", SeededRng(1), catalogs=srd35_catalogs())
    page = character_json(srd35_storage.characters.get(made["id"]), ctx)
    assert page["encumbrance"]["band"] == "light"


def _moving(lb: float, speed: int) -> tuple[str, int]:
    out = enc.compute([("sack", 1, lb)], strength=10, movement_rate=speed, rules=TABLES.encumbrance)
    return out["band"], out["movement"]


def test_a_load_slows_by_the_srds_reduced_speeds():  # DEL-399
    # Str 10: light 33, medium 66, heavy 100. Table: Carrying Loads and its Other Base Speeds: a medium or heavy load
    # takes 20 ft. to 15 ft. (not two thirds, 13), 30 ft. to 20 ft., 40 ft. to 30 ft.
    assert _moving(50, 20) == ("moderate", 15)
    assert _moving(90, 20) == ("heavy", 15)
    assert _moving(50, 30) == ("moderate", 20)
    assert _moving(50, 40) == ("moderate", 30)
    assert _moving(20, 20) == ("light", 20)
    # Lifted off the ground (up to double the heavy load) the character staggers 5 ft. a round, whatever its speed;
    # more can't be lifted.
    assert _moving(150, 20) == ("severe", 5)
    assert _moving(150, 30) == ("severe", 5)
    assert _moving(250, 30) == ("overloaded", 0)
    # A speed the table doesn't give (a sheet's classic 12) keeps two thirds, as before.
    assert _moving(50, 12) == ("moderate", 8)


def test_a_small_character_carries_three_quarters(srd35_call):  # DEL-399
    # Bigger and Smaller Creatures: Small ×3/4. A halfling with Str 10: 33, 66, 100 are 24, 49 and 75 (rounded down);
    # lifting, double the heavy load, 150. A human with Str 10 carries the table's.
    for name, race in (("Pip", "Halfling"), ("Bram", "Human")):
        sheet = {"cls": "Rogue", "level": 1, "race": race, "hp_max": 6, "ability_scores": {**FIGHTER, "str": 10}}
        assert "error" not in srd35_call("create_character", name=name, sheet=sheet)
    halfling = srd35_call("encumbrance", character="Pip")
    assert halfling["thresholds"] == {"light": 24, "moderate": 49, "heavy": 75, "severe": 150}
    human = srd35_call("encumbrance", character="Bram")
    assert human["thresholds"] == {"light": 33, "moderate": 66, "heavy": 100, "severe": 200}


def test_the_multiplier_is_the_races_size():  # DEL-399
    from delve_srd35.engine import Srd35Engine
    from delve_srd35.reference import Srd35Reference

    from delve.domain.characters import Sheet

    engine = Srd35Engine(Srd35Reference())
    assert engine.load_multiplier(Sheet(label="", race="Gnome")) == 0.75
    assert engine.load_multiplier(Sheet(label="", race="Dwarf")) == 1
    assert engine.load_multiplier(Sheet(label="", race="Centaur")) == 1  # not a race of the SRD's: Medium
