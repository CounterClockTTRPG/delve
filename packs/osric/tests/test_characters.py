"""OSRIC characters (DEL-304): every class's entry with its abilities in Delve's words, every ancestry's classes and
level limits, and a new character's THAC0 and saves from the class tables."""

import pytest
from delve_osric.classes import ANCESTRY_CLASSES, FEATURES_OWN_CLASSES, level_limit
from delve_osric.data import CLASSES
from delve_osric.ruleset import OsricRuleset

REF = OsricRuleset().reference


@pytest.mark.parametrize("cls", CLASSES)
def test_every_class_has_its_entry_and_abilities(cls):
    found = REF.char_class(cls)
    assert found["special_abilities"], cls
    assert found["hit_die"].startswith("d") and found["minimum_scores"]
    assert found["ancestries"], cls  # some ancestry may take it
    assert not any(key.startswith("_") for key in (found["spellcaster"] or {}))


def test_the_six_classes_abilities_are_delves_own_words():
    assert set(FEATURES_OWN_CLASSES) == {"assassin", "druid", "illusionist", "monk", "paladin", "ranger"}
    paladin = {f["name"]: f["level"] for f in REF.char_class("paladin")["special_abilities"]}
    assert paladin["Lay on Hands"] == 1 and paladin["Holy Steed"] == 4 and paladin["Divine Spells"] == 9


def test_thieves_carry_their_skill_table():
    skills = REF.char_class("thief")["thief_skills"]
    assert skills["1"]["pick_locks"] == 25 and skills["1"]["backstab"] == 2


def test_every_ancestry_with_its_classes_and_limits():
    for ancestry in ANCESTRY_CLASSES:
        race = REF.race(ancestry)
        assert race["classes"] == list(ANCESTRY_CLASSES[ancestry]) and race["ability_ranges"], ancestry
    assert "fighter/magic-user/thief" in REF.race("elf")["classes"]
    assert not any("/" in c for c in REF.race("human")["classes"])
    assert REF.race("Half Orc")["name"] == "Half-Orc" and REF.race("tiefling") is None


@pytest.mark.parametrize(
    ("ancestry", "cls", "scores", "limit"),
    [
        ("dwarf", "fighter", {"str": "18/50"}, 9),
        ("dwarf", "fighter", {"strength": 17}, 8),
        ("dwarf", "fighter", {"strength": 12}, 7),
        ("dwarf", "thief", {}, None),
        ("elf", "magic-user", {"int": 18}, 11),
        ("halfling", "fighter", {}, 4),
        ("half-orc", "thief", {"dex": 16}, 6),
        ("gnome", "illusionist", {"int": 18, "dex": 17}, 7),
        ("gnome", "illusionist", {"int": 17, "dex": 17}, 6),
        ("gnome", "illusionist", {"int": 16, "dex": 17}, 5),
        ("human", "fighter", {}, None),
        ("human", "monk", {}, 17),
    ],
)
def test_level_limits(ancestry, cls, scores, limit):
    assert level_limit(ancestry, cls, scores) == limit
