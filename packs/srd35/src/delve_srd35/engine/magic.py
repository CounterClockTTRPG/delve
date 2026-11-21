"""Prepared spells and turning undead under 3.5 (DEL-388).

A caster prepares spells of its casting class (`features.casters`), up to the highest level its class table and key
ability give it a slot of (to 9th, DEL-389): no more of a level than its slots, each on its class's list at that level
(`spells.json`'s `levels`), and for a cleric one slot of each level from 1st up holding a spell of its domains
(`domains.json`, the sheet's `d20["domains"]`). A multiclass caster has a pool per class (`derived["casting"]`): each
memorized copy is assigned to a class (`assign`), computed from the memorized list and never stored. A cast reports
the DC by that class's ability, school and save; a copy cast as arcane in armour rolls arcane spell failure first.
Turning is the SRD's Charisma check on Table: Turning Undead, 2d6 + level + Cha in Hit Dice, so many times a day
(`CharacterState.d20["turning_used"]`).

The casters that prepare are the cleric, wizard and druid (to 9th-level spells), the adept (to 5th), and the paladin and
ranger from 4th level (to 4th), at a caster level of half their class level (DEL-389). A sorcerer or bard casts
spontaneously (DEL-389): any spell it knows (the sheet's `d20["known"]`, by class), so many of each level a day
(`derived["casting"]`'s `per_day`), counted in `CharacterState.d20["cast"]` by class and level until a rest of a day.
It memorizes nothing. A sorcerer/cleric's sorcerer spell is cast so when no uncast copy of it is memorized
(`casts_unprepared`). A cleric loses a prepared spell to cast a cure (or inflict) spell of its level in its place, a
druid a summon nature's ally (`convert`)."""

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
from delve_srd35.engine import features, numbers
from delve_srd35.engine.combat import creature_type
from delve_srd35.engine.companions import ordinal

if TYPE_CHECKING:
    from delve.dice import Dice

# Table: Turning Undead: the lowest check of each row and the most powerful undead affected, relative to the level.
TURNING = ((22, 4), (19, 3), (16, 2), (13, 1), (10, 0), (7, -1), (4, -2), (1, -3))
TURNED_OUT = -4
"""The table's "0 or lower" row."""
CONVERTS = {"cure-or-inflict": ("cure-", "inflict-"), "summon-natures-ally": ("summon-natures-ally-",)}
"""What a casting row's `converts` names: the prefix of the ids a prepared spell converts into (a cleric's cure, or
inflict, spells; a druid's summon nature's ally)."""
GOOD, EVIL = ("good", "lg", "ng", "cg"), ("evil", "le", "ne", "ce")


def unprepared(cls: str) -> str:
    """The refusal of a sorcerer's or bard's spell memorized: it casts from the spells it knows."""
    return (f"A {cls} memorizes nothing: it casts any spell it knows (set_build's known), so many a day, with "
            "cast_spell.")  # fmt: skip


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
    return next(iter(features.casters(sheet)), None)


def spontaneous(sheet: Sheet) -> bool:
    """Whether the sheet's first casting class casts spontaneously (a sorcerer, a bard): its casting row isn't
    `prepared`."""
    return (cls := caster(sheet)) is not None and not (features.casting(cls) or {}).get("prepared", True)


def caster_level(sheet: Sheet) -> int:
    """The first casting class's caster level (`numbers.caster_level`: half a paladin's or ranger's level); 0 for a
    non-caster."""
    return 0 if (cls := caster(sheet)) is None else numbers.caster_level(sheet, cls)


def _derived(sheet: Sheet, reference: Any) -> dict[str, Any]:
    return numbers.stored(sheet, reference)


def _casting(sheet: Sheet, reference: Any) -> dict[str, dict[str, Any]]:
    """`derived["casting"]`, the pool of each casting class; worked out again for a sheet stored before it (Phase 2's
    derived numbers have none)."""
    found = _derived(sheet, reference)
    return found["casting"] if "casting" in found else numbers.derived(sheet, reference)["casting"]


def _highest(entry: dict[str, Any]) -> int | None:
    """The highest spell level a prepared class's pool has a slot of; None for none."""
    return max((int(level) for level, count in entry.get("slots", {}).items() if count), default=None)


def _top(level: int) -> str:
    return ordinal(level) if level else "0"  # the SRD's "0-level spells"


