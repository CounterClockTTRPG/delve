"""Inventory and encumbrance (spec §7.8): one list of items per character, and the party's loot pile.

ttrpg2 kept two inventories, gear in the sheet's markdown and consumables in `state.consumables`; Delve keeps one,
`CharacterState.inventory`. Items are the same item when their names are, ignoring case and spacing. An item's weight
comes from the reference (`encumbrance.resolve_weight`); one the reference doesn't know weighs nothing, with a
warning. `transfer` moves items between characters and the loot pile, named `"loot"`.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from delve.domain.campaigns import CampaignState, Character, LootItem
from delve.domain.characters import Item
from delve.domain.data import to_dict
from delve.play.characters import get, party
from delve.play.context import CampaignContext, PlayError
from delve.rules.classic import encumbrance as enc

__all__ = ["LOOT", "add_item", "encumbrance", "inventory", "remove_item", "transfer"]

LOOT = "loot"
"""The name of the loot pile as a `transfer` source or destination."""


def _qty(qty: Any) -> int:
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise PlayError(f"The quantity must be a whole number of at least 1, not {qty!r}.")
    return qty


def _unknown_weight(name: str) -> str:
    return f"No weight known for '{name}': it counts as 0 lb."


def _find(items: tuple[Item, ...], name: str) -> int | None:
    key = enc.item_key(name)
    return next((i for i, item in enumerate(items) if enc.item_key(item.name) == key), None)


def with_item(ctx: CampaignContext, items: tuple[Item, ...], item: Item) -> tuple[tuple[Item, ...], Item]:
    """`items` with `item` added to the same item, or at the end. A new item without a weight gets the reference's."""
    at = _find(items, item.name)
    if at is not None:
        held = items[at]
        merged = replace(
            held, qty=held.qty + item.qty, notes=held.notes or item.notes, dm_notes=held.dm_notes or item.dm_notes
        )
        return (*items[:at], merged, *items[at + 1 :]), merged
    if item.weight_lb is None:
        weight = enc.resolve_weight(item.name, ctx.lookups, rules=ctx.rules.encumbrance)
        if weight["source"] != "unknown":
            item = replace(item, weight_lb=weight["lb"])
    return (*items, item), item


def _taken(items: tuple[Item, ...], name: str, qty: int, holder: str) -> tuple[tuple[Item, ...], Item, int]:
    """`items` less `qty` of `name`: (the items left, the item taken, how many are left of it)."""
    at = _find(items, name)
    have = items[at].qty if at is not None else 0
    if at is None or have < qty:
        raise PlayError(
            f"{holder} has only {have} {items[at].name if at is not None else name} (needed {qty}).",
            hint="See inventory for what they carry.",
        )
    held = items[at]
    left = have - qty
    rest = (*items[:at], *([replace(held, qty=left)] if left else []), *items[at + 1 :])
    return rest, replace(held, qty=qty), left


def _save_items(ctx: CampaignContext, character: Character, items: tuple[Item, ...]) -> Character:
    return ctx.storage.characters.save_state(replace(character, state=replace(character.state, inventory=items)))


def add_item(
    ctx: CampaignContext, ref: str, name: str, qty: int = 1, notes: str = "", dm_notes: str = ""
) -> dict[str, Any]:
    """Give a character `qty` of an item; more of an item it carries adds to it. `dm_notes` are the DM's alone
    (DEL-181): the players never read them."""
    character = get(ctx, ref)
    qty = _qty(qty)
    name = name.strip()
    if not name:
        raise PlayError("An item needs a name.")
    given = Item(name, qty, notes=notes.strip(), dm_notes=dm_notes.strip())
    items, item = with_item(ctx, character.state.inventory, given)
    _save_items(ctx, character, items)
    ctx.log("item_added", character_id=character.id, name=character.name, item=item.name, qty=qty)
    out: dict[str, Any] = {"character_id": character.id, "name": character.name, "item": to_dict(item)}
    if item.weight_lb is None:
        out["warning"] = _unknown_weight(item.name)
    return out


def remove_item(ctx: CampaignContext, ref: str, name: str, qty: int = 1) -> dict[str, Any]:
    """Take `qty` of an item from a character: used up, lost, sold. Nothing changes if it has fewer."""
    character = get(ctx, ref)
    qty = _qty(qty)
    items, item, left = _taken(character.state.inventory, name, qty, character.name)
    _save_items(ctx, character, items)
    ctx.log("item_removed", character_id=character.id, name=character.name, item=item.name, qty=qty)
    return {"character_id": character.id, "name": character.name, "item": item.name, "removed": qty, "remaining": left}


def loot_notes(loot: LootItem) -> str:
    parts = [loot.kind if loot.kind != "item" else "", loot.category, f"{loot.value_gp:g} gp" if loot.value_gp else ""]
    return ", ".join(p for p in parts if p)


