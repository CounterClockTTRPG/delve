"""Prepared spells and turning undead under 3.5 (DEL-388).

A caster prepares spells of its first casting class (`numbers.CASTERS`), up to 3rd level in this slice: no more of a
level than its slots, each on its class's list at that level (`spells.json`'s `levels`), and for a cleric one slot of
each level from 1st up holding a spell of its domains (`domains.json`, the sheet's `d20["domains"]`). A cast reports
the DC, school and save; a wizard in armour rolls arcane spell failure first. Turning is the SRD's Charisma check on
Table: Turning Undead, 2d6 + level + Cha in Hit Dice, so many times a day (`CharacterState.d20["turning_used"]`)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING, Any

from delve.dice import roll_json
from delve.domain.characters import CharacterState, Sheet
from delve.domain.reference import straight_apostrophes
from delve_srd35 import data
from delve_srd35.engine import numbers
from delve_srd35.engine.combat import creature_type

if TYPE_CHECKING:
    from delve.dice import Dice

MAX_LEVEL = 3
"""The highest spell level the slice's casters prepare."""
# Table: Turning Undead: the lowest check of each row and the most powerful undead affected, relative to the level.
TURNING = ((22, 4), (19, 3), (16, 2), (13, 1), (10, 0), (7, -1), (4, -2), (1, -3))
TURNED_OUT = -4
"""The table's "0 or lower" row."""


def _key(name: str) -> str:
    """A spell's id from its name, as the data spells them ("Summon Nature’s Ally IV" is summon-natures-ally-iv),
    whatever its apostrophe."""
    return numbers.slug(straight_apostrophes(name).replace("'", ""))


@cache
def _spells() -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in data.load("spells")}


@cache
def _domains() -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in data.load("domains")}


def spell_row(name: str) -> dict[str, Any] | None:
    return _spells().get(_key(name))


def caster(sheet: Sheet) -> str | None:
    """The first casting class, the one whose slots and DCs the sheet has."""
    return next((cls for cls in sheet.levels if cls in numbers.CASTERS), None)


def _derived(sheet: Sheet, reference: Any) -> dict[str, Any]:
    return (sheet.d20 or {}).get("derived") or numbers.derived(sheet, reference)


def domain_spells(sheet: Sheet, level: int) -> dict[str, str]:
    """The sheet's domains' spells at `level`, by id, with their names."""
    found = {}
    for domain in (sheet.d20 or {}).get("domains", ()):
        if (row := _domains().get(numbers.slug(domain))) and (name := row["spells"].get(str(level))):
            found[_key(name)] = name
    return found


def spell_level(sheet: Sheet, name: str) -> int | None:
    """The spell's level for the sheet's first casting class: on the class's list, else for a cleric on one of its
    domains' lists (the domain slot's, as `can_memorize` reads them); None when it is on none, or for a non-caster."""
    cls = caster(sheet)
    if cls is None or (row := spell_row(name)) is None:
        return None
    if (level := row["levels"].get(cls)) is not None:
        return int(level)
    if cls == "cleric":
        return next((level for level in range(1, 10) if row["id"] in domain_spells(sheet, level)), None)
    return None


