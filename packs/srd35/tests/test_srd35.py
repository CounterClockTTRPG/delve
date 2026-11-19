"""The SRD 3.5 pack (DEL-384): a ruleset campaigns play (DEL-388) and a reference, its lookups over the extracted SRD data, and its
rules text."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from delve.domain.reference import RulesetReference
from delve.packs import loader

PACK = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ruleset():
    from delve_srd35.ruleset import Srd35Ruleset

    return Srd35Ruleset()


def test_the_pack_loads_and_is_playable(tmp_path):
    shutil.copytree(PACK, tmp_path / "srd35", ignore=shutil.ignore_patterns("tests", "scripts", "__pycache__"))
    loader.reset()
    try:
        (loaded,), skipped = loader.load_packs(tmp_path)
        assert skipped == ()
        manifest = loaded.manifest
        assert (manifest.id, manifest.title, manifest.kind) == ("srd35", "SRD 3.5", "ruleset")
        assert (manifest.playable, manifest.monster_pictures, manifest.preferred) == (True, "reuse", False)
        assert loaded.entry.ruleset(loaded.root).id == "srd35"
    finally:
        loader.reset()


def test_its_saves_are_fortitude_reflex_and_will(ruleset):
    assert ruleset.tables.save_types == ("fort", "ref", "will")
    assert [ruleset.tables.save_names[s] for s in ruleset.tables.save_types] == ["Fortitude", "Reflex", "Will"]
    assert ruleset.encounters is None and ruleset.treasure is None


def test_the_reference_is_a_ruleset_reference(ruleset):
    assert isinstance(ruleset.reference, RulesetReference)


def test_lookups_find_by_name(ruleset):
    assert ruleset.kinds() == ("monster", "spell", "item", "weapon", "class", "feat", "skill")
    assert ruleset.lookup("monster", "ogre")[0].title == "Ogre"
    assert ruleset.lookup("feat", "power attack")[0].title == "Power Attack"
    assert ruleset.lookup("skill", "hide")[0].title == "Hide"
    assert ruleset.lookup("spell", "fireball")[0].title == "Fireball"
    assert ruleset.lookup("class", "wizard")[0].title == "Wizard"
    assert ruleset.lookup("item", "bag of holding")[0].title == "Bag of Holding"
    (sword,) = ruleset.lookup("weapon", "longsword")
    assert (sword.title, sword.text) == ("Longsword", "martial one-handed, 1d8, 19–20/x2, 15 gp")


@pytest.mark.parametrize("typed", ["Bull's Strength", "bull’s strength", "Bull`s Strength", "bull´s strength"])
def test_a_name_is_found_whatever_its_apostrophe(ruleset, typed):  # DEL-401: the data's are curly
    assert ruleset.reference.spell(typed)[0]["name"] == "Bull’s Strength"


def test_names_with_apostrophes_are_found_in_every_lookup(ruleset):  # DEL-401
    assert ruleset.reference.monster("will-o'-wisp")[0]["name"] == "Will-o’-wisp"
    assert ruleset.reference.item("philosopher’s stone")[0]["name"] == "Philosopher's Stone"
    assert ruleset.reference.spell("Bull's Strength", "wizard")[0]["name"] == "Bull’s Strength"


def test_a_weapon_is_found_by_name(ruleset):
    assert ruleset.reference.weapon("Longsword")["threat"] == 19
    assert ruleset.reference.weapon("battleaxe")["mult"] == 3
    assert ruleset.reference.weapon("nothing") is None


def test_monsters_rank_the_exact_name_first(ruleset):
    found = [m["name"] for m in ruleset.reference.monster("dragon")]
    assert found and len(found) <= 10
    assert ruleset.reference.monster("Ogre")[0]["name"] == "Ogre"
    assert ruleset.reference.monster("") == []


def test_spell_filters_by_class(ruleset):
    assert [s["name"] for s in ruleset.reference.spell("fireball", "wizard")][:1] == ["Fireball"]
    assert ruleset.reference.spell("fireball", "cleric") == []
    assert ruleset.reference.spell("cure light wounds", "cleric")[0]["levels"]["cleric"] == 1


def test_class_levels_are_the_table(ruleset):
    levels = ruleset.reference.class_levels("fighter")
    assert len(levels) == 20 and levels[5]["bab"] == "+6/+1"
    assert ruleset.reference.char_class("figh")["name"] == "Fighter"
    assert ruleset.reference.char_class("nothing") is None


def test_races_and_abilities(ruleset):
    assert ruleset.reference.race("dwarves")["ability_adjustments"] == {"cha": -2, "con": 2}
    assert ruleset.reference.race("nothing") is None
    eighteen = ruleset.reference.ability("str", "18")
    assert eighteen["values"]["modifier"] == "+4"
    assert len(ruleset.reference.ability("dex", "")["rows"]) == 45
    assert "error" in ruleset.reference.ability("luck", "10")


def test_rules_search_finds_attacks_of_opportunity(ruleset):
    hits = ruleset.reference.rules_search("attacks of opportunity")
    assert hits and "<<" in hits[0]["snippet"]
    with pytest.raises(ValueError):
        ruleset.reference.rules_search("of the")


def test_unknown_kind_raises(ruleset):
    with pytest.raises(ValueError, match="unknown kind"):
        ruleset.lookup("deity", "x")


def test_what_a_reference_has_none_of_is_empty(ruleset):
    ref = ruleset.reference
    assert (ref.proficiency(), ref.turning_undead(), ref.encounter_tables(), ref.osric_magic_items()) == (
        [],
        [],
        {},
        {},
    )


def test_the_notice_and_prompt_say_what_it_is(ruleset):
    assert "Open Game License" in ruleset.notice and "System Reference Document" in ruleset.notice
    assert "reference" in ruleset.prompt.lower()
