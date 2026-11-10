"""The magic merchant in play (plan 6 Task 9; ttrpg2's `tools/merchant.py`): a merchant's shelf, rolled once with
the campaign's dice and kept in `storage.merchants` until the DM restocks it, and buying off it.

The shelf is the DM's: the DM narrates it, and the players' feed shows only the tool's name. Buying pays from the
party's coin as ttrpg2 did (`rules.spend`: gold first, a larger coin broken for change), and puts the item in the
character's inventory. `Merchant.seed` counts the shelves rolled for a merchant; each roll of a shelf is keyed by it,
so a restock rolls fresh even within one beat.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from delve.domain.characters import Item
from delve.domain.world import Merchant
from delve.play.characters import get
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.play.inventory import with_item
from delve.rules.classic import merchant as rules

__all__ = ["EMPTY", "buy_magic_item", "magic_merchant"]

EMPTY = "nothing for sale today"


def _slug(merchant: str) -> str:
    return merchant.lower().strip()


def _gp(amount: float) -> str:
    """A sum of gold pieces as the DM reads it: "2,000", "99.5"."""
    return f"{amount:,.2f}".rstrip("0").rstrip(".")


def _view(ctx: CampaignContext, merchant: Merchant) -> dict[str, Any]:
    npc = ctx.storage.characters.get(merchant.npc_id) if merchant.npc_id else None
    out: dict[str, Any] = {
        "merchant": merchant.id,
        "name": merchant.name,
        "npc": npc.name if npc is not None else "",
        "settlement": merchant.settlement,
        "cost": merchant.cost,
        "rolled_day": merchant.rolled_day,
        "items": [{"index": i, **item} for i, item in enumerate(merchant.items)],
        "sold": list(merchant.sold),
    }
    if not merchant.items:
        out["note"] = EMPTY
    return out


def magic_merchant(
    ctx: CampaignContext,
    merchant: str,
    settlement: str = "pedlar",
    cost: str = "moderate",
    name: str = "",
    npc: str = "",
    restock: bool = False,
) -> dict[str, Any]:
    """A merchant's shelf: rolled the first time, then the same until `restock`. A restock keeps the name, the NPC
    and what was sold, unless given anew."""
    if settlement not in rules.SETTLEMENTS:
        raise PlayError(f"Unknown settlement '{settlement}'.", hint=f"Use one of {', '.join(rules.SETTLEMENTS)}.")
    if cost not in rules.COST_GRADES:
        raise PlayError(f"Unknown cost grade '{cost}'.", hint=f"Use one of {', '.join(rules.COST_GRADES)}.")
    merchant_id = _slug(merchant)
    if not merchant_id:
        raise PlayError("A merchant needs a name.", hint="Name it with a short slug, such as 'ostler'.")
    with ctx.storage.transaction():
        kept = ctx.storage.merchants.get(ctx.campaign_id, merchant_id)
        if kept is not None and not restock:
            return _view(ctx, kept)
        npc_id = get(ctx, npc).id if npc else (kept.npc_id if kept is not None else None)
        stock = (kept.seed if kept is not None else 0) + 1
        catalogue = ctx.ruleset.merchant_catalogue() if ctx.ruleset is not None else ()
        if not catalogue:
            raise PlayError("The ruleset has no magic-item catalogue.", hint="Play a campaign whose ruleset has one.")
        shelf = rules.roll_shelf(ctx.dice, catalogue, settlement, cost, target=f"{merchant_id}#{stock}")
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        rolled = Merchant(
            campaign_id=ctx.campaign_id,
            id=merchant_id,
            name=name or (kept.name if kept is not None else merchant.strip()),
            npc_id=npc_id,
            settlement=settlement,
            cost=cost,
            seed=stock,
            rolled_day=state.day if state is not None else 1,
            items=tuple(shelf),
            sold=kept.sold if kept is not None else (),
        )
        ctx.storage.merchants.put(rolled)
        ctx.log(
            "merchant_stock",
            merchant=merchant_id,
            settlement=settlement,
            cost=cost,
            items=[item["name"] for item in shelf],
            notes=f"{rolled.name}: {len(shelf)} item(s) stocked",
        )
    return _view(ctx, rolled)


def _find_item(merchant: Merchant, item: str) -> int:
    """The shelf's index of `item`: its index, or its exact name ignoring case."""
    wanted = str(item).strip()
    if wanted.isdigit() and int(wanted) < len(merchant.items):
        return int(wanted)
    for i, entry in enumerate(merchant.items):
        if entry["name"].casefold() == wanted.casefold():
            return i
    raise NotFound(
        f"'{item}' is not on {merchant.name}'s shelf.",
        [{"index": i, "name": entry["name"]} for i, entry in enumerate(merchant.items)],
        hint="Name an item of the shelf exactly, or give its index.",
    )


def buy_magic_item(
    ctx: CampaignContext, merchant: str, item: str, character: str, price_gp: float = 0
) -> dict[str, Any]:
    """Buy one item off a merchant's shelf for `character`, at the listed price or the haggled `price_gp`, paid from
    the party's coin. Refused when the party is short."""
    merchant_id = _slug(merchant)
    with ctx.storage.transaction():
        kept = ctx.storage.merchants.get(ctx.campaign_id, merchant_id)
        if kept is None:
            raise PlayError(f"No merchant '{merchant_id}'.", hint="Roll a shelf with magic_merchant first.")
        at = _find_item(kept, item)
        buyer = get(ctx, character)
        entry = kept.items[at]
        paid = price_gp if price_gp > 0 else entry["price_gp"]
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        purse = rules.spend(state.coin, paid)
        if purse is None:
            raise PlayError(
                f"The party has {_gp(rules.purse_gp(state.coin))} gp; the price is {_gp(paid)} gp.",
                hint="Haggle (price_gp), or the party gathers more coin first.",
            )
        ctx.storage.campaign_states.put(replace(state, coin=purse))
        sale = {"name": entry["name"], "to": buyer.id, "price_gp": paid, "day": state.day}
        ctx.storage.merchants.put(
            replace(kept, items=(*kept.items[:at], *kept.items[at + 1 :]), sold=(*kept.sold, sale))
        )
        notes = f"{entry['item_type']}, bought from {kept.name} for {_gp(paid)} gp"
        items, _ = with_item(ctx, buyer.state.inventory, Item(entry["name"], 1, notes=notes))
        ctx.storage.characters.save_state(replace(buyer, state=replace(buyer.state, inventory=items)))
        ctx.log(
            "purchase",
            merchant=merchant_id,
            item=entry["name"],
            character_id=buyer.id,
            price_gp=paid,
            notes=f"{buyer.name} bought {entry['name']} from {kept.name} for {_gp(paid)} gp",
        )
    return {
        "bought": entry["name"],
        "by": buyer.name,
        "character_id": buyer.id,
        "price_gp": paid,
        "listed_gp": entry["price_gp"],
        "left_on_shelf": len(kept.items) - 1,
        "coin": purse,
    }
