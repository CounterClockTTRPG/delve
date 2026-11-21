"""SRD 3.5's treasure (DEL-389 part 3), core's `Treasure`: a hoard by encounter level, from the SRD's tables.

The treasure line carries the level: "EL 5, double standard", "EL 3, half standard", "EL 7, none", or a monster
entry's own line ("Standard coins; double goods; standard items"). Without "EL n" the level is the CR of the monster
the hoard's source names, and the result says so ("CR 3 (Ogre)").

Coins, goods and items are each one d% on the level's row of Table: Treasure (`rules/20-01-…`, read from the pack's
own rules file); "double" rolls a column twice, "1/10 coins" divides the coins, "50% goods" is a d% chance before the
roll (SRD, Treasure ratings). A gem is a d% on Table: Gems, its value dice, and a die over the band's examples; an art
object the same on Table: Art Objects; a mundane item a d% down Table: Mundane Items' nested tables. A magic item is
a d% on Table: Random Magic Item Generation for its grade, then that kind's table in `data/magic_tables.json`
(extracted from the SRD's RTFs by `scripts/extract_rtf.py`), its rows naming `items.json`, `spells.json` or
`weapons.json` entries. Above 20th level the 20th-level row is rolled and random major items added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

from delve.dice import Dice, Roll
from delve.domain.reference import name_key
from delve.rules.classic.treasure import COINS, ArtObject, Check, Gem, MagicItem, TreasureResult, TreasureTypeError
from delve_srd35.data import load

__all__ = ["TREASURE", "Spec", "Srd35Treasure", "parse_spec", "treasure_tables"]

RULES = "20-01-monsters-with-treasure.md"
COLUMNS = ("coins", "goods", "items")
MOST_REROLLS = 20
_DASHES = "–-"
_SPAN = re.compile(rf"^(\d{{1,3}})(?:[{_DASHES}](\d{{1,3}}))?$")
_COIN = re.compile(r"^(\d+)d(\d+) x ([\d,]+) (cp|sp|gp|pp)$")
_COUNT = re.compile(r"^(\d+)(?:d(\d+))? (gems?|art|mundane|minor|medium|major)$")
_VALUE = re.compile(r"^(\d+)d(\d+)(?: x ([\d,]+))? gp$")
_EL = re.compile(r"(?i)\b(?:EL|CR|encounter level|level)\s*(\d+)(?:/(\d+))?\b,?")
_SHARE = re.compile(
    r"(?i)\b(no|standard|double|triple|quadruple|half|1/\d+(?:th)?|\d+%)\s+(coins|goods|items)\b(\s*\([^)]*\))?"
)
_WHOLE = re.compile(r"(?i)^(?:(double|triple|quadruple|half)\s+)?standard\b(\s*\((?!including)[^)]*\))?")
_NONE = re.compile(r"(?i)^(?:none|nil|no treasure)\b")
_INCLUDING = re.compile(r"(?i)\(including ([^)]*)\)")
_PLUS = re.compile(r"(?i)(?:\bplus\b|\band\b(?=\s*\+))\s*(.+)$")
TIMES = {"no": 0, "standard": 1, "double": 2, "triple": 3, "quadruple": 4}


def _span(cell: str) -> tuple[int, int] | None:
    found = _SPAN.match(cell.strip())
    if not found:
        return None
    return int(found.group(1)) or 100, int(found.group(2) or found.group(1)) or 100


# The tables of the rules file


def _pipe_rows(text: str, title: str) -> list[list[str]]:
    """The body rows of the pipe table under "**Table: <title>**", each as its cells."""
    lines = text.splitlines()
    start = lines.index(f"**Table: {title}**")
    rows: list[list[str]] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            if rows:
                break
            continue
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("- "):
            continue  # the header's rule
        rows.append(cells)
    return rows[1:]  # without the header


def _treasure_rows(text: str) -> dict[int, dict[str, list[dict[str, Any]]]]:
    """Table: Treasure by level: each column's d% bands. The conversion closes up a column's empty cells, so a band
    sits in the column whose next band starts where it does, the one it is printed under first (the 6th level's
    "100 | 1 medium" is printed under Goods and is an Items band)."""
    levels: dict[int, dict[str, list[dict[str, Any]]]] = {}
    current: dict[str, list[dict[str, Any]]] = {}
    for cells in _pipe_rows(text, "Treasure"):
        if cells[0]:
            current = levels.setdefault(int(re.sub(r"\D", "", cells[0])), {column: [] for column in COLUMNS})
        for position in range(3):
            band, value = cells[1 + 2 * position], cells[2 + 2 * position]
            span = _span(band) if band else None
            if span is None:
                continue
            nexts = {c: (current[c][-1]["to"] + 1 if current[c] else 1) for c in COLUMNS}
            fits = [COLUMNS[position]] if nexts[COLUMNS[position]] == span[0] else []
            fits += [c for c in COLUMNS if nexts[c] == span[0]]
            if not fits:
                raise ValueError(f"Table: Treasure: no column for {band} {value}")
            current[fits[0]].append({"from": span[0], "to": span[1], "value": value})
    return levels


def _valued(text: str, title: str) -> list[dict[str, Any]]:
    """Table: Gems or Table: Art Objects: d% bands, each with its value dice, average and examples."""
    rows = []
    for band, value, average, examples in _pipe_rows(text, title):
        span = _span(band)
        if span is None:
            raise ValueError(f"Table: {title}: {band!r}")
        rows.append({"from": span[0], "to": span[1], "value": value, "average": average,
                     "examples": [e.strip() for e in examples.split(";") if e.strip()]})  # fmt: skip
    return rows


def _nested(text: str) -> list[dict[str, Any]]:
    """Table: Mundane Items, whose subtables the conversion prints in line under their row: a band that starts at 01
    after another opens the subtable of the row before it; a band that starts where an outer table's next band does
    closes the subtables down to that table."""
    top: list[dict[str, Any]] = []
    stack: list[list[dict[str, Any]]] = [top]
    for band, words in _pipe_rows(text, "Mundane Items"):
        span = _span(band)
        if span is None:
            raise ValueError(f"Table: Mundane Items: {band!r}")
        row = {"from": span[0], "to": span[1], "item": words}
        if span[0] == 1 and stack[-1]:
            sub: list[dict[str, Any]] = []
            stack[-1][-1]["sub"] = sub
            stack.append(sub)
        else:
            while len(stack) > 1 and (not stack[-1] or stack[-1][-1]["to"] + 1 != span[0]):
                stack.pop()
        stack[-1].append(row)
    return top


@cache
def treasure_tables() -> dict[str, Any]:
    """The rules file's tables: `levels` (Table: Treasure), `above` (the major items added above 20th level), `gems`,
    `art` and `mundane`."""
    text = resources.files("delve_srd35").joinpath("rules", RULES).read_text("utf-8")
    after = text[text.index("For treasures above 20th level") :]
    above = {int(level): int(more) for level, more in re.findall(r"\| (\d+)(?:st|nd|rd|th) \| \+(\d+) ", after)}
    return {
        "levels": _treasure_rows(text),
        "above": above,
        "gems": _valued(text, "Gems"),
        "art": _valued(text, "Art Objects"),
        "mundane": _nested(text),
    }


# The treasure line


@dataclass(frozen=True)
class Share:
    """How much of one column a creature has: `times` rolls, each after a `chance` d% when given, the coins
    divided by `divide`."""

    times: int = 1
    chance: int | None = None
    divide: int = 1
    note: str = ""


@dataclass(frozen=True)
class Spec:
    level: int | None
    shares: dict[str, Share] = field(default_factory=dict)
    extras: tuple[str, ...] = ()
    said: str = ""
    """A fraction's words ("CR 1/2"), read as the 1st level."""