def _levels_of(sheet: Sheet, row: dict[str, Any], cls: str) -> list[int]:
    """The levels `cls` prepares the spell at: its list's, and for a cleric its domains' (the domain slot's)."""
    out = [int(at)] if (at := row["levels"].get(cls)) is not None else []
    if cls == "cleric":
        out += [level for level in range(1, 10) if level not in out and row["id"] in domain_spells(sheet, level)]
    return out


def domain_spells(sheet: Sheet, level: int) -> dict[str, str]:
    """The sheet's domains' spells at `level`, by id, with their names."""
    found = {}
    for domain in (sheet.d20 or {}).get("domains", ()):
        if (row := _domains().get(numbers.slug(domain))) and (name := row["spells"].get(str(level))):
            found[_key(name)] = name
    return found


def spell_level(sheet: Sheet, name: str, reference: Any) -> int | None:
    """The spell's level for the sheet's casting classes: a class's list's, else for a cleric one of its domains' lists
    (the domain slot's, as `can_memorize` reads them); None when it is on none, or for a non-caster. Of a multiclass
    caster's classes, the first in the sheet's order that can cast it at that level, else the first that has it."""
    if (row := spell_row(name)) is None:
        return None
    found = []
    for cls in features.casters(sheet):
        if levels := _levels_of(sheet, row, cls):
            found.append((cls, levels[0]))
    if len(found) > 1:
        casting = _casting(sheet, reference)
        for cls, level in found:
            entry = casting.get(cls, {})
            if not entry.get("prepared", True) or ((top := _highest(entry)) is not None and level <= top):
                return level
    return found[0][1] if found else None


def can_memorize(sheet: Sheet, levels: Iterable[int], spells: Sequence[str], reference: Any) -> str | None:
    """A refusal, or None. `spells`, when given, are the names, one per entry of `levels`."""
    levels, names = list(levels), list(spells)
    if names and len(names) != len(levels):
        raise ValueError(f"srd35: {len(names)} spell names for {len(levels)} levels.")
    if not levels:
        return None
    cls = caster(sheet)
    if cls is None:
        return (f"A {sheet.cls or 'character'} casts no spells: clerics, wizards, druids and adepts prepare them, "
                "paladins and rangers from 4th level.")  # fmt: skip
    if len(features.casters(sheet)) > 1:
        return _can_memorize_pools(sheet, levels, names, reference)
    if spontaneous(sheet):
        return unprepared(cls)
    slots = _derived(sheet, reference)["slots"]
    counts = Counter(levels)
    # The highest level the class table and the key ability give a slot of; a caster with no slot at all (a 4th-level
    # paladin's "0" without the Wisdom for a bonus spell) is told its slots below.
    highest = max((int(level) for level, count in slots.items() if count), default=None)
    for level in sorted(counts):
        if highest is not None and level > highest:
            return f"{sheet.label or sheet.cls or cls.title()} can cast up to {_top(highest)}-level spells."
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


def _can_memorize_pools(sheet: Sheet, levels: list[int], names: list[str], reference: Any) -> str | None:
    """`can_memorize` for a caster of more than one casting class: each copy must find a class whose list has it at
    that level and whose pool has room (`assign`). Without names, the levels are counted against the pools' sum."""
    casting = _casting(sheet, reference)
    prepared = {cls: entry for cls, entry in casting.items() if entry.get("prepared")}
    if not prepared:
        return unprepared(" or ".join(casting) or "spontaneous caster")
    who = sheet.label or sheet.cls or next(iter(prepared)).title()
    highest = max((top for entry in prepared.values() if (top := _highest(entry)) is not None), default=None)
    if highest is not None and any(level > highest for level in levels):
        return f"{who} can cast up to {_top(highest)}-level spells."
    if not names:
        counts = Counter(levels)
        for level in sorted(counts):
            cap = sum(entry["slots"].get(str(level), 0) for entry in prepared.values())
            if counts[level] > cap:
                return f"Too many level-{level} spells: {counts[level]} given, {cap} slots available."
        return None
    for name in names:
        if spell_row(name) is None:
            return f"'{name}' is no spell in the SRD."
    _, refusal = assign(sheet, list(zip(names, levels, strict=True)), casting)
    return refusal


