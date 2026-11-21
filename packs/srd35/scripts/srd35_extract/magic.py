"""The SRD's random magic item tables (DEL-389 part 3), read from the RTFs' `MagicItems*.rtf`: which kind of item a
minor, medium or major roll gives, and each kind's table (armour and shields, weapons, potions, rings, rods, scrolls,
staffs, wands, wondrous items, the specific items and the special abilities). The RTFs are untrusted input: they are
only read as text.

Each row is `{"from": 1, "to": 4, "item": …, "name": …}`: `name` the table's words, `item` the `items.json`,
`spells.json` or `weapons.json` id they name (`ref` says which; the words when none), `bonus` a "+2" the words carry,
`price` the table's market price, `roll` the table a row sends the roll on to, `sub` a row's own d% table.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from srd35_extract.rtf import _read, _superscripts, lines

FILES = ("MagicItemsI.rtf", "MagicItemsII.rtf", "MagicItemsIII.rtf", "MagicItemsIV.rtf", "MagicItemsV.rtf")
GRADES = ("minor", "medium", "major")

TABLES: dict[str, tuple[str, str]] = {
    "generation": ("Random Magic Item Generation", ""),
    "armor": ("Armor and Shields", ""),
    "armor_types": ("Random Armor Type", "items:armor"),
    "shield_types": ("Random Shield Type", "items:armor"),
    "armor_abilities": ("Armor Special Abilities", "items:armor"),
    "shield_abilities": ("Shield Special Abilities", "items:armor"),
    "specific_armors": ("Specific Armors", "items:armor"),
    "specific_shields": ("Specific Shields", "items:armor"),
    "weapons": ("Weapons", ""),
    "weapon_types": ("Weapon Type Determination", ""),
    "common_melee": ("Common Melee Weapons", "weapons"),
    "uncommon_weapons": ("Uncommon Weapons", "weapons"),
    "common_ranged": ("Common Ranged Weapons", "weapons"),
    "melee_abilities": ("Melee Weapon Special Abilities", "items:weapon"),
    "ranged_abilities": ("Ranged Weapon Special Abilities", "items:weapon"),
    "specific_weapons": ("Specific Weapons", "items:weapon"),
    "potions": ("Potions and Oils", "spells"),
    "rings": ("Rings", "items:ring"),
    "rods": ("Rods", "items:rod"),
    "scroll_types": ("Scroll Types", ""),
    "scroll_levels": ("Scroll Spell Levels", ""),
    "staffs": ("Staffs", "items:staff"),
    "wands": ("Wands", "spells"),
    "minor_wondrous": ("Minor Wondrous Items", "items:wondrous"),
    "medium_wondrous": ("Medium Wondrous Items", "items:wondrous"),
    "major_wondrous": ("Major Wondrous Items", "items:wondrous"),
}
"""Each table's key in `magic_tables.json`: its title in the RTFs and what its rows name."""

ROLLS = {
    "armor and shields": "armor", "weapons": "weapons", "potions": "potions", "rings": "rings", "rods": "rods",
    "scrolls": "scrolls", "staffs": "staffs", "wands": "wands", "wondrous items": "wondrous",
    "specific armor": "specific_armors", "specific shield": "specific_shields", "specific weapon": "specific_weapons",
    "special ability and roll again": "ability", "roll twice again": "twice", "roll again twice": "twice",
    "common melee weapon": "common_melee", "uncommon weapon": "uncommon_weapons",
    "common ranged weapon": "common_ranged",
}  # fmt: skip
"""The rows that send the roll on, to another table or again on this one."""

_RANGE = re.compile(r"^(\d{1,3})(?:[–-](\d{1,3}))?$")
_NONE = ("—", "-", "–")
_ENHANCED = re.compile(r"^\+(\d+)(?: (armor|shield))?$")
_BONUS = re.compile(r"\s\+(\d+)(?=\s*(?:\(|$))")
_LEVEL = re.compile(r"^(\d)(?:st|nd|rd|th)?-Level (Arcane|Divine) Spells$")
_SCROLL_COUNT = re.compile(r"^(Minor|Medium|Major) scroll\t(\d+d\d+) spells$")
_CHOICE = re.compile(r"chaos/evil/good/law|\(alignment\)")
"""A spell the scroll or potion leaves to a choice ("protection from chaos/evil/good/law"): it names no one spell."""
_FIRST = ("greater", "lesser", "mass", "improved", "minor", "major")
FALLBACK = {"items:weapon": ("items:armor",), "items:armor": ("items:weapon",), "items:wondrous": ("items:artifact",)}