def _take_loot(state: CampaignState, name: str, qty: int) -> tuple[CampaignState, Item, int]:
    key = enc.item_key(name)
    at = next((i for i, loot in enumerate(state.loot) if enc.item_key(loot.description) == key), None)
    have = state.loot[at].qty if at is not None else 0
    if at is None or have < qty:
        raise PlayError(
            f"The loot pile has only {have} {name} (needed {qty}).", hint="See loot_pile for what is there."
        )
    loot = state.loot[at]
    left = have - qty
    pile = (*state.loot[:at], *([replace(loot, qty=left)] if left else []), *state.loot[at + 1 :])
    return replace(state, loot=pile), Item(loot.description, qty, notes=loot_notes(loot)), left


def _put_loot(state: CampaignState, item: Item) -> tuple[CampaignState, int]:
    key = enc.item_key(item.name)
    at = next(
        (i for i, loot in enumerate(state.loot) if loot.kind == "item" and enc.item_key(loot.description) == key), None
    )
    if at is None:
        return replace(state, loot=(*state.loot, LootItem("item", item.name, qty=item.qty))), item.qty
    loot = replace(state.loot[at], qty=state.loot[at].qty + item.qty)
    return replace(state, loot=(*state.loot[:at], loot, *state.loot[at + 1 :])), loot.qty


def transfer(ctx: CampaignContext, item: str, qty: int, source: str, dest: str) -> dict[str, Any]:
    """Move `qty` of an item between two characters, or between a character and the loot pile (`"loot"`). Nothing
    moves if the source has fewer."""
    qty = _qty(qty)
    from_loot, to_loot = source.strip().lower() == LOOT, dest.strip().lower() == LOOT
    giver = None if from_loot else get(ctx, source)
    taker = None if to_loot else get(ctx, dest)
    if (giver is None and taker is None) or (giver is not None and taker is not None and giver.id == taker.id):
        raise PlayError("The source and the destination are the same.")
    with ctx.storage.transaction():
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        if giver is None:
            state, moved, from_now = _take_loot(state, item, qty)
        else:
            items, moved, from_now = _taken(giver.state.inventory, item, qty, giver.name)
            _save_items(ctx, giver, items)
        if taker is None:
            state, to_now = _put_loot(state, moved)
        else:
            taker = get(ctx, taker.id)
            items, held = with_item(ctx, taker.state.inventory, moved)
            _save_items(ctx, taker, items)
            to_now = held.qty
        if from_loot or to_loot:
            ctx.storage.campaign_states.put(state)
        from_name = giver.name if giver is not None else "the loot pile"
        to_name = taker.name if taker is not None else "the loot pile"
        ctx.log(
            "transfer",
            item=moved.name,
            qty=qty,
            **{"from": giver.id if giver else LOOT, "to": taker.id if taker else LOOT},
            notes=f"{qty} {moved.name}: {from_name} → {to_name}",
        )
    return {"item": moved.name, "qty": qty, "from": from_name, "to": to_name, "from_now": from_now, "to_now": to_now}


def _listing(character: Character) -> list[dict[str, Any]]:
    return [to_dict(item) for item in character.state.inventory]


def inventory(ctx: CampaignContext, ref: str = "") -> dict[str, Any]:
    """One character's items; without `ref`, those of every character who carries something, party first."""
    if ref:
        character = get(ctx, ref)
        return {"character_id": character.id, "name": character.name, "items": _listing(character)}
    pcs = party(ctx)
    npcs = [c for c in ctx.storage.characters.list(ctx.campaign_id) if c.kind == "npc"]
    return {"by_character": {c.name: _listing(c) for c in (*pcs, *npcs) if c.state.inventory}}


def weigh(ctx: CampaignContext, character: Character) -> dict[str, Any]:
    """`encumbrance.compute` for a character's inventory, each item with the `source` of its weight ("stored" when
    the item carries it) and a warning per item of unknown weight."""
    loads: list[tuple[str, int, float | None]] = []
    sources: list[str] = []
    for item in character.state.inventory:
        if item.weight_lb is not None:
            loads.append((item.name, item.qty, item.weight_lb))
            sources.append("stored")
        else:
            weight = enc.resolve_weight(item.name, ctx.lookups, rules=ctx.rules.encumbrance)
            loads.append((item.name, item.qty, weight["lb"]))
            sources.append(weight["source"])
    scores = character.sheet.ability_scores
    out = enc.compute(
        loads,
        strength=scores.get("str", 10),
        pct=scores.get("str_pct"),
        movement_rate=character.sheet.movement_rate,
        rules=ctx.rules.encumbrance,
    )
    for row, source in zip(out["items"], sources, strict=True):
        row["source"] = source
    warnings = [_unknown_weight(row["item"]) for row in out["items"] if row["source"] == "unknown"]
    if warnings:
        out["warnings"] = warnings
    return out


def encumbrance(ctx: CampaignContext, ref: str) -> dict[str, Any]:
    """What a character carries against its Strength (the ruleset's encumbrance bands): `{total_lb, band, movement, penalty}`, with the
    thresholds and the weight of each item."""
    character = get(ctx, ref)
    return {"character_id": character.id, "name": character.name, **weigh(ctx, character)}
