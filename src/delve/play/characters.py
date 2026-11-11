"""Characters, NPCs and the party (spec §7.8): creation, lookup, damage and healing, XP, coin, rest and NPCs.

Every function takes the `CampaignContext` of the tool call first, writes through storage and logs an event. A
character is named by its id or by its exact name, ignoring case; a name that fits several characters, or none, raises
`NotFound` with the candidates. There is no prefix matching: "Gob" never means "Goblin 1".
"""

from __future__ import annotations

import json
import re
from dataclasses import fields, replace
from typing import Any

from delve.domain.campaigns import COINS, Character
from delve.domain.characters import CharacterState, Kind, MemorizedSpell, Sheet
from delve.domain.data import DataError
from delve.play import house_rules
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.play.days import answer, pass_days
from delve.rules.classic import checks, class_xp, names, spells
from delve.rules.classic.life import DEAD_AT, life_conditions

__all__ = [
    "NotFound",
    "PlayError",
    "apply_damage",
    "apply_heal",
    "award_xp",
    "create",
    "drain_level",
    "get",
    "introduce_npc",
    "party",
    "rest",
    "set_disposition",
    "set_marching_order",
    "update",
    "update_coin",
]

# Warrior classes get the parenthetical (higher) Constitution HP bonus (PHB Table 6).
_WARRIOR_CLASSES = ("fighter", "paladin", "ranger", "barbarian")

# ttrpg2's disposition bands, from the most positive: the floor of each band and its label.
_DISPOSITION_BANDS = (
    (61, "Devoted ally"),
    (21, "Friendly"),
    (6, "Cordial"),
    (-5, "Neutral"),
    (-20, "Wary"),
    (-60, "Hostile"),
)

_SHEET_FIELDS = tuple(f.name for f in fields(Sheet) if f.name not in ("label", "kind"))
_STATE_FIELDS = tuple(f.name for f in fields(CharacterState))


def _fight():
    """`delve.play.combat`, imported here because it imports this module: a character in a live fight is changed
    through the fight's tracker, so the end of the fight doesn't undo it."""
    from delve.play import combat

    return combat


def _candidate(character: Character) -> dict[str, Any]:
    return {"id": character.id, "name": character.name, "kind": character.kind}


def get(ctx: CampaignContext, ref: str) -> Character:
    """The character with the id `ref`, or the one whose name is exactly `ref` (ignoring case and outer spaces)."""
    wanted = ref.strip()
    everyone = ctx.storage.characters.list(ctx.campaign_id)
    for character in everyone:
        if character.id == wanted:
            return character
    named = [c for c in everyone if c.name.strip().casefold() == wanted.casefold()]
    if len(named) == 1:
        return named[0]
    if named:
        raise NotFound(f"'{ref}' is ambiguous: {len(named)} characters have that name.", map(_candidate, named))
    near = [c for c in everyone if wanted.casefold() and wanted.casefold() in c.name.casefold()]
    raise NotFound(f"No character '{ref}'.", map(_candidate, near or everyone))


def _sheet(ctx: CampaignContext, raw: dict[str, Any]) -> Sheet:
    """The sheet, its saves under their long names (`para` is stored as `paralysis_poison_death`)."""
    try:
        sheet = Sheet.from_dict(raw)
    except DataError as error:
        raise PlayError(f"Bad sheet: {error}", hint=f"The sheet's fields are {', '.join(_SHEET_FIELDS)}.") from None
    saves = {ctx.rules.save_aliases.get(kind.strip().lower(), kind): value for kind, value in sheet.saves.items()}
    return replace(sheet, saves=saves)


def _levels(sheet: Sheet, level: Any) -> dict[str, int]:
    """The sheet's `levels`, checked against its classes; from a single `level` (default 1) when it has none."""
    classes = class_xp.component_classes(sheet.cls)
    if not sheet.levels:
        if level is not None and (isinstance(level, bool) or not isinstance(level, int)):
            raise PlayError(f"Bad sheet: level: expected a whole number, got {level!r}")
        return {c: level or 1 for c in classes}
    levels = {name.strip().lower(): value for name, value in sheet.levels.items()}
    if classes and set(levels) != set(classes):
        raise PlayError(
            f"levels must name every class of '{sheet.cls}': {', '.join(classes)}.",
            hint='For a Fighter/Thief: {"fighter": 1, "thief": 2}.',
        )
    return levels


