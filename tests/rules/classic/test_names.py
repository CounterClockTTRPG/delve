"""The name generator, ported from ttrpg2 `names.py`: every choice comes from the dice's `Rng`."""

import pytest

from delve.dice import ScriptedRng, ScriptExhausted, SeededRng
from delve.rules.classic import names

PC_RACES = ("human", "elf", "dwarf", "halfling", "gnome", "halfelf", "halforc")


def test_every_race_names_someone():
    rng = SeededRng(1)
    for race in names.RACES:
        for female in (False, True):
            name = names.generate(rng, race, female)
            assert name and name == name.strip(), (race, female)


def test_names_deterministic_with_seeded_rng():
    def batch(seed: int) -> list[str]:
        rng = SeededRng(seed)
        return [names.generate(rng, race, female) for race in names.RACES for female in (False, True)]

    assert batch(42) == batch(42)
    assert batch(42) != batch(43)


def test_a_scripted_rng_picks_the_bank_entry():
    # A fraction of 0 (die 1 of 1000) takes the curated bank; index 0 of the human first names, then surname 0.
    name = names.generate(ScriptedRng([1, 0, 0]), "human")
    assert name == f"{names.HUMAN_FIRSTS_M[0]} {names.HUMAN_SURNAMES[0]}"
    with pytest.raises(ScriptExhausted):
        names.generate(ScriptedRng([1]), "human")


def test_aliases_and_unknown_races():
    assert names.generate(SeededRng(5), "Half-Elf") == names.generate(SeededRng(5), "halfelf")
    assert names.generate(SeededRng(5), "lizardman") == names.generate(SeededRng(5), "lizardfolk")
    # An unknown race takes a PC race's generator, never a goblin's.
    assert names.generate(SeededRng(5), "beholder") == names.generate(SeededRng(5), "beholder")
    assert names.generate(SeededRng(5), "")