def _span(cell: str) -> tuple[int, int] | None:
    found = _RANGE.match(cell)
    if not found:
        return None
    low = int(found.group(1)) or 100
    return low, int(found.group(2) or found.group(1)) or 100


def _is_range(cell: str) -> bool:
    return cell in _NONE or _span(cell) is not None


def normal(name: str) -> str:
    """A name compared without case, punctuation or the curly quote: "Shield, light, wooden" is "shield light wooden"."""
    name = name.lower().replace("’", "'").replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9+ ]+", " ", name).split())


class Names:
    """What a row's words can name: `items.json` by item type, `spells.json`, `weapons.json`."""

    def __init__(self, items: list[dict[str, Any]], spells: list[dict[str, Any]], weapons: list[dict[str, Any]]):
        self.by: dict[str, dict[str, str]] = {"spells": {}, "weapons": {}}
        for item in items:
            self.by.setdefault(f"items:{item['item_type']}", {})[normal(item["name"])] = item["id"]
        for spell in spells:
            self.by["spells"][normal(spell["name"])] = spell["id"]
        for weapon in weapons:
            self.by["weapons"][normal(weapon["name"])] = weapon["id"]

    def find(self, ref: str, words: str) -> str | None:
        """The id `words` name in `ref`'s names (or, for a weapon's or armour's special ability, the other's, which
        `items.json` files once: "Ghost Touch"; for a wondrous item, an artifact's): as they are, with a leading
        "greater"/"lesser"… after the rest (the spells' "Magic Fang, Greater"), without a parenthesis ("Shuriken (5)",
        "Fireball (8th)") or a trailing qualifier (", heightened"), in the singular ("Ioun Stones"), or as the longest
        name they begin with ("Bag of holding type III")."""
        for kind in (ref, *FALLBACK.get(ref, ())):
            found = self._find(self.by.get(kind, {}), words)
            if found:
                return found
        return None

    @staticmethod
    def _find(names: dict[str, str], words: str) -> str | None:
        if not names:
            return None
        key, bare = normal(words), normal(re.sub(r"\([^)]*\)", "", words))
        tries = [key, bare, normal(words.rsplit(",", 1)[0])]
        tries += [f"{rest} {first}" for first, _, rest in (t.partition(" ") for t in (key, bare)) if first in _FIRST]
        forms = {}
        for name, found in names.items():
            for form in (name, normal(re.sub(r"\([^)]*\)", "", name)), _singular(name)):
                forms.setdefault(form, found)
        for attempt in tries:
            for form in (attempt, _singular(attempt)):
                if form in forms:
                    return forms[form]
        begun = [form for form in forms if f"{bare} ".startswith(f"{form} ") and form != bare]
        if begun:
            return forms[max(begun, key=len)]
        longer = {forms[form] for form in forms if form.startswith(bare + " ")}
        return longer.pop() if len(longer) == 1 else None


def _singular(name: str) -> str:
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in name.split())


def _row(low: int, high: int, words: str, price: str, ref: str, names: Names) -> dict[str, Any]:
    row: dict[str, Any] = {"from": low, "to": high, "name": words, "item": words}
    if price:
        row["price"] = price
    plain = words.lower().rstrip(":")
    plain = plain.rstrip("0123456789") if plain.rstrip("0123456789") in ROLLS else plain  # a footnote mark kept
    enhanced = _ENHANCED.match(words)
    if plain in ROLLS:
        row["roll"] = ROLLS[plain]
    elif plain.startswith("ammunition"):
        row["roll"] = "sub"
    elif enhanced:
        row["bonus"] = int(enhanced.group(1))
        row["item"] = enhanced.group(2) or ""
    elif ref and not _CHOICE.search(words):
        bonus = _BONUS.search(words)
        if bonus:
            row["bonus"] = int(bonus.group(1))
        found = names.find(ref, _BONUS.sub("", words))
        if found:
            row["item"], row["ref"] = found, ref.split(":")[0]
    return row


def _graded(header: list[str]) -> list[str]:
    return [cell.lower() for cell in header if cell.lower() in GRADES]