def _fill_thac0(ctx: CampaignContext, sheet: Sheet) -> Sheet:
    """The sheet with its THAC0 from the class tables: the best of its classes at their levels. A sheet whose classes
    the tables don't know keeps its own."""
    found = []
    for cls, level in sheet.levels.items():
        rows = ctx.lookups.class_levels(cls)
        row = next((r for r in rows if r.get("level") == level), None)
        if row is not None and row.get("thac0") is not None:
            found.append(int(row["thac0"]))
    return replace(sheet, thac0=min(found)) if found else sheet


def _fill_saves(ctx: CampaignContext, sheet: Sheet) -> Sheet:
    """The sheet with its missing saves from the ruleset's save table by class and level. A classless character keeps
    them missing, so a save says it is made at 0-level; so does a class the table doesn't know."""
    if not sheet.cls:
        return sheet
    saves = dict(sheet.saves)
    for kind in ctx.rules.save_types:
        if kind not in saves:
            try:
                saves[kind] = int(checks.save_base_for(replace(sheet, saves={}), kind, ctx.lookups, rules=ctx.rules))
            except checks.CheckError:
                return sheet
    return replace(sheet, saves=saves)


def create(ctx: CampaignContext, *, name: str = "", kind: Kind = "pc", sheet: dict[str, Any]) -> Character:
    """A new PC (at the back of the marching order) or NPC, at full hit points.

    `sheet` has the fields of `Sheet`, and may give a single `level` for every class instead of `levels`. Saves, a
    THAC0 and spell slots the sheet doesn't give come from the class tables (slots with the ruleset's Wisdom bonus).
    A given name is kept (trimmed); without one, the dice name the character for its sheet's race and gender, as `introduce_npc` does."""
    if kind not in ("pc", "npc"):
        raise PlayError(f"Unknown kind '{kind}'.", hint="Use pc or npc.")
    raw = dict(sheet)
    level = raw.pop("level", None)
    raw.pop("label", None)
    raw["kind"] = kind
    parsed = _sheet(ctx, raw)
    parsed = _fill_saves(ctx, replace(parsed, levels=_levels(parsed, level)))
    if "thac0" not in raw:
        parsed = _fill_thac0(ctx, parsed)
    if not parsed.spell_slots:
        parsed = replace(parsed, spell_slots=_table_slots(ctx, parsed.levels, parsed))
    name = name.strip() or names.generate(
        ctx.dice.rng, race=parsed.race, female=parsed.gender.strip().lower() == "female"
    )
    character = ctx.storage.characters.create(
        ctx.campaign_id, name, kind=kind, sheet=parsed, state=CharacterState(hp=parsed.hp_max)
    )
    ctx.log("character_created", character_id=character.id, name=character.name, kind=kind)
    return character


def update(ctx: CampaignContext, ref: str, patch: dict[str, Any], reason: str = "") -> Character:
    """Change a character: `name`, any field of its sheet, and `hp`, `xp`, `conditions` or `effects` of its state.

    A single-class character may take `level`; a multi-class one gives `levels` for every class."""
    character = get(ctx, ref)
    patch = dict(patch)
    unknown = sorted(set(patch) - {"name", "level", *_SHEET_FIELDS, *_STATE_FIELDS})
    if unknown:
        raise PlayError(
            f"Can't change '{unknown[0]}'.",
            hint=f"Change name, level, a sheet field ({', '.join(_SHEET_FIELDS)}) or hp, xp, conditions, effects.",
        )
    name = str(patch.pop("name", character.name)).strip() or character.name
    level = patch.pop("level", None)
    sheet_patch = {k: v for k, v in patch.items() if k in _SHEET_FIELDS}
    state_patch = {k: v for k, v in patch.items() if k in _STATE_FIELDS}
    sheet = _sheet(ctx, {**character.sheet.to_dict(), **sheet_patch, "label": name})
    if level is not None:
        if class_xp.is_multiclass(sheet):
            raise PlayError(
                f"{name} is multi-class: give levels for each class, not one level.",
                hint=f"levels: {{{', '.join(f'{c!r}: …' for c in class_xp.component_classes(sheet.cls))}}}",
            )
        sheet = replace(sheet, levels={})
    if "levels" in sheet_patch or level is not None or "cls" in sheet_patch:
        sheet = replace(sheet, levels=_levels(sheet, level))
        had = {k: v for k, v in character.sheet.spell_slots.items() if v}
        if "spell_slots" not in sheet_patch and had in ({}, _table_slots(ctx, character.sheet.levels, character.sheet)):
            sheet = replace(sheet, spell_slots=_table_slots(ctx, sheet.levels, sheet))  # the table's, at the new level
    try:
        state = CharacterState.from_dict({**character.state.to_dict(), **state_patch})
    except DataError as error:
        raise PlayError(f"Bad state: {error}") from None
    if "hp" in state_patch:  # a raise that sets hit points clears dead; setting conditions alone keeps them as given
        state = replace(state, conditions=life_conditions(state.conditions, state.hp))
    saved = ctx.storage.characters.save(replace(character, name=name, sheet=sheet, state=state))
    if state_patch:
        _fight().mirror(ctx, saved)
    if {"attacks", "weapon", "thac0", "levels", "cls"} & sheet_patch.keys() or level is not None:
        _fight().rearm(ctx, saved)
    changed = {*sheet_patch, *state_patch, *(["level"] if level is not None else [])}
    if name != character.name:
        changed.add("name")
    ctx.log("character_updated", character_id=saved.id, name=saved.name, fields=sorted(changed), reason=reason)
    return saved


