"""OSRIC's treasure (DEL-306), the classic engine's `Treasure`: its loot classes (Gamemaster Guide §2.12.1: Hoards 1-9
in a lair, Individuals 1-5 on each creature, Caches 1-12 hidden away), rolled line by line through `Dice`.

A coin, gem or jewellery line with a chance is present on a d100 at or under it (a failed one is reported with its
roll); an Individual's lines are always there. Gems are valued on Table 2.12.4A (a d100 for the class, its dice for
the value, a die over the class's stones for the kind); jewellery on Table 2.12.5A (a d100 for the piece, a d10 for
the material, the material's dice for the value). Magic items are rolled on Table 2.13.1A for their type and on that
type's tables for the item, a row with sub-results rolling a d100 among them.
"""

from __future__ import annotations

import re
from typing import Any

from delve.dice import Dice, Roll
from delve.rules.classic.treasure import COINS, ArtObject, Check, Gem, MagicItem, TreasureResult, TreasureTypeError
from delve_osric.data import load

CODE = re.compile(r"\b(hoard|individual|cache)\s*((?:\d+\s*(?:,|and|or)?\s*)+)", re.IGNORECASE)
FAMILY_LABEL = {"hoard": "lair", "individual": "individual", "cache": "cache"}

MAGIC_TABLES: dict[str, tuple[str, ...]] = {
    "potion": ("potions",),
    "ring": ("rings",),
    "rod_staff_wand": ("rods_staves_wands",),
    "armour_shield": ("armour_shield_type", "armour_shield_properties"),
    "misc_weapon": ("misc_weapons_type", "misc_weapons_properties"),
    "sword": ("sword_type", "sword_properties"),
}
"""The tables of each type of magic item, rolled in turn: the item, then its bonus."""

MISC_RARITY = {
    "common": "misc_magic_common",
    "less common": "misc_magic_less_common",
    "uncommon": "misc_magic_uncommon",
    "rare": "misc_magic_rare",
}


class _Roller:
    """The dice of one hoard: `treasure:<code>.<n>`, the n-th die of it, with the hoard's source as the target."""

    def __init__(self, dice: Dice, code: str, source: str, rolls: list[Roll]) -> None:
        self.dice, self.code, self.source, self.rolls, self.n = dice, code, source, rolls, 0

    def die(self, sides: int) -> int:
        self.n += 1
        roll = self.dice.table(sides, purpose=f"treasure:{self.code}.{self.n}", target=self.source)
        self.rolls.append(roll)
        return roll.total

    def dice_of(self, notation: str) -> int:
        """`NdS` rolled as N dice; a bare number as it is."""
        found = re.fullmatch(r"\s*(\d*)d(\d+)\s*", str(notation))
        if found is None:
            return int(str(notation).strip() or 0)
        return sum(self.die(int(found.group(2))) for _ in range(int(found.group(1) or 1)))


def _die_of(table: dict[str, Any]) -> int:
    return int(str(table.get("_die") or table.get("die") or "d100").lstrip("d"))


def _span(raw: str) -> tuple[int, int]:
    """A printed range ("01–50", "51–00", "7") as numbers; "00" is 100."""
    parts = [int(p) or 100 for p in re.findall(r"\d+", raw)]
    return (parts[0], parts[-1]) if parts else (1, 100)


def _row(r: _Roller, table: dict[str, Any], key: str = "roll") -> dict[str, Any]:
    """The row a roll of the table's die lands on; a row with sub-results rolls a d100 among them."""
    rows = table["rows"]
    face = r.die(_die_of(table))
    row = next((x for x in rows if x[key][0] <= face <= x[key][1]), rows[-1])
    if row.get("subrolls"):
        sub = r.die(100)
        row = next((s for s in row["subrolls"] if _span(s["roll_raw"])[0] <= sub <= _span(s["roll_raw"])[1]), row)
    return row


def _name(row: dict[str, Any]) -> str:
    return re.sub(r"\s*\((?:see|proceed)[^)]*\)\s*$", "", str(row.get("result", "")), flags=re.IGNORECASE).strip()


def titled(kind: str, name: str) -> str:
    """A potion's or a ring's table name as the item's: "Potion of Delusion", "Ring of Feather Falling"; an oil, a
    philter or an elixir keeps its own."""
    if kind == "potion" and not name.lower().startswith(("oil", "philter", "philtre", "elixir", "potion")):
        return f"Potion of {name}"
    if kind == "ring" and not name.lower().startswith("ring"):
        return f"Ring of {name}"
    return name


