"""The class features a character uses (DEL-389): `use_feature`'s handlers, one function per feature id in `USES`,
so a later part adds its features (a prestige class's) as entries; and the rules the engine reads of them in a fight:
the smite on a swing, rage's bonus on Fortitude and Will saves, and the monk's flurry of blows on its attack forms.

What a character has spent since its last rest is in `CharacterState.d20["used"]` (`{"rage": 1, "lay-on-hands": 3}`;
bardic music, which inspire courage spends, is `"bardic-music"`); `progress.rest` clears it, but for the uses a week
(remove disease), which only a rest of 7 days or more clears. A barbarian's rage is in
`CharacterState.d20["rage"]` (the hit points it added, and whether they went on the sheet's maximum or the
combatant's), and `Combatant.d20["raging"]` in a fight; a paladin's smite waiting for its swing is
`Combatant.d20["smite"]` (its to-hit and damage); a druid's wild shape is `CharacterState.d20["shape"]`, which
`combat.shaped` reads. Core counts an effect down and lets it expire with no hook for a
pack, so a rage is ended through `use_feature(character, "rage", amount=-1)`, which takes the hit points off and
leaves the barbarian fatigued.

Only the pack's tools module imports core's play layer (`tests/packs/test_pack_imports.py`): it hands
`delve.play.characters` and `delve.play.combat` to `use_feature`, and the engine (`combat`) reads the rules here with
no campaign being played."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from delve.domain.characters import Sheet
from delve.rules.classic import combat as rules
from delve.rules.classic.checks import CheckError
from delve.rules.classic.life import with_condition
from delve_srd35.engine import attack_line, companions, features, items, numbers

Context = Any
"""A `delve.play.context.CampaignContext`."""

END = -1
"""`amount` that ends a feature under way (a rage)."""
RAGE_AC = 2
"""Rage's -2 AC, at every level (greater and mighty rage raise only the Str, Con and Will bonuses)."""
RAGE_FIRST = {"str": 4, "con": 4, "will": 2}
"""Rage's bonuses at 1st level (the rage row's `bonuses` has them by level): what a raging mark without its numbers
reads."""
TIRELESS = "tireless-rage"
FATIGUED = "fatigued"
EXHAUSTED = "exhausted"
RAGE_FATIGUE = "rage_fatigue"
"""The key in a combatant's `d20` marking the fatigue its rage left in the fight (`end_rage`), which lasts "for the
rest of the encounter" and so comes off at its end (`tools._end_combat`), unlike a fatigue the DM gave."""
MONK_WEAPONS = frozenset({"unarmed-strike", "kama", "nunchaku", "quarterstaff", "sai", "shuriken-5", "siangham"})
"""The unarmed strike and the special monk weapons, which a monk flurries with."""
SIDES = ("party", "ally")
ELEMENTAL = "wild-shape-elemental"
"""Where a druid's elemental wild shapes are counted in `CharacterState.d20["used"]`, apart from her ordinary ones."""


# --- the rules the engine reads ----------------------------------------------------------------------------------


RAGE_EFFECT = "Rage"
"""The name of the effect `rage` puts on (its -2 AC), which core counts down and lets expire."""
RUN_OUT = "Rage has run out: call use_feature(rage, amount=-1)."
"""The swing's note for a barbarian whose Rage effect expired while the state still says raging."""
RAGE_SAVES = ("fort", "will")
"""The saves rage raises: Fortitude by its Con bonus's modifier (+2 of +4), Will by its morale bonus (+2)."""


def rage_numbers(sheet: Sheet | None) -> dict[str, int]:
    """Rage's Str, Con and Will bonuses at the sheet's barbarian level, the rage row's `bonuses`: +4, +4 and +2; greater
    rage (11th) +6, +6 and +3; mighty rage (20th) +8, +8 and +4. The 1st level's without a sheet or a rage."""
    found = None if sheet is None else _granted(sheet, "rage")
    if sheet is None or found is None:
        return dict(RAGE_FIRST)
    row = _row(found["class"], "rage")
    return dict(features.at_level(row.get("bonuses") or {}, sheet.levels.get(found["class"], 0)) or RAGE_FIRST)


def _rage_of(d20: Mapping[str, Any] | None, sheet: Sheet | None) -> dict[str, int]:
    """The raging numbers: a combatant's `d20["rage_bonus"]` (`combat.combatant_from_sheet` and `rage` put them there),
    else the sheet's (`rage_numbers`), else the 1st level's."""
    held = (d20 or {}).get("rage_bonus")
    return dict(held) if isinstance(held, Mapping) else rage_numbers(sheet)


def raging(d20: Mapping[str, Any] | None, effects: Iterable[Any]) -> bool:
    """Whether rage's numbers count: the rage's mark (`Combatant.d20["raging"]` or `CharacterState.d20["rage"]`)
    and the Rage effect still on (`effects`, the combatant's or the character's). Core lets the effect expire after
    3 + Con rounds with no hook for a pack, so a mark without the effect counts for nothing (`rage_ran_out`)."""
    d20 = d20 or {}
    return bool(d20.get("raging") or d20.get("rage")) and any(e.name == RAGE_EFFECT for e in effects)


def rage_ran_out(d20: Mapping[str, Any] | None, effects: Iterable[Any]) -> bool:
    """Whether the mark says raging but the Rage effect has expired: the DM is to end the rage."""
    d20 = d20 or {}
    return bool(d20.get("raging") or d20.get("rage")) and not any(e.name == RAGE_EFFECT for e in effects)


def rage_save(d20: Mapping[str, Any] | None, save: str, effects: Iterable[Any], sheet: Sheet | None = None) -> int:
    """Rage's bonus on a Fortitude save (its Con bonus's modifier: +2, +3 with greater rage, +4 with mighty) and on a
    Will save (its morale bonus: +2, +3, +4), while raging (`raging`), by the combatant's `d20` or else the character's
    `sheet` (`_rage_of`); 0 on Reflex, or when not raging."""
    if save not in RAGE_SAVES or not raging(d20, effects):
        return 0
    bonus = _rage_of(d20, sheet)
    return bonus["con"] // 2 if save == "fort" else bonus["will"]


FATIGUE = 2
"""What fatigue takes off Strength and Dexterity (the SRD's -2 each)."""