def party(ctx: CampaignContext) -> list[Character]:
    """The PCs in the party, front of the marching order first: not those that left it (`delve.play.departures`)."""
    pcs = [c for c in ctx.storage.characters.list(ctx.campaign_id) if c.kind == "pc" and c.departure is None]
    return sorted(pcs, key=lambda c: (c.order is None, c.order if c.order is not None else 0))


def set_marching_order(ctx: CampaignContext, refs: list[str]) -> list[Character]:
    """Put the named PCs at the front, in that order; the others fall in behind in their current order."""
    front: list[Character] = []
    for ref in refs:
        character = get(ctx, ref)
        if character.kind != "pc":
            raise PlayError(f"{character.name} is an NPC, not in the marching order.")
        if character.id not in {c.id for c in front}:
            front.append(character)
    ordered = front + [c for c in party(ctx) if c.id not in {f.id for f in front}]
    saved = []
    for position, character in enumerate(ordered):
        saved.append(
            character
            if character.order == position
            else ctx.storage.characters.save(replace(character, order=position))
        )
    ctx.log("marching_order", order=[c.name for c in saved], ids=[c.id for c in saved])
    return saved


def _amount(amount: Any) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise PlayError(f"The amount must be a whole number of at least 0, not {amount!r}.")
    return amount


def apply_damage(ctx: CampaignContext, ref: str, amount: int) -> dict[str, Any]:
    """Take hit points off a character, to no less than -10 (dead). At 0 or below it is downed, at -10 dead
    (`life_conditions`). A character in the
    live fight takes it through the fight's tracker (`in_combat`)."""
    character = get(ctx, ref)
    amount = _amount(amount)
    fought = _fight().tracked_damage(ctx, character, amount)
    if fought is not None:
        return fought
    before = character.state.hp
    after = max(before - amount, DEAD_AT)
    slain = ctx.rules.fight.unconscious_slain_by_damage and amount > 0 and DEAD_AT < before <= 0
    if slain:
        after = DEAD_AT  # the ruleset's: any damage to someone unconscious kills at once
    conditions = life_conditions(character.state.conditions, after)
    ctx.storage.characters.save_state(
        replace(character, state=replace(character.state, hp=after, conditions=conditions))
    )
    ctx.log("damage", character_id=character.id, name=character.name, amount=amount, hp_before=before, hp_after=after)
    return {
        "character_id": character.id,
        "name": character.name,
        "damage": amount,
        "hp_before": before,
        "hp_after": after,
        "downed": after <= 0,
        "dead": after <= DEAD_AT,
        **({"slain_while_unconscious": True} if slain else {}),
    }


def apply_heal(ctx: CampaignContext, ref: str, amount: int) -> dict[str, Any]:
    """Give a character hit points, up to its maximum. Above 0 it is no longer downed. A character in the live fight
    is healed through the fight's tracker (`in_combat`).

    The dead (-10 or below) are not healed: PHB ch. 9 and DMG ch. 9 (Death's Door) make -10 death, which only magic
    such as raise dead or resurrection reverses."""
    character = get(ctx, ref)
    amount = _amount(amount)
    fought = _fight().tracked_heal(ctx, character, amount)
    if fought is not None:
        return fought
    before = character.state.hp
    if before <= DEAD_AT:
        raise PlayError(
            f"{character.name} is dead (HP {before}); healing doesn't raise the dead.",
            hint="Use raise dead or resurrection (with resurrection_check), then set hp with update_character.",
        )
    after = min(before + amount, character.sheet.hp_max)
    conditions = life_conditions(character.state.conditions, after)
    ctx.storage.characters.save_state(
        replace(character, state=replace(character.state, hp=after, conditions=conditions))
    )
    ctx.log("heal", character_id=character.id, name=character.name, amount=amount, hp_before=before, hp_after=after)
    return {
        "character_id": character.id,
        "name": character.name,
        "healed": after - before,
        "hp_before": before,
        "hp_after": after,
    }