def assign(
    sheet: Sheet, copies: Sequence[tuple[str, int]], casting: dict[str, dict[str, Any]]
) -> tuple[list[str | None], str | None]:
    """The class each memorized copy (name, level) is cast as, in the list's order, and the refusal of the first copy
    no class has room for (None when all fit). A copy goes to a prepared class whose list has it at that level and
    whose pool has a slot of that level; a spell only one such class has goes to it, in memorized order; then a spell
    both lists have goes to the first class in the sheet's order with room once those are in (so a loadout the
    first-with-room order would fill is filled the same, and one it would refuse for a later single-list copy isn't).
    A cleric's pool keeps its domain slot (`_room`). Computed from the sheet and the list, never stored, so it is the
    same on every read."""
    prepared = {cls: entry for cls, entry in casting.items() if entry.get("prepared")}
    held: dict[tuple[str, int], list[dict[str, Any]]] = {}
    classes: list[str | None] = [None] * len(copies)
    refusals: dict[int, str] = {}
    candidates: list[list[str]] = []
    for name, level in copies:
        row = spell_row(name)
        listed = [cls for cls in prepared if row is not None and level in _levels_of(sheet, row, cls)]
        candidates.append([cls for cls in listed if prepared[cls]["slots"].get(str(level), 0)])
        if row is None:
            refusals[len(candidates) - 1] = f"'{name}' is no spell in the SRD."
        elif not listed:
            refusals[len(candidates) - 1] = _off_lists(row, level, prepared, casting)
        elif not candidates[-1]:
            refusals[len(candidates) - 1] = (
                f"{row['name']} is a level-{level} {' and '.join(listed)} spell: the {listed[0]} can cast up to "
                f"{_top(_highest(prepared[listed[0]]) or 0)}-level spells."
            )
    for single in (True, False):  # the single-list copies first, then the ones of more lists
        for i, (name, level) in enumerate(copies):
            if i in refusals or (len(candidates[i]) == 1) != single:
                continue
            row = spell_row(name) or {}
            reasons = []
            for cls in candidates[i]:
                here = held.setdefault((cls, level), [])
                if (reason := _room(sheet, cls, prepared[cls]["slots"], [*here, row], level)) is None:
                    here.append(row)
                    classes[i] = cls
                    break
                reasons.append((cls, reason))
            else:
                refusals[i] = _full(row["name"], level, reasons, prepared)
    return classes, refusals[min(refusals)] if refusals else None


def _off_lists(row: dict[str, Any], level: int, prepared: dict[str, Any], casting: dict[str, Any]) -> str:
    """The refusal of a copy no prepared class's list has at its level."""
    if cls := next((c for c, e in casting.items() if not e.get("prepared") and row["levels"].get(c) == level), None):
        return f"{row['name']} is a {cls} spell. {unprepared(cls)}"
    return f"{row['name']} is no level-{level} spell of the {' or '.join(prepared)} list."


def _room(sheet: Sheet, cls: str, slots: dict[str, int], here: list[dict[str, Any]], level: int) -> str | None:
    """Why `here`, the copies of `level` a class holds with one more, overfills its pool; None when they fit. A cleric's
    one slot of each level from 1st is the domain slot: it alone holds a spell off the cleric list, and a spell of its
    domains."""
    cap = slots.get(str(level), 0)
    if len(here) > cap:
        return "full"
    if cls == "cleric" and level >= 1:
        domain = domain_spells(sheet, level)
        off = [row["name"] for row in here if row["levels"].get("cleric") != level]
        if len(off) > 1:
            return (f"Only the level-{level} domain slot holds a spell off the cleric list, and it holds one: "
                    f"{', '.join(off)} given.")  # fmt: skip
        if (others := sum(1 for row in here if row["id"] not in domain)) > cap - 1:
            offer = ", ".join(domain.values()) or "none: the sheet names no domains"
            return (f"One level-{level} slot is the domain slot, for a spell of the cleric's domains ({offer}): "
                    f"{others} other spells given, {cap - 1} slots for them.")  # fmt: skip
    return None


def _full(name: str, level: int, reasons: list[tuple[str, str]], prepared: dict[str, Any]) -> str:
    """The refusal of a copy that fits none of its classes: the domain slot's rule, else the pools named full."""
    if other := next((reason for _, reason in reasons if reason != "full"), None):
        return other
    pools = [f"the {cls}'s {prepared[cls]['slots'].get(str(level), 0)}" for cls, _ in reasons]
    named = " and ".join([", ".join(pools[:-1]), pools[-1]] if len(pools) > 1 else pools)
    return f"{named[0].upper()}{named[1:]} level-{level} slots are full: {name} is one too many."


