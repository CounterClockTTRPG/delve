"""Magic items' numbers on a character (DEL-389 part 3), read from the build's `Sheet.d20["items"]` and the pack's
`data/item_effects.json` (made by `scripts/extract_item_effects.py` from `items.json`).

A build's item is `{"id", "kind", "name", "bonus"?, "abilities"?, "material"?}`: `kind` is `worn` (an item of the
effects table: a ring of protection, a cloak of resistance), `weapon` (`id` a `weapons.json` id), `armor` or `shield`
(an armour of `items.json`, "chain-shirt"), or `note` (an item the engine has no numbers for, shown on the sheet for
the DM). Bonuses of one type don't stack: the highest counts (the SRD's Combining Magical Effects); different types
add."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import cache
from typing import Any

from delve.domain.characters import Sheet
from delve_srd35.data import load

MASTERWORK = frozenset({"masterwork", "adamantine", "mithral"})
"""The materials always made masterwork (the SRD's Special Materials: adamantine and mithral "are always masterwork
items as well"); a magic weapon or armour is masterwork too ("All magic weapons are also masterwork weapons")."""
BYPASS_MATERIALS = frozenset({"silver", "cold iron", "adamantine"})
"""The materials a monster's damage reduction names."""
ADAMANTINE_DR = {"light": 1, "medium": 2, "heavy": 3}
"""'Armor made from adamantine grants its wearer damage reduction of 1/— if it's light armor, 2/— if it's medium
armor, and 3/— if it's heavy armor.'"""
LIGHTER = {"heavy": "medium", "medium": "light"}
"""Mithral: "Heavy armors are treated as medium, and medium armors are treated as light"."""


@cache
def effects() -> dict[str, dict[str, Any]]:
    return dict(load("item_effects"))


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


def carried(sheet: Sheet) -> list[dict[str, Any]]:
    """The build's items, each a dict (a stored list with anything else in it reads as none of it)."""
    return [item for item in (sheet.d20 or {}).get("items") or () if isinstance(item, Mapping) and item.get("id")]


def worn_bonus(items: Iterable[Mapping[str, Any]], kind: str, target: str) -> int:
    """The highest bonus of one type (`kind`: deflection, natural, resistance, armor, enhancement) on `target` (ac,
    saves, str ...) among the worn items: they don't stack."""
    table = effects()
    found = [int(item.get("bonus") or 0) for item in items if item.get("kind", "worn") == "worn"
             and (row := table.get(str(item["id"]))) and row["type"] == kind and row["target"] == target]  # fmt: skip
    return max(found, default=0)


def ability_bonus(sheet: Sheet, ability: str) -> int:
    """The enhancement bonus the worn items give the ability score (the highest of them)."""
    return worn_bonus(carried(sheet), "enhancement", ability)


def skill_point_bonus(sheet: Sheet, ability: str) -> int:
    """The part of `ability_bonus` that counts for skill points: none from an item whose row says it doesn't
    (`skill_points` false: the headband of intellect's "This enhancement bonus does not earn the wearer extra skill
    points")."""
    table = effects()
    kept = [item for item in carried(sheet) if table.get(str(item["id"]), {}).get("skill_points", True)]
    return worn_bonus(kept, "enhancement", ability)


def piece(sheet: Sheet, kind: str, key: str) -> Mapping[str, Any] | None:
    """The build's magic weapon, armour or shield (`kind`) whose id is `key` (a `weapons.json` id, an armour slug):
    the one in hand or worn; None for none."""
    return next((item for item in carried(sheet) if item.get("kind") == kind and item["id"] == key), None)


def masterwork(item: Mapping[str, Any] | None) -> bool:
    return bool(item) and (int(item.get("bonus") or 0) > 0 or item.get("material") in MASTERWORK
                           or bool(item.get("masterwork")))  # fmt: skip


def armour_piece(armour: dict[str, Any], item: Mapping[str, Any] | None) -> dict[str, Any]:
    """An `armour_table` row as the build's item makes it: its enhancement adds to its bonus; masterwork (any magic
    armour, "with an armor check penalty 1 less than normal") lessens its check penalty by 1, mithral by 3 with 2 more
    maximum Dex, 10% less spell failure and one category lighter (not a shield's); the check penalty no better than
    0. Adamantine armour's damage reduction is its `dr`."""
    if item is None:
        return armour
    out = dict(armour)
    out["bonus"] = armour["bonus"] + int(item.get("bonus") or 0)
    material = item.get("material")
    better = 3 if material == "mithral" else 1 if masterwork(item) else 0
    out["acp"] = min(0, armour["acp"] + better)
    if material == "mithral":
        out["failure"] = max(0, armour["failure"] - 10)
        if armour["max_dex"] is not None:
            out["max_dex"] = armour["max_dex"] + 2
        out["category"] = LIGHTER.get(armour["category"], armour["category"])
    if material == "adamantine" and armour["category"] in ADAMANTINE_DR:
        out["dr"] = ADAMANTINE_DR[armour["category"]]
    return out


def weapon_abilities(item: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The weapon's special abilities' rows (with their `id`), those the effects table has."""
    table = effects()
    return [{"id": a, **table[a]} for a in (item or {}).get("abilities") or () if a in table]


BURST_BY_MULT = ("2", "3", "4")


def weapon_numbers(item: Mapping[str, Any] | None, name: str, mult: int) -> dict[str, Any]:
    """What the build's magic weapon `item` (or, without one, the weapon's name: "+1 longsword", "cold iron
    longsword") adds to its form: `enhancement` (to hit and damage), `masterwork` (+1 to hit without an enhancement),
    `materials`, `aligned` (holy: good), `plus` (its energies' dice on a hit, "1d6 fire"), `burst` (a burst's on a
    critical hit by the weapon's multiplier, x2 1d10, x3 2d10, x4 3d10), `against` (holy's 2d6 against evil),
    `keen`, `silver` (-1 damage) and `dm` (the abilities the engine has no numbers for, the DM's)."""
    words = name.lower()
    enhancement = int((item or {}).get("bonus") or 0)
    if not item and (found := re.match(r"\s*\+(\d+)\s", words)):
        enhancement = int(found.group(1))
    material = (item or {}).get("material") or next(
        (m for m in ("cold iron", "alchemical silver", "silvered", "silver", "adamantine", "mithral") if m in words),
        None,
    )
    material = "silver" if material in ("alchemical silver", "silvered") else material
    out: dict[str, Any] = {}
    if enhancement:
        out["enhancement"] = enhancement
    elif material in MASTERWORK or (item or {}).get("masterwork") or "masterwork" in words:
        out["masterwork"] = True
    if material in BYPASS_MATERIALS:
        out["materials"] = [material]
    if material == "silver":
        out["silver"] = True  # "the wielder takes a –1 penalty on the damage roll (with the usual minimum of 1)"
    rows = weapon_abilities(item)
    aligned = [a for row in rows for a in row.get("aligned", ())]
    if aligned:
        out["aligned"] = aligned
    if energies := [row["energy"] for row in rows if row.get("energy")]:
        out["plus"] = " and ".join(energies)
    bursts = [f"{row['burst'][str(min(max(mult, 2), 4))]} {row['burst']['kind']}" for row in rows if row.get("burst")]
    if bursts:
        out["burst"] = " and ".join(bursts)
    if against := [{"ability": row["id"], **row["against"]} for row in rows if row.get("against")]:
        out["against"] = against
    if any(row.get("threat") == "double" for row in rows):
        out["keen"] = True
    if dm := [a for a in (item or {}).get("abilities") or () if not _has_numbers(a)]:
        out["dm"] = dm
    return out


def shown(sheet: Sheet, weapon: str, armour: str, shield: str) -> list[dict[str, Any]]:
    """`derived["items"]`: each item of the build with its name and bonus, `in_use` for a magic weapon in hand or
    armour or shield worn (one carried adds nothing), `note` for an item the engine has no numbers for, and `dm` for
    its special abilities without numbers (speed, vorpal: the DM's)."""
    out = []
    for item in carried(sheet):
        kind = item.get("kind", "worn")
        entry: dict[str, Any] = {"id": item["id"], "name": str(item.get("name") or item["id"]), "kind": kind}
        if item.get("bonus"):
            entry["bonus"] = int(item["bonus"])
        if kind == "note":
            entry["note"] = True
        elif kind in ("weapon", "armor", "shield"):
            entry["in_use"] = item["id"] == {"weapon": weapon, "armor": armour, "shield": shield}[kind]
        if dm := [a for a in item.get("abilities") or () if not _has_numbers(a)]:
            entry["dm"] = dm
        out.append(entry)
    return out


NUMBERS = frozenset({"energy", "burst", "aligned", "against", "threat"})
"""The keys of an ability's row the engine applies."""


def _has_numbers(ability: str) -> bool:
    return bool(NUMBERS & set(effects().get(ability, {})))
