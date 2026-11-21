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
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any

from delve.dice import Dice
from delve.domain.characters import CharacterState, Sheet
from delve.rules.classic.checks import CheckError
from delve.rules.classic.combat import NONLETHAL, Combatant
from delve.rules.classic.life import DEAD_AT
from delve.rules.d20 import Progress
from delve_srd35 import data
from delve_srd35.engine import companions, features, numbers

__all__ = ["BelowFloor", "award_xp", "below_floor", "cr_award", "cr_for", "drain", "entry_refusal", "floor", "hints",
           "level_for", "level_up", "progress", "raised", "rest", "top", "xp_for_defeated", "xp_penalty"]  # fmt: skip

DRAIN_HP = 5
"""The hit points each negative level costs."""
REST_BASIS = "level × days (×2 complete bed rest)"
WEEK = 7
"""The days of rest that give back a use a week."""

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


_VARIANT_CR = re.compile(r"^\s*(\d+(?:/\d+)?)\s*(?:\(|or\b)")
"""A CR followed by a variant's: its first number."""


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
    Hit Dice; None when there is none. A CR with a variant's after it ("8 (elder 9)", "2 (without pipes) or 4 (with
    pipes)") is its first number, the stat block's own."""
    raw = str(row.get("cr", ""))
    for said in (raw, *(found.group(1) for found in [_VARIANT_CR.match(raw)] if found)):
        try:
            return _cr_text(_cr(said))
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


xp_penalty = numbers.xp_penalty
"""The multiclass XP penalty in percent (`numbers.xp_penalty`; the derived numbers carry it too)."""


def top(sheet: Sheet, reference: Any) -> bool:
    """Whether the character's ECL (`numbers.ecl`) is the slice's last level, 20th: no level after it."""
    return numbers.ecl(sheet, reference) >= min(data.load("slice")["max_level"], len(data.load("xp")["levels"]))


TOP_NOTE = "20th level is the top: the XP still adds up, but there is no level after it."


@dataclass(frozen=True)
class BelowFloor(Progress):
    """`Progress` for a character whose XP is below its level's floor: `note` says so."""

    note: str = ""


def floor(sheet: Sheet, reference: Any) -> int:
    """The XP the character's ECL (`numbers.ecl`) needs by Table 6-13: 16,000 at 6th."""
    levels = data.load("xp")["levels"]
    return levels[min(max(numbers.ecl(sheet, reference), 1), len(levels)) - 1]


def below_floor(sheet: Sheet, xp: int, reference: Any) -> str | None:
    """What to say of XP below the floor of the character's level (`floor`), as a character made at a level with no
    XP has: the sheet's level stands, and the next award starts from the floor. None when it isn't below."""
    least = floor(sheet, reference)
    if xp >= least:
        return None
    level = companions.ordinal(numbers.ecl(sheet, reference))
    return f"{xp:,} XP is below {level} level's {least:,}: the level stands, and an award first raises the XP to {least:,}."


def raised(sheet: Sheet, xp: int, reference: Any) -> tuple[int, str] | None:
    """The floor an award first raises XP below it to (`floor`), and what the answer says of it; None when the XP
    isn't below."""
    least = floor(sheet, reference)
    if xp >= least:
        return None
    level = companions.ordinal(numbers.ecl(sheet, reference))
    return least, f"{xp:,} XP was below {level} level's {least:,}: raised to {least:,} before the award."


def progress(sheet: Sheet, state: CharacterState, reference: Any) -> Progress:
    """The level the XP reaches; the XP the character's next level needs (None at the slice's last level, 20th:
    `top`); and its classes, ready when the XP reaches a level above the character's ECL (`numbers.ecl`), up to the
    slice's last level. XP below the ECL's floor (`below_floor`) gives the ECL, with a `note` (`BelowFloor`)."""
    levels = data.load("xp")["levels"]
    cap = min(data.load("slice")["max_level"], len(levels))
    level, total = level_for(state.xp), numbers.ecl(sheet, reference)
    xp_next = levels[total] if total < cap else None
    ready = tuple(sheet.levels) if total < min(level, cap) else ()
    if (note := below_floor(sheet, state.xp, reference)) is not None:
        return BelowFloor(total, state.xp, xp_next, ready, note)
    return Progress(level, state.xp, xp_next, ready)