def cast_as(sheet: Sheet, state: CharacterState, row: dict[str, Any], level: int, reference: Any) -> str | None:
    """The class the copy core just spent is cast as: the last spent copy of the spell in the memorized list (core
    spends the first uncast one) by `assign`; for a spell cast with no such copy, the first prepared class whose list
    has it at that level; for a caster of one casting class, that class."""
    casters = list(features.casters(sheet))
    if len(casters) <= 1:
        return next(iter(casters), None)
    casting = _casting(sheet, reference)
    memorized = state.memorized
    spent = [i for i, s in enumerate(memorized) if s.cast and _key(s.name) == row["id"]]
    if spent:
        classes, _ = assign(sheet, [(s.name, s.level) for s in memorized], casting)
        if (cls := classes[spent[-1]]) is not None:
            return cls
    prepared = [c for c, entry in casting.items() if entry.get("prepared") and level in _levels_of(sheet, row, c)]
    return next(iter(prepared), None)


def _somatic(row: dict[str, Any]) -> bool:
    """Whether the spell has a somatic component. A spell whose components the data lacks counts as having one: the
    SRD exempts only a spell that lacks it."""
    parts = [part.strip().split()[0] for part in row["components"].split(",") if part.strip()]
    return not parts or "S" in parts


def known(sheet: Sheet, cls: str) -> list[str]:
    """The spells a spontaneous class knows, by name, as `set_build(known=…)` set them."""
    return list(((sheet.d20 or {}).get("known") or {}).get(cls, ()))


def knower(sheet: Sheet, row: dict[str, Any], reference: Any) -> str | None:
    """The first spontaneous class of the sheet (in its order) that knows the spell and has it on its list."""
    for cls, entry in _casting(sheet, reference).items():
        if entry.get("prepared") or row["levels"].get(cls) is None:
            continue
        if row["id"] in {_key(name) for name in known(sheet, cls)}:
            return cls
    return None


def casts_unprepared(sheet: Sheet, spell: str, reference: Any) -> bool:
    """Whether a spontaneous class of the sheet knows the spell: core casts it from that class's spells a day when no
    uncast copy is memorized (a sorcerer/cleric's sorcerer spell)."""
    return (row := spell_row(spell)) is not None and knower(sheet, row, reference) is not None


def _who(sheet: Sheet) -> str:
    return sheet.label or sheet.cls or "The caster"


def failure_chance(sheet: Sheet, cls: str, reference: Any) -> int:
    """The arcane spell failure chance of a spell cast as `cls`: the armour's and shield's, for an arcane class. A class
    whose casting row has `no_failure_in` ignores the body armour's chance in armour that light or lighter, not a
    shield's (the bard: "A bard can cast bard spells while wearing light armor without incurring the normal arcane spell
    failure chance … a bard wearing medium or heavy armor or using a shield incurs" it): light armour and a shield is
    the shield's chance alone; medium or heavy armour is the armour's and the shield's."""
    row = features.casting(cls) or {}
    if row.get("type") != "arcane":
        return 0
    chance = _derived(sheet, reference).get("spell_failure", 0)
    build = sheet.d20 or {}
    if light := row.get("no_failure_in"):
        table = numbers.armour_table()
        body = table.get(numbers.slug(build.get("armor") or ""))
        if body is None or numbers.ARMOUR_RANK.get(body["category"], 0) <= numbers.ARMOUR_RANK[light]:
            shield = table.get(numbers.slug(build.get("shield") or "")) if build.get("shield") else None
            return shield["failure"] if shield else 0
    return chance


def _failure(
    row: dict[str, Any], chance: int, dice: Dice | None, purpose: str, actor: str | None
) -> dict[str, Any] | None:
    """Arcane spell failure's roll for a spell with a somatic part, at `chance`; None when nothing is rolled."""
    # SRD, Arcane Spell Failure: the armour's number "is the chance that the spell fails and is ruined. If the spell
    # lacks a somatic component, however, it can be cast with no chance of arcane spell failure." A 20% chance is 20
    # faces of the d100, 1 to 20: a roll equal to the chance fails.
    if chance <= 0 or not _somatic(row):
        return None
    if dice is None:
        raise ValueError("srd35: a cast in armour rolls arcane spell failure and needs dice.")
    roll = dice.d(100, purpose=purpose, actor=actor)
    return {"chance": chance, "roll": roll.total, "failed": roll.total <= chance}


