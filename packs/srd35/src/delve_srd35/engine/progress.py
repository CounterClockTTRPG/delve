"""Levels, XP, energy drain and rest under 3.5 (DEL-388).

XP is Unearthed Arcana's level-independent pair (`data/xp.json`, see SOURCES.md § XP): one total per character, the
levels of Table 6-13, and the award by CR of Table 6-14, the same whatever the party's levels. Hit points come from the
class's hit die each level, plus Con. An energy drain gives negative levels, which keep the class levels: the count is
kept in `Sheet.d20["negative_levels"]`, and the checks and swings take one off per level (Tasks 7 and 8); here each
costs 5 hit points. Natural healing is the character's level a day, twice that with complete bed rest.

CRs in the data come as "1/2", "0.5", "½" or "3"; a skeleton or zombie row without one takes its template's CR by Hit
Dice (`cr_for`)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from fractions import Fraction
from typing import Any

from delve.dice import Dice
from delve.domain.characters import CharacterState, Sheet
from delve.rules.classic.combat import Combatant
from delve.rules.classic.life import DEAD_AT
from delve.rules.d20 import Progress
from delve_srd35 import data
from delve_srd35.engine import numbers

__all__ = ["award_xp", "cr_award", "cr_for", "drain", "hints", "level_for", "level_up", "progress", "rest",
           "xp_for_defeated"]  # fmt: skip

DRAIN_HP = 5
"""The hit points each negative level costs."""
REST_BASIS = "level × days (×2 complete bed rest)"

# The SRD's Skeleton and Zombie templates, "Challenge Rating: Depends on Hit Dice": the lowest Hit Dice of each row and
# its CR. Neither template's table is in the pack's data (the templates' rows have no text), so they are the rule here,
# as numbers.SIZE is. Hit Dice between two rows (the zombie table skips 3, 5, 7 …) take the lower row.
SKELETON_CR = ((Fraction(1, 2), "1/6"), (1, "1/3"), (2, "1"), (4, "2"), (6, "3"), (8, "4"), (10, "5"), (12, "6"),
               (15, "7"), (18, "8"))  # fmt: skip
ZOMBIE_CR = ((Fraction(1, 2), "1/8"), (1, "1/4"), (2, "1/2"), (4, "1"), (6, "2"), (8, "3"), (12, "4"), (15, "5"),
             (18, "6"))  # fmt: skip
TEMPLATE_MAX_HD = 20
"""Neither template's table goes past 20 Hit Dice."""


_HIT_DICE = re.compile(r"(\d+(?:/\d+)?)\s*d\s*\d")
_FRACTION_SLASH = str.maketrans({"⁄": "/", "∕": "/"})


def _cr(text: Any) -> Fraction:
    """A CR as a number: "1/2", "0.5", "½" and "3" all read; anything else ("None", "—", "") is a ValueError."""
    raw = str(text).strip().translate(_FRACTION_SLASH)
    if len(raw) == 1 and not raw.isdigit() and unicodedata.numeric(raw, None) is not None:
        value = Fraction(unicodedata.numeric(raw)).limit_denominator(12)
    else:
        try:
            value = Fraction(raw)
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"Not a challenge rating: {text!r}.") from None
    if value <= 0:
        raise ValueError(f"Not a challenge rating: {text!r}.")
    return value


