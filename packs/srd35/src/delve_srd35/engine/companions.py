"""A druid's (and a ranger's) animal companion, a paladin's special mount, and wild shape's forms (DEL-389): what
the rows of `features.json` say of them, read with the SRD's monster rows. No storage: the pack's tools module makes a
companion (`add_companion`) and the engine's `combat` makes its numbers from these.

A companion is a character of its own whose `Sheet.d20` holds `companion_of` (its master's id), `animal` (its monster
row's name) and `companion`, the block its master's level gives: the `animal-companion` or `special-mount` row's
`companion` table at that level (`bonus_hd`, `natural_armour`, `str`, `dex`, a mount's `int`, a companion's `tricks`)
and the special abilities gained so far. Its numbers are the monster row's with the block's on them (`deltas`): bonus
Hit Dice (d8s with the Con modifier) raise the BAB as a druid's or cleric's of the new Hit Dice (three quarters of
them) and the Fortitude and Reflex saves as good saves, Will as a poor one."""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import cache
from typing import Any

from delve.domain.characters import Sheet
from delve.rules.classic.checks import CheckError
from delve_srd35 import data
from delve_srd35.engine import features, numbers

FEATURES = ("special-mount", "animal-companion")
"""The features that give a companion; a mount first, so a druid-paladin's warhorse is her mount."""
SIZES = ("fine", "diminutive", "tiny", "small", "medium", "large", "huge", "gargantuan", "colossal")
FORM_TYPES = ("animal", "plant", "elemental")
"""The creature types wild shape takes, as its row's `forms` names them."""
_HIT_DICE = re.compile(r"\s*(\d+)\s*(?:/\s*(\d+))?\s*d", re.IGNORECASE)


@cache
def _monsters() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in data.load("monsters"):
        rows.setdefault(str(row.get("name") or "").lower(), row)
        rows.setdefault(str(row.get("id") or ""), row)
    return rows


def monster(name: str) -> dict[str, Any] | None:
    """The monster row by its name or id, whatever the case; None for one the SRD hasn't."""
    asked = name.strip().lower()
    return _monsters().get(asked) or _monsters().get(numbers.slug(asked))


def hit_dice(row: Mapping[str, Any]) -> int:
    """The row's Hit Dice as a count: "2d8+4" is 2, "12d8+51" 12; a fraction of a die ("1/2 d8") counts as 1."""
    found = _HIT_DICE.match(str(row.get("hit_dice") or ""))
    if found is None:
        return 1
    return 1 if found.group(2) else max(1, int(found.group(1)))


def scores(row: Mapping[str, Any]) -> dict[str, int]:
    """The row's ability scores as numbers; a "—" (none) as 10."""
    raw = dict(row.get("abilities") or {})
    return {a: numbers.signed(raw.get(a)) if numbers.signed(raw.get(a)) is not None else 10
            for a in ("str", "dex", "con", "int", "wis", "cha")}  # fmt: skip


def _bab(hd: int) -> int:
    return hd * 3 // 4


def _good(hd: int) -> int:
    return 2 + hd // 2


def _poor(hd: int) -> int:
    return hd // 3


def _average(hd: int) -> int:
    """`hd` d8s at their average, 4.5 each, rounded down: the monster rows' hit points before Con."""
    return hd * 9 // 2


# --- the master's companion feature ------------------------------------------------------------------------------


def _row(cls: str, fid: str) -> dict[str, Any] | None:
    return next((r for r in features.rows(cls) if r["id"] == fid), None)


def feature_level(sheet: Sheet, fid: str) -> int:
    """The master's level for the feature's table: the paladin level for a mount; for a companion the druid level,
    with half the ranger level added (an `effective_druid_level` of "half"): the SRD stacks the levels of the classes
    that give one. 0 without the feature."""
    total = 0
    for cls, level in sheet.levels.items():
        row = _row(cls, fid)
        if row is None or level < row["level"]:
            continue
        total += level // 2 if row.get("effective_druid_level") == "half" else level
    return total


def table_row(fid: str) -> dict[str, Any]:
    """The row that holds the feature's `companion` table: the druid's for an animal companion (the ranger's reads
    it), the paladin's for a mount."""
    return next(r for cls in ("druid", "paladin") for r in features.rows(cls) if r["id"] == fid and "companion" in r)


def _listed(row: Mapping[str, Any], animal: str) -> bool:
    return animal in (*row.get("animals", ()), *row.get("aquatic", ()), *row.get("allowed", ()))