def _dc(dcs: dict[str, Any], level: int, sheet: Sheet, row: dict[str, Any]) -> int | None:
    """The DC of a spell of `level` from the class's DCs by level, with Spell Focus's +1 and Greater Spell Focus's +1
    more where the feat's school is the spell's (they stack); None where the class has no DC at that level."""
    dc = dcs.get(str(level))
    if dc is None:
        return None
    school = str(row.get("school") or "").strip().lower()
    chosen = {f["id"] for f in (sheet.d20 or {}).get("feats", ()) if isinstance(f, dict)
              and str(f.get("choice") or "").strip().lower() == school}  # fmt: skip
    return int(dc) + len(chosen & {"spell-focus", "greater-spell-focus"})


def spell_numbers(sheet: Sheet, state: CharacterState, spell: str, reference: Any) -> dict[str, Any]:
    """The DC, school and save of the sheet's cast of `spell`, as `cast` answers them, read without spending or rolling
    anything (a spell declared in `setup_combat` was spent at setup): from the caster's spells a day when a
    spontaneous class knows it, else by the class of a prepared copy. Empty for no spell, or one the sheet can't
    cast."""
    if (row := spell_row(spell)) is None:
        return {}
    if casts_unprepared(sheet, spell, reference):
        _, said = _from_pool(sheet, state, row, reference)
        return {k: said[k] for k in ("dc", "school", "save") if said.get(k) is not None}
    if (level := spell_level(sheet, spell, reference)) is None:
        return {}
    multi = len(features.casters(sheet)) > 1
    cls = cast_as(sheet, state, row, level, reference)
    if multi and cls is None:
        return {}
    dcs = _casting(sheet, reference)[cls]["dc"] if multi and cls else _derived(sheet, reference)["dc"]
    found = {"dc": _dc(dcs, level, sheet, row), "school": row["school"], "save": row["saving_throw"]}
    return {k: v for k, v in found.items() if v is not None}


def cast(
    sheet: Sheet,
    state: CharacterState,
    spell: str,
    level: int,
    dice: Dice | None,
    reference: Any,
    *,
    actor: str | None = None,
    unprepared: bool = False,
) -> tuple[CharacterState, dict[str, Any]]:
    """A spell's cast: a prepared spell's, whose copy core has spent (the DC, school and save, or a failure in armour;
    the state is unchanged), or one from a spontaneous caster's spells a day (`_cast_known`): core says so
    (`unprepared`), and a caster that prepares nothing has no copy to spend. `actor` is the caster's character id, the
    failure roll's actor; without one, its sheet's label."""
    if (row := spell_row(spell)) is None:
        return state, {"cast": False, "refusal": f"'{spell}' is no spell in the SRD."}
    if unprepared or not any(entry.get("prepared") for entry in _casting(sheet, reference).values()):
        return _cast_known(sheet, state, row, dice, reference, actor=actor)
    multi = len(features.casters(sheet)) > 1
    found = _derived(sheet, reference)
    cls = cast_as(sheet, state, row, level, reference)
    if multi and cls is None:  # no prepared class has it at this level
        return state, {"cast": False, "refusal": f"{row['name']} is no level-{level} spell of the caster's lists."}
    # The DC by the class the copy is cast as; one casting class's is the sheet's stored `dc`, as Phase 2 read it.
    dc = _casting(sheet, reference)[cls]["dc"] if multi and cls else found["dc"]
    said: dict[str, Any] = {"dc": _dc(dc, level, sheet, row), "school": row["school"], "save": row["saving_throw"]}
    if multi:
        said["class"] = cls
    if multi or (features.casting(cls or "") or {}).get("caster_level") == "half":
        # a paladin's or ranger's (half its level), or a multiclass caster's class's, for the range and duration
        said["caster_level"] = numbers.caster_level(sheet, cls or "")
    # Only a copy cast as arcane rolls arcane spell failure: a cleric/wizard's cleric spell is divine. A stored roll is
    # found again by its key (beat, actor, purpose …): the caster is its character id (DEL-395), else its sheet's label
    # (storage keeps it the character's name), the copy the count spent so far.
    copy = sum(1 for s in state.memorized if s.cast and _key(s.name) == row["id"])
    chance = found.get("spell_failure", 0) if (features.casting(cls or "") or {}).get("type") == "arcane" else 0
    purpose = f"spell_failure:{row['id']}#{max(copy, 1)}"
    if (failure := _failure(row, chance, dice, purpose, actor or sheet.label or None)) is not None:
        if failure["failed"]:
            return state, {"cast": False, "lost": True, "spell_failure": failure}
        said["spell_failure"] = failure
    return state, said