def _cr_text(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def cr_award(cr: str) -> int:
    """The XP for defeating one monster of `cr`: Table 6-14 for CR 1 to 20; a fraction of CR 1's award for a fraction,
    rounded down (1/3 is 100); above 20, twice the award of CR − 2."""
    value = _cr(cr)
    by_cr = data.load("xp")["by_cr"]
    if value < 1:
        return int(by_cr["1"] * value)
    if value.denominator != 1:
        raise ValueError(f"No award for a challenge rating between rows: {cr!r}.")
    if value > 20:
        return 2 * cr_award(str(value - 2))
    return by_cr[str(value)]


def cr_for(row: dict[str, Any]) -> str | None:
    """The text CR of a monster row ("1/2", "3"): its own, or for a skeleton or zombie without one, its template's by
    Hit Dice; None when there is none."""
    try:
        return _cr_text(_cr(row.get("cr", "")))
    except ValueError:
        pass
    name = str(row.get("id") or row.get("name") or "").lower()
    table = SKELETON_CR if name.endswith("skeleton") else ZOMBIE_CR if name.endswith("zombie") else None
    found = _HIT_DICE.search(str(row.get("hit_dice", "")))
    if table is None or found is None:
        return None
    hd = Fraction(found.group(1))
    if hd > TEMPLATE_MAX_HD:
        return None
    rows = [cr for low, cr in table if low <= hd]
    return rows[-1] if rows else None


def level_for(xp: int) -> int:
    """The character level `xp` reaches by Table 6-13 (1st to 20th)."""
    return sum(1 for needed in data.load("xp")["levels"] if xp >= needed) or 1


def _total(sheet: Sheet) -> int:
    return sum(sheet.levels.values())


def progress(sheet: Sheet, state: CharacterState) -> Progress:
    """The level the XP reaches; the XP the character's next level needs (None at the slice's last level); and its
    classes, ready when the XP reaches a level above the character's, up to the slice's last level."""
    levels = data.load("xp")["levels"]
    cap = min(data.load("slice")["max_level"], len(levels))
    level, total = level_for(state.xp), _total(sheet)
    xp_next = levels[total] if total < cap else None
    ready = tuple(sheet.levels) if total < min(level, cap) else ()
    return Progress(level, state.xp, xp_next, ready)


def award_xp(state: CharacterState, amount: int) -> CharacterState:
    return replace(state, xp=state.xp + amount)


def _die(reference: Any, cls: str) -> int:
    found = reference.char_class(cls)
    if found is None or found["id"] != numbers.slug(cls):
        raise ValueError(f"Unknown class '{cls}'.")
    return int(found["hit_die"].lstrip("d"))


def hints(sheet: Sheet, cls: str, reference: Any) -> list[str]:
    """What the DM gives with the level `sheet` has just taken in `cls`: the skill points (the class's + Int, at least
    1, ×4 at the first level, and a human's extra), a feat at 1st, 3rd, 6th … level, the class table's bonus feat
    (a fighter's at 1, 2, 4 …, a wizard's at 5 …), and an ability increase at 4th, 8th … level."""
    total, level = _total(sheet), sheet.levels[cls]
    per_level = numbers.signed(reference.char_class(cls)["skill_points"]) or 0
    points = max(1, per_level + numbers.modifier(numbers.ability_score(sheet, "int")))
    points *= 4 if total == 1 else 1
    race = numbers.race_named(reference, sheet.race)
    feats = []
    for trait in race["traits"] if race else ():
        if found := re.match(r"(\d+) extra skill points at 1st level and (\d+) extra skill points? at each", trait):
            points += int(found.group(1) if total == 1 else found.group(2))
        elif total == 1 and re.match(r"1 extra feat at 1st level", trait):
            feats.append("a racial bonus feat")
    out = [f"{points} skill point{'s' * (points != 1)}"]
    if total == 1 or total % 3 == 0:
        out.append("a feat")
    out += feats
    if "bonus feat" in numbers.class_row(reference, cls, level)["special"].lower():
        out.append(f"a {numbers.slug(cls)} bonus feat")
    if total % 4 == 0:
        out.append("an ability increase")
    return out


def level_up(sheet: Sheet, cls: str, reference: Any, dice: Dice) -> Sheet:
    """The sheet with one more level in `cls`: the hit die + Con (at least 1; the die's maximum at the first level, as
    the SRD gives) on `hp_max`, and the level-up in `d20["level_up"]`: its class, level, hit points and `hints`. The
    engine fills its numbers again after."""
    die = _die(reference, cls)
    raised = replace(sheet, levels={**sheet.levels, cls: sheet.levels.get(cls, 0) + 1})
    level = raised.levels[cls]
    numbers.class_row(reference, cls, level)  # a level past the class table refuses here
    con = numbers.modifier(numbers.ability_score(sheet, "con"))
    if _total(raised) == 1:
        face = die
    else:
        face = dice.roll(f"1d{die}", purpose=f"level_up:hp:{cls}:{level}", actor=sheet.label or None).total
    gained = max(1, face + con)
    said = {"class": cls, "level": level, "hit_points": gained, "hints": hints(raised, cls, reference)}
    return replace(raised, hp_max=sheet.hp_max + gained, d20={**(sheet.d20 or {}), "level_up": said})


def drain(sheet: Sheet, state: CharacterState, levels: int) -> tuple[Sheet, CharacterState, dict[str, Any]]:
    """`levels` more negative levels: the class levels stay, and each costs 5 hit points off the maximum (to at least
    1) and the current. What the maximum actually lost is kept, as a running total, in `d20["drain_hp"]`, for a
    restoration to give back. The character dies at as many negative levels as levels, or when the hit points fall
    to `DEAD_AT`."""
    if isinstance(levels, bool) or not isinstance(levels, int) or levels < 1:
        raise ValueError(f"A drain takes at least 1 level, not {levels!r}.")
    build = sheet.d20 or {}
    negative = int(build.get("negative_levels", 0)) + levels
    lost = DRAIN_HP * levels
    hp_max = max(1, sheet.hp_max - lost)
    taken = int(build.get("drain_hp", 0)) + sheet.hp_max - hp_max
    after = replace(sheet, hp_max=hp_max, d20={**build, "negative_levels": negative, "drain_hp": taken})
    hp = state.hp - lost
    slain = negative >= _total(sheet) or hp <= DEAD_AT
    return (
        after,
        replace(state, hp=DEAD_AT if slain else hp),
        {"slain": slain, "levels": levels, "negative_levels": negative, "hp_lost": lost},
    )


def rest(sheet: Sheet, state: CharacterState, days: int, *, bed_rest: bool = False) -> tuple[CharacterState, dict]:
    """The character's level in hit points a day, twice that with complete bed rest, up to `hp_max`; a rest also
    gives back the day's turning attempts."""
    gained = _total(sheet) * max(0, days) * (2 if bed_rest else 1)
    hp = max(state.hp, min(sheet.hp_max, state.hp + gained))
    after = replace(state, hp=hp, d20={**(state.d20 or {}), "turning_used": 0})
    return after, {"healed": hp - state.hp, "basis": REST_BASIS}


def xp_for_defeated(combatant: Combatant) -> int | None:
    """The award for the combatant's `d20["cr"]` (Task 8 fills it with `cr_for`); None when it has no CR."""
    try:
        return cr_award((combatant.d20 or {}).get("cr", ""))
    except ValueError:
        return None