def award_xp(ctx: CampaignContext, ref: str, amount: int) -> dict[str, Any]:
    """Add XP. A multi-class character's award is split evenly between its classes (PHB ch. 3): `per_class` has each
    class's share, level and next threshold, and `level_up_hints` names each class whose share crossed one. The level
    itself changes only through `update`. When a hint fires, `house_rules` has the campaign's level-up rules (spec
    §9)."""
    character = get(ctx, ref)
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise PlayError(f"The XP must be a whole number, not {amount!r}.")
    bonus, bonus_basis = _xp_bonus(ctx, character.sheet, amount) if ctx.rules.xp_bonus else (0, [])
    before = character.state.xp
    after = before + amount + bonus
    ctx.storage.characters.save_state(replace(character, state=replace(character.state, xp=after)))
    hints = class_xp.level_up_hints(character.sheet, before, after, ctx.lookups, rules=ctx.rules)
    per_class = [
        {k: row[k] for k in ("class", "level", "xp", "xp_next", "ready")}
        for row in class_xp.progress(character.sheet, after, ctx.lookups, rules=ctx.rules)
    ]
    ctx.log(
        "xp_awarded", character_id=character.id, name=character.name, amount=amount + bonus, xp_total=after, hints=hints
    )
    out = {
        "character_id": character.id,
        "name": character.name,
        "xp_gained": amount + bonus,
        "xp_total": after,
        "per_class": per_class,
        "level_up_hints": hints,
    }
    if bonus:
        out["xp_awarded"] = amount
        out["xp_bonus"] = bonus
        out["xp_bonus_basis"] = bonus_basis
    if hints:
        out["house_rules"] = house_rules.given(ctx, house_rules.level_up_rules(ctx, character))
    return out


_ABILITY_KEYS = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis",
                 "charisma": "cha"}  # fmt: skip


def _score(sheet: Sheet, ability: str) -> int | None:
    """The sheet's whole score in `ability` ("strength"): 18 for "18/50"; None when it has none."""
    short = _ABILITY_KEYS.get(ability.lower(), ability.lower()[:3])
    raw = sheet.ability_scores.get(short, sheet.ability_scores.get(ability.lower()))
    found = re.match(r"\s*(\d+)", str(raw)) if raw is not None else None
    return int(found.group(1)) if found else None


def _xp_bonus(ctx: CampaignContext, sheet: Sheet, amount: int) -> tuple[int, list[str]]:
    """The prime-requisite bonus on `amount` (OSRIC: 10% for a class whose prime requisites are all at their
    threshold), and what earned it. A multi-class character's share of each class takes that class's bonus."""
    classes = list(sheet.levels) or [c.strip() for c in sheet.cls.split("/") if c.strip()]
    if amount <= 0 or not classes:
        return 0, []
    share = amount / len(classes)
    bonus, basis = 0.0, []
    for cls in classes:
        found = ctx.lookups.char_class(cls) or {}
        wanted = found.get("xp_bonus_requisites") or {}
        scores = {ability: _score(sheet, ability) for ability in wanted}
        if wanted and all(scores[a] is not None and scores[a] >= low for a, low in wanted.items()):
            bonus += share / 10
            have = ", ".join(f"{a.capitalize()} {sheet.ability_scores.get(_ABILITY_KEYS.get(a, a[:3]), scores[a])}"
                             for a in wanted)  # fmt: skip
            basis.append(f"+10% for {found.get('name') or cls} ({have})")
    return int(bonus), basis


_HIT_DICE = re.compile(r"^\s*(\d+)\s*d\s*(\d+)\s*(?:\+\s*(\d+))?\s*$", re.IGNORECASE)


def _level_row(ctx: CampaignContext, cls: str, level: int) -> dict[str, Any]:
    """The class tables' row of `cls` at `level`; {} when they don't have it."""
    rows = ctx.lookups.class_levels(cls)
    return next((r for r in rows if r.get("level") == level), {})