def _cast_known(
    sheet: Sheet, state: CharacterState, row: dict[str, Any], dice: Dice | None, reference: Any, *, actor: str | None
) -> tuple[CharacterState, dict[str, Any]]:
    """A sorcerer's or bard's cast of a spell it knows, at its own list's level, from its spells a day of that level
    (`per_day`), counted in `CharacterState.d20["cast"]` by class and level. A spell lost to arcane spell failure is
    still one of the day's ("the spell fails and is ruined"): it says `lost`, without `cast: False`, so the spent spell
    is kept."""
    state, said = _from_pool(sheet, state, row, reference)
    if said.get("cast") is False:
        return state, said
    cls, level = said.pop("_class"), said["level"]
    purpose = f"spell_failure:{row['id']}#{cls}:{level}.{said.pop('_count')}"
    failure = _failure(row, failure_chance(sheet, cls, reference), dice, purpose, actor or sheet.label or None)
    if failure is not None:
        said["spell_failure"] = failure
        if failure["failed"]:
            return state, {"lost": True, "level": level, "spell_failure": failure, "left_today": said["left_today"]}
    return state, said


def pool_refusal(sheet: Sheet, state: CharacterState, spells: Sequence[str], reference: Any) -> str | None:
    """Why the caster's spells a day can't pay for `spells` (one caster's casts from its pool, in order: a round's
    declarations), or None when they can. Nothing is rolled: arcane spell failure comes with the cast itself."""
    for spell in spells:
        if (row := spell_row(spell)) is None:
            return f"'{spell}' is no spell in the SRD."
        state, said = _from_pool(sheet, state, row, reference)
        if said.get("cast") is False:
            return str(said["refusal"])
    return None


def _from_pool(
    sheet: Sheet, state: CharacterState, row: dict[str, Any], reference: Any
) -> tuple[CharacterState, dict[str, Any]]:
    """`_cast_known` before arcane spell failure: the spell counted against its class's spells a day of its level, or
    a refusal (`cast: False`). The answer keeps `_class` and `_count` (the day's count with this one) for the roll."""
    casting = _casting(sheet, reference)
    who = _who(sheet)
    cls = knower(sheet, row, reference)
    if cls is None:
        listed = [c for c, entry in casting.items() if not entry.get("prepared") and row["levels"].get(c) is not None]
        if not listed:
            return state, {"cast": False, "refusal": f"{row['name']} is on none of {who}'s spell lists."}
        names = ", ".join(known(sheet, listed[0])) or "none yet: set them with set_build's known"
        return state, {"cast": False, "refusal": f"{who} doesn't know {row['name']}: the {listed[0]}'s spells known "
                                                 f"are {names}."}  # fmt: skip
    entry, level = casting[cls], int(row["levels"][cls])
    per_day = entry["per_day"].get(str(level), 0)
    cast_today = (state.d20 or {}).get("cast") or {}
    spent = cast_today.get(cls, {}).get(str(level), 0)
    if spent >= per_day:
        return state, {"cast": False, "refusal": f"{who} has cast all {per_day} of the {cls}'s level-{level} spells "
                                                 "today: they come back with a rest of a day."}  # fmt: skip
    counted = {**cast_today, cls: {**cast_today.get(cls, {}), str(level): spent + 1}}
    state = replace(state, d20={**(state.d20 or {}), "cast": counted})
    said: dict[str, Any] = {"level": level, "dc": _dc(entry["dc"], level, sheet, row), "school": row["school"],
                            "save": row["saving_throw"], "left_today": per_day - spent - 1}  # fmt: skip
    if len(casting) > 1:
        said |= {"class": cls, "caster_level": entry["caster_level"]}
    return state, {**said, "_class": cls, "_count": spent + 1}


def energy_of(sheet: Sheet) -> str | None:
    """The energy a cleric's alignment channels: "positive" for a good one, "negative" for an evil one, None for one
    neither good nor evil (who chooses, `choices.energy`)."""
    words = sheet.alignment.lower().replace("-", " ").split()
    if any(word in GOOD for word in words):
        return "positive"
    if any(word in EVIL for word in words):
        return "negative"
    return None


