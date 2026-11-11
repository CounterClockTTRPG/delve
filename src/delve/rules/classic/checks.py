"""Checks and saves: saving throws, percentile and ability checks, reaction, morale,
surprise, system shock, resurrection survival, turning undead and encounter checks.

Each function takes the dice (and the reference where it needs one) and returns a frozen result with the rolls it used,
in `all_rolls`. None of them write state: the play services apply the results and log the events.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Self

from delve.dice import Dice, Roll
from delve.domain.reference import RulesetReference
from delve.domain.wandering import WanderingTable, countable
from delve.rules.classic.class_xp import class_levels
from delve.rules.classic.encounters import Encounters
from delve.rules.classic.tables import RuleTables
from delve.rules.classic.terrain import TERRAIN_ALIASES


class CheckError(ValueError):
    """A check that can't be made as asked: an unknown save type, class or undead, or a missing input."""

    def __init__(self, message: str, hint: str = "", candidates: Iterable[str] = ()) -> None:
        self.hint = hint
        self.candidates = tuple(candidates)
        super().__init__(message)


# --- saving throws -----------------------------------------------------------------------------------------------


class SaveBase(int):
    """A saving-throw target with where it came from: `sheet`, `class: Fighter 3`, the ruleset's save table (`OSRIC
    class table: fighter 3`), `monster: HD 3+1 saves as fighter 4` or `0-level: no class on the sheet`."""

    basis: str

    def __new__(cls, value: int, basis: str) -> Self:
        base = super().__new__(cls, value)
        base.basis = basis
        return base


@dataclass(frozen=True)
class SaveResult:
    success: bool
    needed: int
    """The d20 face needed: the base less every modifier."""
    roll: Roll
    save_type: str
    name: str
    base: int
    modifier: int
    """The modifier and the effects' `save` modifiers together."""
    basis: str

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return (self.roll,)


def save_type_for(save_type: str, *, rules: RuleTables) -> str:
    """The save type, as in `rules.save_types`, for any name the DM may use ("para", "bw", "MAGIC")."""
    kind = rules.save_aliases.get(save_type.strip().lower())
    if kind is None:
        raise CheckError(
            f"Unknown save type '{save_type}'. Use: {', '.join(rules.save_short)}.",
            candidates=rules.save_short,
        )
    return kind


def normalize_saves(saves: Any, *, rules: RuleTables) -> dict[str, int]:
    """Saves by type from `{type: value}`, five values in the ruleset's order, or ttrpg2's `[{type, value}]`."""
    if not saves:
        return {}
    if isinstance(saves, Mapping):
        return {rules.save_aliases[k.lower()]: int(v) for k, v in saves.items() if k.lower() in rules.save_aliases}
    if all(isinstance(s, int | float) for s in saves):
        return {kind: int(value) for kind, value in zip(rules.save_types, saves, strict=False)}
    found = {}
    for entry in saves:
        if isinstance(entry, Mapping) and entry.get("type") in rules.save_types and entry.get("value") is not None:
            found[entry["type"]] = int(entry["value"])
    return found


def _get(subject: Any, name: str) -> Any:
    if isinstance(subject, Mapping):
        return subject.get(name)
    return getattr(subject, name, None)


def _class_save(name: str, level: int, kind: str, reference: RulesetReference, *, rules: RuleTables) -> SaveBase:
    group = rules.class_group(name)
    if group is None:
        found = reference.char_class(name)
        group = rules.class_group(found["name"]) if found else None
    if group is None:
        raise CheckError(
            f"No saving throws known for the class '{name}'.",
            hint="Put the saves on the sheet, or name a class of the ruleset.",
        )
    return SaveBase(rules.group_saves(group, level)[kind], f"{rules.saves_source}: {group} {level}")


def monster_save_level(hit_dice: str) -> int:
    """The level a monster saves at: its Hit Dice, one more with extra hit points. Under 1 HD
    ("1-2 hp", "1/2") is level 0. "1-1" is 1 HD less a point, and "4-6" (an HD range) its low end."""
    text = str(hit_dice).strip()
    low = text.lower()
    if "½" in text or "1/2" in text or re.search(r"h(p|it\s*point)", low):
        return 0
    match = re.match(r"^(\d+)\s*([+-])\s*(\d+)", text)
    if match:
        dice, sign = int(match.group(1)), match.group(2)
        return dice + 1 if sign == "+" else dice
    number = re.search(r"\d+", text)
    if number is None:
        raise CheckError(f"Can't read the Hit Dice '{hit_dice}'.", hint="Give the monster's save base yourself.")
    return int(number.group())