def _table_slots(ctx: CampaignContext, levels: dict[str, int], sheet: Sheet | None = None) -> dict[int, int]:
    """The spell slots the class tables give these class levels, by spell level, without the empty ones. A row has
    them as '{"1": 2, "2": 0}' (2e) or a list from 1st level up (OSRIC). With the `sheet`, a class of the ruleset's
    `bonus_spell_classes` adds Wisdom's bonus spells of the levels it can cast."""
    slots: dict[int, int] = {}
    for cls, level in levels.items():
        own = _class_slots(ctx, cls, level)
        if sheet is not None and ctx.rules.class_group(cls) in ctx.rules.bonus_spell_classes:
            wisdom = _score(sheet, "wisdom")
            bonus = next((b for score, b in sorted(ctx.rules.bonus_spells.items(), reverse=True)
                          if wisdom is not None and wisdom >= score), {})  # fmt: skip
            for spell_level, count in bonus.items():
                if int(spell_level) in own:
                    own[int(spell_level)] += count
        for spell_level, count in own.items():
            slots[spell_level] = slots.get(spell_level, 0) + count
    return slots


def _class_slots(ctx: CampaignContext, cls: str, level: int) -> dict[int, int]:
    """The spell slots one class's table gives at `level`, by spell level, without the empty ones."""
    slots: dict[int, int] = {}
    raw = _level_row(ctx, cls, level).get("spell_slots")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if isinstance(raw, list):
        raw = dict(enumerate(raw, start=1))
    for spell_level, count in (raw if isinstance(raw, dict) else {}).items():
        if isinstance(count, int) and count > 0:
            slots[int(spell_level)] = slots.get(int(spell_level), 0) + count
    return slots


def _table_saves(ctx: CampaignContext, sheet: Sheet) -> dict[str, int]:
    """The saves the save table gives the sheet's classes at their levels; {} when it doesn't know them."""
    try:
        return {
            kind: int(checks.save_base_for(replace(sheet, saves={}), kind, ctx.lookups, rules=ctx.rules))
            for kind in ctx.rules.save_types
        }
    except checks.CheckError:
        return {}