def _domain_bound(
    sheet: Sheet,
    row: dict[str, Any],
    level: int,
    at: int,
    memorized: Sequence[Any],
    classes: Sequence[str | None],
    reference: Any,
) -> bool:
    """Whether the cleric's copy at `at` must be the one its level's domain slot holds, so it doesn't convert: a spell
    of the cleric's domains at that level, with the level's other cleric copies too many for the ordinary slots
    without it in the domain slot (`_room`'s rule: one slot of each level from 1st holds a domain spell). The other
    copies fit around it in an ordinary slot when they are at most the ordinary slots less one, or the ordinary slots
    when another of them is a domain spell to hold the domain slot."""
    domain = domain_spells(sheet, level)
    if row["id"] not in domain:
        return False
    cap = _casting(sheet, reference).get("cleric", {}).get("slots", {}).get(str(level), 0)
    others = [
        _key(s.name) for i, s in enumerate(memorized) if i != at and s.level == level and classes[i] in ("cleric", None)
    ]
    room = cap - 2 + any(other in domain for other in others)
    return len(others) > room


def _conversions(cls: str, row: dict[str, Any], level: int, sheet: Sheet) -> tuple[list[dict[str, Any]], str | None]:
    """The spells a `cls` copy of `level` converts into, lowest level first, or a refusal. SRD: a good cleric "can
    'lose' any prepared spell that is not a domain spell in order to cast any cure spell of the same spell level or
    lower", an evil one an inflict spell (a neutral cleric's by the energy it channels: its alignment's, else the
    build's `choices.energy`); a druid "any summon nature's ally spell of the same level or lower"."""
    kind = (features.casting(cls) or {}).get("converts")
    if kind is None:
        return [], (f"A {cls}'s prepared spell doesn't convert: only a cleric's (into a cure or inflict spell) or a "
                    "druid's (into summon nature's ally).")  # fmt: skip
    if level < 1:
        return [], "Only a prepared spell of 1st level or higher converts."
    prefixes = CONVERTS[kind]
    if kind == "cure-or-inflict":
        if row["levels"].get(cls) != level:
            return [], f"{row['name']} is the domain slot's spell: a domain spell doesn't convert."
        energy = energy_of(sheet) or str((((sheet.d20 or {}).get("choices") or {}).get("energy")) or "").lower()
        if energy not in ("positive", "negative"):
            return [], ("A neutral cleric converts into cure or inflict spells by the energy it channels (its "
                        'alignment names no good or evil): set it with set_build\'s choices {"energy": "positive"} '
                        'or {"energy": "negative"}.')  # fmt: skip
        prefixes = prefixes[:1] if energy == "positive" else prefixes[1:]
    found = [
        r for r in _spells().values()
        if r["id"].startswith(prefixes) and (at := r["levels"].get(cls)) is not None and 1 <= at <= level
        and (kind != "cure-or-inflict" or r["id"].endswith(("-wounds", "-wounds-mass")))
    ]  # fmt: skip
    return sorted(found, key=lambda r: (r["levels"][cls], r["id"])), None


def convert(
    sheet: Sheet, state: CharacterState, prepared: str, into: str, reference: Any
) -> tuple[CharacterState, dict[str, Any]]:
    """A cleric's spontaneous cure or inflict spell, or a druid's summon nature's ally: the first uncast copy of the
    prepared spell is spent, and a spell it converts into (`_conversions`: of the copy's level or lower) is cast:
    `into`, else the highest of them. The DC is that spell's own level's, of the class the copy is of; the answer has
    both levels. A refusal keeps the state."""
    who = _who(sheet)
    if (row := spell_row(prepared)) is None:
        return state, {"refusal": f"'{prepared}' is no spell in the SRD."}
    memorized = state.memorized
    at = next((i for i, s in enumerate(memorized) if _key(s.name) == row["id"] and not s.cast), None)
    if at is None:
        return state, {"refusal": f"{who} has no uncast copy of {row['name']} memorized."}
    level = memorized[at].level
    casters = list(features.casters(sheet))
    if len(casters) > 1:
        classes = assign(sheet, [(s.name, s.level) for s in memorized], _casting(sheet, reference))[0]
    else:
        classes = [next(iter(casters), None)] * len(memorized)
    if (cls := classes[at]) is None:
        return state, {"refusal": f"{row['name']} is no prepared copy of {who}'s classes."}
    options, refusal = _conversions(cls, row, level, sheet)
    if refusal is None and cls == "cleric" and _domain_bound(sheet, row, level, at, memorized, classes, reference):
        refusal = (f"{row['name']} holds the level-{level} domain slot (the other level-{level} spells fill the rest): "
                   "a domain spell doesn't convert.")  # fmt: skip
    if refusal is not None:
        return state, {"refusal": refusal}
    if not options:
        return state, {"refusal": f"No spell of level {level} or lower converts from {row['name']}."}
    if into.strip():
        spell = next((r for r in options if r["id"] == _key(into)), None)
        if spell is None:
            names = ", ".join(r["name"] for r in options)
            return state, {"refusal": f"A level-{level} {row['name']} of the {cls} converts into a spell of level "
                                      f"{level} or lower of these: {names}; not {into}."}  # fmt: skip
    else:
        spell = options[-1]
    cast_at = int(spell["levels"][cls])
    memorized = (*memorized[:at], replace(memorized[at], cast=True), *memorized[at + 1 :])
    state = replace(state, memorized=memorized)
    dc = _casting(sheet, reference)[cls]["dc"]
    said: dict[str, Any] = {"spell": spell["name"], "level": cast_at, "converted": memorized[at].name,
                            "converted_level": level, "dc": _dc(dc, cast_at, sheet, spell), "school": spell["school"],
                            "save": spell["saving_throw"]}  # fmt: skip
    if len(casters) > 1:
        said |= {"class": cls, "caster_level": numbers.caster_level(sheet, cls)}
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


