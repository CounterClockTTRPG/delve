"""Spell loadouts (spec §7.8): the spells a caster knows and memorizes by default, what is memorized now, and what
has been cast.

A spell is named as the reference names it, ignoring case; an unknown name raises `NotFound` with the reference's
near names. The slots of each level (`Sheet.spell_slots`) cap the default loadout and what is memorized. A cast marks
one memorized spell until the next rest (`play.characters.rest`), which makes them uncast again or, with
`rememorize`, memorizes the default.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from delve.domain.campaigns import Character
from delve.domain.characters import MemorizedSpell, SpellLoadout
from delve.domain.reference import name_key
from delve.play.characters import get
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.rules.classic import spells as rules

__all__ = ["cast", "memorize", "set_loadout", "spell_status"]


def _by_level(spells: Iterable[MemorizedSpell]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for spell in sorted(spells, key=lambda s: s.level):
        out.setdefault(str(spell.level), []).append(spell.name)
    return out


def _level(level: Any) -> int:
    try:
        number = int(level)
    except (TypeError, ValueError):
        raise PlayError(f"Bad spell level {level!r}.", hint="Spell levels are 1 to 9.") from None
    if not 1 <= number <= 9:
        raise PlayError(f"Bad spell level {level!r}.", hint="Spell levels are 1 to 9.")
    return number


def _resolve(ctx: CampaignContext, name: str, kind: str, caster: Character | None = None) -> tuple[str, int]:
    """(the reference's spelling, the level) of the spell `name`: under a d20 engine the level the engine names for
    `caster` (ruling R16), else the classic reference's by the `kind` list."""
    if ctx.d20 is not None and caster is not None:
        return _resolve_d20(ctx, name, caster)
    try:
        return rules.level_of(ctx.lookups, name, kind)
    except rules.UnknownSpell as unknown:
        raise NotFound(str(unknown), unknown.candidates, hint="Name a spell as the reference has it.") from None


def _resolve_d20(ctx: CampaignContext, name: str, caster: Character) -> tuple[str, int]:
    """The spell by its exact name (ignoring case and the apostrophe's shape) and its level for `caster` by the
    engine; `NotFound` with the near names for an unknown one, and for one on none of the caster's lists."""
    wanted = name_key(name)
    rows = ctx.lookups.spell(name) if wanted else []
    row = next((row for row in rows if name_key(row["name"]) == wanted), None)
    if row is None:
        raise NotFound(
            f"No spell '{name}'.", [{"name": r["name"]} for r in rows], hint="Name a spell as the reference has it."
        )
    level = ctx.d20.spell_level(caster.sheet, row["name"])  # type: ignore[union-attr]
    if level is None:
        raise NotFound(
            f"{row['name']} is on none of {caster.name}'s spell lists.", hint="Name a spell of the caster's lists."
        )
    return row["name"], level


def _spell_map(
    ctx: CampaignContext, raw: Mapping[Any, Iterable[str]], kind: str, caster: Character | None = None
) -> dict[int, tuple[str, ...]]:
    """`{level: [names]}` with every name as the reference spells it. The level is the one given, as ttrpg2."""
    out: dict[int, tuple[str, ...]] = {}
    for level, names in raw.items():
        if isinstance(names, str):
            raise PlayError(f"Level {level}: expected a list of spell names, got {names!r}.")
        spelled = tuple(_resolve(ctx, str(name), kind, caster)[0] for name in names)
        if spelled:
            out[_level(level)] = spelled
    return dict(sorted(out.items()))


def _check(character: Character, levels: Iterable[int]) -> None:
    try:
        rules.check_slots(levels, character.sheet.spell_slots)
    except rules.SlotsExceeded as over:
        raise PlayError(str(over), hint=f"{character.name}'s slots: {_slots(character)}.") from None


def _kind(ctx: CampaignContext, character: Character) -> str:
    """The spell list the caster draws from: the classic tables name it, a d20 engine has no such lists."""
    return "" if ctx.d20 is not None else rules.caster_kind(character.sheet.cls, rules=ctx.rules)


def _allowed(ctx: CampaignContext, character: Character, levels: Iterable[int], names: Sequence[str] = ()) -> None:
    """Refuse levels the caster can't hold: by the sheet's slots, or under a d20 engine by what it says."""
    if ctx.d20 is not None:
        refusal = ctx.d20.can_memorize(character.sheet, list(levels), list(names))
        if refusal:
            raise PlayError(refusal)
        return
    _check(character, levels)


def _slots(character: Character) -> str:
    slots = character.sheet.spell_slots
    return ", ".join(f"level {level}: {slots[level]}" for level in sorted(slots)) or "none"


def _loadout_json(loadout: SpellLoadout) -> dict[str, Any]:
    return {
        "known": {str(level): list(names) for level, names in loadout.known.items()},
        "default": {str(level): list(names) for level, names in loadout.default.items()},
    }


def set_loadout(
    ctx: CampaignContext,
    ref: str,
    *,
    known: Mapping[Any, Iterable[str]] | None = None,
    default: Mapping[Any, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Set the spells a caster knows and the ones it memorizes by default, each as `{level: [names]}`. What isn't
    given stays as it was. The default has at most the slots of each level."""
    character = get(ctx, ref)
    kind = _kind(ctx, character)
    loadout = character.sheet.spell_loadout
    if known is not None:
        loadout = replace(loadout, known=_spell_map(ctx, known, kind, character))
    if default is not None:
        loadout = replace(loadout, default=_spell_map(ctx, default, kind, character))
        _allowed(
            ctx,
            character,
            [level for level, names in loadout.default.items() for _ in names],
            [name for names in loadout.default.values() for name in names],
        )
    ctx.storage.characters.save_sheet(replace(character, sheet=replace(character.sheet, spell_loadout=loadout)))
    out = _loadout_json(loadout)
    ctx.log("spell_loadout", character_id=character.id, name=character.name, **out)
    return {"character_id": character.id, "name": character.name, **out}


def memorize(ctx: CampaignContext, ref: str, spells: list[str] | None = None) -> dict[str, Any]:
    """Memorize spells, all uncast, in place of what was memorized. `None` memorizes the default loadout.

    A named spell takes its level from the caster's loadout, else from the reference by the caster's list (a priest's
    Hold Person is 2nd level, a wizard's 3rd)."""
    character = get(ctx, ref)
    if spells is None:
        memorized = rules.default_memorized(character.sheet)
        if not memorized:
            raise PlayError(f"{character.name} has no default loadout.", hint="Set one with set_spell_loadout.")
    else:
        kind = _kind(ctx, character)
        loadout = character.sheet.spell_loadout
        levels = {
            name.lower(): level
            for book in (loadout.known, loadout.default)
            for level, names in book.items()
            for name in names
        }
        chosen = []
        for name in spells:
            spelled, level = _resolve(ctx, name, kind, character)
            chosen.append(MemorizedSpell(spelled, levels.get(spelled.lower(), level)))
        memorized = tuple(chosen)
    if ctx.d20 is None and not character.sheet.spell_slots:
        raise PlayError(f"{character.name} has no spell slots.", hint="Give the sheet spell_slots first.")
    _allowed(ctx, character, [s.level for s in memorized], [s.name for s in memorized])
    ctx.storage.characters.save_state(replace(character, state=replace(character.state, memorized=memorized)))
    by_level = _by_level(memorized)
    ctx.log("spells_memorized", character_id=character.id, name=character.name, by_level=by_level)
    return {
        "character_id": character.id,
        "name": character.name,
        "memorized": [s.name for s in memorized],
        "by_level": by_level,
    }


def _remaining(memorized: Iterable[MemorizedSpell]) -> dict[str, int]:
    return {str(level): n for level, n in rules.remaining(memorized).items()}


def cast(ctx: CampaignContext, ref: str, spell: str) -> dict[str, Any]:
    """Cast a memorized spell: its first uncast copy is spent until the next rest. Under a d20 engine a caster with
    no spell slots casts through the engine instead, and its refusal is a `PlayError`; a memorized copy keeps the
    engine's report beside core's keys, and one refused or failed says `lost: True` (it was begun, so it is used)."""
    character = get(ctx, ref)
    wanted = spell.strip().lower()
    memorized = character.state.memorized
    at = next((i for i, s in enumerate(memorized) if s.name.lower() == wanted and not s.cast), None)
    if at is None and ctx.d20 is not None and not character.sheet.spell_slots:
        return _cast_d20(ctx, character, spell)
    if at is None:
        if any(s.name.lower() == wanted for s in memorized):
            raise PlayError(
                f"'{spell}' has already been cast: every memorized copy is spent.", hint="Spells come back with rest."
            )
        available = sorted({s.name for s in memorized if not s.cast})
        raise PlayError(
            f"'{spell}' is not memorized by {character.name}.",
            hint=f"Memorized and uncast: {', '.join(available) or 'nothing'}.",
        )
    spent = replace(memorized[at], cast=True)
    memorized = (*memorized[:at], spent, *memorized[at + 1 :])
    state = replace(character.state, memorized=memorized)
    said: dict[str, Any] = {}
    if ctx.d20 is not None:
        state, said = ctx.d20.cast(character.sheet, state, spent.name, spent.level, dice=ctx.dice, actor=character.id)
        lost = said.get("cast") is False or "refusal" in said  # the copy was begun, so it is used (R6)
        said = {key: value for key, value in said.items() if key != "cast"} | ({"lost": True} if lost else {})
    ctx.storage.characters.save_state(replace(character, state=state))
    ctx.log("spell_cast", character_id=character.id, name=character.name, spell=spent.name, level=spent.level)
    return {
        **said,
        "character_id": character.id,
        "name": character.name,
        "spell": spent.name,
        "level": spent.level,
        "remaining": _remaining(state.memorized),
    }


def _cast_d20(ctx: CampaignContext, character: Character, spell: str) -> dict[str, Any]:
    """A per-day caster's cast: the engine names the spell's level for the caster and spends from its pool; a spell
    off the caster's lists, or a refusal, raises."""
    spelled, level = _resolve(ctx, spell, "", character)
    state, said = ctx.d20.cast(character.sheet, character.state, spelled, level, dice=ctx.dice, actor=character.id)
    if said.get("cast") is False:
        raise PlayError(str(said.get("refusal") or f"{character.name} can't cast {spelled}."))
    ctx.storage.characters.save_state(replace(character, state=state))
    ctx.log("spell_cast", character_id=character.id, name=character.name, spell=spelled, level=level)
    return {"character_id": character.id, "name": character.name, "spell": spelled, "level": level, **said}


def spell_status(ctx: CampaignContext, ref: str) -> dict[str, Any]:
    """A caster's loadout, what is memorized (cast or not), and per level its slots, memorized and uncast spells."""
    character = get(ctx, ref)
    memorized = character.state.memorized
    remaining = rules.remaining(memorized)
    counts: dict[int, int] = {}
    for spell in memorized:
        counts[spell.level] = counts.get(spell.level, 0) + 1
    levels = sorted({*character.sheet.spell_slots, *counts})
    return {
        "character_id": character.id,
        "name": character.name,
        "loadout": _loadout_json(character.sheet.spell_loadout),
        "memorized": [{"name": s.name, "level": s.level, "cast": s.cast} for s in memorized],
        "available": [s.name for s in memorized if not s.cast],
        "spent": [s.name for s in memorized if s.cast],
        "slots": {
            str(level): {
                "max": character.sheet.spell_slots.get(level, 0),
                "memorized": counts.get(level, 0),
                "remaining": remaining.get(level, 0),
            }
            for level in levels
        },
    }