def award_xp(sheet: Sheet, state: CharacterState, amount: int, reference: Any) -> CharacterState:
    """`amount` more XP, less the multiclass penalty the sheet's levels give now (`xp_penalty`), rounded down: the
    penalty is on XP earned while it holds, never on the XP the character already has. A loss takes no penalty. A
    companion (`d20["companion_of"]`) takes no XP: it grows with its master's level. An award to a character whose XP
    is below its level's floor (`below_floor`) first raises the XP to the floor."""
    if (sheet.d20 or {}).get("companion_of"):
        return state
    xp = state.xp
    if amount > 0:
        amount = amount * (100 - xp_penalty(sheet, reference)) // 100
        xp = max(xp, floor(sheet, reference))
    return replace(state, xp=xp + amount)


def _die(reference: Any, cls: str) -> int:
    found = reference.char_class(cls)
    if found is None or found["id"] != numbers.slug(cls):
        raise ValueError(f"Unknown class '{cls}'.")
    return int(found["hit_die"].lstrip("d"))


def hints(sheet: Sheet, cls: str, reference: Any) -> list[str]:
    """What the DM gives with the level `sheet` has just taken in `cls`, by its character level, its Hit Dice (racial
    and class, never the level adjustment): the skill points (the class's + Int, at least 1, ×4 on the first Hit Die,
    and a human's extra), a feat at 1st, 3rd, 6th … level, the class table's bonus feat (a fighter's at 1, 2, 4 …, a
    wizard's at 5 …), and an ability increase at 4th, 8th … level. A monster race's racial Hit Dice took the first
    Hit Die's ×4, and with its first class level the DM gives what they give too: their skill points (the race's
    "Racial Skills", else its type's), feats ("Racial Feats", else 1 + Hit Dice / 3) and an ability increase per 4."""
    race = numbers.race_named(reference, sheet.race)
    racial = numbers.racial_levels(race)
    total, level = racial + _total(sheet), sheet.levels[cls]
    int_mod = numbers.modifier(numbers.skill_point_score(sheet, "int"))
    per_level = numbers.signed(reference.char_class(cls)["skill_points"]) or 0
    points = max(1, per_level + int_mod)
    points *= 4 if total == 1 else 1
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
        out.append(f"{'an' if numbers.slug(cls)[0] in 'aeiou' else 'a'} {numbers.slug(cls)} bonus feat")
    if total % 4 == 0:
        out.append("an ability increase")
    if racial and _total(sheet) == 1:
        skill = race["racial_skill_points"]
        gained = skill["times"] * max(1, skill["per_hd"] + int_mod)
        out.append(f"{gained} skill points from its {racial} racial Hit Dice")
        count = race["racial_feats"]
        out.append(f"{count} feat{'s' * (count != 1)} from its racial Hit Dice")
        if increases := racial // 4:
            out.append(f"{increases} ability increase{'s' * (increases != 1)} from its racial Hit Dice")
    return out


ENTRY_HINT = (
    'A special requirement holds once you confirm it was met in play: set_build(choices={"requirements": '
    '{"<class>": ["<its words>"]}}).'
)


def entry_refusal(sheet: Sheet, cls: str, reference: Any) -> str | None:
    """Why the character can't take a first level in the prestige class `cls`: every requirement it doesn't meet
    (`numbers.requirement_problems`), in the class's order; None when it meets them all."""
    problems = numbers.requirement_problems(sheet, cls, reference)
    if not problems:
        return None
    return f"{sheet.label or 'The character'} can't enter the {numbers.slug(cls).replace('-', ' ')}: it needs " \
           f"{'; '.join(problems)}."  # fmt: skip