def _share(word: str, column: str, note: str = "") -> Share:
    word = word.lower()
    if word in TIMES:
        return Share(TIMES[word], note=note)
    if word == "half":
        return Share(divide=2, note=note) if column == "coins" else Share(chance=50, note=note)
    if word.endswith("%"):
        return Share(chance=int(word[:-1]), note=note)
    divide = int(re.sub(r"\D", "", word.split("/")[1]))
    return Share(divide=divide, note=note) if column == "coins" else Share(chance=100 // divide, note=note)


def parse_spec(spec: str) -> Spec | None:
    """The line as a `Spec`, or None when it holds no treasure rating. "EL 5, double standard", "standard" (no
    level: the source's CR), "EL 7, none", "No coins; 50% goods; 50% items", "Standard, plus rope and +1 flaming
    composite longbow": the named things come back as `extras`."""
    text = " ".join((spec or "").split())
    level_found = _EL.search(text)
    level = int(level_found.group(1)) if level_found else None
    said = ""
    if level_found and level_found.group(2):  # "CR 1/2": a CR below 1 is the 1st level, as a monster's
        level, said = max(1, level // int(level_found.group(2))), level_found.group(0).strip(" ,")
    rest = _EL.sub("", text, count=1).strip(" ,;:") if level_found else text
    if not rest:
        return Spec(level, {column: Share() for column in COLUMNS}, said=said)
    if _NONE.match(rest):
        return Spec(level, {column: Share(0) for column in COLUMNS}, said=said)
    extra = _INCLUDING.search(rest) or _PLUS.search(rest)
    extras = tuple(e.strip() for e in re.split(r",? and |, ", extra.group(1)) if e.strip()) if extra else ()
    whole = _WHOLE.match(rest)
    if whole and not _SHARE.match(rest):
        word = (whole.group(1) or "standard").lower()
        note = (whole.group(2) or "").strip()
        if word == "half":
            shares = {"coins": Share(divide=2, note=note), "goods": Share(chance=50, note=note),
                      "items": Share(chance=50, note=note)}  # fmt: skip
        else:
            shares = {column: Share(TIMES[word], note=note) for column in COLUMNS}
        return Spec(level, shares, extras, said)
    found = {m.group(2).lower(): _share(m.group(1), m.group(2).lower(), (m.group(3) or "").strip())
             for m in _SHARE.finditer(rest)}  # fmt: skip
    if not found:
        return None
    return Spec(level, {column: found.get(column, Share(0)) for column in COLUMNS}, extras, said)


# Rolling


class _Roller:
    """The dice of one hoard: `treasure:<code>.<n>`, the n-th die of it, with the hoard's source as the target."""

    def __init__(self, dice: Dice, code: str, source: str) -> None:
        self.dice, self.code, self.source, self.n = dice, code, source, 0
        self.rolls: list[Roll] = []

    def die(self, sides: int) -> int:
        self.n += 1
        roll = self.dice.table(sides, purpose=f"treasure:{self.code}.{self.n}", target=self.source)
        self.rolls.append(roll)
        return roll.total

    def dice_of(self, count: int, sides: int) -> int:
        return sum(self.die(sides) for _ in range(count))

    def band(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """The row a d% lands on: the first that holds it (the SRD's tables overlap in two places, Table: Rings'
        medium 47–51/50–56 and Table: Scroll Spell Levels' major 86–95/95–100; the first row printed wins)."""
        face = self.die(100)
        return next((r for r in rows if r["from"] <= face <= r["to"]), rows[-1])


def _number(text: str) -> int:
    return int(text.replace(",", ""))


def _first_lower(words: str) -> str:
    return words[:1].lower() + words[1:] if words[1:2].islower() or len(words) == 1 else words


def plain_name(words: str) -> str:
    """A table's "Sword, bastard" as one says it, "bastard sword"; "Shield, heavy, steel" "heavy steel shield",
    "Longbow, composite (+1 Str bonus)" "composite longbow (+1 Str bonus)"."""
    found = re.match(r"^([^(]*?)(\s*\(.*\))?$", words)
    head, tail = (found.group(1), found.group(2) or "") if found else (words, "")
    parts = head.split(", ")
    return (" ".join([*parts[1:], parts[0]]) if len(parts) > 1 else head).lower() + tail


def _gem(r: _Roller) -> Gem:
    band = r.band(treasure_tables()["gems"])
    count, sides, times = _VALUE.match(band["value"]).groups()  # type: ignore[union-attr]
    value = r.dice_of(int(count), int(sides)) * _number(times or "1")
    example = band["examples"][r.die(len(band["examples"])) - 1]
    return Gem(_first_lower(example), value, f"{band['average']} gem")


def _art(r: _Roller) -> ArtObject:
    band = r.band(treasure_tables()["art"])
    count, sides, times = _VALUE.match(band["value"]).groups()  # type: ignore[union-attr]
    value = r.dice_of(int(count), int(sides)) * _number(times or "1")
    return ArtObject(_first_lower(band["examples"][r.die(len(band["examples"])) - 1]), value)


_QUANTITY = re.compile(r"^(.*?) \((\d+)d(\d+) (\w+), ([\d,]+ gp) each\)$")
_SIZE = re.compile(r"\(roll d%: 01–(\d+) = Small, \d+–100 = Medium\)")
_MASTERWORK = {"masterwork common melee weapon": "common_melee", "masterwork uncommon weapon": "uncommon_weapons",
               "masterwork common ranged weapon": "common_ranged"}  # fmt: skip


def _mundane(r: _Roller) -> MagicItem:
    """A d% down Table: Mundane Items to a leaf: "Alchemist's fire (3 flasks, 20 gp each)", "Chain shirt (Small,
    100 gp)", a masterwork weapon by the magic weapons' type tables ("Masterwork longsword")."""
    rows, size, words, path = treasure_tables()["mundane"], "", "", []
    while True:
        row = r.band(rows)
        words = row["item"]
        small = _SIZE.search(words)
        if small:
            size = "Small" if r.die(100) <= int(small.group(1)) else "Medium"
        if not row.get("sub"):
            break
        path.append(words)
        rows = row["sub"]
    if len(path) > 1:  # Darkwood or Masterwork shield: "Darkwood buckler (205 gp)"
        words = f"{path[-1].split()[0]} {_first_lower(words)}"
    quantity = _QUANTITY.match(words)
    if quantity:
        name, count, sides, unit, each = quantity.groups()
        n = r.dice_of(int(count), int(sides))
        words = f"{name} ({n} {unit if n != 1 else unit.rstrip('s')}, {each} each)"
    elif words.lower() in _MASTERWORK:
        weapon = _weapon_row(r, _MASTERWORK[words.lower()])
        words = f"Masterwork {plain_name(weapon['name'])}"
    elif size:
        words = re.sub(r"\((.*)\)$", rf"({size}, \1)", words) if words.endswith(")") else f"{words} ({size})"
    return MagicItem("mundane", words)


# Magic items


@cache
def magic_tables() -> dict[str, Any]:
    return load("magic_tables")


@cache
def _effects() -> dict[str, dict[str, Any]]:
    return dict(load("item_effects"))


@cache
def _weapons() -> dict[str, dict[str, Any]]:
    return {w["id"]: w for w in load("weapons")}


def _weapon_row(r: _Roller, table: str) -> dict[str, Any]:
    row = r.band(magic_tables()[table])
    return r.band(row["sub"]) if row.get("sub") else row


def _ability_fits(ability: dict[str, Any], weapon: dict[str, Any] | None) -> bool:
    """Table: Melee Weapon Special Abilities' footnotes: keen and vorpal only on a piercing or slashing weapon,
    disruption only on a bludgeoning one."""
    kind = (weapon or {}).get("type", "").lower()
    if not kind:
        return True
    name = ability["name"].lower().rstrip("0123456789")
    if name in ("keen", "vorpal"):
        return "piercing" in kind or "slashing" in kind
    if name == "disruption":
        return "bludgeoning" in kind
    return True


MOST_TOTAL = 10
"""A weapon's or armour's enhancement and special ability bonus equivalents "can't total more than +10"."""
OPPOSED = ({"good", "evil"}, {"lawful", "chaotic"})


def _incompatible(row: dict[str, Any], chosen: list[dict[str, Any]]) -> bool:
    """An ability incompatible with one already rolled: the opposite alignment (holy and unholy, axiomatic and
    anarchic), or a burst and the energy it "functions as" (flaming and flaming burst)."""
    effects = _effects()
    mine = effects.get(str(row.get("item")), {})
    for other in chosen:
        theirs = effects.get(str(other.get("item")), {})
        aligned = set(mine.get("aligned", ())) | set(theirs.get("aligned", ()))
        if any(pair <= aligned for pair in OPPOSED):
            return True
        if mine.get("energy") and mine.get("energy") == theirs.get("energy"):
            return True
    return False


def _abilities(
    r: _Roller, table: list[dict[str, Any]], wanted: int, weapon: dict[str, Any] | None = None, bonus: int = 0
) -> list[str]:
    """`wanted` special abilities off `table`, each once ("roll twice again" adds two), rerolled when they don't fit
    the weapon, are incompatible with one already rolled, or put the item over +10 with its enhancement `bonus`
    (Table: Melee Weapon Special Abilities: "Reroll if you get a duplicate special ability, an ability incompatible
    with an ability that you've already rolled, or if the extra ability puts you over the +10 limit")."""
    effects = _effects()
    names: list[str] = []
    chosen: list[dict[str, Any]] = []
    total = bonus
    tries = 0
    while len(names) < wanted and tries < MOST_REROLLS:
        tries += 1
        row = r.band(table)
        if row.get("roll") == "twice":
            wanted += 1  # this roll is two more: one now counted, one added
            continue
        name = row["name"].rstrip("0123456789")
        price = int(effects.get(str(row.get("item")), {}).get("price") or 0)
        if name in names or not _ability_fits(row, weapon) or _incompatible(row, chosen) or total + price > MOST_TOTAL:
            continue
        names.append(name)
        chosen.append(row)
        total += price
    return names


def _enhanced(r: _Roller, grade: str, table: str) -> tuple[dict[str, Any], int]:
    """Table: Armor and Shields or Table: Weapons: the row that gives the item (a bonus or a specific item) and the
    number of special abilities rolled on the way ("Special ability and roll again")."""
    abilities = 0
    for _ in range(MOST_REROLLS):
        row = r.band(magic_tables()[table][grade])
        if row.get("roll") == "ability":
            abilities += 1
            continue
        if abilities and row.get("roll"):
            continue  # a specific item rolled after a special ability: roll again for the bonus
        return row, abilities
    return {"bonus": 1, "item": "", "name": "+1"}, abilities


def _armor(r: _Roller, grade: str) -> MagicItem:
    row, abilities = _enhanced(r, grade, "armor")
    if row.get("roll"):
        return MagicItem(f"{grade} armor", _specific(r, grade, row["roll"]))
    shield = row["item"] == "shield"
    base = r.band(magic_tables()["shield_types" if shield else "armor_types"])
    rolled = _abilities(r, magic_tables()["shield_abilities" if shield else "armor_abilities"][grade], abilities,
                        bonus=int(row["bonus"]))  # fmt: skip
    return MagicItem(f"{grade} {'shield' if shield else 'armor'}", _bonus_name(row["bonus"], base["name"], rolled))


def _weapon(r: _Roller, grade: str) -> MagicItem:
    row, abilities = _enhanced(r, grade, "weapons")
    if row.get("roll"):
        return MagicItem(f"{grade} weapon", _specific(r, grade, row["roll"]))
    kind = r.band(magic_tables()["weapon_types"])["roll"]
    base = _weapon_row(r, kind)
    weapon = _weapons().get(base["item"]) if base.get("ref") == "weapons" else None
    ranged = kind == "common_ranged" or (weapon or {}).get("kind") == "ranged"
    table = magic_tables()["ranged_abilities" if ranged else "melee_abilities"][grade]
    rolled = _abilities(r, table, abilities, weapon, int(row["bonus"]))
    return MagicItem(f"{grade} weapon", _bonus_name(row["bonus"], base["name"], rolled))


def _bonus_name(bonus: int, base: str, abilities: list[str]) -> str:
    """"+2 chain shirt", "+1 longsword (flaming, keen)"."""
    name = f"+{bonus} {plain_name(base)}"
    return f"{name} ({'; '.join(a.lower() for a in abilities)})" if abilities else name


def _specific(r: _Roller, grade: str, table: str) -> str:
    return r.band(magic_tables()[table][grade])["name"]


_FORM = re.compile(r" \((?:potion|oil|potion or oil)\)$")
TITLES = {"rings": "Ring of", "rods": "Rod of", "staffs": "Staff of", "wands": "Wand of"}


def _titled(kind: str, row: dict[str, Any]) -> str:
    """The item as it is called: "Ring of protection +2", "Wand of magic missile (3rd)", "Potion of cure light
    wounds", "Oil of magic weapon"; an item whose own name says what it is keeps it ("Immovable Rod")."""
    words = row["name"]
    if kind == "potions":
        form = "Oil" if words.endswith("(oil)") else "Potion"
        return f"{form} of {_first_lower(_FORM.sub('', words))}"
    if kind == "rods" and row.get("ref") == "items":
        own = next((i["name"] for i in load("items") if i["id"] == row["item"]), "")
        if own.lower().endswith(" rod"):
            return own
    return f"{TITLES[kind]} {_first_lower(words)}"


_LEVEL_KEY = re.compile(r"^(\d)")


def _scroll(r: _Roller, grade: str) -> MagicItem:
    """Table: Scroll Types (arcane or divine), Table: Number of Spells on a Scroll, then for each spell Table: Scroll
    Spell Levels and that level's spell table."""
    tables = magic_tables()
    kind = r.band(tables["scroll_types"])["name"].lower()
    count, sides = (int(n) for n in tables["scroll_counts"][grade].split("d"))
    spells = []
    for _ in range(r.dice_of(count, sides)):
        level = _LEVEL_KEY.match(r.band(tables["scroll_levels"][grade])["name"]).group(1)  # type: ignore[union-attr]
        spells.append(r.band(tables["scroll_spells"][kind][level])["name"])
    return MagicItem(f"{grade} scroll", f"Scroll ({kind}): {'; '.join(spells)}")


def magic_item(r: _Roller, grade: str, kind: str = "") -> MagicItem:
    """One random magic item of `grade` (minor, medium, major): Table: Random Magic Item Generation for the kind, or
    the `kind` given ("rings", "wondrous"…), then that kind's table."""
    kind = kind or r.band(magic_tables()["generation"][grade])["roll"]
    if kind == "armor":
        return _armor(r, grade)
    if kind == "weapons":
        return _weapon(r, grade)
    if kind == "scrolls":
        return _scroll(r, grade)
    if kind == "wondrous":
        return MagicItem(f"{grade} wondrous item", r.band(magic_tables()["wondrous"][grade])["name"])
    row = r.band(magic_tables()[kind][grade])
    return MagicItem(f"{grade} {kind.rstrip('s')}", _titled(kind, row))


# The hoard


def _monster_cr(source: str) -> tuple[int, str] | None:
    """The level a monster's CR gives, and its name: the source as a monster's name ("Ogre", "ogres", "Orc 2")."""
    wanted = name_key(re.sub(r"\s+\d+$", "", source.strip()))
    for key in (wanted, re.sub(r"s$", "", wanted), re.sub(r"es$", "", wanted)):
        row = next((m for m in load("monsters") if name_key(m["name"]) == key or m["id"] == key), None)
        if row is not None:
            cr = str(row.get("cr") or "")
            whole = re.match(r"^(\d+)(?:/(\d+))?$", cr)
            if whole:
                return max(1, int(whole.group(1)) // int(whole.group(2) or 1)), f"{row['name']}'s CR {cr}"
    return None


class Srd35Treasure:
    """SRD 3.5's treasure by encounter level for core's treasure tools. There are no lair types: a 3.5 hoard is the
    encounter's, rolled by its level."""

    lair_name = "none (3.5 rolls a hoard by encounter level)"
    individual_name = "the encounter's treasure, by its level"
    no_hoard: tuple[str, ...] = ()

    def lair_codes(self, codes: list[str]) -> list[str]:
        return []

    def parse_types(self, spec: str) -> dict[str, Any]:
        """The line as one group: `{"groups": [{"label": "EL 5", "codes": ["coins", "goods", "goods", "items"]}]}`;
        none for a line with no treasure ("EL 7, none")."""
        parsed = parse_spec(spec)
        if parsed is None:
            return {"groups": []}
        codes = [column for column in COLUMNS for _ in range(parsed.shares[column].times)]
        if not codes:
            return {"groups": []}
        label = f"EL {parsed.level}" if parsed.level is not None else "CR"
        return {"groups": [{"label": label, "codes": codes}]}

    def generate(self, dice: Dice, types: str, *, source: str | None = None) -> TreasureResult:
        parsed = parse_spec(types)
        if parsed is None:
            raise TreasureTypeError(
                f"'{types}' is no 3.5 treasure: give the encounter level and the rating, as 'EL 5, standard', "
                "'EL 3, double standard', 'EL 7, none' or a monster's line ('EL 4, no coins; 50% goods; 50% items')."
            )
        target = (source or "").strip() or types.strip()
        level, label = parsed.level, parsed.said
        if level is None:
            found = _monster_cr(source or "")
            if found is None:
                raise TreasureTypeError(
                    f"'{types}' gives no encounter level and the source '{source or ''}' is no monster: pass "
                    "'EL n, …' (the encounter's level), or the monster as the source to use its CR."
                )
            level, label = found
        level = max(1, level)
        code = f"EL{level}"
        r = _Roller(dice, code, target)
        row = treasure_tables()["levels"][min(level, 20)]
        coins = dict.fromkeys(COINS, 0)
        gems: list[Gem] = []
        art: list[ArtObject] = []
        magic: list[MagicItem] = []
        checks: list[Check] = []
        rolled = [f"EL {level}" + (f" ({label})" if label else "")]
        for column in COLUMNS:
            share = parsed.shares[column]
            for _ in range(share.times):
                rolled.append(column + (f" {share.note}" if share.note else ""))
                if share.chance is not None:
                    face = r.die(100)
                    checks.append(Check(code, column, share.chance, face, face <= share.chance))
                    if face > share.chance:
                        continue
                value = r.band(row[column])["value"]
                if column == "coins":
                    found = _COIN.match(value)
                    if found:
                        count, sides, times, coin = found.groups()
                        coins[coin] += r.dice_of(int(count), int(sides)) * _number(times) // share.divide
                    continue
                count = _COUNT.match(value)
                if count is None:
                    continue  # "—"
                n = int(count.group(1)) if count.group(2) is None else r.dice_of(int(count.group(1)), int(count.group(2)))
                what = count.group(3)
                for _ in range(n):
                    if what.startswith("gem"):
                        gems.append(_gem(r))
                    elif what == "art":
                        art.append(_art(r))
                    elif what == "mundane":
                        magic.append(_mundane(r))
                    else:
                        magic.append(magic_item(r, what))
        if level > 20 and parsed.shares["items"].times:
            above = treasure_tables()["above"]
            more = above.get(level, above[max(above)])
            rolled.append(f"+{more} major (above 20th level)")
            magic += [magic_item(r, "major") for _ in range(more)]
        magic += [MagicItem("named in the entry", extra) for extra in parsed.extras]
        return TreasureResult(
            types=tuple(rolled),
            coins=coins,
            gems=tuple(gems),
            art=tuple(art),
            magic=tuple(magic),
            checks=tuple(checks),
            rolls=tuple(r.rolls),
        )


TREASURE = Srd35Treasure()
