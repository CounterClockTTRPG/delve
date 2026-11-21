"""The class features of a 3.5 character (DEL-389), read from the pack's `features.json` (`{class_id: [row, ...]}`):
the features a sheet's class levels grant, the bonuses among them, uses a day, weapon proficiency and the casting
classes. A row's `by_level` holds its value from that class level on, until the next key; a row without one has its
`value` (or none: lay on hands is so many hit points, not a number of uses)."""

from __future__ import annotations

import re
from functools import cache
from typing import Any

from delve.domain.characters import Sheet
from delve_srd35 import data

OPTIONAL = ("condition", "ability", "feat", "target", "targets", "per", "spends", "bypass")
"""The row's fields a granted feature carries when the row has them: `spends` names the feature whose uses it spends
(each bardic music performance, bardic music's), `bypass` what overcomes a damage reduction ("—", nothing)."""
SAVES = frozenset({"fort", "ref", "will"})
"""The targets a `saves` bonus adds to."""


def class_id(cls: str) -> str:
    """A class's id by its key or name: "eldritch knight", "Eldritch Knight" and "eldritch-knight" are one class (a
    sheet keeps its levels under the names the DM gave)."""
    return re.sub(r"[^a-z0-9]+", "-", str(cls).lower()).strip("-")


def rows(cls: str) -> list[dict[str, Any]]:
    """The class's feature rows by its id or name (`class_id`), none for a class the table hasn't."""
    return data.load("features").get(class_id(cls), [])


def at_level(by_level: dict[str, Any], level: int) -> Any:
    """The value of `by_level` at `level`: that of the highest key not above it; None below the first."""
    found = [int(key) for key in by_level if int(key) <= level]
    return by_level[str(max(found))] if found else None


def granted(sheet: Sheet) -> list[dict[str, Any]]:
    """The sheet's granted features by its class levels, in class and table order. `value` is the row's `by_level` at
    the class's level (or its `value`); `per_day` is None here, `numbers.derived` fills it (`per_day`). Wild shape
    from 16th has `elemental_per_day` too, its row's `elemental_by_level`: the elemental forms' own uses, "in addition
    to her normal wild shape usage". A prestige class's requirement rows are no features: they are to enter it
    (`numbers.requirement_problems`)."""
    out = []
    for cls, level in sheet.levels.items():
        for row in rows(cls):
            if level < row["level"] or row["kind"] == "requirement":
                continue
            value = at_level(row["by_level"], level) if "by_level" in row else row.get("value")
            feature = {"id": row["id"], "class": cls, "name": row["name"], "kind": row["kind"], "value": value,
                       "per_day": None}  # fmt: skip
            feature.update({key: row[key] for key in OPTIONAL if key in row})
            if (elemental := at_level(row.get("elemental_by_level") or {}, level)) is not None:
                feature["elemental_per_day"] = int(elemental)
            out.append(feature)
    return out


def _targets(feature: dict[str, Any]) -> list[str]:
    return feature.get("targets") or ([feature["target"]] if "target" in feature else [])


def bonus(features: list[dict[str, Any]], target: str, conditions: set[str], mods: dict[str, int] | None = None) -> int:
    """The sum of the `bonus` features for `target` whose condition holds (is in `conditions`, or there is none); a
    `saves` bonus counts for each save. With `mods`, a feature with an `ability` adds that ability's bonus, if any
    (the monk's Wisdom to AC, the paladin's Charisma to saves: never a penalty), to its value (none: divine grace)."""
    total = 0
    for feature in features:
        ability = feature.get("ability") if mods is not None else None
        if feature["kind"] != "bonus" or not (isinstance(feature["value"], int) or ability):
            continue
        aims = _targets(feature)
        holds = feature.get("condition") is None or feature["condition"] in conditions
        if holds and (target in aims or (target in SAVES and "saves" in aims)):
            total += (feature["value"] or 0) + (max(0, mods.get(ability, 0)) if mods and ability else 0)
    return total


FAVOURED_RAISE = 2
"""Each favoured enemy's bonus, and what each raise at 5th, 10th, 15th and 20th adds to one of them."""