def table(rows: list[str], title: str, ref: str, names: Names) -> dict[str, list[dict[str, Any]]] | list[dict[str, Any]]:
    """The rows of "Table: <title>": by grade for a table with Minor/Medium/Major columns, else one d% list, a row that
    starts again at 01 after another (the ranged weapons' "Ammunition (roll again):") holding them as its `sub`."""
    start = rows.index(f"Table: {title}")
    header = rows[start + 1].split("\t")
    grades = _graded(header)
    by_grade: dict[str, list[dict[str, Any]]] = {grade: [] for grade in grades}
    flat: list[dict[str, Any]] = []
    for line in rows[start + 2 :]:
        cells = line.split("\t")
        columns = len(grades) or 1
        if len(cells) < columns + 1 or not all(_is_range(cell) for cell in cells[:columns]):
            break
        words = cells[columns].strip()
        price = cells[columns + 1].strip() if len(cells) > columns + 1 else ""
        if grades:
            for grade, cell in zip(grades, cells[:columns], strict=True):
                span = _span(cell)
                if span:
                    by_grade[grade].append(_row(*span, words, price, ref, names))
            continue
        span = _span(cells[0])
        if span is None:
            continue
        row = _row(*span, words, price, ref, names)
        if flat and span[0] == 1 and flat[-1].get("roll") == "sub":
            flat[-1].setdefault("sub", []).append(row)
        elif flat and flat[-1].get("sub") and flat[-1]["sub"][-1]["to"] < 100:
            flat[-1]["sub"].append(row)
        else:
            flat.append(row)
    return by_grade if grades else flat


def scroll_spells(rows: list[str], names: Names) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """The arcane and divine spell scrolls by spell level: `{"arcane": {"0": [rows], "1": …}, "divine": …}`."""
    found: dict[str, dict[str, list[dict[str, Any]]]] = {"arcane": {}, "divine": {}}
    current: list[dict[str, Any]] | None = None
    start = rows.index("Table: Arcane Spell Scrolls")
    for line in rows[start + 1 :]:
        if line.startswith("Table: ") and line != "Table: Divine Spell Scrolls":
            break
        level = _LEVEL.match(line)
        if level:
            current = found[level.group(2).lower()].setdefault(level.group(1), [])
            continue
        cells = line.split("\t")
        span = _span(cells[0])
        if current is None or span is None or len(cells) < 2:
            continue
        current.append(_row(*span, cells[1].strip(), cells[2].strip() if len(cells) > 2 else "", "spells", names))
    return found


def scroll_counts(rows: list[str]) -> dict[str, str]:
    """Table: Number of Spells on a Scroll: the dice of spells by grade."""
    return {m.group(1).lower(): m.group(2) for m in map(_SCROLL_COUNT.match, rows) if m}


def magic_tables(rtf_dir: Path, names: Names) -> dict[str, Any]:
    """Every table `TABLES` names, the scrolls' spells and counts, from the RTFs in `rtf_dir`."""
    rows = [line for name in FILES for line in lines(_superscripts(_read(rtf_dir / name), ""))]
    found: dict[str, Any] = {key: table(rows, title, ref, names) for key, (title, ref) in TABLES.items()}
    found["wondrous"] = {grade: found.pop(f"{grade}_wondrous") for grade in GRADES}
    found["scroll_spells"] = scroll_spells(rows, names)
    found["scroll_counts"] = scroll_counts(rows)
    return found


def unresolved(tables: dict[str, Any]) -> list[str]:
    """The words of the rows that should name an entry and don't, as `table: words`, sorted and once each."""
    out: set[str] = set()

    def walk(key: str, value: Any) -> None:
        if isinstance(value, dict) and "from" in value:
            ref = TABLES.get(key, ("", "spells" if key.startswith("scroll_spells") else ""))[1]
            if ref and "roll" not in value and "ref" not in value and value["item"]:
                out.add(f"{key}: {value['name']}")
            for sub in value.get("sub", []):
                walk(key, sub)
        elif isinstance(value, dict):
            for inner in value.values():
                walk(key, inner)
        elif isinstance(value, list):
            for inner in value:
                walk(key, inner)

    for key, value in tables.items():
        walk(key if key != "wondrous" else "minor_wondrous", value)
    return sorted(out)