def magic_item(r: _Roller, kind: str, depth: int = 0) -> list[MagicItem]:
    """The magic items of `kind` ("any", "potion", "sword"…), as Table 2.13.1A and the type's tables roll them."""
    tables = load("magic_items")
    if kind == "any":
        types = load("loot_classes")["magic_item_types"]
        kind = _row(r, types, "d20")["type"]
    if kind in MAGIC_TABLES:
        first, *rest = MAGIC_TABLES[kind]
        item = _name(_row(r, tables[first]))
        bonus = _name(_row(r, tables[rest[0]])) if rest else ""
        if bonus.lower().startswith("cursed"):
            return [MagicItem(kind, f"{item}, cursed")]
        if bonus.lower().startswith("special"):
            special = {"sword": "special_magic_swords", "misc_weapon": "special_misc_weapons"}.get(kind)
            if special is None:
                return [MagicItem(kind, f"{item} of special make (the DM's choice)")]
            return [MagicItem(kind, _name(_row(r, tables[special])))]
        return [MagicItem(kind, titled(kind, f"{item} {bonus}".strip()))]
    if kind == "misc_magic":
        rarity = _name(_row(r, tables["misc_magic_rarity"]))
        if rarity.lower().startswith("roll twice") and depth < 2:
            return magic_item(r, "misc_magic", depth + 1) + magic_item(r, "misc_magic", depth + 1)
        key = next((t for word, t in MISC_RARITY.items() if rarity.lower().endswith(word)), "misc_magic_common")
        return [MagicItem(kind, _name(_row(r, tables[key])))]
    if kind == "scroll":
        what = _name(_row(r, tables["scroll_type"])).lower()
        if what.startswith("spell"):
            return [MagicItem(kind, f"Scroll of {_name(_row(r, tables['spell_scrolls'])).lower()} spells")]
        if what.startswith("protection"):
            return [
                MagicItem(kind, f"Scroll of warding against {_name(_row(r, tables['scrolls_of_warding'])).lower()}")
            ]
        return [MagicItem(kind, "Cursed scroll")]
    return [MagicItem(kind, kind.replace("_", " "))]


def _gem(r: _Roller) -> Gem:
    classes = load("treasure_valuation")["gems"]["classes"]
    face = r.die(100)
    cls = next((c for c in classes if c["d100"][0] <= face <= c["d100"][1]), classes[-1])
    dice = cls["value_dice"]
    value = sum(r.die(dice["sides"]) for _ in range(dice["count"])) * dice.get("multiplier", 1)
    stone = cls["examples"][r.die(len(cls["examples"])) - 1] if cls.get("examples") else cls["class"]
    return Gem(stone, value, cls["class"])


def _jewel(r: _Roller) -> ArtObject:
    jewellery = load("treasure_valuation")["jewellery"]
    face = r.die(100)
    piece = next((i for i in jewellery["items"] if i["d100"][0] <= face <= i["d100"][1]), jewellery["items"][-1])
    band = r.die(10)
    material = next((m for m, b in piece["material_bands"].items() if b["d10"][0] <= band <= b["d10"][1]), "silver")
    found = next(m for m in jewellery["materials"] if m["key"] == material)
    dice = found["value_dice"]
    value = sum(r.die(dice["sides"]) for _ in range(dice["count"])) * dice.get("multiplier", 1)
    return ArtObject(f"{piece['item']} ({found['label'].lower()})", value)


class OsricTreasure:
    """OSRIC's loot classes for the classic engine."""

    lair_name = "a Hoard"
    individual_name = "an Individual or a Cache"
    no_hoard = ("non", "animal", "semi")

    def lair_codes(self, codes: list[str]) -> list[str]:
        return [code for code in codes if code.lower().startswith("hoard")]

    def parse_types(self, spec: str) -> dict[str, Any]:
        """A loot line as the bestiary prints it ("Individual 1, 2, 3, 4 (each); in lair, Hoard 2"), in groups of
        one family: `{"groups": [{"label": "individual", "codes": ["individual 1", …]}, …]}`. "Nil" is none."""
        groups: dict[str, list[str]] = {}
        for family, numbers in CODE.findall(spec or ""):
            for number in re.findall(r"\d+", numbers):
                code = f"{family.lower()} {int(number)}"
                if code in load("loot_classes")["classes"]:
                    groups.setdefault(FAMILY_LABEL[family.lower()], []).append(code)
        return {"groups": [{"label": label, "codes": codes} for label, codes in groups.items()]}

    def generate(self, dice: Dice, types: str, *, source: str | None = None) -> TreasureResult:
        groups = self.parse_types(types)["groups"]
        if not groups and not re.fullmatch(r"\s*(nil|none)?\s*", types or "", re.IGNORECASE):
            raise TreasureTypeError(f"No loot class in '{types}'.")
        if len(groups) > 1:
            raise TreasureTypeError(f"'{types}' holds several groups: roll one.", groups)
        codes = groups[0]["codes"] if groups else []
        target = (source or "").strip() or types.strip()
        coins = dict.fromkeys(COINS, 0)
        gems: list[Gem] = []
        art: list[ArtObject] = []
        magic: list[MagicItem] = []
        checks: list[Check] = []
        rolls: list[Roll] = []
        for code in codes:
            r = _Roller(dice, code.replace(" ", ""), target, rolls)
            for line in load("loot_classes")["classes"][code]["lines"]:
                kind = line["t"]
                column = line.get("coin") or kind
                if line.get("pct") is not None:
                    face = r.die(100)
                    present = face <= line["pct"]
                    checks.append(Check(code, column, line["pct"], face, present))
                    if not present:
                        continue
                if kind == "coin":
                    coins[line["coin"]] += r.dice_of(line["dice"]) * line.get("mult", 1)
                elif kind == "gems":
                    gems += [_gem(r) for _ in range(r.dice_of(line["dice"]) * line.get("mult", 1))]
                elif kind == "jewellery":
                    art += [_jewel(r) for _ in range(r.dice_of(line["dice"]) * line.get("mult", 1))]
                elif kind == "magic":
                    for slot in line["items"]:
                        for _ in range(slot.get("n", 1)):
                            magic += magic_item(r, slot["type"])
                elif kind == "special":
                    magic += [MagicItem("special", line["item"])] * line.get("n", 1)
        return TreasureResult(
            types=tuple(codes),
            coins=coins,
            gems=tuple(gems),
            art=tuple(art),
            magic=tuple(magic),
            checks=tuple(checks),
            rolls=tuple(rolls),
        )


TREASURE = OsricTreasure()