def save_base_for(sheet_or_monster: Any, save_type: str, reference: RulesetReference, *, rules: RuleTables) -> int:
    """The saving-throw target of a character or a monster, as a `SaveBase` that carries its `basis`.

    A character uses its sheet's saves; a save the sheet lacks comes from the ruleset's save table by class group and
    level (the reference only resolves a class name it doesn't know, such as a kit). A multi-class character uses the
    best of its classes. A monster (`hit_dice`, or a `name` the reference's monsters know, and no class) saves by its HD:
    on the ruleset's own table of monster saves (by whether it has a mind, from its `intelligence` or its entry's), else
    as the ruleset's monster group of its HD. Only a character with no class saves at 0-level.

    ttrpg2's `class_levels` save columns, copied into the reference, disagree with the save table for every class (a
    1st-level cleric has 14/16/15/17/16 there, 10/14/13/16/15 in the table), so they aren't used."""
    kind = save_type_for(save_type, rules=rules)
    on_sheet = normalize_saves(_get(sheet_or_monster, "saves"), rules=rules)
    if kind in on_sheet:
        return SaveBase(on_sheet[kind], "sheet")
    levels = class_levels(sheet_or_monster)
    hit_dice = _get(sheet_or_monster, "hit_dice")
    intelligence = _get(sheet_or_monster, "intelligence")
    monster = not levels and _get(sheet_or_monster, "kind") not in ("pc", "npc")
    if monster and (hit_dice in (None, "") or (intelligence is None and rules.monster_saves is not None)):
        name = _get(sheet_or_monster, "name")
        found = reference.monster(name) if name else []
        hit_dice = hit_dice if hit_dice not in (None, "") else (found[0].get("hit_dice") if found else None)
        intelligence = found[0].get("intelligence") if found else intelligence
    if not levels and hit_dice not in (None, ""):
        level = monster_save_level(hit_dice)
        mindless = str(intelligence or "").strip().lower().startswith(("non", "0"))
        own = rules.monster_save(level, intelligent=not mindless)
        if own is not None:
            table = "non-intelligent" if mindless else "intelligent"
            return SaveBase(own[kind], f"monster: HD {hit_dice} saves as {table} {level}")
        value = rules.group_saves(rules.monster_save_group, level)[kind]
        return SaveBase(value, f"monster: HD {hit_dice} saves as {rules.monster_save_group} {level}")
    if not levels:
        return SaveBase(rules.group_saves(rules.monster_save_group, 0)[kind], "0-level: no class on the sheet")
    bases = [_class_save(name, level, kind, reference, rules=rules) for name, level in levels.items()]
    return min(bases, key=int)


def _effect_save(effect: Any) -> int:
    return int(_get(effect, "save") or 0)


def saving_throw(
    dice: Dice,
    *,
    save_type: str,
    base: int,
    modifier: int = 0,
    effects: Iterable[Any] = (),
    actor: str | None,
    target: str | None = None,
    combat_round: int | None = None,
    rules: RuleTables,
) -> SaveResult:
    """A d20 at or above the base, with the modifier and every effect's `save` modifier added; a natural 1 fails
    whatever the modifier where the ruleset says so (`save_natural_one_fails`)."""
    kind = save_type_for(save_type, rules=rules)
    total_modifier = modifier + sum(_effect_save(effect) for effect in effects)
    needed = int(base) - total_modifier
    roll = dice.d(20, purpose=f"save:{kind}", actor=actor, target=target, combat_round=combat_round)
    return SaveResult(
        success=roll.total >= needed and not (rules.save_natural_one_fails and roll.total == 1),
        needed=needed,
        roll=roll,
        save_type=kind,
        name=rules.save_names[kind],
        base=int(base),
        modifier=total_modifier,
        basis=getattr(base, "basis", "given"),
    )


# --- percentile, ability and Constitution checks -----------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    success: bool
    needed: int
    roll: Roll
    name: str

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return (self.roll,)