def offset(fid: str, animal: str, level: int) -> int:
    """How far below the master's level the animal's companion stands: 0 for one of the feature's own list, an
    alternative list's offset for one of those (a brown bear from 7th, as a druid 6 levels lower). Refused for an
    animal of no list, or one whose list the level hasn't reached. A mount may be any animal (the SRD: another kind
    "may be allowed"), as the DM rules."""
    row = table_row(fid)
    if _listed(row, animal) or fid == "special-mount":
        return 0
    for at, alternative in sorted(row.get("alternatives", {}).items(), key=lambda item: int(item[0])):
        if animal in alternative["animals"]:
            if level < int(at):
                raise CheckError(f"A {animal} companion is on the list for a druid of {ordinal(int(at))} level "
                                 f"or higher; this one's companion level is {level}.",
                                 hint=f"From the base list: {', '.join(row['animals'])}.")  # fmt: skip
            return int(alternative["offset"])
    raise CheckError(f"A {animal} isn't on the animal companion lists.",
                     hint=f"From the base list: {', '.join(row['animals'])}.")  # fmt: skip


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def block(fid: str, level: int) -> dict[str, Any]:
    """The companion's block at the (companion) level: the table's numbers there and the special abilities gained to
    it, with the feature and the level."""
    table = table_row(fid)["companion"]
    reached = [table[key] for key in sorted(table, key=int) if int(key) <= level]
    at = dict(reached[-1])
    gains = [gain for entry in reached for gain in entry.get("gains", ())]
    at.pop("gains", None)
    return {"feature": fid, "level": level, **at, "special": gains}


# --- its numbers -------------------------------------------------------------------------------------------------


def companion_scores(row: Mapping[str, Any], held: Mapping[str, Any]) -> dict[str, int]:
    """The animal's scores with the block's Str and Dex adjustments, and a mount's Int."""
    out = scores(row)
    out["str"] += int(held.get("str", 0))
    out["dex"] += int(held.get("dex", 0))
    if held.get("int"):
        out["int"] = int(held["int"])
    return out


def deltas(row: Mapping[str, Any], held: Mapping[str, Any]) -> dict[str, int]:
    """What the block changes of the monster row's numbers: its Hit Dice (`hd`, the new count), BAB, saves, AC,
    touch and flat-footed AC, initiative, the Str and Dex modifiers (on the attacks) and the hit points."""
    hd = hit_dice(row)
    more = int(held.get("bonus_hd", 0))
    before, after = scores(row), companion_scores(row, held)
    dex = numbers.modifier(after["dex"]) - numbers.modifier(before["dex"])
    strength = numbers.modifier(after["str"]) - numbers.modifier(before["str"])
    con = numbers.modifier(after["con"])
    natural = int(held.get("natural_armour", 0))
    return {
        "hd": hd + more,
        "bab": _bab(hd + more) - _bab(hd),
        "fort": _good(hd + more) - _good(hd),
        "ref": _good(hd + more) - _good(hd) + dex,
        "will": _poor(hd + more) - _poor(hd),
        "ac": natural + dex,
        "touch": dex,
        "flat_footed": natural + min(dex, 0),
        "init": dex,
        "dex": dex,
        "str": strength,
        "hp": _average(hd + more) - _average(hd) + more * con,
    }


def hp_max(row: Mapping[str, Any], held: Mapping[str, Any]) -> int:
    return max(1, int(row.get("hp") or _average(hit_dice(row))) + deltas(row, held)["hp"])


def of(sheet: Sheet) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """A companion's monster row and block, from its sheet; None for a sheet that isn't a companion's (or whose
    animal the SRD no longer has)."""
    build = sheet.d20 or {}
    if not build.get("companion_of") or not build.get("companion"):
        return None
    row = monster(str(build.get("animal") or ""))
    return None if row is None else (row, dict(build["companion"]))


def rest_level(sheet: Sheet) -> int | None:
    """A companion's Hit Dice, its level for a night's healing (the SRD: 1 hp per Hit Die); None for a sheet that
    isn't a companion's."""
    found = of(sheet)
    return None if found is None else deltas(*found)["hd"]


_DAMAGE = re.compile(r"^(\d+d\d+)([+-]\d+)?$")


def plus(damage: str, more: int) -> str:
    """Damage dice with `more` on their bonus: "1d6+1" and 1 is "1d6+2"; a damage that isn't plain dice as it is."""
    found = _DAMAGE.match(str(damage).replace(" ", ""))
    if found is None or not more:
        return damage
    total = int(found.group(2) or 0) + more
    return found.group(1) + (f"{total:+d}" if total else "")


# --- wild shape --------------------------------------------------------------------------------------------------


def _said(sizes: list[str]) -> str:
    words = [s.capitalize() for s in sizes]
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} or {words[-1]}"


def form_refusal(row: Mapping[str, Any], kind: str, size: str, forms: Mapping[str, Any], level: int) -> str | None:
    """Why a druid of `level` can't wild shape into the row's creature (its type `kind`, its size `size`), by the
    wild-shape row's `forms` at that level and its Hit Dice no more than her level; None when she can."""
    allowed = dict(features.at_level(forms, level) or {})
    name = str(row.get("name") or "").lower()
    if kind not in allowed:
        kinds = " or ".join(f"{k}s" if k != "animal" else "animals" for k in FORM_TYPES if k in allowed)
        return f"Wild shape at druid level {level} takes {kinds}: a {name} is a {kind or 'creature of no type'}."
    if size not in allowed[kind]:
        return (f"Wild shape at druid level {level} takes a {kind} of {_said(allowed[kind])} size: a {name} is "
                f"{size.capitalize()}.")  # fmt: skip
    if hit_dice(row) > level:
        return f"Wild shape's form can't have more Hit Dice than the druid level ({level}): a {name} has " \
               f"{hit_dice(row)} Hit Dice."  # fmt: skip
    return None
