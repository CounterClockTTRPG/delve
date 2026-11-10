"""The magic merchant (ttrpg2 `tools/merchant.py`; plan 6 Task 9): a merchant's shelf and buying off it. The shelf is
for the DM only (decision 9): the DM narrates it, and the players' feed shows only the tool's name."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, boolean, params, string, tool
from delve.play import merchant as merchants
from delve.play.context import CampaignContext
from delve.rules.classic.merchant import COST_GRADES, SETTLEMENTS

SPECS: list[ToolSpec] = []

SHELF = ("items", "sold")
"""The DM-only keys of a shelf: what is for sale and what was sold."""


@tool(
    SPECS,
    "magic_merchant",
    params(
        "merchant",
        merchant=string("The merchant's slug, such as 'ostler'; its shelf is kept under it."),
        settlement=string(
            "hamlet | village | town | city | capital | pedlar (a travelling dealer: 1d4+2 items, no rare ones). Sets "
            "how many items are for sale and how rare they can be.",
            enum=list(SETTLEMENTS),
        ),
        cost=string(
            "cheap (x1 list value) | moderate (x2) | expensive (x3.5) | very_expensive (x5).", enum=list(COST_GRADES)
        ),
        name=string("The shop's or dealer's name, as the characters know it."),
        npc=string("The NPC who keeps the shop, by id or exact name."),
        restock=boolean("Roll a new shelf; what was sold stays sold."),
    ),
    mutates=True,
    areas=(),
    dm_only_keys=SHELF,
)
def magic_merchant(
    ctx: CampaignContext,
    merchant: str,
    settlement: str = "pedlar",
    cost: str = "moderate",
    name: str = "",
    npc: str = "",
    restock: bool = False,
) -> dict[str, Any]:
    """A magic-item merchant's shelf: what is for sale, and at what price. A house rule: the rulebooks have no magic shops. The
    first call for a merchant rolls the stock and keeps it; later calls answer the same shelf until restock=true, and
    the items bought with buy_magic_item leave it. The shelf is for you only: describe what the characters see on it.
    Each item's price_source says where its list value came from. Haggling is a reaction roll; the agreed figure goes
    to buy_magic_item(price_gp=)."""
    return merchants.magic_merchant(ctx, merchant, settlement, cost, name, npc, restock)


@tool(
    SPECS,
    "buy_magic_item",
    params(
        "merchant",
        "item",
        "character",
        merchant=string("The merchant's slug, as magic_merchant was called."),
        item=string("The shelf's index of the item, or its exact name."),
        character=string("Who takes it, by id or exact name; it goes into their inventory."),
        price_gp={"type": "number", "minimum": 0, "description": "The haggled price in gp; the listed one by default."},
    ),
    mutates=True,
    areas=("characters",),
)
def buy_magic_item(
    ctx: CampaignContext, merchant: str, item: str, character: str, price_gp: float = 0
) -> dict[str, Any]:
    """Buy one item off a merchant's shelf (see magic_merchant), paid from the party's coin: gold first, and a larger
    coin broken for change. Refused when the party can't cover the price. The item goes into the character's
    inventory, with its notes, and off the shelf."""
    return merchants.buy_magic_item(ctx, merchant, item, character, price_gp)
