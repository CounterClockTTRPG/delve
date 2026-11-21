"""Make the SRD 3.5 pack's table of magic items' numbers, `data/item_effects.json` (DEL-389 part 3).

    python -I packs/srd35/scripts/extract_item_effects.py DATA_DIR

DATA_DIR holds `items.json` (packs/srd35/src/delve_srd35/data); `item_effects.json` is written beside it, the same
bytes for the same input. It maps an `items.json` id to the numbers the engine applies:

- the worn items of `srd35_extract/item_effects_hand.json` (`worn`): their bonus type and what it adds to, by hand;
  their bonuses read from the item's text ("+1 to +5", the price's "(+2)", "(+4)", "(+6)", or "a +2 enhancement
  bonus"), and the hand's type checked against the text's words for it ("deflection bonus", "natural armor" ...);
- each armour and shield of the armour table (an `armor` item with no text): its enhancement, +1 to +5, and `weapon`
  for any weapon of `weapons.json`;
- each weapon and armour special ability (a `weapon` or `armor` item priced "+N bonus" or "+N gp"): its bonus
  equivalent (`price`), and from its text an energy's dice on a hit ("an extra 1d6 points of fire damage on a
  successful hit"), a burst's on a critical hit by the multiplier (x2, x3, x4), the alignment it gives ("makes the
  weapon good-aligned"), the dice against an alignment ("an extra 2d6 points of damage against all of evil
  alignment") and a doubled threat range (keen).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HAND = Path(__file__).resolve().parent / "srd35_extract" / "item_effects_hand.json"
SHIELDS = ("shield-", "buckler")
ALIGNED = {"good": "good", "evil": "evil", "law": "lawful", "chaos": "chaotic"}
_RANGE = re.compile(r"\+(\d+) to \+(\d+)")
_PRICED = re.compile(r"\((?:ring )?\+(\d+)\)")
_FIXED = re.compile(r"\+(\d+) enhancement bonus")
_PRICE = re.compile(r"^\+(\d+)(?: bonus)?$")
_ENERGY = re.compile(r"extra (\d+d\d+) points of (\w+) damage on a successful hit")
_BURST = re.compile(r"extra (\d+d10) points of (\w+) damage on a successful critical hit\. If the weapon's critical "
                    r"multiplier is x3, add an extra (\d+d10) points of \w+ damage instead, and if the multiplier is "
                    r"x4, add an extra (\d+d10)")  # fmt: skip
_AS = re.compile(r"functions as an? (\w+) weapon")
_ALIGNED = re.compile(r"makes the weapon (\w+)-aligned")
_AGAINST = re.compile(r"extra (\d+d\d+) points of damage against all of (\w+) alignment")
_NO_SKILL_POINTS = "does not earn the wearer extra skill points"


def bonuses(text: str) -> list[int]:
    """The bonuses an item comes in, read from its text: a range ("+1 to +5"), else the price's "(+2)" ..., else the
    one "+2 enhancement bonus"."""
    if found := _RANGE.search(text):
        return list(range(int(found.group(1)), int(found.group(2)) + 1))
    if priced := sorted({int(n) for n in _PRICED.findall(text)}):
        return priced
    if fixed := _FIXED.search(text):
        return [int(fixed.group(1))]
    return []


def worn(items: dict[str, dict[str, Any]], hand: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The hand's worn items with their bonuses from the text, and a problem for each the text doesn't bear out."""
    out, problems = {}, []
    for id, row in hand["worn"].items():
        item = items.get(id)
        if item is None:
            problems.append(f"{id}: no such item")
            continue
        text = item["text"]
        found = bonuses(text)
        if not found:
            problems.append(f"{id}: no bonus in its text")
        if hand["words"][row["type"]] not in text:
            problems.append(f"{id}: its text has no '{hand['words'][row['type']]}'")
        if (ability := hand["abilities"].get(row["target"])) and ability not in text:
            problems.append(f"{id}: its text doesn't name {ability}")
        entry = {"type": row["type"], "target": row["target"], "by_bonus": len(found) > 1, "bonuses": found}
        if _NO_SKILL_POINTS in text:
            entry["skill_points"] = False
        out[id] = entry
    return out, problems


def _price(item: dict[str, Any]) -> int:
    found = _PRICE.match(item["price"].strip())
    return int(found.group(1)) if found else 0


def ability(item: dict[str, Any], rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A special ability's row: what it is on, its bonus equivalent, and the numbers its text gives."""
    text = item["text"]
    row: dict[str, Any] = {"type": "ability", "on": item["item_type"], "price": _price(item)}
    if found := _ENERGY.search(text):
        row["energy"] = f"{found.group(1)} {found.group(2)}"
    if (base := _AS.search(text)) and "energy" in rows.get(base.group(1), {}):
        row["energy"] = rows[base.group(1)]["energy"]
    if burst := _BURST.search(text):
        row["burst"] = {"kind": burst.group(2), "2": burst.group(1), "3": burst.group(3), "4": burst.group(4)}
    if aligned := _ALIGNED.search(text):
        row["aligned"] = [ALIGNED[aligned.group(1)]]
    if against := _AGAINST.search(text):
        row["against"] = {"dice": against.group(1), "alignment": against.group(2)}
    if "doubles the threat range" in text:
        row["threat"] = "double"
    return row


def effects(items: list[dict[str, Any]], hand: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    by_id = {item["id"]: item for item in items}
    table, problems = worn(by_id, hand)
    most, total = hand["enhancement"]["most"], hand["enhancement"]["total"]
    plus = list(range(1, most + 1))
    table["weapon"] = {"type": "enhancement", "target": "weapon", "by_bonus": True, "bonuses": plus, "total": total}
    abilities: dict[str, dict[str, Any]] = {}
    # The plain abilities first, so a burst finds the energy of the one it "functions as".
    special = [i for i in items if i["item_type"] in ("weapon", "armor") and i["id"] not in hand["extras"]
               and (i["price"].startswith("+") or i["price"].strip() == "Modifier")]  # fmt: skip
    for item in sorted(special, key=lambda i: ("functions as" in i["text"], i["id"])):
        abilities[item["id"]] = ability(item, abilities)
    table.update(abilities)
    for item in items:
        if item["item_type"] == "armor" and not item["text"].strip() and item["id"] not in hand["extras"]:
            target = "shield" if item["id"].startswith(SHIELDS) else "armor"
            table[item["id"]] = {"type": "enhancement", "target": target, "by_bonus": True, "bonuses": plus,
                                 "total": total}  # fmt: skip
    return dict(sorted(table.items())), problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    folder = Path(argv[1])
    items = json.loads((folder / "items.json").read_text(encoding="utf-8"))
    hand = json.loads(HAND.read_text(encoding="utf-8"))
    table, problems = effects(items, hand)
    if problems:
        print("extract_item_effects: " + "; ".join(problems), file=sys.stderr)
        return 1
    text = json.dumps(table, ensure_ascii=False, indent=1)
    (folder / "item_effects.json").write_text(text + "\n", encoding="utf-8")
    print(f"item effects: {len(table)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