def can_memorize(sheet: Sheet, levels: Iterable[int], spells: Sequence[str], reference: Any) -> str | None:
    """A refusal, or None. `spells`, when given, are the names, one per entry of `levels`."""
    levels, names = list(levels), list(spells)
    if names and len(names) != len(levels):
        raise ValueError(f"srd35: {len(names)} spell names for {len(levels)} levels.")
    if not levels:
        return None
    cls = caster(sheet)
    if cls is None:
        return f"A {sheet.cls or 'character'} casts no spells: only clerics and wizards prepare them."
    slots = _derived(sheet, reference)["slots"]
    counts = Counter(levels)
    for level in sorted(counts):
        if level > MAX_LEVEL:
            return f"Level-{level} spells can't be prepared: casters here prepare spells up to 3rd level."
        cap = slots.get(str(level), 0)
        if counts[level] > cap:
            return f"Too many level-{level} spells: {counts[level]} given, {cap} slots available."
    for name, level in zip(names, levels, strict=True):
        if (row := spell_row(name)) is None:
            return f"'{name}' is no spell in the SRD."
        domain = domain_spells(sheet, level) if cls == "cleric" else {}
        if row["levels"].get(cls) != level and row["id"] not in domain:
            at = row["levels"].get(cls)
            where = f"a level-{at} {cls} spell, not level {level}" if at is not None else f"not on the {cls} list"
            return f"{row['name']} is {where}."
    if cls == "cleric" and names:
        for level in sorted(lv for lv in counts if lv >= 1):
            domain = domain_spells(sheet, level)
            here = [spell_row(n) for n, lv in zip(names, levels, strict=True) if lv == level]
            off = [row["name"] for row in here if row and row["levels"].get("cleric") != level]
            if len(off) > 1:  # a spell off the cleric list can only be the domain slot's, and there is one
                return (f"Only the level-{level} domain slot holds a spell off the cleric list, and it holds one: "
                        f"{', '.join(off)} given.")  # fmt: skip
            others = sum(1 for row in here if row and row["id"] not in domain)
            room = slots.get(str(level), 0) - 1
            if others > room:
                offer = ", ".join(domain.values()) or "none: the sheet names no domains"
                return (f"One level-{level} slot is the domain slot, for a spell of the cleric's domains ({offer}): "
                        f"{others} other spells given, {room} slots for them.")  # fmt: skip
    return None


def _somatic(row: dict[str, Any]) -> bool:
    """Whether the spell has a somatic component. A spell whose components the data lacks counts as having one: the
    SRD exempts only a spell that lacks it."""
    parts = [part.strip().split()[0] for part in row["components"].split(",") if part.strip()]
    return not parts or "S" in parts


def cast(
    sheet: Sheet,
    state: CharacterState,
    spell: str,
    level: int,
    dice: Dice | None,
    reference: Any,
    *,
    actor: str | None = None,
) -> tuple[CharacterState, dict[str, Any]]:
    """A prepared spell's cast, whose copy core has spent: the DC, school and save, or a failure in armour. The state
    is unchanged. `actor` is the caster's character id, the failure roll's actor; without one, its sheet's label."""
    if (row := spell_row(spell)) is None:
        return state, {"cast": False, "refusal": f"'{spell}' is no spell in the SRD."}
    found = _derived(sheet, reference)
    said: dict[str, Any] = {"dc": found["dc"].get(str(level)), "school": row["school"], "save": row["saving_throw"]}
    chance = found.get("spell_failure", 0)
    # SRD, Arcane Spell Failure: the armour's number "is the chance that the spell fails and is ruined. If the spell
    # lacks a somatic component, however, it can be cast with no chance of arcane spell failure." A 20% chance is 20
    # faces of the d100, 1 to 20: a roll equal to the chance fails.
    if caster(sheet) in numbers.ARCANE and chance > 0 and _somatic(row):
        if dice is None:
            raise ValueError("srd35: a cast in armour rolls arcane spell failure and needs dice.")
        # A stored roll is found again by its key (beat, actor, purpose …): the caster is its character id (DEL-395),
        # else its sheet's label (storage keeps it the character's name), the copy the count spent so far.
        copy = sum(1 for s in state.memorized if s.cast and _key(s.name) == row["id"])
        roll = dice.d(100, purpose=f"spell_failure:{row['id']}#{max(copy, 1)}", actor=actor or sheet.label or None)
        failure = {"chance": chance, "roll": roll.total, "failed": roll.total <= chance}
        if failure["failed"]:
            return state, {"cast": False, "lost": True, "spell_failure": failure}
        said["spell_failure"] = failure
    return state, said


def max_hd(check: int, level: int) -> int:
    """Table: Turning Undead: the Hit Dice of the most powerful undead the check affects."""
    return level + next((more for lowest, more in TURNING if check >= lowest), TURNED_OUT)


