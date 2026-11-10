"""Magic-item merchants: ttrpg2's house rule for buying magic gear (`tools/merchant.py`), adapted from the OSRIC
toolkit's `magic-shop` generator. The rulebooks have no shopping economy for magic: items are treasure, not
merchandise.

- A **settlement** (hamlet to capital, or a travelling `pedlar`) sets how many items are on offer and how rare they
  can be.
- A **cost grade** (cheap to very expensive) is a flat markup on the list value, from ×1 to ×5.
- The **tier** comes from the value: up to 2,500 gp common, up to 7,500 less common, up to 20,000 uncommon, above
  that rare. Rarer items appear only at larger settlements, and are scarce even there.

The catalogue of what a merchant could stock, priced, is the ruleset's (`Ruleset.merchant_catalogue`). Pure: the
shelf is rolled with the campaign's `Dice`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from delve.dice import Dice

__all__ = [
    "COST_GRADES",
    "SETTLEMENTS",
    "TIERS",
    "CatalogueItem",
    "norm",
    "parse_cost",
    "price",
    "purse_gp",
    "roll_shelf",
    "spend",
    "tier",
]

TIERS = ("common", "less_common", "uncommon", "rare")
"""From the commonest; a shelf is sorted rarest first."""
_VALUE_BANDS = ((2500, "common"), (7500, "less_common"), (20000, "uncommon"))


@dataclass(frozen=True)
class Settlement:
    count: str
    """The dice of how many items are on offer; never below 0."""
    weights: dict[str, int]
    """How likely each tier is; a tier not named is never stocked."""


SETTLEMENTS: dict[str, Settlement] = {
    "hamlet": Settlement("1d3-1", {"common": 1}),
    "village": Settlement("1d3", {"common": 7, "less_common": 3}),
    "town": Settlement("1d4+1", {"common": 5, "less_common": 3, "uncommon": 2}),
    "city": Settlement("2d4", {"common": 4, "less_common": 3, "uncommon": 2, "rare": 1}),
    "capital": Settlement("2d6", {"common": 3, "less_common": 3, "uncommon": 2, "rare": 2}),
    # A travelling dealer: a few portable pieces, nothing truly rare.
    "pedlar": Settlement("1d4+2", {"common": 6, "less_common": 3, "uncommon": 1}),
}

COST_GRADES = {"cheap": 1.0, "moderate": 2.0, "expensive": 3.5, "very_expensive": 5.0}

# item_type values of mundane gear, never stocked.
_DENOM_CP = {"pp": 500, "gp": 100, "ep": 50, "sp": 10, "cp": 1}


@dataclass(frozen=True)
class CatalogueItem:
    name: str
    item_type: str
    """The reference's item type ("Ring", "Wondrous Item"), or `armour` and `weapon` for the generic +N ones."""
    value_gp: int
    """The list value, before the merchant's markup."""
    tier: str
    price_source: str
    """Where the value came from: `listed`, `osric` or `estimate (5x XP)`."""


def tier(value_gp: int) -> str:
    for ceiling, name in _VALUE_BANDS:
        if value_gp <= ceiling:
            return name
    return "rare"


def price(value_gp: int, markup: float) -> int:
    """The marked-up price, rounded to a tidy figure for a price list: to 100 from 1,000 gp, to 10 from 100 gp."""
    p = value_gp * markup
    step = 100 if p >= 1000 else (10 if p >= 100 else 1)
    return int(round(p / step) * step)


# --- the catalogue -----------------------------------------------------------------------------------------------


def norm(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"^(potion|oil|ring|wand|rod|staff|scroll) of ", "", s)
    s = re.sub(r"[^a-z0-9+ ]", "", s)
    return " ".join(s.split())


def parse_cost(cost: Any) -> int | None:
    """The first gp figure in a cost ('1,500 gp', '750gp', '3,000'); None for none."""
    if not cost:
        return None
    text = str(cost)
    m = re.search(r"([\d,]+)\s*gp", text, re.IGNORECASE) or re.fullmatch(r"\s*([\d,]+)\s*", text)
    if not m:
        return None
    try:
        v = int(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v or None


# --- the shelf ---------------------------------------------------------------------------------------------------


def roll_shelf(
    dice: Dice, items: Sequence[CatalogueItem], settlement: str, cost: str, *, target: str
) -> list[dict[str, Any]]:
    """Roll a shelf of `items` for a merchant of `settlement` and `cost` grade: the item count, then for each item a
    tier (by the settlement's weights, among the tiers with an item left) and an item of it. Every roll is keyed by
    `target`, so a restock (a new target) rolls fresh. Answers the shelf's entries, `CatalogueItem`s with their
    `price_gp`, rarest and priciest first."""
    town = SETTLEMENTS[settlement]
    markup = COST_GRADES[cost]
    by_tier: dict[str, list[CatalogueItem]] = {}
    for item in items:
        if item.tier in town.weights:
            by_tier.setdefault(item.tier, []).append(item)

    n = max(0, dice.roll(town.count, purpose="merchant stock", target=target).total)
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for i in range(1, n + 1):
        tiers = [t for t in town.weights if any(item.name not in used for item in by_tier.get(t, []))]
        if not tiers:
            break
        drawn = dice.table(sum(town.weights[t] for t in tiers), purpose=f"merchant tier #{i}", target=target).total
        for t in tiers:
            drawn -= town.weights[t]
            if drawn <= 0:
                break
        left = [item for item in by_tier[t] if item.name not in used]
        pick = left[dice.table(len(left), purpose=f"merchant pick #{i}", target=target).total - 1]
        used.add(pick.name)
        chosen.append(
            {
                "name": pick.name,
                "item_type": pick.item_type,
                "value_gp": pick.value_gp,
                "tier": pick.tier,
                "price_source": pick.price_source,
                "price_gp": price(pick.value_gp, markup),
            }
        )
    chosen.sort(key=lambda item: (TIERS.index(item["tier"]), item["price_gp"]), reverse=True)
    return chosen


# --- coin --------------------------------------------------------------------------------------------------------


def purse_gp(coin: Mapping[str, int]) -> float:
    """What a purse is worth in gold pieces."""
    return sum(int(coin.get(d, 0)) * v for d, v in _DENOM_CP.items()) / 100


def spend(coin: Mapping[str, int], gp: float) -> dict[str, int] | None:
    """A new purse with `gp` gold pieces' worth taken out, or None when the purse can't cover it (ttrpg2's
    `stronghold.spend`). Gold goes first, then pp, ep, sp and cp; when whole coins can't make the sum, one larger coin
    is broken and the change comes back in gp, sp and cp."""
    need = round(float(gp) * 100)
    new = {d: int(coin.get(d, 0)) for d in _DENOM_CP}
    if need > sum(new[d] * v for d, v in _DENOM_CP.items()):
        return None
    for d in ("gp", "pp", "ep", "sp", "cp"):
        v = _DENOM_CP[d]
        take = min(new[d], need // v)
        new[d] -= take
        need -= take * v
    if need > 0:
        for d in ("sp", "ep", "gp", "pp"):
            if new[d] > 0 and _DENOM_CP[d] > need:
                new[d] -= 1
                change = _DENOM_CP[d] - need
                for cd in ("gp", "sp", "cp"):
                    q, change = divmod(change, _DENOM_CP[cd])
                    new[cd] += q
                break
    return new