def _drained_hp(ctx: CampaignContext, character: Character, cls: str, level: int) -> int:
    """The hit points the level `level` of `cls` gave (DMG ch. 9, Energy Drain): its hit die rolled with the
    Constitution bonus, or the set hit points of a level past the class's last die; the sheet's average per level
    when the class tables don't say."""
    old = _HIT_DICE.match(str(_level_row(ctx, cls, level).get("hit_dice") or ""))
    new = _HIT_DICE.match(str(_level_row(ctx, cls, level - 1).get("hit_dice") or "")) if level > 1 else None
    if old and (new or level == 1):
        dice = int(old[1]) - (int(new[1]) if new else 0)
        if dice > 0:
            rolled = ctx.dice.roll(f"{dice}d{old[2]}", purpose=f"drain:hp:{character.name}").total
            return max(1, rolled + dice * _con_hp_bonus(ctx, character.sheet))
        return max(0, int(old[3] or 0) - (int(new[3] or 0) if new else 0))
    return max(1, character.sheet.hp_max // max(sum(character.sheet.levels.values()), 1))


def _drained_class(ctx: CampaignContext, levels: dict[str, int]) -> str:
    """The class that loses the level: the highest; of equal ones, the one whose level needs more XP (2e) or one at
    random (OSRIC)."""
    top = max(levels.values())
    tied = [cls for cls, level in levels.items() if level == top]
    if len(tied) == 1:
        return tied[0]
    if ctx.rules.level_drain.tie == "random":
        return tied[ctx.dice.roll(f"1d{len(tied)}", purpose="drain:class").total - 1]

    def needed(cls: str) -> int:
        table = class_xp.xp_table(cls, ctx.lookups, rules=ctx.rules)
        return table[top - 1] if 0 < top <= len(table) else 0

    return max(tied, key=needed)


def _drained_xp(ctx: CampaignContext, levels: dict[str, int], xp: int, drained: set[str]) -> int:
    """The XP total after a drain: each drained class's share down to where the ruleset puts it at its new level
    (`LevelDrain.xp`), 0 at 0-level; never up."""
    shares = []
    for cls in drained:
        table = class_xp.xp_table(cls, ctx.lookups, rules=ctx.rules)
        level = levels[cls]
        if level < 1:
            shares.append(0)
        elif level <= len(table):
            midpoint = ctx.rules.level_drain.xp == "midpoint" and level < len(table)
            shares.append((table[level - 1] + table[level]) // 2 if midpoint else table[level - 1])
    return min(xp, min(shares) * max(len(levels), 1)) if shares else xp


def _within_slots(memorized: tuple[MemorizedSpell, ...], slots: dict[int, int]) -> tuple[MemorizedSpell, ...]:
    """The memorized spells that still fit `slots`, the uncast ones kept first."""
    kept: list[MemorizedSpell] = []
    for spell in sorted(memorized, key=lambda s: s.cast):
        if sum(1 for k in kept if k.level == spell.level) < slots.get(spell.level, 0):
            kept.append(spell)
    return tuple(s for s in memorized if s in kept)


def drain_level(ctx: CampaignContext, ref: str, levels: int = 1, reason: str = "") -> dict[str, Any]:
    """An energy drain (DMG ch. 9; OSRIC Player's Guide §1.6.7): the character loses `levels` levels, each from its
    highest class (`_drained_class`). Each takes the hit points that level gave off the maximum, and the XP drops as
    the ruleset says. The THAC0, saves and spell slots that came from the class tables become the new level's; ones
    set otherwise on the sheet stay, named in `kept`. Spells memorized past the new slots are forgotten.

    Drained below 1st level, the character dies; in 2e one drained from 1st level lives on at 0-level, an ordinary
    person, and dies at the next drain (`LevelDrain.zero_level`)."""
    character = get(ctx, ref)
    if isinstance(levels, bool) or not isinstance(levels, int) or levels < 1:
        raise PlayError(f"levels must be a whole number of 1 or more, not {levels!r}.")
    sheet, state = character.sheet, character.state
    if not sheet.levels:
        raise PlayError(f"{character.name} has no class levels to drain.", hint="A monster loses a Hit Die instead.")
    if state.hp <= DEAD_AT:
        raise PlayError(f"{character.name} is already dead (HP {state.hp}).")
    now = dict(sheet.levels)
    hp_lost, drained, slain = 0, set(), False
    for _ in range(levels):
        cls = _drained_class(ctx, now)
        if now[cls] < 1 or (now[cls] == 1 and not ctx.rules.level_drain.zero_level):
            slain = True
            break
        hp_lost += _drained_hp(ctx, character, cls, now[cls])
        now[cls] -= 1
        drained.add(cls)
    after = replace(sheet, levels=now, hp_max=max(1, sheet.hp_max - hp_lost))
    zero = min(now.values()) < 1
    kept = []
    was = _fill_thac0(ctx, replace(sheet, thac0=0)).thac0
    if was == sheet.thac0:
        after = replace(after, thac0=20) if zero else _fill_thac0(ctx, after)
    elif was:
        kept.append("thac0")
    table_saves = _table_saves(ctx, sheet)
    new_saves = {} if zero else _table_saves(ctx, after)
    saves = dict(sheet.saves)
    for kind, value in sheet.saves.items():
        if table_saves.get(kind) == value and kind in new_saves:
            saves[kind] = new_saves[kind]
        elif kind in table_saves:
            kept.append(f"saves.{kind}")
    after = replace(after, saves=saves)
    if sheet.spell_slots:
        if {k: v for k, v in sheet.spell_slots.items() if v} == _table_slots(ctx, sheet.levels, sheet):
            after = replace(after, spell_slots=_table_slots(ctx, now, sheet))
        else:
            kept.append("spell_slots")
    memorized = _within_slots(state.memorized, after.spell_slots)
    xp = _drained_xp(ctx, now, state.xp, drained)
    hp = DEAD_AT if slain else min(state.hp, after.hp_max)
    conditions = life_conditions(state.conditions, hp)
    state_after = replace(state, hp=hp, xp=xp, memorized=memorized, conditions=conditions)
    saved = ctx.storage.characters.save(replace(character, sheet=after, state=state_after))
    _fight().drained(ctx, saved, after.thac0 - sheet.thac0)
    ctx.log(
        "level_drained",
        character_id=saved.id,
        name=saved.name,
        levels=levels,
        levels_after=now,
        hp_lost=hp_lost,
        slain=slain,
        reason=reason,
    )
    out: dict[str, Any] = {
        "character_id": saved.id,
        "name": saved.name,
        "levels_before": dict(sheet.levels),
        "levels_after": now,
        "hp_max_before": sheet.hp_max,
        "hp_max_after": after.hp_max,
        "hp": hp,
        "xp_before": state.xp,
        "xp_after": xp,
        "thac0": after.thac0,
        "saves": after.saves,
        "spell_slots": after.spell_slots,
    }
    if len(memorized) < len(state.memorized):
        out["spells_forgotten"] = [s.name for s in state.memorized if s not in memorized]
    if kept:
        out["kept"] = kept
        out["kept_note"] = "Set on the sheet, not from the class tables: change them with update_character if need be."
    if slain:
        out["slain"] = True
        out["note"] = "Drained below 1st level: dead. The monster's entry says whether and when the victim rises."
    elif zero:
        out["note"] = (
            "0-level: an ordinary person without class abilities until restoration or a wish; another drain slays."
        )
    return out


_COIN_DELTA = re.compile(r"^([+-]?\d+)\s*(pp|gp|ep|sp|cp)$")


def update_coin(ctx: CampaignContext, delta: str) -> dict[str, Any]:
    """Add or take the party's coin: "+450pp", "+50gp", "-10sp", "+3ep", "+100cp"."""
    match = _COIN_DELTA.match(delta.strip().lower())
    if not match:
        raise PlayError(
            f"Cannot parse coin delta '{delta}'.", hint="Expected format: +450pp, +50gp, -10sp, +3ep, +100cp."
        )
    amount, coin = int(match.group(1)), match.group(2)
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    purse = {**dict.fromkeys(COINS, 0), **state.coin}
    purse[coin] += amount
    ctx.storage.campaign_states.put(replace(state, coin=purse))
    ctx.log("coin", delta=delta.strip(), coin=purse)
    return {"delta": delta.strip(), "coin": purse}


def _con_hp_bonus(ctx: CampaignContext, sheet: Sheet) -> int:
    """The per-level Constitution hit-point bonus (PHB Table 6), for the weekly bed-rest bonus. Warriors get the
    bracketed value. 0 when the Constitution is unknown."""
    con = sheet.ability_scores.get("con") or sheet.ability_scores.get("constitution")
    if con is None:
        return 0
    adjust = str((ctx.lookups.ability("constitution", str(con)).get("values") or {}).get("hp_adj", "0"))
    warrior = any(k in sheet.cls.lower() for k in _WARRIOR_CLASSES)
    bracketed = re.search(r"\(([+-]?\d+)\)", adjust)
    if warrior and bracketed:
        return int(bracketed.group(1))
    plain = re.match(r"\s*([+-]?\d+)", adjust)
    return int(plain.group(1)) if plain else 0


def rest(
    ctx: CampaignContext,
    ref: str = "",
    days: int = 1,
    bed_rest: bool = False,
    full: bool = False,
    rememorize: bool = False,
) -> dict[str, Any]:
    """Rest for some days, healing at the ruleset's natural rate (`RuleTables.healing`). The engine's own, as ttrpg2's
    `rest`: 1 hp per day of light activity, 3 per day of complete bed rest, and the Constitution hit-point bonus for
    each full week of bed rest. A ruleset may have no bed rest, delay healing by a Constitution penalty, add the bonus
    once over the second week, and heal anyone fully after some weeks. The dead don't heal. `full` is the DM's
    override to restore everyone living to maximum, not the book rule. A character in the live fight rests in its tracker too, as `update` does.

    A rest of a day or more makes every memorized spell uncast again, as ttrpg2's; with `rememorize` a caster with a
    default loadout memorizes it instead (PHB ch. 7: spells are memorized after a night's rest).

    `ref` names one character; without it the whole party rests, and a rest of a day or more lets its days pass
    (`days.pass_days`), keeping the time of day. One character resting doesn't move the clock."""
    days = max(0, int(days))
    resting = [get(ctx, ref)] if ref else party(ctx)
    rates = ctx.rules.healing
    bed_rest = bed_rest and rates.bed_rest_per_day is not None
    rate = rates.bed_rest_per_day if bed_rest and rates.bed_rest_per_day is not None else rates.per_day
    healing: dict[str, dict[str, Any]] = {}
    rememorized: dict[str, list[str]] = {}
    for character in resting:
        hp_max, before = character.sheet.hp_max, character.state.hp
        con_bonus = 0
        if before <= DEAD_AT:  # neither rest nor the DM's override raises the dead, as `apply_heal` doesn't
            after = before
        elif full:
            after = hp_max
        elif rates.full_after_days is not None and days >= rates.full_after_days:
            after = max(before, hp_max)
        else:
            con = _con_hp_bonus(ctx, character.sheet)
            delay = -con if rates.con_penalty_delays and con < 0 else 0
            gained = rate * max(0, days - delay)
            if rates.con_bonus == "bed_rest_weekly" and bed_rest and days >= 7:
                con_bonus = con * (days // 7)
            elif rates.con_bonus == "second_week" and days >= 14 and con > 0:
                con_bonus = con
            gained += con_bonus
            after = min(hp_max, max(before, before + gained))
        conditions = life_conditions(character.state.conditions, after)
        memorized = character.state.memorized
        if days >= 1:
            default = spells.default_memorized(character.sheet) if rememorize else ()
            memorized = default or spells.uncast(memorized)
            if default:
                rememorized[character.name] = [s.name for s in default]
        state = replace(character.state, hp=after, conditions=conditions, memorized=memorized)
        saved = ctx.storage.characters.save_state(replace(character, state=state))
        _fight().mirror(ctx, saved)  # else the live fight's next write-through puts its old hit points back
        report = {"hp_before": before, "hp_after": after, "healed": after - before, "at_max": after >= hp_max}
        if con_bonus:
            report["con_weekly_bonus"] = con_bonus
        healing[character.name] = report

    if full:
        basis = "DM override — restored to maximum (not the PHB rate)."
    else:
        basis = f"{rate} hp/day x {days} day(s)" + (
            " (complete bed rest)" if bed_rest else " (light activity)" if rates.bed_rest_per_day else " (rest)"
        )
        if rates.full_after_days is not None and days >= rates.full_after_days:
            basis += f"; {rates.full_after_days} days of rest heal fully"
    out: dict[str, Any] = {
        "rested": list(healing),
        "days": days,
        "rate_per_day": rate,
        "basis": basis,
        "healing": healing,
    }
    still_hurt = [name for name, report in healing.items() if not report["at_max"]]
    if still_hurt and not full:
        out["still_wounded"] = still_hurt
    if rememorized:
        out["memorized"] = rememorized
    casters = [c.name for c in resting if c.sheet.spell_slots and c.name not in rememorized]
    if days >= 1 and casters:
        out["reminder"] = f"Spells are uncast again. Call memorize_spells to change what {', '.join(casters)} memorize."
    ctx.log("rest", days=days, bed_rest=bed_rest, full=full, healing=healing)
    if not ref and days >= 1:
        out.update(answer(pass_days(ctx, days, reason="rest")))
    return out


def introduce_npc(
    ctx: CampaignContext, *, race: str, gender: str = "", description: str = "", faction: str = ""
) -> Character:
    """A new NPC, named for its race by `names.generate` with this beat's dice. `description` is its role or look
    ("innkeeper", "guard captain"); `faction` the id of the faction it belongs to."""
    name = names.generate(ctx.dice.rng, race=race, female=gender.strip().lower() == "female")
    character = ctx.storage.characters.create(
        ctx.campaign_id,
        name,
        kind="npc",
        sheet=Sheet(kind="npc", race=race, gender=gender, background=description, faction=faction),
    )
    ctx.log("npc_met", character_id=character.id, name=name, race=race, notes=description)
    return character


def disposition_band(value: int) -> str:
    """The label of a disposition (-100 … 100): "Devoted ally" … "Sworn enemy"."""
    return next((label for floor, label in _DISPOSITION_BANDS if value >= floor), "Sworn enemy")


def set_disposition(ctx: CampaignContext, ref: str, value: int, reason: str = "") -> dict[str, Any]:
    """Set an NPC's disposition towards the party, -100 (sworn enemy) to 100 (devoted ally). It becomes a reaction
    modifier of disposition / 20, truncated towards zero."""
    character = get(ctx, ref)
    if character.kind != "npc":
        raise PlayError(f"{character.name} is a PC; only NPCs have a disposition.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlayError(f"The disposition must be a whole number from -100 to 100, not {value!r}.")
    before = character.sheet.disposition
    after = max(-100, min(100, value))
    ctx.storage.characters.save_sheet(replace(character, sheet=replace(character.sheet, disposition=after)))
    ctx.log(
        "disposition_change",
        character_id=character.id,
        name=character.name,
        before=before,
        after=after,
        notes=reason or f"disposition {before:+d} → {after:+d}",
    )
    return {
        "character_id": character.id,
        "name": character.name,
        "before": before,
        "after": after,
        "band": disposition_band(after),
        "modifier_applied_to_reaction": checks.disposition_modifier(after, rules=ctx.rules),
    }