EXHAUSTION = 6
"""What exhaustion takes off Strength and Dexterity (the SRD's -6 each); it also halves speed."""


def penalty_of(conditions: Iterable[str]) -> int:
    """What the conditions take off Str and Dex: exhaustion's 6, else fatigue's 2, else 0 (exhausted replaces
    fatigued: the two are not added)."""
    held = set(conditions)
    return EXHAUSTION if EXHAUSTED in held else FATIGUE if FATIGUED in held else 0


def tired(sheet: Sheet, penalty: int = FATIGUE) -> Sheet:
    """The sheet as a fatigued character's (`penalty` 2) or an exhausted one's (6, and half speed): that much off its
    Str and Dex scores, and its stored derived numbers dropped so they are made again from those (the combatant's AC,
    Ref, attacks and damage; a save's or a check's)."""
    scores = {**sheet.ability_scores, **{a: numbers.base_score(sheet, a) - penalty for a in ("str", "dex")}}
    d20 = {key: value for key, value in (sheet.d20 or {}).items() if key != "derived"}
    if penalty >= EXHAUSTION:
        d20["exhausted"] = True  # numbers.derived halves the speed
        sheet = replace(sheet, movement_rate=sheet.movement_rate // 2)
    return replace(sheet, ability_scores=scores, d20=d20)


def monster_row(target: rules.Combatant) -> Mapping[str, Any] | None:
    """The target's monster row: by its `d20["monster"]` id (`combat.combatant_from_monster` puts it there), else by
    the name it was added under (`group`, which a label overrides: "Orc raiders"); None for a character."""
    for name in (str((target.d20 or {}).get("monster") or ""), target.group):
        if name.strip() and (row := companions.monster(name)) is not None:
            return row
    return None


def aligned(target: rules.Combatant, word: str) -> bool:
    """Whether the target's alignment has `word` ("evil", "good"): its `d20["alignment"]` when it has one, else its
    monster row's (`monster_row`); a character's is unknown here, and counts as not having it."""
    theirs = target.d20 or {}
    alignment = str(theirs.get("alignment") or (monster_row(target) or {}).get("alignment") or "")
    return word in alignment.lower()


def evil(target: rules.Combatant) -> bool:
    """Whether the target's alignment has "evil" (`aligned`)."""
    return aligned(target, "evil")


def smite(
    mine: Mapping[str, Any], form: Mapping[str, Any], target: rules.Combatant
) -> tuple[int, int, str | None, bool]:
    """The waiting smite's to-hit and damage on this swing, the swing's note, and whether the swing spends it. The SRD
    gives it to "one normal melee attack": a ranged or a spell's touch swing leaves it waiting for a melee one, with
    a note. A melee swing spends it, on a target that isn't evil to no effect (a blackguard's smite good, `against`
    "good": one that isn't good). (0, 0, None, False) with none."""
    waiting = mine.get("smite")
    if not waiting:
        return 0, 0, None, False
    word = str(waiting.get("against") or "evil")
    if form.get("ranged") or form.get("touch"):
        return 0, 0, f"smite {word} waits for a melee attack: not on this one", False
    if not aligned(target, word):
        return 0, 0, f"smite {word}: {target.name} isn't {word}, no effect; the smite is spent", True
    to_hit, damage = int(waiting.get("to_hit", 0)), int(waiting.get("damage", 0))
    return to_hit, damage, f"smite {word}: {to_hit:+d} to hit, {damage:+d} damage", True


def _granted(sheet: Sheet, fid: str) -> dict[str, Any] | None:
    return next((f for f in features.granted(sheet) if f["id"] == fid), None)


def _row(cls: str, fid: str) -> dict[str, Any]:
    return next(r for r in features.rows(cls) if r["id"] == fid)


def flurry_refusal(sheet: Sheet, form: Mapping[str, Any] | None) -> str | None:
    """Why the sheet's monk can't flurry with the form it holds, or None: only a monk, without armour or a shield, and
    with an unarmed strike or a special monk weapon."""
    if _granted(sheet, "flurry-of-blows") is None:
        return f"{sheet.label or 'It'} has no flurry of blows: only a monk flurries."
    build = sheet.d20 or {}
    if build.get("armor") or build.get("shield"):
        return "A monk flurries only without armour and without a shield."
    if form is None or _monk_weapon(form) is None:
        return "A monk flurries with an unarmed strike or a special monk weapon (kama, nunchaku, quarterstaff, sai, " \
               "shuriken, siangham)."  # fmt: skip
    return None


def _monk_weapon(form: Mapping[str, Any]) -> str | None:
    found = attack_line.weapon(str(form.get("name") or ""))
    return found["id"] if found is not None and found["id"] in MONK_WEAPONS else None


def flurried(sheet: Sheet, forms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The forms with the monk's flurry of blows on each it flurries with: its penalty at the monk's level on the
    bonus (-2 to 4th, -1 to 8th, none from 9th) and its extra attacks (one, two from 11th: greater flurry) on the count,
    which holds her iterative attacks by her BAB too, the penalty kept as `flurry` for the swing's note and, on an
    iterative form, the extra attacks as `flurry_extra` (at the full bonus, before the iterative ones). The forms as
    they are where the monk can't flurry (`flurry_refusal`)."""
    found = _granted(sheet, "flurry-of-blows")
    if found is None or (sheet.d20 or {}).get("armor") or (sheet.d20 or {}).get("shield"):
        return forms
    level = sheet.levels.get(found["class"], 0)
    row = _row(found["class"], "flurry-of-blows")
    penalty = int(features.at_level(row["by_level"], level) or 0)
    extra = int(features.at_level(row.get("extra_attacks") or {}, level) or 0)
    out = []
    for form in forms:
        if form.get("touch") or _monk_weapon(form) is None:
            out.append(form)
        else:
            flurried = {**form, "bonus": form["bonus"] + penalty, "count": form["count"] + extra, "flurry": penalty}
            if form.get("iterative"):  # her extra attacks at the full bonus, her iterative ones after them
                flurried["flurry_extra"] = extra
            out.append(flurried)
    return out


# --- use_feature -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Use:
    """One use_feature call: the character (`delve.domain.campaigns.Character`), its granted feature (`granted`'s
    shape, `per_day` filled), and the call's target and amount."""

    ctx: Context
    who: Any
    feature: dict[str, Any]
    target: str
    amount: int
    characters: Any
    """`delve.play.characters`, which the pack's tools module passes in (only it imports core's play layer)."""
    combat: Any
    """`delve.play.combat`."""


def _who(character: Any) -> dict[str, Any]:
    return {"character_id": character.id, "character": character.name}


def _derived(ctx: Context, sheet: Sheet) -> dict[str, Any]:
    return numbers.stored(sheet, ctx.lookups)


def _feature(ctx: Context, who: Any, asked: str) -> dict[str, Any]:
    """The character's granted feature by id or name, with its uses a day; refused for one no class has, or one the
    character's classes don't give. A feature whose row `spends` another's uses (every bardic music performance,
    inspire courage among them, spends one of bardic music's) has that feature's uses a day."""
    fid = numbers.slug(asked)
    if fid not in USES:
        raise CheckError(f"Unknown feature '{asked}'.", hint=f"use_feature takes {', '.join(USES)}.")
    found = next((f for f in _derived(ctx, who.sheet).get("features") or () if f["id"] == fid), None)
    if found is None:
        name = fid.replace("-", " ").capitalize()
        raise CheckError(f"{who.name} hasn't {name}: no class level of theirs gives it.")
    # The row is the source: a sheet whose stored derived numbers predate `spends` reads it there.
    if spent := found.get("spends") or _row(found["class"], fid).get("spends"):
        spends = next((f for f in _derived(ctx, who.sheet)["features"] if f["id"] == spent), None)
        found = {**found, "per_day": (spends or {}).get("per_day") or 0, "spends": spent,
                 "spends_name": (spends or {}).get("name", "")}  # fmt: skip
    return found


def _used(who: Any, key: str) -> int:
    return int(((who.state.d20 or {}).get("used") or {}).get(key, 0))


def _check_uses(use: Use) -> int:
    """The feature's uses left, refused when there are none: "Rage: 1 a day at this level, used 1." """
    key = use.feature.get("spends", use.feature["id"])
    per_day, used = int(use.feature.get("per_day") or 0), _used(use.who, key)
    if used >= per_day:
        name = use.feature.get("spends_name") or use.feature["name"]
        if use.feature.get("per") == "week":
            raise CheckError(f"{name}: {per_day} a week at this level, used {used}.",
                             hint="They come back with a rest of 7 days.")  # fmt: skip
        raise CheckError(f"{name}: {per_day} a day at this level, used {used}.", hint="They come back with rest.")
    return per_day - used


def _state(use: Use, change: Callable[[dict[str, Any]], dict[str, Any]], **fields: Any) -> Any:
    """The character as stored now with `change` made to its `CharacterState.d20` (and `fields` on its state), saved
    straight to storage: engine-owned state, as core writes an effect (no state patch, so no fight is mirrored)."""
    character = use.ctx.storage.characters.get(use.who.id)
    state = replace(character.state, d20=change(dict(character.state.d20 or {})), **fields)
    return use.ctx.storage.characters.save_state(replace(character, state=state))


def _spend(use: Use, n: int = 1) -> None:
    key = use.feature.get("spends", use.feature["id"])

    def change(d20: dict[str, Any]) -> dict[str, Any]:
        used = dict(d20.get("used") or {})
        used[key] = int(used.get(key, 0)) + n
        return {**d20, "used": used}

    _state(use, change)


def _live(ctx: Context) -> tuple[str, rules.Combat] | None:
    live = ctx.storage.combats.live(ctx.campaign_id)
    return None if live is None else (live[0], rules.from_json(live[1]))


def _put(ctx: Context, id: str, fight: rules.Combat, c: rules.Combatant) -> None:
    fight = replace(fight, combatants={**fight.combatants, c.id: c})
    ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))