@cache
def favoured_enemies() -> dict[str, str]:
    """Table: Ranger Favored Enemies, read from the pack's ranger text in `classes.json`: each choice by the name it
    is kept under (a type, "magical beast", or a humanoid's or outsider's subtype, "orc", "evil"), with its line as
    the table has it ("Humanoid (orc)")."""
    ranger = next(row for row in data.load("classes") if row["id"] == "ranger")
    table = ranger["text"].split("Table: Ranger Favored Enemies", 1)[1].split("\n\n#", 1)[0]
    out = {}
    for cell in re.findall(r"\|\s*([^|\n]+?)\s*(?=\|)", table):
        if cell.startswith("Type") or set(cell) <= {"-", " "}:
            continue
        found = re.fullmatch(r"(.+?)\s*\((.+)\)", cell)
        out[(found.group(2) if found else cell).lower()] = cell
    return out


def favoured_enemy(name: str) -> str | None:
    """The favoured enemy a name means ("orc", "Humanoid (orc)", "orcs", "Magical Beast"), as `favoured_enemies`
    keeps it; None for one the table hasn't (a bare "humanoid", which needs its subtype)."""
    wanted = " ".join(str(name).lower().replace("_", " ").split())
    table = favoured_enemies()
    if found := re.fullmatch(r"(?:humanoid|outsider)\s*\((.+)\)", wanted):
        wanted = found.group(1).strip()
    for key in (wanted, wanted.removesuffix("s"), wanted.removesuffix("es")):
        if key in table:
            return key
    return None


def favoured_count(sheet: Sheet) -> int:
    """How many favoured enemies the sheet's ranger levels give (none without them)."""
    found = next((f for f in granted(sheet) if f["id"] == "favoured-enemy"), None)
    return int(found["value"]) if found and isinstance(found["value"], int) else 0


def favoured_bonuses(sheet: Sheet) -> dict[str, int]:
    """The sheet's favoured enemies (`Sheet.d20["choices"]["favoured_enemy"]`, in the order chosen) with their bonus:
    +2 each, and +2 more for each name the list repeats (a raise). The raises the list leaves go to the first. A list
    past what the level allows (an older build) counts only the first `count` enemies and `count - 1` raises, so no
    bonus passes the SRD's +2 + 2 per raise (+4 at 5th, +6 at 10th)."""
    chosen = list(((sheet.d20 or {}).get("choices") or {}).get("favoured_enemy") or ())
    count = favoured_count(sheet)
    if not chosen or not count:
        return {}
    out: dict[str, int] = {}
    raises = count - 1  # one with each enemy past the first
    for name in chosen:
        if name in out and raises:
            out[name] += FAVOURED_RAISE
            raises -= 1
        elif name not in out and len(out) < count:
            out[name] = FAVOURED_RAISE
    out[chosen[0]] += FAVOURED_RAISE * raises
    return out


def ability_boost(sheet: Sheet, ability: str) -> int:
    """What the sheet's class levels add to an ability score (the dragon disciple's ability boost, "gained as if
    through level advancement", and its 10th level's +4 Str and +2 Cha): the `abilities` bonus rows' value at the
    class's level, summed; 0 for none."""
    total = 0
    for cls, level in sheet.levels.items():
        for row in rows(cls):
            if row["kind"] == "bonus" and row.get("target") == "abilities" and level >= row["level"]:
                total += int((at_level(row["by_level"], level) or {}).get(ability, 0))
    return total


def dice_sum(values: list[Any]) -> str:
    """Dice of one kind added together ("2d6" and "1d6" is "3d6"); "" for none. Sneak attack from two classes: "the
    bonuses on damage stack"."""
    found = [re.fullmatch(r"\s*(\d+)(d\d+)\s*", str(v or "")) for v in values]
    dice = [m for m in found if m]
    if not dice:
        return ""
    return f"{sum(int(m.group(1)) for m in dice)}{dice[0].group(2)}"