def match_skill(skills: Mapping[str, Any], query: str) -> str | None:
    """The first of the sheet's skills whose name contains `query`, ignoring case, spaces and underscores."""
    wanted = query.strip().lower().replace(" ", "_")
    return next((name for name in skills if wanted in name.lower().replace(" ", "_")), None)


def _occasion(purpose: str, occasion: str) -> str:
    """A roll's purpose for one occasion: the same check again for another occasion ("jump the gap", "tie the knot")
    is a fresh roll, the same occasion again the stored one (review D-b)."""
    return f"{purpose}#{occasion}" if occasion else purpose


def skill_check(
    dice: Dice,
    *,
    skill: str,
    percent: int,
    actor: str | None,
    combat_round: int | None = None,
    occasion: str = "",
) -> CheckResult:
    """A thief's or other percentile skill: d100 at or under the percentage."""
    roll = dice.d(100, purpose=_occasion(f"skill:{skill}", occasion), actor=actor, combat_round=combat_round)
    return CheckResult(roll.total <= percent, percent, roll, skill)


def ability_check(
    dice: Dice,
    *,
    ability: str,
    score: int,
    modifier: int = 0,
    actor: str | None,
    combat_round: int | None = None,
    occasion: str = "",
) -> CheckResult:
    """A d20 at or under the ability score plus the modifier."""
    needed = score + modifier
    roll = dice.d(20, purpose=_occasion(f"ability:{ability}", occasion), actor=actor, combat_round=combat_round)
    return CheckResult(roll.total <= needed, needed, roll, ability)


def system_shock(
    dice: Dice, *, con: int, actor: str | None, combat_round: int | None = None, rules: RuleTables
) -> CheckResult:
    """A d100 at or under the Constitution's system-shock percentage. Failing it kills."""
    needed = rules.shock.get(con, rules.shock_default)
    roll = dice.d(100, purpose="system_shock", actor=actor, combat_round=combat_round)
    return CheckResult(roll.total <= needed, needed, roll, "system shock")


@dataclass(frozen=True)
class ResurrectionResult:
    success: bool
    needed: int
    roll: Roll
    con_before: int
    con_after: int
    """The Constitution after the attempt: one less, whatever the roll."""

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return (self.roll,)


def resurrection(dice: Dice, *, con: int, actor: str | None, rules: RuleTables) -> ResurrectionResult:
    """A d100 at or under the Constitution's resurrection-survival percentage. Each attempt costs a point of
    Constitution; with none left the character can't be raised."""
    if con <= 0:
        raise CheckError(f"Constitution {con}: beyond resurrection.")
    needed = rules.resurrect.get(con, rules.resurrect_default)
    roll = dice.d(100, purpose="resurrection", actor=actor)
    return ResurrectionResult(roll.total <= needed, needed, roll, con, con - 1)


# --- reaction and morale -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReactionResult:
    total: int
    band: str
    roll: Roll
    raw: int
    modifier: int
    """The modifier, disposition and reputation adjustments together."""
    disposition_applied: int
    reputation_applied: int
    description: str

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return (self.roll,)