def turning_level(sheet: Sheet) -> int:
    """The sheet's turning level: each class's level that turns (a `turn-undead` row it has reached) plus the row's
    `turning_level_offset`, summed: a cleric's level, a paladin's less 3 from 4th, a blackguard's command undead
    less 2 from 3rd ("He commands undead as would a cleric of two levels lower"); 0 for none."""
    total = 0
    for cls, level in sheet.levels.items():
        row = next((r for r in features.rows(cls) if r["id"] in numbers.TURNING), None)
        if row is not None and level >= row["level"]:
            total += max(0, level + int(row.get("turning_level_offset", 0)))
    return total


def rebukes(sheet: Sheet) -> bool:
    """Whether the sheet's turning rebukes and commands rather than turns: every turning row it has reached is a
    rebuke's (the blackguard's command undead, "the supernatural ability to command and rebuke undead"). A cleric's
    energy is the DM's (`energy_of`)."""
    reached = [r for cls, level in sheet.levels.items() for r in features.rows(cls)
               if r["id"] in numbers.TURNING and level >= r["level"]]  # fmt: skip
    return bool(reached) and all(r.get("rebuke") for r in reached)


def _turning_synergies(sheet: Sheet | None) -> list[dict[str, Any]]:
    """The synergy rows on the turning check the sheet's ranks give (`data/synergies.json`: Knowledge (religion)'s,
    "against undead", which every turning check is)."""
    return numbers.synergies(((sheet.d20 or {}).get("skills") or {}), "turning") if sheet is not None else []


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
    the answer's `state` keeps the count; without a sheet the Charisma is +0 and nothing is counted. A sheet with 5 or
    more ranks of Knowledge (religion) adds +2 to the check (`synergy`, the synergies table's row). A sheet's turning
    level (`turning_level`: a cleric's level, a paladin's less 3) is the level; `level` is the DM's for one without
    (or without a sheet)."""
    cha = numbers.modifier(numbers.ability_score(sheet, "cha")) if sheet else 0
    if sheet is not None and (turning := turning_level(sheet)) > 0:
        level = turning
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
    # "You get a +2 bonus on turning checks against undead if you have 5 or more ranks in Knowledge (religion)."
    rows = _turning_synergies(sheet)
    synergy = sum(row["bonus"] for row in rows)
    check = check_roll.total + cha + synergy
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
        **({"synergy": ", ".join(f"+{r['bonus']} ({numbers.skill_title(r['from'])} {r['ranks']}+ ranks)" for r in rows)}
           if synergy else {}),
        "max_hd": most,
        "total_hd": total,
        "destroy_up_to_hd": level // 2,
        "attempts_left": None if per_day is None else per_day - attempt,
        "rolls": [roll_json(roll) for roll in rolls],
    }
    if hd:
        said |= {"hd": hd, "turned": turned, "destroyed": turned and hd <= level // 2}
    if sheet is not None and rebukes(sheet):
        said["rebukes"] = True  # what it turns is rebuked (cowers), what it would destroy is commanded
    if state is not None and sheet is not None:
        said["state"] = replace(state, d20={**(state.d20 or {}), "turning_used": attempt})
    return said
