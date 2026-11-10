"""`play.inventory`: one inventory per character, moving items between characters and the loot pile, encumbrance."""

from dataclasses import replace

import pytest

from delve.domain.campaigns import LootItem
from delve.domain.characters import Item
from delve.play import characters, inventory
from delve.play.context import NotFound, PlayError

GARREK = {"race": "human", "cls": "Fighter", "level": 3, "hp_max": 24, "ability_scores": {"str": 12}}
PIPPA = {"race": "halfling", "cls": "Thief", "level": 2, "hp_max": 9, "ability_scores": {"str": "9"}}


def events(ctx, type):
    return [e.data for e in ctx.storage.events.list(ctx.campaign_id) if e.type == type]


def test_one_inventory(ctx):
    """ttrpg2 kept gear in the sheet's markdown and consumables in `state.consumables`; Delve has one list of items
    in the character's state, with quantities, weights from the reference and notes."""
    garrek = characters.create(ctx, name="Garrek", sheet=GARREK)
    out = inventory.add_item(ctx, "Garrek", "Torch", qty=6)
    assert out["item"] == {"name": "Torch", "qty": 6, "weight_lb": 1.0, "notes": "", "dm_notes": ""}
    inventory.add_item(ctx, "garrek", "torch", qty=2)  # the same item, whatever the case
    inventory.add_item(ctx, "Garrek", "Long sword", notes="his father's")
    state = ctx.storage.characters.get(garrek.id).state
    assert state.inventory == (Item("Torch", 8, 1.0), Item("Long sword", 1, 4.0, "his father's"))
    assert events(ctx, "item_added")[0] == {"character_id": garrek.id, "name": "Garrek", "item": "Torch", "qty": 6}

    out = inventory.remove_item(ctx, "Garrek", "TORCH", qty=3)
    assert (out["removed"], out["remaining"]) == (3, 5)
    inventory.remove_item(ctx, "Garrek", "Long sword")
    assert ctx.storage.characters.get(garrek.id).state.inventory == (Item("Torch", 5, 1.0),)
    with pytest.raises(PlayError) as short:
        inventory.remove_item(ctx, "Garrek", "Torch", qty=9)
    assert "only 5" in short.value.message
    with pytest.raises(PlayError):
        inventory.remove_item(ctx, "Garrek", "Spoon")
    with pytest.raises(PlayError):
        inventory.add_item(ctx, "Garrek", "Torch", qty=0)
    assert ctx.storage.characters.get(garrek.id).state.inventory == (Item("Torch", 5, 1.0),)


def test_unknown_item_weighs_nothing_with_a_warning(ctx):
    characters.create(ctx, name="Garrek", sheet=GARREK)
    out = inventory.add_item(ctx, "Garrek", "Blorp of Doom")
    assert out["item"]["weight_lb"] is None
    assert "Blorp of Doom" in out["warning"]
    weighed = inventory.encumbrance(ctx, "Garrek")
    assert weighed["total_lb"] == 0.0 and "Blorp of Doom" in weighed["warnings"][0]


def test_transfer_between_characters_and_loot(ctx):
    garrek = characters.create(ctx, name="Garrek", sheet=GARREK)
    pippa = characters.create(ctx, name="Pippa", sheet=PIPPA)
    inventory.add_item(ctx, "Garrek", "Torch", qty=6)

    out = inventory.transfer(ctx, "torch", 4, "Garrek", "Pippa")
    assert (out["from_now"], out["to_now"]) == (2, 4)
    assert ctx.storage.characters.get(pippa.id).state.inventory == (Item("Torch", 4, 1.0),)
    assert events(ctx, "transfer")[0]["notes"] == "4 Torch: Garrek → Pippa"

    inventory.transfer(ctx, "Torch", 2, "Garrek", "loot")
    assert ctx.storage.characters.get(garrek.id).state.inventory == ()
    assert ctx.storage.campaign_states.get(ctx.campaign_id).loot == (LootItem("item", "Torch", qty=2),)

    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    ctx.storage.campaign_states.put(
        replace(state, loot=(*state.loot, LootItem("gem", "Bloodstone", 50, "Semi-precious")))
    )
    inventory.transfer(ctx, "bloodstone", 1, "Loot", "Pippa")
    inventory.transfer(ctx, "Torch", 1, "loot", "Pippa")
    pippa_items = ctx.storage.characters.get(pippa.id).state.inventory
    assert pippa_items == (Item("Torch", 5, 1.0), Item("Bloodstone", 1, None, "gem, Semi-precious, 50 gp"))
    assert ctx.storage.campaign_states.get(ctx.campaign_id).loot == (LootItem("item", "Torch", qty=1),)


def test_failed_transfer_moves_nothing(ctx):
    characters.create(ctx, name="Garrek", sheet=GARREK)
    characters.create(ctx, name="Pippa", sheet=PIPPA)
    inventory.add_item(ctx, "Garrek", "Torch", qty=2)
    before = ctx.storage.characters.list(ctx.campaign_id)
    with pytest.raises(PlayError):
        inventory.transfer(ctx, "Torch", 3, "Garrek", "Pippa")
    with pytest.raises(PlayError):
        inventory.transfer(ctx, "Torch", 0, "Garrek", "Pippa")
    with pytest.raises(PlayError):
        inventory.transfer(ctx, "Torch", 1, "Garrek", "Garrek")
    with pytest.raises(NotFound):
        inventory.transfer(ctx, "Torch", 1, "Garrek", "Nobody")
    with pytest.raises(PlayError):
        inventory.transfer(ctx, "Torch", 1, "loot", "Pippa")
    assert ctx.storage.characters.list(ctx.campaign_id) == before
    assert events(ctx, "transfer") == []


def test_inventory_listing(ctx):
    characters.create(ctx, name="Garrek", sheet=GARREK)
    characters.create(ctx, name="Pippa", sheet=PIPPA)
    characters.create(ctx, name="Tira", kind="npc", sheet={})
    inventory.add_item(ctx, "Garrek", "Torch", qty=2)
    inventory.add_item(ctx, "Tira", "Backpack")
    one = inventory.inventory(ctx, "Garrek")
    torch = {"name": "Torch", "qty": 2, "weight_lb": 1.0, "notes": "", "dm_notes": ""}
    assert one["name"] == "Garrek" and one["items"] == [torch]
    everyone = inventory.inventory(ctx)
    assert list(everyone["by_character"]) == ["Garrek", "Tira"]  # characters with nothing are left out
    assert everyone["by_character"]["Tira"][0]["name"] == "Backpack"


def test_encumbrance_from_the_inventory(ctx):
    """ttrpg2's `encumbrance` tool: weights by item, the STR band and its movement penalty."""
    characters.create(ctx, name="Garrek", sheet={**GARREK, "movement_rate": 12})
    inventory.add_item(ctx, "Garrek", "Plate mail")
    inventory.add_item(ctx, "Garrek", "Torch", qty=6)
    out = inventory.encumbrance(ctx, "Garrek")
    assert (out["total_lb"], out["band"], out["penalty"], out["movement"]) == (56.0, "moderate", -3, 9)
    assert out["strength"] == 12
    assert out["items"][0] == {"item": "Plate mail", "qty": 1, "unit_lb": 50.0, "weight_lb": 50.0, "source": "stored"}
    # an item given on the sheet without a weight is weighed from the reference
    characters.update(ctx, "Garrek", {"inventory": [{"name": "Studded leather armour", "qty": 1}]})
    out = inventory.encumbrance(ctx, "Garrek")
    assert out["total_lb"] == 20.0 and out["items"][0]["source"] == "db"
