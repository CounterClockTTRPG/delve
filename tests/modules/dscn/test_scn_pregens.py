"""Pregens (faithful modules Task 16): a seventh entity kind, `pregens`, with its ref `pregen:<id>`. Version 3
of the format adds the kind; a reader takes versions 1 to 3, so a version 2 bundle Delve wrote with pregens still reads."""
from __future__ import annotations

from tests.modules.dscn.scn_helpers import codes

from delve.modules.dscn import VERSION, Bundle, parse_ref, validate
from delve.modules.dscn.container import ENTITY_KINDS
from delve.modules.dscn.refs import ENTITY_REF_KINDS

PREGENS = [
    {
        "id": "ned",
        "name": "Ned Shakeshaft",
        "audience": "player",
        "race": "human",
        "class": "thief",
        "level": 3,
        "alignment": "CN",
        "gear": ["leather armour", "short sword", "thieves' picks"],
        "background": "A young rogue from Saltmarsh.",
        "stats": {"adnd2e": {"ability_scores": {"str": 11, "dex": 17, "con": 12, "int": 13, "wis": 9, "cha": 14},
                             "hp_max": 12, "ac": 6, "cls": "thief", "levels": 3}},
    },
    {"id": "ilsa", "name": "Ilsa", "race": "½E", "class": "fighter/mage", "level": "3/3"},
]


def test_pregens_are_the_last_kind_of_version_3():
    assert ENTITY_KINDS[-1] == "pregens"
    assert ENTITY_REF_KINDS["pregen"] == "pregens"
    assert parse_ref("pregen:ned").kind == "pregen"
    assert VERSION == 3
    assert Bundle.new("Pregens").manifest["version"] == 3


def test_a_version_2_bundle_with_pregens_still_reads():
    bundle = Bundle.new("Pregens")
    bundle.set_entities("pregens", PREGENS)
    bundle.manifest["version"] = 2
    again = Bundle.from_zip(bundle.to_zip())
    assert validate(again) == []
    assert again.entities("pregens") == PREGENS


def test_two_pregens_validate_and_round_trip(sample):
    assert sample.set_entities("pregens", PREGENS) == "entities/pregens.yaml"
    assert validate(sample) == []
    again = Bundle.from_zip(sample.to_zip())
    assert again.entities("pregens") == PREGENS
    assert again.to_zip() == sample.to_zip()


def test_a_pregen_without_a_name_is_a_schema_error(sample):
    sample.set_entities("pregens", [{"id": "nameless", "race": "dwarf"}])
    assert "schema" in codes(validate(sample))


def test_a_pregens_level_is_a_number_or_a_string(sample):
    sample.set_entities("pregens", [{"id": "x", "name": "X", "level": [3]}])
    assert "schema" in codes(validate(sample))


def test_a_pregen_ref_resolves_and_a_missing_one_dangles(sample):
    sample.set_entities("pregens", PREGENS)
    sample.manifest["keys"][0]["npcs"] = ["pregen:ned"]
    assert validate(sample) == []
    sample.manifest["keys"][0]["npcs"] = ["pregen:nobody"]
    assert any("pregen:nobody" in d.message for d in validate(sample) if d.code == "dangling-ref")