def _undead(name: str, hd: int, reference: Any) -> tuple[int, str | None]:
    """The undead's Hit Dice (the one given, else its row's), or a refusal when the row names another type."""
    if not name.strip():
        return hd, None
    rows = reference.monster(name)
    row = rows[0] if rows else None
    kind = creature_type(row) if row else ""
    if kind and kind != "undead":
        return hd, f"The {row['name'].lower()} is a {kind}, not undead: only undead can be turned."
    if not hd and kind == "undead":
        hd = max(1, numbers.signed(str(row.get("hit_dice") or "").split("d")[0].split("/")[0]) or 0)
    return hd, None


def turn_undead(
    sheet: Sheet | None,
    level: int,
    undead: str,
    hd: int,
    dice: Dice,
    reference: Any,
    *,
    actor: str | None,
    state: CharacterState | None,
) -> dict[str, Any]:
    """One turning attempt by the SRD (Turn or Rebuke Undead). With a sheet and a state the attempt is counted and
    the answer's `state` keeps the count; without a sheet the Charisma is +0 and nothing is counted. A sheet's cleric
    level is the turning level; `level` is the DM's for one without (or without a sheet)."""
    cha = numbers.modifier(numbers.ability_score(sheet, "cha")) if sheet else 0
    if sheet is not None and sheet.levels.get("cleric", 0) > 0:
        level = sheet.levels["cleric"]
    per_day = _derived(sheet, reference)["turning_per_day"] if sheet else None
    used = (state.d20 or {}).get("turning_used", 0) if state else 0
    hd, refusal = _undead(undead, hd, reference)
    if refusal:
        return {"note": refusal, "attempts_left": None if per_day is None else max(0, per_day - used)}
    if sheet is not None and per_day == 0:
        return {"note": f"A {sheet.cls or 'character'} can't turn undead.", "attempts_left": 0}
    if per_day is not None and used >= per_day:
        return {"note": f"No turning attempts left: {per_day} times a day, all used. They come back with rest.",
                "attempts_left": 0}  # fmt: skip
    attempt = used + 1
    keys = {"actor": actor}
    # A counted attempt is keyed by its number (and the turner's id); one nothing counts by what is turned at which
    # level, so two in one beat roll their own checks (DEL-395) and the same one asked again is the stored roll.
    of = "" if state is not None and sheet is not None else f":{numbers.slug(undead) or f'{hd}hd'}@{level}"
    # Turning Check: "a Charisma check (1d20 + your Charisma modifier)", read on Table: Turning Undead.
    check_roll = dice.d(20, purpose=f"turning{of}:check#{attempt}", **keys)
    check = check_roll.total + cha
    most = max_hd(check, level)
    affected = hd <= most if hd else most >= 1
    # Turning Damage: "If your roll on Table: Turning Undead is high enough to let you turn at least some of the undead
    # ... roll 2d6 + your cleric level + your Charisma modifier". Destroying Undead: "If you have twice as many levels
    # (or more) as the undead have Hit Dice, you destroy any that you would normally turn."
    rolls = [check_roll]
    total = 0
    if affected:
        damage_roll = dice.roll("2d6", purpose=f"turning{of}:damage#{attempt}", **keys)
        rolls.append(damage_roll)
        total = max(0, damage_roll.total + level + cha)
    # The turning damage is the total Hit Dice turned: an undead of more Hit Dice than it isn't.
    turned = affected and (total >= hd if hd else total >= 1)
    said: dict[str, Any] = {
        "check": check,
        "max_hd": most,
        "total_hd": total,
        "destroy_up_to_hd": level // 2,
        "attempts_left": None if per_day is None else per_day - attempt,
        "rolls": [roll_json(roll) for roll in rolls],
    }
    if hd:
        said |= {"hd": hd, "turned": turned, "destroyed": turned and hd <= level // 2}
    if state is not None and sheet is not None:
        said["state"] = replace(state, d20={**(state.d20 or {}), "turning_used": attempt})
    return said