def _fighting(use: Use) -> tuple[str, rules.Combat, rules.Combatant] | None:
    """The live fight and the character's combatant in it; None when it isn't fighting."""
    live = _live(use.ctx)
    if live is None or use.who.id not in live[1].combatants:
        return None
    return live[0], live[1], live[1].combatants[use.who.id]


def rage(use: Use) -> dict[str, Any]:
    """Rage (barbarian): +4 Str and Con, +2 on Will saves, -2 AC, for 3 + the new Con modifier rounds; greater rage
    (11th) +6, +6, +3 and mighty rage (20th) +8, +8, +4 (`rage_numbers`). As an Effect "Rage" (source "rage") for its
    `ac`, +2 in core's classic sign (2 easier to hit), with no to-hit or damage: the Str comes in the swing by the
    attack (`rage_strength`). Half the Con bonus in hit points per Hit Die (racial and class: `numbers.character_level`)
    on the current hit points and on the sheet's maximum (and a fighting combatant's); the Fort and Will bonuses from
    the rage's mark (`rage_save`). Refused while the barbarian is fatigued (which also keeps it to once an encounter),
    unless a 17th level's tireless rage. Indomitable will (14th), +4 on Will against enchantment while raging, is said,
    not applied."""
    if use.amount == END:
        return end_rage(use)
    if use.amount:
        raise CheckError("Rage takes no amount: amount=-1 ends it.")
    if (use.who.state.d20 or {}).get("rage"):
        raise CheckError(f"{use.who.name} is already raging.", hint="use_feature with amount=-1 ends the rage.")
    left = _check_uses(use)
    if _fatigued(use) and _granted(use.who.sheet, TIRELESS) is None:
        raise CheckError(f"{use.who.name} is fatigued: a barbarian can't rage again until it passes.",
                         hint="A night's rest (rest, days=1) ends fatigue.")  # fmt: skip
    characters, combat = use.characters, use.combat
    sheet = use.who.sheet
    bonus = rage_numbers(sheet)
    con = numbers.modifier(numbers.ability_score(sheet, "con") + bonus["con"])
    rounds = max(1, 3 + con)
    gained = bonus["con"] // 2 * max(1, numbers.character_level(sheet, use.ctx.lookups))
    applied = combat.apply_effect(use.ctx, use.who.id, "Rage", rounds, ac=RAGE_AC, source="rage")
    # The maximum always goes on the sheet (a sheet patch alone: no fight is mirrored), so a fight made later has it
    # and the end takes it off one maximum, whichever fight the rage ends in.
    who = characters.get(use.ctx, use.who.id)
    characters.update(use.ctx, who.id, {"hp_max": who.sheet.hp_max + gained}, reason="rage")
    fighting = _fighting(use)
    if fighting is not None:
        id, fight, c = fighting
        hp = c.hp + gained
        d20 = {**(c.d20 or {}), "raging": True, "rage_bonus": bonus}
        _put(use.ctx, id, fight, replace(c, hp=hp, hp_max=c.hp_max + gained, d20=d20))
    else:
        hp = who.state.hp + gained
        characters.update(use.ctx, who.id, {"hp": hp}, reason="rage")
    _state(use, lambda d20: {**d20, "rage": {"hp": gained}})
    _spend(use)
    fatigue = "" if _granted(sheet, TIRELESS) else f" It leaves {use.who.name} fatigued when it ends."
    fort, will, strength = bonus["con"] // 2, bonus["will"], bonus["str"] // 2
    saves = (
        f"+{fort} on Fortitude and Will saves" if fort == will else f"+{fort} on Fortitude and +{will} on Will saves"
    )
    lasts = (
        f"{saves} while raging (the effect's save stays 0); +{strength} on melee attack rolls, +{strength} damage "
        f"in melee and thrown (+{strength * 3 // 2} two-handed), by the swing. Rage lasts {rounds} rounds: when it "
        f"ends, or {use.who.name} stops early, call use_feature(rage, amount=-1), which takes the {gained} hp off "
        f"again; a rest ends it too.{fatigue}"
    )
    bars = (
        "While raging: no Charisma-, Dexterity- or Intelligence-based skills but Balance, Escape Artist, Intimidate "
        "and Ride; no Concentration, no spells, no items that need concentration."
    )
    notes = [lasts, bars]
    if (indomitable := _granted(sheet, "indomitable-will")) is not None:
        notes.append(f"Indomitable will: +{indomitable['value']} on Will saves against enchantment spells while "
                     "raging, on top of the rage's: add it as the save's modifier.")  # fmt: skip
    return {**_who(use.who), "feature": "rage", "effect": applied["effect"], "rounds": rounds, "hp_gained": gained,
            "hp": hp, "uses_left": left - 1, "notes": notes}  # fmt: skip