def per_day(feature: dict[str, Any], mods: dict[str, int], extra: int = 0) -> int:
    """The feature's uses a day: its value plus the modifier of its ability where it has one, plus `extra` (a feat's
    uses, as Extra Turning's 4), at least 0. A feature without a number of uses (lay on hands) has none. A row with
    `per: "week"` (remove disease) has its value so, as uses a week: the sheet says "n a week", and only a rest of
    7 days or more gives them back (`weekly`)."""
    if not isinstance(feature["value"], int):
        return 0
    return max(0, feature["value"] + (mods.get(feature["ability"], 0) if feature.get("ability") else 0) + extra)


def weekly(sheet: Sheet) -> set[str]:
    """The ids of the sheet's granted features counted a week (`per: "week"`), whose spent uses a shorter rest
    leaves."""
    return {f["id"] for f in granted(sheet) if f.get("per") == "week"}


def _classes(sheet: Sheet) -> list[str]:
    """The sheet's classes with levels, or its `cls` as an id when it has none."""
    named = re.sub(r"[^a-z0-9]+", "-", sheet.cls.lower()).strip("-")
    return [c for c in sheet.levels if sheet.levels[c] > 0] or [named]


def proficient(sheet: Sheet, weapon: dict[str, Any], race: str) -> bool:
    """Whether the sheet's classes (each class's Weapon and Armor Proficiency row) or its race (`combat.RACE_WEAPONS`,
    `combat.RACE_MARTIAL`) make it proficient with `weapon`, a `weapons.json` row. A class without a proficiency row
    is taken as proficient with everything (the DM's call)."""
    from delve_srd35.engine.combat import RACE_MARTIAL, RACE_WEAPONS  # combat reads this module

    found = {c: next((r for r in rows(c) if r["kind"] == "proficiency"), None) for c in _classes(sheet)}
    if any(row is None for row in found.values()):
        return True
    if weapon["id"] in RACE_WEAPONS.get(race, set()):
        return True
    category = "martial" if weapon["id"] in RACE_MARTIAL.get(race, set()) else weapon["category"]
    return any(category in row["weapons"] or weapon["id"] in row["weapon_ids"] for row in found.values() if row)


def casting(cls: str) -> dict[str, Any] | None:
    """The class's casting row (its key ability, `type` arcane or divine, the level it casts from), if it casts. A
    prestige class's row that `advances` an existing class's casting is not its own casting: None (the assassin's and
    the blackguard's own lists are casting rows)."""
    return next((row for row in rows(cls) if row["kind"] == "casting" and "advances" not in row), None)


def advancing(cls: str) -> dict[str, Any] | None:
    """The prestige class's casting row that `advances` an existing class's casting ("+1 level of existing arcane
    spellcasting class"), if it has one: `advances` the kind of class ("arcane", "divine", "any", or a list of kinds
    for `count` classes at once), `by_level` the prestige levels that gain a level of it, `caster_level_only` when they
    raise only the caster level (the hierophant's)."""
    return next((row for row in rows(cls) if row["kind"] == "casting" and "advances" in row), None)


def advance_levels(row: dict[str, Any], level: int) -> int:
    """How many levels of the class it advances a prestige class's casting row gives at the prestige class's `level`:
    its `by_level` keys up to it (the eldritch knight's from 2nd)."""
    return sum(1 for key in row.get("by_level") or {} if int(key) <= level)


def kinds(row: dict[str, Any]) -> list[str]:
    """The kinds of class a prestige casting row advances, one per class: ["arcane"], ["arcane", "divine"]."""
    advances = row["advances"]
    return list(advances) if isinstance(advances, list) else [advances] * int(row.get("count", 1))


def casters(sheet: Sheet) -> dict[str, str]:
    """The sheet's casting classes, by its class order, each with its key ability: the classes with a casting row at
    or under their level (a paladin casts from 4th)."""
    out = {}
    for cls, level in sheet.levels.items():
        if (row := casting(cls)) is not None and level >= row["level"]:
            out[cls] = row["ability"]
    return out


def arcane(sheet: Sheet) -> bool:
    """Whether one of the sheet's casting classes casts arcane spells, which armour can make fail."""
    return any((casting(cls) or {}).get("type") == "arcane" for cls in casters(sheet))
