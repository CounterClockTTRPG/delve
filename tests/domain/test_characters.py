"""Sheets and states as plain data: every field is checked, and they survive JSON."""

import json

import pytest

from delve.domain.campaigns import CampaignState, LootItem
from delve.domain.characters import Attack, CharacterState, Effect, Item, Sheet
from delve.domain.data import DataError


def test_sheet_roundtrips_through_json():
    sheet = Sheet(
        kind="npc",
        label="Tira",
        cls="Thief",
        levels={"thief": 3},
        saves={"spell": 13},
        ability_scores={"str": "18/76", "dex": 17},
        attacks=(Attack("dagger", speed=2, attacks="3/2", damage_sm="1d4", damage_l="1d3", range="10/20/30"),),
        nwps=("disguise",),
        spell_slots={1: 2},
        disposition=-45,
    )
    raw = json.loads(json.dumps(sheet.to_dict()))
    assert raw["spell_slots"] == {"1": 2} and raw["attacks"][0]["attacks"] == "3/2"
    assert Sheet.from_dict(raw) == sheet
    state = CharacterState(hp=-3, xp=10, conditions=("downed",), effects=(Effect("sleep", 2, source="mon_1"),))
    assert CharacterState.from_dict(json.loads(json.dumps(state.to_dict()))) == state
    camp = CampaignState("cmp_000000000001", loot=(LootItem("magic", "a wand", 500.5, "wand"),))
    assert CampaignState.from_dict(json.loads(json.dumps(camp.to_dict()))) == camp


def test_attack_rate_as_number_or_text():
    assert Sheet.from_dict({"attacks": [{"name": "claw", "attacks": 2}]}).attacks[0].attacks == 2
    assert Sheet.from_dict({"attacks": [{"name": "sword", "attacks": 1.5}]}).attacks[0].attacks == 1.5


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ({"hp_max": "lots"}, "hp_max"),
        ({"hp_max": True}, "hp_max"),
        ({"kind": "monster"}, "kind"),
        ({"wings": 2}, "wings"),
        ({"attacks": [{"name": "claw", "sped": 3}]}, "attacks[0].sped"),
        ({"attacks": [{"speed": 3}]}, "attacks[0]"),
        ({"spell_slots": {"first": 2}}, "spell_slots.first"),
        ({"saves": [12, 14]}, "saves"),
        ({"nwps": "tracking"}, "nwps"),
    ],
)
def test_bad_fields_are_named(raw, field):
    with pytest.raises(DataError) as caught:
        Sheet.from_dict(raw)
    assert caught.value.field == field


@pytest.mark.parametrize(
    ("notes", "kept", "dm"),
    [
        ("Glass phial, stoppered (DM: potion of neutralise poison, 2 doses)", "Glass phial, stoppered",
         "potion of neutralise poison, 2 doses"),
        ("A rusty key. DM: opens the crypt door", "A rusty key.", "opens the crypt door"),
        ("Helm [GM only: cursed]", "Helm", "cursed"),
        ("DM: everything", "", "everything"),
        ("engraved with a rose", "engraved with a rose", ""),
        ("Given by the ADMIRAL: a token", "Given by the ADMIRAL: a token", ""),
    ],
)
def test_an_items_dm_part_moves_to_its_dm_notes(notes, kept, dm):
    """DEL-181: what the DM wrote for itself into an item's notes is the DM's alone, a stored item's too."""
    item = Item("Phial", notes=notes)
    assert (item.notes, item.dm_notes) == (kept, dm)
    assert CharacterState.from_dict({"inventory": [{"name": "Phial", "notes": notes}]}).inventory[0] == item
    assert Item("Phial", notes=notes, dm_notes="charged").dm_notes == "; ".join(p for p in ("charged", dm) if p)


def test_pronouns_come_from_the_sheet_or_its_gender():
    """DEL-327: the story kept a female PC as "he" for want of them in reach."""
    from delve.domain.characters import pronouns_of

    assert pronouns_of(Sheet(gender="Female")) == "she/her"
    assert pronouns_of(Sheet(gender="m")) == "he/him"
    assert pronouns_of(Sheet(gender="female", pronouns="they/them")) == "they/them"
    assert pronouns_of(Sheet(gender="")) == "" and pronouns_of(Sheet(gender="nonbinary")) == ""
