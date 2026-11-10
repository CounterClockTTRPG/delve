"""`module_pregens` (faithful modules Task 19): the DM reads the pinned revision's pregenerated characters, every
audience, each with the sheet `create_character` takes, and makes the party from them."""

import pytest

from delve.domain.modules import ModuleMap
from delve.modules.source import ModuleSource
from tests.dm.tools.conftest import CRYPT, SECRET

NED = {
    "id": "ned",
    "name": "Ned Shakeshaft",
    "audience": "player",
    "summary": "A spy, as the book says.",
    "race": "Human",
    "class": "Fighter/Thief",
    "level": "3/3",
    "alignment": "Neutral",
    "background": "A sailor from Saltmarsh.",
    "gear": ["Leather armour", "Short sword", "Thieves' tools"],
    "stats": {
        "adnd2e": {
            "ability_scores": {"str": "18/76", "dex": 16, "con": 12, "int": 11, "wis": 9, "cha": 10},
            "hp_max": 17,
            "ac": 6,
            "line": "AC 6; MV 12; HD 3; hp 17",
        }
    },
}
SPY = {
    "id": "spy",
    "name": "The Spy",
    "audience": "gm",
    "description": f"{SECRET}: works for the smugglers.",
    "race": "Half-elf",
    "class": "Thief",
    "level": 2,
    "stats": {"adnd2e": {"hp_max": 7}},
}


@pytest.fixture
def campaign(storage):
    module = storage.modules.create("The Sinister Secret")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    storage.module_sources.put(module.id, ModuleSource(entities={"pregens": [NED, SPY]}))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")


def test_module_pregens_gives_each_sheet(call):
    out = call("module_pregens")
    assert out == {
        "pregens": [
            {
                "id": "ned",
                "name": "Ned Shakeshaft",
                "audience": "player",
                "sheet": {
                    "ability_scores": {"str": "18/76", "dex": 16, "con": 12, "int": 11, "wis": 9, "cha": 10},
                    "hp_max": 17,
                    "ac": 6,
                    "race": "Human",
                    "cls": "Fighter/Thief",
                    "levels": {"fighter": 3, "thief": 3},
                    "alignment": "Neutral",
                    "background": "A sailor from Saltmarsh.",
                },
                "gear": ["Leather armour", "Short sword", "Thieves' tools"],
            },
            {
                "id": "spy",
                "name": "The Spy",
                "audience": "gm",
                "sheet": {"hp_max": 7, "race": "Half-elf", "cls": "Thief", "level": 2},
                "gear": [],
            },
        ]
    }


def test_create_character_makes_the_pc_from_the_sheet(call):
    [ned, _] = call("module_pregens")["pregens"]
    made = call("create_character", name=ned["name"], sheet=ned["sheet"])
    assert "error" not in made, made
    assert (made["name"], made["kind"]) == ("Ned Shakeshaft", "pc")
    sheet = made["sheet"]
    assert (sheet["race"], sheet["cls"], sheet["levels"]) == ("Human", "Fighter/Thief", {"fighter": 3, "thief": 3})
    assert sheet["ability_scores"]["str"] == "18/76" and sheet["hp_max"] == 17 and sheet["ac"] == 6
    assert made["state"]["hp"] == 17
    for line in ned["gear"]:
        assert "error" not in call("add_item", character="Ned Shakeshaft", item=line)


def test_module_pregens_are_the_pinned_revisions(storage, host, call, campaign):
    """Editing the module changes no campaign until the host upgrades it; a revision without pregens has none."""
    storage.module_sources.put(campaign.module_id, ModuleSource())
    later = storage.revisions.snapshot(campaign.module_id)
    assert [p["id"] for p in call("module_pregens")["pregens"]] == ["ned", "spy"]
    other = storage.campaigns.create(
        "Wednesday", campaign.module_id, later.number, ruleset="osric", setting="greyhawk"
    )
    assert host.call(other.id, "beat-1", "module_pregens", {}) == {"pregens": []}