def _fatigued(use: Use) -> bool:
    """Whether the character is fatigued or exhausted: on its state, or on its combatant in the fight."""
    fighting = _fighting(use)
    held = (*use.who.state.conditions, *(fighting[2].conditions if fighting is not None else ()))
    return FATIGUED in held or EXHAUSTED in held


def end_rage(use: Use) -> dict[str, Any]:
    """The rage ends: the Rage effect comes off (if core hasn't expired it), the hit points it added come off the
    sheet's maximum (and a fighting combatant's) and the current, the current to no less than 1 by this alone, and the
    barbarian is fatigued (unless a 17th level's tireless rage). In a fight its combatant is made again, so the
    fatigue's -2 Str and Dex are on its numbers (`combat.combatant_from_sheet`), and marked `RAGE_FATIGUE`: the
    fatigue ends with the encounter (DEL-412)."""
    raged = (use.who.state.d20 or {}).get("rage")
    if not raged:
        raise CheckError(f"{use.who.name} isn't raging.")
    characters, combat = use.characters, use.combat
    gained = int(raged.get("hp", 0))
    tired = _granted(use.who.sheet, TIRELESS) is None
    notes = []
    who = characters.get(use.ctx, use.who.id)
    characters.update(use.ctx, who.id, {"hp_max": max(1, who.sheet.hp_max - gained)}, reason="rage ends")
    fighting = _fighting(use)
    if fighting is not None:
        if any(e.name == "Rage" for e in fighting[2].effects):
            combat.remove_effect(use.ctx, use.who.id, "Rage")
        id, fight, c = _fighting(use) or fighting
        before = c.hp
        hp = max(before - gained, min(before, 1))
        d20 = {k: v for k, v in (c.d20 or {}).items() if k not in ("raging", "rage_bonus")}
        if tired:
            d20[RAGE_FATIGUE] = True
        conditions = with_condition(c.conditions, FATIGUED, True) if tired else c.conditions
        _put(use.ctx, id, fight, replace(c, hp=hp, hp_max=max(1, c.hp_max - gained), d20=d20, conditions=conditions))
        kept = use.ctx.storage.characters.get(use.who.id).state.conditions  # the fight's go back at its end
    else:
        if any(e.name == "Rage" for e in who.state.effects):
            combat.remove_effect(use.ctx, use.who.id, "Rage")
        before = who.state.hp
        hp = max(before - gained, min(before, 1))
        characters.update(use.ctx, who.id, {"hp": hp}, reason="rage ends")
        kept = with_condition(characters.get(use.ctx, use.who.id).state.conditions, FATIGUED, tired)
    _state(use, lambda d20: {k: v for k, v in d20.items() if k != "rage"}, conditions=kept)
    if fighting is not None:
        combat.rearm(use.ctx, characters.get(use.ctx, use.who.id))
    if before - gained < hp:
        notes.append(f"The rage's {gained} hp came off to 1 hp, not below. By the SRD a barbarian can drop when the "
                     "Con bonus goes: rule it with apply_damage if so.")  # fmt: skip
    if tired:
        notes.append(f"{use.who.name} is fatigued (-2 Str and Dex, can't charge or run) for the rest of the encounter.")
    return {**_who(use.who), "feature": "rage", "ended": True, "hp_lost": before - hp, "hp": hp, "fatigued": tired,
            "notes": notes}  # fmt: skip


def end_rages_at_rest(ctx: Context, play: tuple[Any, Any], ids: list[str]) -> list[dict[str, Any]]:
    """Each of the characters `ids` still raging has its rage ended (`end_rage`) before a rest: a rage the DM forgot
    to end doesn't outlast the night. The ends' answers, none for a character not raging."""
    characters, combat = play
    ended = []
    for id in ids:
        who = characters.get(ctx, id)
        if (who.state.d20 or {}).get("rage"):
            ended.append(end_rage(Use(ctx, who, {"id": "rage", "name": "Rage"}, "", END, characters, combat)))
            who = characters.get(ctx, id)
        if (who.state.d20 or {}).get("defending"):  # a defensive stance left on, the same way
            stance = {"id": "defensive-stance", "name": "Defensive stance"}
            ended.append(end_stance(Use(ctx, who, stance, "", END, characters, combat)))
    return ended


