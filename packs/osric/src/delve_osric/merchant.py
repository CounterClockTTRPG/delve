"""OSRIC's magic-item catalogue for the classic engine's merchants (DEL-306): every item of the Gamemaster Guide's
magic-item tables that prints its gold-piece value, one per distinct name, priced at that value."""

from __future__ import annotations

from functools import cache
from typing import Any

from delve.rules.classic.merchant import CatalogueItem, norm, tier
from delve_osric.data import load, own
from delve_osric.treasure import titled

KINDS = {
    "potions": "potion",
    "rings": "ring",
    "rods_staves_wands": "rod_staff_wand",
    "misc_magic_common": "misc_magic",
    "misc_magic_less_common": "misc_magic",
    "misc_magic_uncommon": "misc_magic",
    "misc_magic_rare": "misc_magic",
    "special_magic_swords": "sword",
    "special_misc_weapons": "misc_weapon",
}
"""The tables a merchant stocks from, and the kind of item each holds."""


def _priced(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    out = []
    for row in rows:
        for entry in row.get("subrolls") or [row]:
            if isinstance(entry.get("value_gp"), int) and entry["value_gp"] > 0:
                out.append((str(entry["result"]).strip(), entry["value_gp"]))
    return out


@cache
def catalogue() -> tuple[CatalogueItem, ...]:
    """Every priced item of the stocked tables, cheapest first within its table."""
    tables = own(load("magic_items"))
    seen: set[str] = set()
    items: list[CatalogueItem] = []
    for table, kind in KINDS.items():
        for name, value in sorted(_priced(tables[table]["rows"]), key=lambda item: item[1]):
            if norm(name) not in seen:
                seen.add(norm(name))
                items.append(CatalogueItem(titled(kind, name), kind, value, tier(value), "osric"))
    return tuple(items)