def _towards_zero(value: int, step: int) -> int:
    return -(-value // step) if value < 0 else value // step


def disposition_modifier(disposition: int, *, rules: RuleTables) -> int:
    """An NPC's disposition (-100 … 100) as a reaction modifier: / 20, truncated towards zero (±5 at the ends)."""
    return _towards_zero(disposition, rules.disposition_step)


def reputation_modifier(reputation: int, *, rules: RuleTables) -> int:
    """A faction's reputation (-100 … 100) as a reaction modifier: / 25, truncated towards zero (±4 at the ends)."""
    return _towards_zero(reputation, rules.reputation_step)


def reaction(
    dice: Dice,
    *,
    modifier: int = 0,
    disposition: int = 0,
    reputation: int = 0,
    actor: str | None = None,
    npc: str | None = None,
    rules: RuleTables,
) -> ReactionResult:
    """The ruleset's reaction roll plus the modifier, the NPC's disposition and its faction's reputation (each divided
    by its step and truncated towards zero), read against the ruleset's bands."""
    disposition_applied = disposition_modifier(disposition, rules=rules)
    reputation_applied = reputation_modifier(reputation, rules=rules)
    total_modifier = modifier + disposition_applied + reputation_applied
    roll = dice.roll(rules.reaction_roll, purpose="reaction", actor=actor, target=npc)
    total = roll.total + total_modifier
    band, description = next(
        ((band, text) for top, band, text in rules.reaction_bands if total <= top), rules.reaction_top
    )
    return ReactionResult(
        total, band, roll, roll.total, total_modifier, disposition_applied, reputation_applied, description
    )


@dataclass(frozen=True)
class MoraleResult:
    holds: bool
    roll: Roll
    rating: int
    modifier: int
    total: int
    description: str

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return (self.roll,)


def morale(
    dice: Dice,
    *,
    rating: int,
    modifier: int = 0,
    actor: str | None,
    combat_round: int | None = None,
    rules: RuleTables | None = None,
) -> MoraleResult:
    """The ruleset's morale roll (2d10 without one) plus the modifier; morale holds at or under the rating and breaks
    above it."""
    roll = dice.roll(
        rules.morale_roll if rules is not None else "2d10", purpose="morale", actor=actor, combat_round=combat_round
    )
    total = roll.total + modifier
    holds = total <= rating
    if holds:
        description = f"Holds firm. Roll {total} does not exceed rating {rating}."
    else:
        description = f"Morale breaks! Roll {total} exceeds rating {rating}."
    return MoraleResult(holds, roll, rating, modifier, total, description)


# --- surprise ----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SurpriseResult:
    party_surprised: bool
    enemies_surprised: bool
    rolls: dict[str, Roll]
    """The d10 of each side, under `party` and `enemies`."""
    party_threshold: int
    enemy_threshold: int
    description: str

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return (self.rolls["party"], self.rolls["enemies"])


def surprise(dice: Dice, *, party_modifier: int = 0, enemy_modifier: int = 0, rules: RuleTables) -> SurpriseResult:
    """Each side rolls a d10 and is surprised on 1-3, adjusted by its own modifier: a positive modifier makes that side
    less likely to be surprised. A surprised side loses the first round; combat applies it."""
    party_threshold = max(0, rules.surprise_on - party_modifier)
    enemy_threshold = max(0, rules.surprise_on - enemy_modifier)
    party = dice.d(rules.surprise_die, purpose="surprise:party")
    enemies = dice.d(rules.surprise_die, purpose="surprise:enemies")
    party_surprised = party.total <= party_threshold
    enemies_surprised = enemies.total <= enemy_threshold
    if party_surprised and enemies_surprised:
        description = "Both sides surprised — encounter begins simultaneously, no advantage."
    elif party_surprised:
        description = "Party is surprised. The enemies act freely for one round."
    elif enemies_surprised:
        description = "Enemies are surprised. The party acts freely for one round."
    else:
        description = "Neither side surprised — roll initiative normally."
    return SurpriseResult(
        party_surprised,
        enemies_surprised,
        {"party": party, "enemies": enemies},
        party_threshold,
        enemy_threshold,
        description,
    )


# --- turning undead ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TurningResult:
    undead: str
    role: str
    caster_level: int
    effective_level: int
    level_column: str | None
    cell: str
    """The turning table's entry: a number to roll, T (turned), D (destroyed), D* (destroyed, with the ruleset's
    more) or —."""
    can_turn: bool
    needed: int | None
    turned: bool
    destroyed: bool
    count: int
    """How many undead are turned or destroyed (the ruleset's dice: 2d6 for most)."""
    extra_turned: int
    """For D*, where the ruleset has them: how many more are turned (2d4)."""
    meaning: str
    roll: Roll | None
    count_roll: Roll | None
    extra_roll: Roll | None

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return tuple(roll for roll in (self.roll, self.count_roll, self.extra_roll) if roll is not None)


_TURN_MEANINGS = {
    "—": "A priest of this level cannot turn this type.",
    "T": "Automatically turned — no d20 roll required. Affects {count} creatures.",
    "D": "Automatically destroyed (dispel). Affects {count} creatures.",
    "D*": "Automatically destroyed (dispel). Affects {count} creatures.",
}


def _turning_dice(rules: RuleTables, cell: str, undead_type: str) -> tuple[str, str | None]:
    """The dice of how many a turning affects, and of how many more it turns, for the table's `cell` and type."""
    count, extra = rules.turning_counts.get(cell if cell in _TURN_MEANINGS else "number", ("2d6", None))
    kind = undead_type.strip().lower()
    few = next((dice for name, dice in rules.turning_few.items() if kind.startswith(name)), None)
    return (few, None) if few else (count, extra)


def _undead_row(reference: RulesetReference, undead: str, hd: int) -> dict:
    rows = reference.turning_undead()
    if undead:
        needle = undead.strip().lower()
        row = next((r for r in rows if needle in [a.lower() for a in r.get("aliases") or ()]), None)
        row = row or next((r for r in rows if needle in r["undead_type"].lower()), None)
        if row is None:
            raise CheckError(f"No turning entry matching '{undead}'.", candidates=[r["undead_type"] for r in rows])
        return row
    if hd <= 0:
        raise CheckError("Provide either undead (name) or hd (hit dice).")
    row = next(
        (r for r in rows if r.get("min_hd") is not None and r["min_hd"] <= hd <= (r.get("max_hd") or r["min_hd"])),
        None,
    )
    if row is None:
        raise CheckError(
            f"No HD-based turning entry for {hd} HD.",
            hint="Zombies and ghasts have no HD bucket: look them up by name.",
            candidates=[r["undead_type"] for r in rows],
        )
    return row


def turning_undead(
    dice: Dice,
    reference: RulesetReference,
    *,
    level: int,
    undead: str = "",
    hd: int = 0,
    role: str = "priest",
    actor: str | None = None,
    combat_round: int | None = None,
    rules: RuleTables,
) -> TurningResult:
    """Turn undead by the ruleset's turning table, by name or Hit Dice. A paladin turns as a priest two levels lower. A
    number is the d20 roll needed; how many are turned or destroyed is the ruleset's (`turning_counts`)."""
    role = (role or "priest").strip().lower()
    if role not in ("priest", "paladin"):
        raise CheckError(f"Unknown role '{role}'. Use 'priest' or 'paladin'.", candidates=("priest", "paladin"))
    row = _undead_row(reference, undead, hd)
    name = row["undead_type"]
    effective = level - 2 if role == "paladin" else level
    column = rules.turning_column(effective)
    cell = row["results"][column] if column is not None else "—"
    label = rules.turning_level_columns[column] if column is not None else None
    base = {
        "undead": name,
        "role": role,
        "caster_level": level,
        "effective_level": effective,
        "level_column": label,
        "cell": cell,
    }
    if cell == "—":
        meaning = (
            _TURN_MEANINGS["—"]
            if column is not None
            else (f"{role.capitalize()} of level {level} cannot turn undead (effective turning level {effective}).")
        )
        return TurningResult(**base, can_turn=False, needed=None, turned=False, destroyed=False, count=0,
                             extra_turned=0, meaning=meaning, roll=None, count_roll=None, extra_roll=None)  # fmt: skip

    purpose = f"turn:{name.lower()}"
    keys = {"actor": actor, "combat_round": combat_round}
    roll = needed = None
    count_dice, extra_dice = _turning_dice(rules, cell, name)
    if cell in _TURN_MEANINGS:
        meaning = _TURN_MEANINGS[cell].format(count=count_dice)
        if extra_dice:
            meaning += f" An additional {extra_dice} of that type are turned."
        works = True
    else:
        needed = int(cell)
        meaning = f"Roll 1d20; on a result of {cell} or higher, {count_dice} of these undead are turned and flee."
        roll = dice.d(20, purpose=purpose, **keys)
        works = roll.total >= needed
    count_roll = dice.roll(count_dice, purpose=f"{purpose}:count", **keys) if works else None
    extra_roll = dice.roll(extra_dice, purpose=f"{purpose}:extra", **keys) if works and extra_dice else None
    destroyed = works and cell.startswith("D")
    return TurningResult(
        **base,
        can_turn=True,
        needed=needed,
        turned=works and not destroyed,
        destroyed=destroyed,
        count=count_roll.total if count_roll else 0,
        extra_turned=extra_roll.total if extra_roll else 0,
        meaning=meaning,
        roll=roll,
        count_roll=count_roll,
        extra_roll=extra_roll,
    )


# --- encounters --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EncounterResult:
    terrain: str
    triggered: bool
    check: Roll
    die: int
    threshold: int
    interval: str
    """How often the check is made in this terrain: "10m", "4h", "1h 30m"."""
    party_level: int
    tier: str = ""
    drift: str = ""
    """How the 2d6 drift moved the tier: "down" on a 2, "up" on a 12, else "none"."""
    drift_roll: int | None = None
    table_roll: int | None = None
    result: str = ""
    category: str = ""
    monster: str = ""
    note: str = ""
    number: str = ""
    """How many come, when the ruleset's tables say."""
    drift_dice: Roll | None = None
    table: Roll | None = None
    more: tuple[Roll, ...] = ()
    """The rolls of a ruleset's own determination (`Encounters`), or the count of a module table's line."""
    source: str = "ruleset"
    """Whose table determined it: "ruleset", "module" (the module's own wandering table), or "" when none did yet."""
    table_id: str = ""
    table_name: str = ""
    """The module table rolled on, or the one that applies where the party is when the check brings nothing."""
    creature: str = ""
    """The module line's creature, as its ref (`monster:giant-rat`)."""
    choose: tuple[dict[str, Any], ...] = ()
    """The module's tables to choose from (`WanderingTable.to_json`), when more than one may apply where the party is:
    the check came up and waits for the DM to name one."""

    @property
    def all_rolls(self) -> tuple[Roll, ...]:
        return tuple(roll for roll in (self.check, self.drift_dice, self.table) if roll is not None) + self.more


def _module_encounter(dice: Dice, found: dict[str, Any], table: WanderingTable, occasion: str) -> EncounterResult:
    """A line of the module's own table, rolled with its die, and the count of a line that gives dice."""
    named = {"source": "module", "table_id": table.id, "table_name": table.name}
    notation = table.dice
    if notation is None:
        lines = "; ".join(f"{row.roll}: {row.result or row.creature}" for row in table.rows)
        return EncounterResult(
            **found, triggered=True, **named, note=f"The table's rolls aren't plain numbers: pick its line. {lines}"
        )
    rolled = dice.roll(notation, purpose=_occasion("encounter:table", occasion))
    row = table.line(rolled.total)
    if row is None:
        return EncounterResult(
            **found, triggered=True, **named, table=rolled, table_roll=rolled.total,
            note=f"No line of the table takes {rolled.total}: nothing comes.",
        )  # fmt: skip
    count = dice.roll(row.count, purpose=_occasion("encounter:count", occasion)) if countable(row.count) else None
    monster = row.creature.split(":", 1)[1].replace("-", " ") if ":" in row.creature else row.creature
    return EncounterResult(
        **found,
        triggered=True,
        **named,
        table=rolled,
        table_roll=rolled.total,
        result=row.result or " ".join(part for part in (row.count, monster) if part),
        category=row.category,
        monster=monster,
        creature=row.creature,
        number=str(count.total) if count is not None else row.count,
        note=row.notes,
        more=(count,) if count is not None else (),
    )


def _interval(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def _band(level: int, bands: list[dict]) -> int:
    for i, band in enumerate(bands):
        low, high = band.get("party_levels", [1, 99])
        if low <= level <= high:
            return i
    return len(bands) - 1


WORLD_TAG = re.compile(
    r"\((athas|cerilia|krynn|mystara|kara-tur|toril|oerth|zakhara|savage coast|maztica|ravenloft|aebrynis)\)",
    re.IGNORECASE,
)
"""A world an encounter entry names as its own: "Human (Cerilia), Brecht (Tradesman)"."""


def _of_world(entries: list[dict], world: str) -> list[dict]:
    """The tier's entries that may come in `world` (all of them without one): untagged, or of that world; their
    ranges laid end to end again, each as wide as it was, so the die runs over what is left."""
    if not world:
        return entries
    kept = [
        e
        for e in entries
        if not (tag := WORLD_TAG.search(f"{e.get('result', '')} {e.get('monster', '')}"))
        or tag.group(1).lower() == world.lower()
    ]
    if not kept or len(kept) == len(entries):
        return entries
    out, low = [], 1
    for e in kept:
        width = e["range"][1] - e["range"][0] + 1
        out.append({**e, "range": [low, low + width - 1]})
        low += width
    return out


def _nearest_tier(tiers: list[list[dict]], index: int) -> int | None:
    if not tiers:
        return None
    index = max(0, min(len(tiers) - 1, index))
    for distance in range(len(tiers)):
        for j in (index - distance, index + distance):
            if 0 <= j < len(tiers) and tiers[j]:
                return j
    return None


def encounter_check(
    dice: Dice,
    reference: RulesetReference,
    *,
    terrain: str,
    level: int = 0,
    dungeon_level: int = 0,
    occasion: str = "",
    rules: RuleTables,
    encounters: Encounters | None = None,
    module_table: WanderingTable | None = None,
    choose: Iterable[WanderingTable] = (),
    world: str = "",
) -> EncounterResult:
    """Check for a random encounter and, when one comes, determine it from the module's own table (`module_table`,
    DEL-321), else from the tiered encounter tables. With tables to `choose` from it determines nothing and names them.

    The check is a d6 (a d20 in towns) at or under 1. The party's level (`level`, else `dungeon_level`, else 1) picks
    a band; a 2d6 drift of 2 steps down a band and 12 up, to the nearest tier with entries; then one exact die over
    the tier's ranges picks the entry, as ttrpg2's `check_encounter` and `determine_encounter`. Each `occasion` (the
    game time of the check) rolls its own. With the campaign's `world` ("oerth"), an entry of another world ("Human
    (Cerilia)") is left out, and the die runs over the rest (DEL-337)."""
    check_key = terrain.strip().lower()
    config = rules.encounter_checks.get(check_key, rules.encounter_check_default)
    key = TERRAIN_ALIASES.get(check_key, check_key)
    party_level = level or dungeon_level or 1
    check = dice.d(config["die"], purpose=_occasion("encounter:check", occasion))
    found = {
        "terrain": key,
        "check": check,
        "die": config["die"],
        "threshold": config["threshold"],
        "interval": _interval(config["interval_minutes"]),
        "party_level": party_level,
    }
    if module_table is not None and not module_table.rows:
        return EncounterResult(
            **found, triggered=False, source="module", table_id=module_table.id, table_name=module_table.name,
            note="The module has no wandering monsters here.",
        )  # fmt: skip
    if check.total > config["threshold"]:
        if module_table is not None:
            return EncounterResult(**found, triggered=False, table_id=module_table.id, table_name=module_table.name)
        return EncounterResult(**found, triggered=False)
    options = tuple(choose)
    if options:
        return EncounterResult(
            **found,
            triggered=True,
            source="",
            choose=tuple(option.to_json() for option in options),
            note="The module has more than one wandering table that may apply here: call encounter_check again with "
            "the table for where the party is (table=<id>), or table='ruleset' for the ruleset's.",
        )
    if module_table is not None:
        return _module_encounter(dice, found, module_table, occasion)
    if encounters is not None:
        met = encounters.determine(
            dice, terrain=key, party_level=party_level, dungeon_level=dungeon_level, occasion=occasion
        )
        if met is None:
            return EncounterResult(**found, triggered=True, note=f"No encounter table for terrain '{key}'.")
        return EncounterResult(
            **found,
            triggered=True,
            tier=met.tier,
            result=met.result,
            category=met.category,
            monster=met.monster,
            number=met.number,
            note=met.note,
            more=met.rolls,
        )

    data = reference.encounter_tables() or {}
    terrains = data.get("terrains", {})
    if key not in terrains:
        return EncounterResult(**found, triggered=True, note=f"No encounter table for terrain '{key}'.")
    bands = data.get("bands", [])
    drift_dice = dice.roll("2d6", purpose=_occasion("encounter:drift", occasion))
    step = -1 if drift_dice.total == 2 else (1 if drift_dice.total == 12 else 0)
    tiers = terrains[key].get("tiers", [])
    index = _nearest_tier(tiers, _band(party_level, bands) + step)
    if index is None:
        return EncounterResult(
            **found, triggered=True, drift_dice=drift_dice, drift_roll=drift_dice.total,
            note=f"No populated encounter tier for '{key}'.",
        )  # fmt: skip
    entries = _of_world(tiers[index], world)
    table = dice.table(max(entry["range"][1] for entry in entries), purpose=_occasion("encounter:table", occasion))
    entry = next((e for e in entries if e["range"][0] <= table.total <= e["range"][1]), entries[-1])
    return EncounterResult(
        **found,
        triggered=True,
        tier=bands[index]["name"] if index < len(bands) else str(index),
        drift="down" if step < 0 else ("up" if step > 0 else "none"),
        drift_roll=drift_dice.total,
        table_roll=table.total,
        result=entry.get("result", "Unknown"),
        category=entry.get("category", ""),
        monster=entry.get("monster", ""),
        drift_dice=drift_dice,
        table=table,
    )