LAUNCHED_OR_SLUNG = ("bow", "crossbow", "sling")
"""What a ranged weapon's id has when its Str bonus doesn't add to its damage (`combat._weapon_form`'s `might`)."""


def rage_strength(
    mine: Mapping[str, Any], form: Mapping[str, Any], effects: Iterable[Any]
) -> tuple[int, int, str | None]:
    """Rage's Str bonus by the attack (DEL-389), its modifier: +4 Str is +2 on a melee attack roll; on damage, +2 in
    melee and thrown, +3 two-handed (an off-hand's +1 isn't known here: the forms hold one weapon), none with a bow,
    crossbow or sling; none on a spell's touch. Greater rage's +6 Str is +3 (+4 two-handed), mighty rage's +8 +4 (+6),
    by the attacker's `rage_bonus`. Only while the Rage effect is on the attacker (`effects`, `raging`): marked raging
    without it, nothing, and the note `RUN_OUT`. The to-hit, the damage and the swing's note; (0, 0, None) when not
    raging."""
    if rage_ran_out(mine, effects):
        return 0, 0, RUN_OUT
    if not raging(mine, effects):
        return 0, 0, None
    return by_the_attack(form, _rage_of(mine, None)["str"] // 2, "rage")


def by_the_attack(form: Mapping[str, Any], strength: int, label: str) -> tuple[int, int, str | None]:
    """A Str modifier more (`strength`, from rage's or a defensive stance's Str) by the attack: on a melee attack
    roll; on damage in melee and thrown, 1½ times two-handed, none with a bow, crossbow or sling; none on a spell's
    touch. The to-hit, the damage and the swing's note ("<label>: +1 to hit, +1 damage"); (0, 0, None) for none."""
    if form.get("touch") or str(form.get("damage")) == "0":
        return 0, 0, None
    melee = not form.get("ranged")
    weapon = attack_line.weapon(str(form.get("name") or ""))
    launched = not melee and (weapon is None or any(word in weapon["id"] for word in LAUNCHED_OR_SLUNG))
    to_hit = strength if melee else 0
    damage = 0 if launched else (strength * 3 // 2 if form.get("hands") == 2 else strength)
    if not (to_hit or damage):
        return 0, 0, None
    said = ", ".join(part for part in (f"+{to_hit} to hit" if to_hit else "", f"+{damage} damage" if damage else "")
                     if part)  # fmt: skip
    return to_hit, damage, f"{label}: {said}"


def smite_evil(use: Use) -> dict[str, Any]:
    """Smite evil (paladin): the next swing adds the Cha bonus to hit and the paladin level to damage, if the target
    is evil; spent either way."""
    return _smite(use, "evil", "paladin")


def smite_good(use: Use) -> dict[str, Any]:
    """Smite good (blackguard 2nd): smite evil reversed, "his Charisma modifier (if positive) to his attack roll and
    ... 1 extra point of damage per class level" if the target is good; "If a blackguard accidentally smites a creature
    that is not good, the smite has no effect but it is still used up for that day"."""
    return _smite(use, "good", "blackguard")


def _smite(use: Use, word: str, who: str) -> dict[str, Any]:
    """The smite of `use.feature` against targets of alignment `word`, waiting in `Combatant.d20["smite"]` for the
    next swing (`smite`): the row's ability bonus to hit, its class level × `damage_per_level` to damage."""
    name = use.feature["name"]
    fighting = _fighting(use)
    if fighting is None:
        raise CheckError(f"{name} marks the {who}'s next swing: it needs a fight.", hint="Start one first.")
    left = _check_uses(use)
    id, fight, c = fighting
    sheet = use.who.sheet
    row = _row(use.feature["class"], use.feature["id"])
    to_hit = max(0, numbers.modifier(numbers.ability_score(sheet, row.get("attack_ability", "cha"))))
    damage = sheet.levels.get(use.feature["class"], 0) * int(row.get("damage_per_level", 1))
    waiting = {"to_hit": to_hit, "damage": damage} | ({} if word == "evil" else {"against": word})
    _put(use.ctx, id, fight, replace(c, d20={**(c.d20 or {}), "smite": waiting}))
    _spend(use)
    said = (
        f"{use.who.name}'s next swing (resolve_attack) smites: {to_hit:+d} to hit and {damage:+d} damage if the "
        f"target is {word}, on a melee attack: a ranged or touch attack leaves it waiting. On a melee attack at a "
        f"target that isn't {word} it does nothing, and is spent all the same."
    )
    return {**_who(use.who), "feature": use.feature["id"], "smite": {"to_hit": to_hit, "damage": damage},
            "uses_left": left - 1, "notes": [said]}  # fmt: skip


def inspire_courage(use: Use) -> dict[str, Any]:
    """Inspire courage (bard, one bardic music use, Perform 3 ranks): each of the party and its allies in the fight,
    the bard too, gets +N to hit and damage (+1, +2 at 8th …) as an Effect "Inspire Courage +N" until removed; and +N
    on saves against charm and fear, said, not in the effect (it would add to every save)."""
    fighting = _fighting(use)
    if fighting is None:
        raise CheckError("Inspire courage is for a fight: the party in it hears the bard.", hint="Start one first.")
    row = _row(use.feature["class"], "inspire-courage")
    ranks = max((r for s, r in ((use.who.sheet.d20 or {}).get("skills") or {}).items()
                 if s == "perform" or s.startswith("perform-")), default=0)  # fmt: skip
    if ranks < int(row.get("perform_ranks", 3)):
        raise CheckError(f"Inspire courage needs {row.get('perform_ranks', 3)} ranks in Perform; "
                         f"{use.who.name} has {ranks:g}.", hint="set_build gives skill ranks.")  # fmt: skip
    left = _check_uses(use)
    combat = use.combat
    bonus = int(use.feature["value"] or 1)
    name = f"Inspire Courage +{bonus}"
    inspired = []
    for c in fighting[1].combatants.values():
        if c.side not in SIDES or "removed" in c.conditions or c.hp <= 0 or any(e.name == name for e in c.effects):
            continue
        combat.apply_effect(use.ctx, c.id, name, 0, to_hit=bonus, dmg=bonus, source="inspire-courage")
        inspired.append(c.name)
    _spend(use)
    said = (
        f"{name} to hit and damage; +{bonus} on saves against charm and fear, which you add as the save's modifier. "
        "Both are morale bonuses: on a save they don't stack with another morale bonus, such as a rage's +2 on Will "
        "(only the larger counts). "
        f"It lasts while the bard performs and 5 rounds after: when the song stops, remove_effect '{name}' from each "
        "5 rounds later."
    )
    return {**_who(use.who), "feature": "inspire-courage", "effect": name, "inspired": inspired,
            "uses_left": left - 1, "notes": [said]}  # fmt: skip


def lay_on_hands(use: Use) -> dict[str, Any]:
    """Lay on hands (paladin 2nd): heals `amount` hit points of the paladin's pool, paladin level × Cha bonus a day,
    on the target (the paladin by default)."""
    if use.amount < 1:
        raise CheckError("Lay on hands heals a number of hit points: give amount.")
    level = use.who.sheet.levels.get(use.feature["class"], 0)
    pool = level * max(0, numbers.modifier(numbers.ability_score(use.who.sheet, "cha")))
    used = _used(use.who, "lay-on-hands")
    if used + use.amount > pool:
        raise CheckError(f"Lay on hands: {pool} hp a day at this level, used {used}: {pool - used} left.",
                         hint="It comes back with rest.")  # fmt: skip
    characters, combat = use.characters, use.combat
    target = use.target.strip() or use.who.id
    fighting = combat.combatant(use.ctx, target)
    if fighting is not None and fighting.character_id is None:
        healed = combat.heal(use.ctx, fighting.id, use.amount)
    else:
        healed = characters.apply_heal(use.ctx, target, use.amount)
    _spend(use, use.amount)
    return {**_who(use.who), "feature": "lay-on-hands", "healed": healed, "pool": pool,
            "left": pool - used - use.amount, "notes": [UNDEAD_TOUCH]}  # fmt: skip


UNDEAD_TOUCH = (
    "On an undead lay on hands deals the damage instead (a touch attack, no attack of opportunity): rule it with "
    "apply_damage."
)


def wild_shape(use: Use) -> dict[str, Any]:
    """Wild shape (druid 5th): the druid takes the form of the creature `target` names, by the row's `forms` at her
    druid level (Small or Medium animals at 5th, Large from 8th, Tiny from 11th, plants from 12th, Huge from 15th,
    elementals from 16th) and its Hit Dice no more than her level; an elemental spends its own uses (the row's
    `elemental_by_level`, kept as `"wild-shape-elemental"` in `used`), not her ordinary ones. As
    `CharacterState.d20["shape"]` (`{"monster": "wolf", "since_round": 3}`); in a fight her combatant is made again in
    it (`combat.shaped`). An empty `target` takes her back to her own shape, which spends no use. Each change heals her
    as a night's rest (her character level in hit points, the SRD's polymorph), unless she is dead."""
    asked = use.target.strip()
    shape = (use.who.state.d20 or {}).get("shape")
    if not asked:
        if not shape:
            raise CheckError(f"{use.who.name} is in her own shape already.", hint="target names the form to take.")
        _state(use, lambda d20: {k: v for k, v in d20.items() if k != "shape"})
        healed = _shape_changed(use)
        return {**_who(use.who), "feature": "wild-shape", "shape": None, "healed": healed,
                "notes": [f"{use.who.name} is back in her own shape."]}  # fmt: skip
    row = companions.monster(asked)
    if row is None:
        raise CheckError(f"Unknown creature '{asked}' for wild shape.",
                         hint="Name an SRD animal: 'wolf', 'black bear'.")  # fmt: skip
    from delve_srd35.engine import combat as fight_rules  # combat reads this module: imported when used

    level = use.who.sheet.levels.get(use.feature["class"], 0)
    shapes = _row(use.feature["class"], "wild-shape")
    kind, size = fight_rules.creature_type(row), fight_rules.creature_size(row)
    if (refusal := companions.form_refusal(row, kind, size, shapes["forms"], level)) is not None:
        raise CheckError(refusal)
    if kind == "elemental":  # "in addition to her normal wild shape usage": its own uses, by the row
        elemental = int(features.at_level(shapes.get("elemental_by_level") or {}, level) or 0)
        use = replace(use, feature={**use.feature, "per_day": elemental, "spends": ELEMENTAL,
                                    "spends_name": "Elemental wild shape"})  # fmt: skip
    left = _check_uses(use)
    live = _live(use.ctx)
    name = str(row["name"]).lower()
    _state(use, lambda d20: {**d20, "shape": {"monster": name, "since_round": live[1].round if live else 0}})
    _spend(use)
    healed = _shape_changed(use)
    said = (
        f"{use.who.name} is a {name}: its attacks at her BAB, its natural armour, size, Str, Dex and Con; her own hit "
        f"points, base saves, Int, Wis and Cha. She can't speak or cast spells in it. It lasts up to {level} hours (1 "
        "an hour per druid level; not tracked): use_feature(wild-shape, target='') takes her back."
    )
    return {**_who(use.who), "feature": "wild-shape", "shape": name, "healed": healed, "uses_left": left - 1,
            "notes": [said]}  # fmt: skip


def _shape_changed(use: Use) -> int:
    """After a change of shape: her combatant made again in a fight, and the night's rest's hit points (her
    character level) healed; the hit points healed."""
    who = use.characters.get(use.ctx, use.who.id)
    use.combat.rearm(use.ctx, who)
    if "dead" in who.state.conditions:
        return 0
    out = use.characters.apply_heal(use.ctx, who.id, max(1, sum(who.sheet.levels.values())))
    return int(out.get("hp_after", 0)) - int(out.get("hp_before", 0))


def remove_disease(use: Use) -> dict[str, Any]:
    """Remove disease (paladin 6th): one of its uses a week (1, 2 at 9th … 5 at 18th), on the target (the paladin by
    default); the cure is the spell's, which the DM rules. A rest of 7 days or more gives the uses back
    (`progress.rest`)."""
    left = _check_uses(use)
    target = use.target.strip() or use.who.name
    _spend(use)
    said = f"A remove disease effect on {target}, as the spell: the DM rules the cure."
    return {**_who(use.who), "feature": "remove-disease", "target": target, "uses_left": left - 1,
            "per": "week", "notes": [said]}  # fmt: skip


# --- the dwarven defender's defensive stance ---------------------------------------------------------------------

STANCE_EFFECT = "Defensive Stance"
"""The name of the effect `defensive_stance` puts on (its +4 dodge AC), which core counts down and lets expire."""
STANCE_FIRST = {"str": 2, "con": 4, "saves": 2, "ac": 4}
"""The stance's bonuses (its row's `bonuses`): +2 Str, +4 Con, +2 resistance on all saves, +4 dodge AC."""
WINDED = "winded"
"""The condition after a defensive stance: "the defender is winded and takes a –2 penalty to Strength for the
duration of that encounter" (on the combatant: it goes with the fight)."""
WIND = 2


def stance_numbers(sheet: Sheet | None) -> dict[str, int]:
    found = None if sheet is None else _granted(sheet, "defensive-stance")
    if found is None:
        return dict(STANCE_FIRST)
    return dict(_row(found["class"], "defensive-stance").get("bonuses") or STANCE_FIRST)


def defending(d20: Mapping[str, Any] | None, effects: Iterable[Any]) -> bool:
    """Whether the stance's numbers count: its mark (`Combatant.d20["defending"]` or `CharacterState.d20["defending"]`)
    and the Defensive Stance effect still on, as for rage (`raging`)."""
    return bool((d20 or {}).get("defending")) and any(e.name == STANCE_EFFECT for e in effects)


def stance_save(d20: Mapping[str, Any] | None, save: str, effects: Iterable[Any], sheet: Sheet | None = None) -> int:
    """A defensive stance's bonus on a save while it holds (`defending`): its +2 resistance bonus on each (less a
    worn cloak of resistance's: resistance bonuses don't stack, the higher counts), and on Fortitude the +4 Con's +2;
    0 when not defending."""
    if save not in ("fort", "ref", "will") or not defending(d20, effects):
        return 0
    bonus = stance_numbers(sheet)
    worn = items.worn_bonus(items.carried(sheet), "resistance", "saves") if sheet is not None else 0
    return max(0, bonus["saves"] - worn) + (bonus["con"] // 2 if save == "fort" else 0)


def stance_strength(
    mine: Mapping[str, Any], form: Mapping[str, Any], effects: Iterable[Any]
) -> tuple[int, int, str | None]:
    """A defensive stance's +2 Str by the attack (`by_the_attack`): +1 to hit in melee, +1 damage; none when not
    defending."""
    if not defending(mine, effects):
        return 0, 0, None
    return by_the_attack(form, STANCE_FIRST["str"] // 2, "defensive stance")


def winded(sheet: Sheet) -> Sheet:
    """The sheet as a winded defender's: 2 off its Str score, its stored derived numbers dropped (`tired`'s way)."""
    scores = {**sheet.ability_scores, "str": numbers.base_score(sheet, "str") - WIND}
    d20 = {key: value for key, value in (sheet.d20 or {}).items() if key != "derived"}
    return replace(sheet, ability_scores=scores, d20=d20)


def defensive_stance(use: Use) -> dict[str, Any]:
    """Defensive stance (dwarven defender): +2 Str, +4 Con, +2 resistance on all saves and +4 dodge AC, for 3 + the
    new Con modifier rounds; "he cannot move from the spot he is defending" (said; mobile defense, 8th, allows a
    5-foot step). As an Effect "Defensive Stance" (its AC, -4 in core's classic sign: 4 harder to hit), the Str by the
    attack (`stance_strength`), the saves by the mark (`stance_save`), and the Con's 2 hit points per level on the
    current and maximum hit points as rage's. `amount=-1` ends it: the hit points go and, in a fight, the defender is
    winded (-2 Str) for the rest of the encounter."""
    if use.amount == END:
        return end_stance(use)
    if use.amount:
        raise CheckError("Defensive stance takes no amount: amount=-1 ends it.")
    if (use.who.state.d20 or {}).get("defending"):
        raise CheckError(f"{use.who.name} is already in a defensive stance.",
                         hint="use_feature with amount=-1 ends it.")  # fmt: skip
    left = _check_uses(use)
    sheet = use.who.sheet
    bonus = stance_numbers(sheet)
    rounds = max(1, 3 + numbers.modifier(numbers.ability_score(sheet, "con") + bonus["con"]))
    gained = bonus["con"] // 2 * max(1, numbers.character_level(sheet, use.ctx.lookups))
    applied = use.combat.apply_effect(use.ctx, use.who.id, STANCE_EFFECT, rounds, ac=-bonus["ac"],
                                      source="defensive-stance")  # fmt: skip
    hp = _gain_hp(use, gained, {"defending": True})
    _state(use, lambda d20: {**d20, "defending": {"hp": gained}})
    _spend(use)
    mobile = _granted(sheet, "mobile-defense") is not None
    said = (
        f"+{bonus['con'] // 2 + bonus['saves']} on Fortitude, +{bonus['saves']} on Reflex and Will saves (the effect's "
        f"save stays 0); +{bonus['str'] // 2} to hit and damage in melee, by the swing. It lasts {rounds} rounds: when "
        f"it ends, or {use.who.name} ends it, call use_feature(defensive-stance, amount=-1), which takes the {gained} "
        f"hp off and leaves {use.who.name} winded (-2 Str) for the encounter. "
        + ("He may take one 5-foot step a round (mobile defense)." if mobile else "He can't move from his spot.")
    )
    return {**_who(use.who), "feature": "defensive-stance", "effect": applied["effect"], "rounds": rounds,
            "hp_gained": gained, "hp": hp, "uses_left": left - 1, "notes": [said]}  # fmt: skip


def _gain_hp(use: Use, gained: int, marks: dict[str, Any]) -> int:
    """`gained` hit points on the sheet's maximum and the current, a fighting combatant's too with `marks` on its
    d20, as rage puts its own on; the current hit points after."""
    characters = use.characters
    who = characters.get(use.ctx, use.who.id)
    characters.update(use.ctx, who.id, {"hp_max": who.sheet.hp_max + gained}, reason=use.feature["id"])
    fighting = _fighting(use)
    if fighting is not None:
        id, fight, c = fighting
        _put(use.ctx, id, fight, replace(c, hp=c.hp + gained, hp_max=c.hp_max + gained, d20={**(c.d20 or {}), **marks}))
        return c.hp + gained
    characters.update(use.ctx, who.id, {"hp": who.state.hp + gained}, reason=use.feature["id"])
    return who.state.hp + gained


def end_stance(use: Use) -> dict[str, Any]:
    """The defensive stance ends: the effect comes off (if core hasn't expired it), its hit points come off the
    maximum and the current (to no less than 1 by this alone), and in a fight the defender's combatant is winded,
    made again with 2 off its Str (`winded`, `combat.combatant_from_sheet`); the fight's conditions go with it, as
    "for the duration of that encounter" asks."""
    held = (use.who.state.d20 or {}).get("defending")
    if not held:
        raise CheckError(f"{use.who.name} isn't in a defensive stance.")
    characters, combat = use.characters, use.combat
    gained = int(held.get("hp", 0))
    who = characters.get(use.ctx, use.who.id)
    characters.update(use.ctx, who.id, {"hp_max": max(1, who.sheet.hp_max - gained)}, reason="defensive stance ends")
    fighting = _fighting(use)
    notes = []
    if fighting is not None:
        if any(e.name == STANCE_EFFECT for e in fighting[2].effects):
            combat.remove_effect(use.ctx, use.who.id, STANCE_EFFECT)
        id, fight, c = _fighting(use) or fighting
        before = c.hp
        hp = max(before - gained, min(before, 1))
        d20 = {k: v for k, v in (c.d20 or {}).items() if k != "defending"}
        conditions = with_condition(c.conditions, WINDED, True)
        _put(use.ctx, id, fight, replace(c, hp=hp, hp_max=max(1, c.hp_max - gained), d20=d20, conditions=conditions))
        notes.append(f"{use.who.name} is winded: -2 Str for the rest of the encounter.")
    else:
        if any(e.name == STANCE_EFFECT for e in who.state.effects):
            combat.remove_effect(use.ctx, use.who.id, STANCE_EFFECT)
        before = who.state.hp
        hp = max(before - gained, min(before, 1))
        characters.update(use.ctx, who.id, {"hp": hp}, reason="defensive stance ends")
    _state(use, lambda d20: {k: v for k, v in d20.items() if k != "defending"})
    if fighting is not None:
        combat.rearm(use.ctx, characters.get(use.ctx, use.who.id))
    return {**_who(use.who), "feature": "defensive-stance", "ended": True, "hp_lost": before - hp, "hp": hp,
            "winded": fighting is not None, "notes": notes}  # fmt: skip


# --- features used so many times a day --------------------------------------------------------------------------

ONCE = {
    "seeker-arrow": "An arrow at a target known to her within range travels to it even around corners: no cover or "
                    "concealment modifiers, the attack rolled normally (resolve_attack). A standard action.",
    "phase-arrow": "An arrow at a target known to her within range passes through any nonmagical barrier or wall: no "
                   "cover, concealment or armour modifiers (the DM takes the armour off the AC with modifier). A "
                   "standard action.",
    "hail-of-arrows": "In place of her attacks, one arrow at each target in range, up to one per arcane archer level, "
                      "each at her first attack bonus (a resolve_attack each).",
    "ranged-legerdemain": "Disable Device, Open Lock or Sleight of Hand at up to 30 feet, a standard action (or the "
                          "skill's own time); no taking 10 or 20, and a DC 5 more for Sleight of Hand.",
    "impromptu-sneak-attack": "One attack this round counts the target as flat-footed: the sneak dice if it hits "
                              "(the attack with condition flat-footed).",
    "shadow-illusion": "A silent image, as the spell.",
    "defensive-roll": "Against a blow that would bring her to 0 hp or less: a Reflex save (DC the damage) for half; "
                      "not when she is denied her Dex bonus to AC.",
    "breath-weapon": "Its energy and shape by the dragon variety; a Reflex save for half.",
}
"""What each feature used so many times a day says when used (`once`): the DM rules what it does."""


def once(use: Use) -> dict[str, Any]:
    """A feature counted against its uses a day that the engine doesn't play (`ONCE`): one use spent, and what it
    does said. The dragon disciple's breath weapon says its dice by level (2d8, 4d8 at 7th, 6d8 at 10th) and its DC,
    "10 + class level + Con modifier"."""
    left = _check_uses(use)
    _spend(use)
    out = {**_who(use.who), "feature": use.feature["id"], "uses_left": left - 1, "notes": [ONCE[use.feature["id"]]]}
    row = _row(use.feature["class"], use.feature["id"])
    level = use.who.sheet.levels.get(use.feature["class"], 0)
    if row.get("dice"):
        out["dice"] = features.at_level(row["dice"], level)
    if ability := row.get("dc_ability"):
        out["dc"] = 10 + level + numbers.modifier(numbers.ability_score(use.who.sheet, ability))
    return out


USES: dict[str, Callable[[Use], dict[str, Any]]] = {
    "rage": rage,
    "smite-evil": smite_evil,
    "inspire-courage": inspire_courage,
    "lay-on-hands": lay_on_hands,
    "wild-shape": wild_shape,
    "remove-disease": remove_disease,
    "defensive-stance": defensive_stance,
    "smite-good": smite_good,
    **dict.fromkeys(ONCE, once),
}
"""use_feature's handlers by feature id."""


def use_feature(
    ctx: Context, play: tuple[Any, Any], character: str, feature: str, target: str = "", amount: int = 0
) -> dict[str, Any]:
    """The character uses a class feature by id or name (`USES`), refused past its uses a day. `play` is core's
    `(delve.play.characters, delve.play.combat)`, from the tools module."""
    characters, combat = play
    who = characters.get(ctx, character)
    granted = _feature(ctx, who, feature)
    with ctx.storage.transaction():
        return USES[granted["id"]](Use(ctx, who, granted, target, amount, characters, combat))