def level_up(sheet: Sheet, cls: str, reference: Any, dice: Dice) -> Sheet:
    """The sheet with one more level in `cls`: the hit die + Con (at least 1; the die's maximum at the first level, as
    the SRD gives) on `hp_max`, and the level-up in `d20["level_up"]`: its class, level, hit points and `hints`. The
    engine fills its numbers again after. A level past 20th (ECL, `top`) is refused, and one past the class's table
    (a 6th archmage level); a first level in a prestige class is refused, with every requirement it doesn't meet
    (`entry_refusal`); a later one isn't checked again (the SRD's requirements are to qualify). Entering, a feat's
    prerequisite met by a worn item is noted (`numbers.item_notes`) in the level-up's `notes`."""
    if top(sheet, reference):
        raise CheckError(f"{sheet.label or 'The character'} is 20th level, the top: there is no level after it.")
    die = _die(reference, cls)
    entering = bool(numbers.requirement_rows(cls)) and not sheet.levels.get(cls, 0)
    if entering and (refused := entry_refusal(sheet, cls, reference)):
        raise CheckError(refused, hint=ENTRY_HINT)
    raised = replace(sheet, levels={**sheet.levels, cls: sheet.levels.get(cls, 0) + 1})
    level = raised.levels[cls]
    try:
        numbers.class_row(reference, cls, level)  # a level past the class table refuses here
    except ValueError as error:  # the DM's refusal, not a crash: "The archmage table has no level 6."
        raise CheckError(str(error)) from None
    con = numbers.modifier(numbers.ability_score(sheet, "con"))
    if numbers.character_level(raised, reference) == 1:  # the first Hit Die; a monster race's racial ones come first
        face = die
    else:
        face = dice.roll(f"1d{die}", purpose=f"level_up:hp:{cls}:{level}", actor=sheet.label or None).total
    gained = max(1, face + con)
    said: dict[str, Any] = {"class": cls, "level": level, "hit_points": gained, "hints": hints(raised, cls, reference)}
    if penalty := xp_penalty(raised, reference):  # from now on, on each award (DEL-389)
        said["xp_penalty"] = penalty
    if entering and (notes := numbers.item_notes(sheet, reference)):
        said["notes"] = notes
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
    """The character's level (a companion's Hit Dice) in hit points a day, twice that with complete bed rest, up to
    `hp_max`; a rest also gives back the day's turning attempts, a rest of a day or more the class feature uses
    (`d20["used"]`, cleared where it is kept: they are uses a day, so a rest of 0 days keeps them) but those a week
    (`features.weekly`, remove disease), which only a rest of 7 days or more gives back; a rest of a day or more gives
    back a sorcerer's or bard's spells a day (`d20["cast"]`), clears `fatigued` (the SRD: 8 hours of complete rest;
    core's rest keeps the conditions it had, so the pack's `rest` tool takes it off as well) and the nonlethal damage
    (`d20["nonlethal"]`, said in `nonlethal_cleared`)."""
    level = companions.rest_level(sheet) or _total(sheet)  # a companion heals by its Hit Dice (DEL-389)
    gained = level * max(0, days) * (2 if bed_rest else 1)
    hp = max(state.hp, min(sheet.hp_max, state.hp + gained))
    d20 = {**(state.d20 or {}), "turning_used": 0}
    if "used" in d20 and days >= 1:
        weekly = features.weekly(sheet) if days < WEEK else set()
        d20["used"] = {key: n for key, n in d20["used"].items() if key in weekly}
    if days >= 1:  # a sorcerer's or bard's spells cast today
        d20.pop("cast", None)
    # Nonlethal damage heals "at the rate of 1 hit point per hour per character level": a day clears it (DEL-421).
    nonlethal = int(d20.pop(NONLETHAL, 0) or 0) if days >= 1 else 0
    tired = ("fatigued", "exhausted")  # a day's rest removes both ("8 hours of complete rest")
    rested = days >= 1 and any(c in state.conditions for c in tired)
    conditions = tuple(c for c in state.conditions if c not in tired) if rested else state.conditions
    after = replace(state, hp=hp, d20=d20, conditions=conditions)
    said: dict[str, Any] = {"healed": hp - state.hp, "basis": REST_BASIS}
    if rested:
        said["fatigue_cleared"] = True
    if nonlethal:
        said["nonlethal_cleared"] = nonlethal
    return after, said


def xp_for_defeated(combatant: Combatant) -> int | None:
    """The award for the combatant's `d20["cr"]` (Task 8 fills it with `cr_for`); None when it has no CR."""
    try:
        return cr_award((combatant.d20 or {}).get("cr", ""))
    except ValueError:
        return None
