"""The 3.5 engine's own DM tools (DEL-388), seen only in srd35 campaigns: `set_build`, `set_stance` and `provoke`, and
core's `saving_throw`, `skill_check`, `update_combatant`, `setup_combat` and `add_combatant` with 3.5's numbers (a
fight set up without a surprise roll), and `surprise_check`, `morale_check`, `reaction` and `council` refused with why.
Each keeps the core tool's params and adds its own, and goes through core's play layer as core's tools do
(`PACK_TOOL_IMPORTS`): characters change through `characters.update` (a build as the engine's `d20_build`, never the
DM's sheet patch), and attacks through `combat.resolve_attack`, which swings by the engine and applies the damage. A
combatant's 3.5 numbers (`Combatant.d20`) are engine-owned and written to the live fight directly, as core's rearm
writes a combatant."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from delve.dice import Dice
from delve.dm.tools.host import all_specs
from delve.dm.tools.schema import ToolSpec, array, boolean, integer, obj, params, plain, string, strings
from delve.play import characters, combat
from delve.rules.classic import checks as classic_checks
from delve.rules.classic import combat as rules
from delve.rules.classic.checks import CheckError
from delve_srd35.data import load
from delve_srd35.engine import attack_line, numbers
from delve_srd35.engine import combat as combat_rules

Context = Any
"""A `delve.play.context.CampaignContext`: the tools' context, which a pack names only by what it uses."""

RULESET = "srd35"
BUILD = ("skills", "feats", "domains", "weapon", "armor", "shield")
CHOICES = {"weapon-focus": "weapon", "improved-critical": "weapon", "skill-focus": "skill", "spell-focus": "school"}
"""The slice's feats taken for one thing, and what that is."""
SHIELDS = ("shield-", "buckler")
OVERRIDES = ("ac", "touch_ac", "flat_footed_ac", "attack_bonus", "damage", "critical", "saves")
"""The 3.5 numbers `update_combatant` and `setup_combat`'s groups take."""
NO_SURPRISE = (
    "3.5 has no surprise roll: a side that hasn't noticed the other is flat-footed until it acts. Put the condition "
    "flat-footed on each unaware combatant (add_condition); in a surprise round only the aware act."
)
NO_MORALE = "3.5 has no morale check: a foe flees or surrenders as you rule it, or by its save against a fear effect."
NO_REACTION = (
    "3.5 has no reaction roll: an NPC starts at the attitude you judge (hostile, unfriendly, indifferent, friendly, "
    "helpful), and a character shifts it with a Diplomacy check (skill_check with skill diplomacy; an NPC, a Charisma "
    "check) read against the attitude table (rules_lookup 'diplomacy'). Keep the outcome with set_disposition."
)
_CRITICAL = re.compile(r"^\s*(?:(\d+)\s*[-–]\s*20)?\s*/?\s*(?:[x×](\d+))?\s*$", re.IGNORECASE)

OVERRIDE_PROPS = {
    "ac": integer("Its AC (3.5's: higher is harder to hit)."),
    "touch_ac": integer("Its touch AC."),
    "flat_footed_ac": integer("Its flat-footed AC."),
    "attack_bonus": integer("The attack bonus of the attack it holds."),
    "damage": string("That attack's damage: '1d8+3'."),
    "critical": string("That attack's critical: '19–20/×2', '×3'."),
    "saves": obj('Its saves: {"fort": 3, "ref": 1, "will": 0}; any of them.'),
}


def _core(name: str) -> ToolSpec:
    return next(spec for spec in all_specs() if spec.name == name)


def _scoped(
    core: ToolSpec, description: str, extra: Mapping[str, Any], fn: Callable, required: Iterable[str] | None = None
) -> ToolSpec:
    """The core tool `core` for srd35 campaigns: its params and `extra`, its flags, and `fn`."""
    schema = {**core.params, "properties": {**core.params["properties"], **extra}}
    if required is not None:
        schema["required"] = list(required)
    return ToolSpec(
        core.name,
        description,
        schema,
        fn,
        core.mutates,
        core.player_visible,
        core.dm_only_keys,
        core.areas,
        (RULESET,),
    )


def _who(character: Any) -> dict[str, Any]:
    return {"character_id": character.id, "character": character.name}


# --- set_build ---------------------------------------------------------------------------------------------------


def _key(name: str, keys: Iterable[str]) -> str | None:
    """The table key for a name as written ("chain mail" is chainmail, "heavy steel shield" is "shield-heavy-steel",
    "short sword" is "sword-short"): the name, or its last word first, with or without its hyphens."""
    words = numbers.slug(name).split("-")
    compact = {key.replace("-", ""): key for key in keys}
    for tried in ("-".join(words), "-".join(words[-1:] + words[:-1])):
        if tried in compact.values():
            return tried
        if tried.replace("-", "") in compact:
            return compact[tried.replace("-", "")]
    return None


def _weapon(name: str) -> str | None:
    """The weapon as the build keeps it: the table's name ("sword, short"), or the name as given for one that ends in
    a weapon of the table ("+1 longsword"); None for an unknown one."""
    table = {row["id"]: row for row in load("weapons")}
    key = _key(name, table)
    if key is not None:
        return str(table[key]["name"]).lower()
    return name.strip().lower() if attack_line.weapon(name) is not None else None


def _armour(name: str, shield: bool) -> str | None:
    table = numbers.armour_table()
    key = _key(name, table)
    if key is None or key.startswith(SHIELDS) != shield:
        return None
    return str(table[key]["name"]).lower()


def _feats(reference: Any, asked: list[Any], problems: list[str]) -> list[dict[str, Any]]:
    """The feats as the build keeps them, `{"id", "choice"?}`, each by its id or name; a weapon or skill choice in the
    table's words."""
    out = []
    for item in asked:
        name, choice = (
            (item.get("id") or item.get("name") or "", item.get("choice")) if isinstance(item, dict) else (item, None)
        )
        row = numbers.feat_row(reference, str(name))
        if row is None:
            problems.append(f"Unknown feat '{name}'.")
            continue
        feat: dict[str, Any] = {"id": row["id"]}
        kind = CHOICES.get(row["id"])
        if kind is not None and not choice:
            problems.append(f"{row['name']} is taken for one {kind}: give its choice.")
        elif kind == "weapon":
            found = _weapon(str(choice))
            if found is None:
                problems.append(f"{row['name']}: unknown weapon '{choice}'.")
            feat["choice"] = numbers.slug(found or str(choice))
        elif kind == "skill":
            try:
                feat["choice"] = numbers.skill_named(reference, str(choice))
            except CheckError as error:
                problems.append(f"{row['name']}: {error}")
        elif choice:
            feat["choice"] = str(choice).strip().lower()
        out.append(feat)
    return out


def _skill_problems(sheet: Any, reference: Any, ranks: Mapping[str, float]) -> tuple[list[str], dict[str, Any]]:
    """What the ranks break: the skill points spent against the total so far ((class points + Int) × 4 at 1st level,
    then per level, at least 1 a level, a human's 4 + 1 a level more; a cross-class rank costs 2), and the most ranks
    a skill takes (level + 3, half that cross-class). The points as well."""
    problems = []
    level = sum(sheet.levels.values()) or 1
    int_mod = numbers.modifier(numbers.ability_score(sheet, "int"))
    human = (numbers.race_named(reference, sheet.race) or {}).get("id") == "humans"
    class_skills: set[str] = set()
    total = 0
    first = True
    for cls, count in sheet.levels.items():
        row = reference.char_class(cls) or {}
        class_skills |= set(row.get("class_skills") or ())
        found = re.match(r"\s*(\d+)", str(row.get("skill_points") or "0"))
        per = max(1, (int(found.group(1)) if found else 0) + int_mod) + int(human)
        total += per * (count + 3 * first) if count else 0
        first = first and not count
    spent = 0.0
    for skill, rank in ranks.items():
        own = any(skill == c or skill.startswith(c + "-") for c in class_skills)
        spent += rank * (1 if own else 2)
        most = level + 3 if own else (level + 3) / 2
        if rank > most:
            kind = "a class skill" if own else "cross-class"
            problems.append(
                f"{skill.replace('-', ' ').title()} {rank:g} ranks: at most {most:g} ({kind}, level {level})."
            )
    if spent > total:
        problems.append(f"{spent:g} skill points spent; {sheet.label or 'the character'} has {total} so far.")
    return problems, {"spent": spent, "total": total}


def _domains(sheet: Any, asked: list[str], problems: list[str]) -> list[str]:
    table = {row["id"]: row for row in load("domains")}
    out = []
    for name in asked:
        key = numbers.slug(name)
        if key in table:
            out.append(key)
        else:
            problems.append(f"Unknown domain '{name}': one of {', '.join(sorted(table))}.")
    if not sheet.levels.get("cleric"):
        problems.append("Only a cleric has domains.")
    named = {numbers.slug(name) for name in asked}  # "War" and "war" are one domain
    if len(named) != 2:
        problems.append(f"A cleric takes two domains, not {len(named)}.")
    return out


def set_build(
    ctx: Context,
    character: str,
    skills: dict[str, float] | None = None,
    feats: list[Any] | None = None,
    domains: list[str] | None = None,
    weapon: str | None = None,
    armor: str | None = None,
    shield: str | None = None,
) -> dict[str, Any]:
    """Set a 3.5 character's build: skill ranks, feats (with a choice, such as Weapon Focus's weapon), a cleric's two
    domains, and the weapon, armour and shield in use; what you leave out stays. It is checked against the rules (skill
    points so far, max ranks of level + 3 or half cross-class, feat prerequisites, domains) and refused with every
    problem named; accepted, the sheet's numbers (BAB, saves, AC, skill totals, slots) follow. An empty weapon, armor
    or shield takes it off. A later change that breaks a feat's prerequisite keeps the feat, with a warning."""
    who = characters.get(ctx, character)
    reference = ctx.lookups
    problems: list[str] = []
    build: dict[str, Any] = {}
    if skills is not None:
        build["skills"] = {}
        for name, rank in skills.items():
            try:
                skill = numbers.skill_named(reference, name)
            except CheckError as error:
                problems.append(str(error))
                continue
            if skill in build["skills"]:
                problems.append(f"'{name}' is {skill.replace('-', ' ').title()} again.")
            build["skills"][skill] = build["skills"].get(skill, 0) + rank
    if feats is not None:
        build["feats"] = _feats(reference, feats, problems)
    if domains is not None:
        build["domains"] = _domains(who.sheet, domains, problems)
    for slot, asked in (("weapon", weapon), ("armor", armor), ("shield", shield)):
        if asked is None:
            continue
        if not asked.strip():
            build[slot] = None
            continue
        found = _weapon(asked) if slot == "weapon" else _armour(asked, slot == "shield")
        if found is None:
            known = "weapons" if slot == "weapon" else "shields" if slot == "shield" else "armour"
            problems.append(f"Unknown {slot} '{asked}': name one of the SRD's {known}.")
        build[slot] = found
    candidate = replace(who.sheet, d20={**(who.sheet.d20 or {}), **build})
    points = None
    if skills is not None:
        found_problems, points = _skill_problems(candidate, reference, build["skills"])
        problems += found_problems
    if feats is not None:
        bab = numbers.derived(candidate, reference)["bab"]
        problems += numbers.feat_problems(candidate, reference, bab)
    if problems:
        raise CheckError(f"{who.name}'s build is refused: {' '.join(problems)}", hint="Fix each and call it again.")
    saved = characters.update(ctx, who.id, {}, reason="set_build", d20_build=build)
    d20 = saved.sheet.d20 or {}
    out = {**_who(saved), "build": {key: d20.get(key) for key in BUILD if key in d20}, "derived": d20.get("derived")}
    if points is not None:
        out["skill_points"] = points
    return out


# --- the fight ---------------------------------------------------------------------------------------------------


def _live(ctx: Context) -> tuple[str, rules.Combat]:
    live = ctx.storage.combats.live(ctx.campaign_id)
    if live is None:
        raise CheckError("No combat is under way.", hint="Start one with setup_combat.")
    return live[0], rules.from_json(live[1])


def _put(ctx: Context, id: str, fight: rules.Combat, *changed: rules.Combatant) -> rules.Combat:
    """The fight with `changed` in it, stored: only engine-owned numbers change, so no state is written through."""
    fight = replace(fight, combatants={**fight.combatants, **{c.id: c for c in changed}})
    ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))
    return fight


def _find(fight: rules.Combat, ref: str) -> rules.Combatant:
    try:
        return rules.find(fight, ref)
    except rules.UnknownCombatant as error:
        raise CheckError(error.message, error.hint, error.candidates) from None


def _numbers(c: rules.Combatant) -> dict[str, Any]:
    if c.d20 is None:
        raise CheckError(f"{c.name} has no 3.5 numbers.", hint="Add it to the fight again.")
    return dict(c.d20)


def set_stance(
    ctx: Context, combatant: str, power_attack: int | None = None, defensive: bool | None = None
) -> dict[str, Any]:
    """A combatant's stance in the fight: Power Attack (from 0 up to its base attack bonus: that much off its melee
    attacks, on their damage, twice two-handed) and fighting defensively (-4 to attack, +2 AC). It lasts until set
    again; what you leave out stays."""
    id, fight = _live(ctx)
    c = _find(fight, combatant)
    mine = _numbers(c)
    stance = dict(mine.get("stance") or {"power_attack": 0, "defensive": False})
    if power_attack is not None:
        bab = int(mine.get("bab", 0))
        if not 0 <= power_attack <= bab:
            raise CheckError(f"Power Attack takes 0 to {bab} (its base attack bonus), not {power_attack}.")
        sheet = ctx.storage.characters.get(c.character_id).sheet if c.character_id else None
        if power_attack and sheet is not None and "power-attack" not in numbers.feat_ids(sheet):
            raise CheckError(f"{c.name} hasn't the Power Attack feat.", hint="set_build gives feats.")
        stance["power_attack"] = power_attack
    if defensive is not None:
        stance["defensive"] = defensive
    _put(ctx, id, fight, replace(c, d20={**mine, "stance": stance}))
    return {"id": c.id, "name": c.name, "stance": stance}


ROUND_ONLY = ("attacks_remaining_this_round", "extra_attack", "attacks_per_round")


def provoke(ctx: Context, provoker: str, threatened_by: list[str], weapon: str = "") -> dict[str, Any]:
    """A combatant provokes attacks of opportunity (it moved out of a threatened square, cast, drank, fled…): each
    combatant that threatens it makes one attack at it, if it hasn't used its one attack of opportunity this round.
    A flat-footed one (in round 1 before it has acted, or with the flat-footed condition) makes none. The hits are
    applied at once. weapon picks the threatener's attack by name, as resolve_attack's."""
    id, fight = _live(ctx)
    target = _find(fight, provoker)
    if "removed" in target.conditions:
        raise CheckError(f"{target.name} has been removed from the fight.")
    if not fight.order:
        raise CheckError(
            f"Round {fight.round} hasn't started: its initiative isn't rolled yet.",
            hint="combat_round rolls the round's initiative.",
        )
    answers = []
    for ref in threatened_by:
        c = _find(fight, ref)
        mine = _numbers(c)
        used = dict(mine.get("aoo") or {"round": 0, "used": 0})
        refused = None
        if c.id == target.id:
            refused = "It can't provoke itself."
        elif used.get("round") == fight.round and int(used.get("used", 0)) >= 1:
            refused = "already used its attack of opportunity this round"
        elif c.hp <= 0 or "removed" in c.conditions:
            refused = "It is down or out of the fight."
        elif combat_rules.flat_footed(target, c, fight.round):
            refused = "is flat-footed: no attack of opportunity"
        if refused is not None:
            answers.append({"id": c.id, "name": c.name, "refused": refused})
            continue
        answers.append(_opportunity(ctx, id, fight, c, target, weapon))
        id, fight = _live(ctx)
    return {"provoker": target.name, "provoker_id": target.id, "round": fight.round, "attacks": answers}


def _opportunity(
    ctx: Context, id: str, fight: rules.Combat, c: rules.Combatant, target: rules.Combatant, weapon: str
) -> dict[str, Any]:
    """`c`'s attack of opportunity at `target`, through core's resolve_attack: marked `swinging` for its rolls, and
    afterwards with its own attacks and the weapon it holds as they were and its one attack of opportunity used. On
    any error the mark comes off again."""
    mine = _numbers(c)
    _put(ctx, id, fight, replace(c, d20={**mine, "aoo": {"round": fight.round, "used": 0, "swinging": True}}))
    swung = False
    try:
        swing = combat.resolve_attack(ctx, c.id, target.id, "", weapon)
        swung = True
    finally:
        id, fight = _live(ctx)
        after = fight.combatants[c.id]
        # It isn't one of its own attacks this round: its count and the weapon it holds stay as they were.
        aoo = {"round": fight.round, "used": 1} if swung else mine.get("aoo") or {"round": 0, "used": 0}
        numbers_after = {**_numbers(after), "aoo": aoo}
        _put(ctx, id, fight, replace(after, attacks_used=c.attacks_used, weapon=c.weapon, d20=numbers_after))
    return {k: v for k, v in swing.items() if k not in ROUND_ONLY} | {"attack_of_opportunity": True}


def _critical(text: str) -> tuple[int, int]:
    """The threat and multiplier of "19–20/×2", "18-20", "×3"; 20 and ×2 where it says none."""
    found = _CRITICAL.match(str(text))
    if found is None or not any(found.groups()):
        raise CheckError(f"critical reads '{text}': write it as '19–20/×2' or '×3'.")
    return int(found.group(1) or 20), int(found.group(2) or 2)


def _overridden(c: rules.Combatant, over: Mapping[str, Any]) -> rules.Combatant:
    """The combatant with the 3.5 numbers in `over` (`OVERRIDES`): its AC, touch and flat-footed AC, saves, and the
    bonus, damage and critical of the attack it holds."""
    mine = _numbers(c)
    if over.get("ac") is not None:
        mine["ac"] = int(over["ac"])
        c = replace(c, ac=int(over["ac"]))
    for key, field in (("touch_ac", "touch"), ("flat_footed_ac", "flat_footed")):
        if over.get(key) is not None:
            mine[field] = int(over[key])
    if over.get("saves"):
        unknown = sorted(set(over["saves"]) - {"fort", "ref", "will"})
        if unknown:
            raise CheckError(f"Unknown save '{unknown[0]}'.", hint="Give fort, ref and will.")
        mine["saves"] = {**(mine.get("saves") or {}), **{k: int(v) for k, v in over["saves"].items()}}
    attack = {k: over[k] for k in ("attack_bonus", "damage", "critical") if over.get(k) is not None}
    if attack:
        held = c.attacks[c.weapon] if 0 <= c.weapon < len(c.attacks) else None
        forms = list(mine.get("attacks") or ())
        index = next(
            (i for i, f in enumerate(forms) if held is not None and f["name"] == held.name), 0 if forms else None
        )
        form = dict(forms[index]) if index is not None else {"name": held.name if held else "attack", "bonus": int(mine.get("bab", 0)), "damage": held.damage_sm if held else "1d6", "threat": 20, "mult": 2, "count": 1, "touch": False, "hands": 1, "ranged": False}  # fmt: skip
        if "attack_bonus" in attack:
            form["bonus"] = int(attack["attack_bonus"])
        if "damage" in attack:
            form["damage"] = str(attack["damage"]).replace(" ", "")
            if held is not None:
                block = replace(held, damage_sm=form["damage"], damage_l=form["damage"])
                c = replace(c, attacks=(*c.attacks[: c.weapon], block, *c.attacks[c.weapon + 1 :]))
        if "critical" in attack:
            form["threat"], form["mult"] = _critical(attack["critical"])
        if index is None:
            forms.append(form)
        else:
            forms[index] = form
        mine["attacks"] = forms
    return replace(c, d20=mine)


def _critical_text(form: Mapping[str, Any]) -> str:
    """A form's critical as the SRD writes it, and as `critical` takes it: "18–20/×2", "×3"."""
    threat, mult = int(form.get("threat", 20)), int(form.get("mult", 2))
    return f"×{mult}" if threat == 20 else f"{threat}–20/×{mult}"


def shown(c: rules.Combatant) -> dict[str, Any]:
    """The combatant's 3.5 numbers as the setup and update answers give them (ruling R17b): its AC, touch and
    flat-footed AC, its attack forms with their bonus, damage and critical, and its saves."""
    mine = _numbers(c)
    return {
        "ac": mine["ac"],
        "touch": mine["touch"],
        "flat_footed": mine["flat_footed"],
        "attacks": [
            {"name": f["name"], "bonus": f["bonus"], "damage": f["damage"], "critical": _critical_text(f)}
            for f in mine.get("attacks") or ()
        ],
        "saves": dict(mine.get("saves") or {}),
    }


_DAMAGE_NOTE = re.compile(r"'(.+)' damage reads .* pass dmg=")
"""Core's setup warning for a group whose classic damage line has no dice."""
_MULTI_ATTACK_NOTE = re.compile(r"'(.+)' gets .* attacks/round .* pass dmg= per swing\.")
"""Core's setup note for a group with several attacks a round: under 3.5 its forms are the engine's, each swung by
`resolve_attack` with its `weapon` (the prompt's full attack), so no dmg is passed."""
CLASSIC_GROUP = ("thac0", "damage")
CLASSIC_ATTACK = ("damage_sm", "damage_l", "speed")
"""The classic numbers core's setup answer gives for an enemy group and a character's attack: under 3.5 the
combatant's own (`shown`) take their place."""


def _in_3_5(fight: rules.Combat, out: dict[str, Any]) -> dict[str, Any]:
    """Core's setup answer with each group's and character's classic numbers replaced by the 3.5 ones, and each place
    in the order with its initiative bonus where core says a weapon speed."""
    by_name = {c.name: c for c in fight.combatants.values()}
    groups = [_group_in_3_5(fight, group) for group in out["enemies"]]
    attacks = {
        name: {**{k: v for k, v in entry.items() if k not in CLASSIC_ATTACK}, **shown(by_name[name])}
        if name in by_name
        else entry
        for name, entry in out["party_attacks"].items()
    }
    order = [
        {**{k: v for k, v in entry.items() if k != "speed"}, "bonus": entry.get("speed", 0)} for entry in out["order"]
    ]
    answer = {**out, "enemies": groups, "party_attacks": attacks, "order": order}
    answer.pop("notes", None)
    if notes := _notes(groups, out.get("notes", [])):  # dropped when none is left, as core does
        answer["notes"] = notes
    return answer


def _notes(groups: list[dict[str, Any]], notes: list[str]) -> list[str]:
    """Core's setup notes without its classic "damage reads … pass dmg=" warning: a group whose combatants have the
    engine's attack forms needs no damage from the DM (a dmg would overwrite them), and one without any is told the
    3.5 override instead. Core's "pass dmg= per swing" note for several attacks a round is dropped too."""
    armed = {g["type"]: bool(g.get("attacks")) for g in groups if "type" in g}
    kept = []
    for note in notes:
        if _MULTI_ATTACK_NOTE.match(note):
            continue
        found = _DAMAGE_NOTE.match(note)
        if found is None or found.group(1) not in armed:
            kept.append(note)
        elif not armed[found.group(1)]:
            kept.append(f"'{found.group(1)}' has no attack the 3.5 engine could read: give it one with update_combatant's "
                        "damage and attack_bonus before it swings.")  # fmt: skip
    return kept


def _overrides(raw: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The 3.5 overrides in `raw`, and the rest."""
    return {k: v for k, v in raw.items() if k in OVERRIDES}, {k: v for k, v in raw.items() if k not in OVERRIDES}


def _update_combatant(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        over, _ = _overrides(args)
        stats = dict(args.get("stats") or {})
        for classic, own in (("ac", "ac"), ("dmg", "damage")):  # core's ac and dmg mean the 3.5 ones here
            if classic in stats and own not in over:
                over[own] = stats[classic]
        if over:
            id, fight = _live(ctx)
            c = _find(fight, args["id"])
            _put(ctx, id, fight, _overridden(c, over))
        out = core.fn(ctx, {"id": args["id"], "stats": stats})
        _, fight = _live(ctx)
        return {**out, **({"d20_set": over} if over else {}), "numbers": shown(_find(fight, out["id"]))}

    return run


def _group_in_3_5(fight: rules.Combat, group: dict[str, Any]) -> dict[str, Any]:
    """An enemy group as core's setup or add answer gives it, its classic numbers replaced by its first combatant's 3.5
    ones (`shown`)."""
    first = fight.combatants[group["individuals"][0]["id"]] if group.get("individuals") else None
    kept = {k: v for k, v in group.items() if k not in CLASSIC_GROUP}
    return {**kept, **(shown(first) if first is not None else {})}


def _add_combatant(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        out = core.fn(ctx, args)
        group = _group_in_3_5(_live(ctx)[1], out)
        group.pop("notes", None)
        if notes := _notes([group], out.get("notes", [])):
            group["notes"] = notes
        return group

    return run


def _setup_combat(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        wanted, enemies = [], []
        for spec in args["enemies"]:
            over, rest = _overrides(spec) if isinstance(spec, dict) else ({}, spec)
            if isinstance(spec, dict) and str(spec.get("name", "") or "").strip():
                wanted.append(over)  # in the order core adds the groups it doesn't skip
            enemies.append(rest)
        out = core.fn(ctx, {**args, "enemies": enemies, "surprise": False})
        if any(wanted):
            id, fight = _live(ctx)
            changed = [
                _overridden(fight.combatants[one["id"]], over)
                for group, over in zip(out["enemies"], wanted, strict=True)
                if over
                for one in group["individuals"]
            ]
            fight = _put(ctx, id, fight, *changed)
            out["combat"] = rules.status(fight)
        answer = _in_3_5(_live(ctx)[1], out)
        if args.get("surprise"):
            answer["notes"] = [*answer.get("notes", []), NO_SURPRISE]
        return answer

    return run


def _not_in_3_5(said: str) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        raise CheckError(said)

    return run


# --- saves and skills --------------------------------------------------------------------------------------------


def _fight_save(ctx: Context, c: rules.Combatant, save_type: str, dc: int, modifier: int) -> dict[str, Any]:
    """A combatant's save against a DC in the current round, keyed as core keys a fight's save; a failed one spoils a
    spell or scroll under way, as core's does."""
    id, fight = _live(ctx)
    character = ctx.storage.characters.get(c.character_id) if c.character_id else None
    dice = Dice(ctx.dice.rng, ctx.storage.rolls, ctx.campaign_id, f"{ctx.beat}/{id}")
    assert ctx.d20 is not None
    result = ctx.d20.save(
        character.sheet if character is not None else c,
        save_type,
        dc,
        modifier + classic_checks.effects_save(c.effects),
        dice,
        actor=c.id,
        combat_round=fight.round,
    )
    said = plain(result)
    save = said.pop("name")
    out = {"id": c.id, "name": c.name, **said, "save": save, "round": fight.round}
    if not result.success and c.ongoing is not None and c.ongoing.under_way and c.ongoing.kind in ("spell", "scroll"):
        combat.interrupt(ctx, c.id, f"{c.name} failed a saving throw")
        out["spell_disrupted"] = True
    return out


def _saving_throw(core: ToolSpec) -> Callable[[Context, dict[str, Any]], dict[str, Any]]:
    def run(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
        modifier, dc = args.get("modifier", 0), args.get("dc")
        fighting = combat.combatant(ctx, args["character"])
        if fighting is not None:
            if dc is None:
                return core.fn(ctx, args)
            return _fight_save(ctx, fighting, args["save_type"], dc, modifier)
        who = characters.get(ctx, args["character"])
        assert ctx.d20 is not None
        modifier += classic_checks.effects_save(who.state.effects)
        result = ctx.d20.save(who.sheet, args["save_type"], dc, modifier, ctx.dice, actor=who.id)
        return {**_who(who), **plain(result)}

    return run


def _skill_check(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    who = characters.get(ctx, args["character"])
    assert ctx.d20 is not None
    occasion = str(args.get("occasion", "")).strip()
    result = ctx.d20.skill_check(
        who.sheet, args["skill"], args.get("dc"), args.get("modifier", 0), ctx.dice, actor=who.id, occasion=occasion
    )
    return {**_who(who), "skill": result.name, **plain(result)}


# --- the list ----------------------------------------------------------------------------------------------------


def specs() -> list[ToolSpec]:
    """The tools, each scoped to srd35."""
    own: list[ToolSpec] = [
        ToolSpec(
            "set_build",
            " ".join((set_build.__doc__ or "").split()),
            params(
                "character",
                character=string("The character."),
                skills=obj(
                    'Ranks by skill, its 3.5 name or id: {"climb": 4, "move silently": 2}. Replaces the ranks it had.',
                    additionalProperties={"type": "number", "minimum": 0},
                ),
                feats=array(
                    'The feats, replacing those it had: ["power attack", {"id": "weapon focus", "choice": "warhammer"}].',
                ),
                domains=strings("A cleric's two domains: ['war', 'good']."),
                weapon=string("The weapon in hand: 'warhammer', 'short sword'."),
                armor=string("The armour worn: 'scale mail', 'chain mail'."),
                shield=string("The shield carried: 'heavy steel shield', 'buckler'."),
            ),
            lambda ctx, args: set_build(ctx, **args),
            True,
            True,
            areas=("characters", "combat"),
        ),
        ToolSpec(
            "set_stance",
            " ".join((set_stance.__doc__ or "").split()),
            params(
                "combatant",
                combatant=string("A combatant by id (chr_…, mon_1) or exact name."),
                power_attack=integer("Power Attack's number, 0 for none.", minimum=0),
                defensive=boolean("Fighting defensively."),
            ),
            lambda ctx, args: set_stance(ctx, **args),
            True,
            True,
            areas=("combat",),
        ),
        ToolSpec(
            "provoke",
            " ".join((provoke.__doc__ or "").split()),
            params(
                "provoker",
                "threatened_by",
                provoker=string("Who provokes, by id or exact name."),
                threatened_by=strings("The combatants threatening it, by id or exact name."),
                weapon=string("Part of the name of the threateners' attack: 'sword'."),
            ),
            lambda ctx, args: provoke(ctx, **args),
            True,
            True,
            areas=("characters", "combat"),
        ),
    ]
    resolve = _core("resolve_attack")
    saving = _core("saving_throw")
    skill = _core("skill_check")
    update = _core("update_combatant")
    setup = _core("setup_combat")
    add = _core("add_combatant")
    dc = integer("The difficulty class to beat.")
    skill_props = {
        "skill": string(
            "The skill by its 3.5 name or id, or a unique part of one: 'move silently', 'open lock', 'lock'."
        ),
        "modifier": integer("Added to the d20: circumstances, the DM's ruling."),
        "dc": dc,
    }
    setup_enemies = {
        **setup.params["properties"]["enemies"],
        "description": setup.params["properties"]["enemies"]["description"]
        + " Under 3.5 a group also takes ac, touch_ac, flat_footed_ac, attack_bonus, damage, critical ('19–20/×2') and"
        ' saves ({"fort", "ref", "will"}); thac0 means nothing.',
    }
    condition = string(
        "flanked (+2; an ally on the target's far side; melee only), charging (+2, -2 AC until its next turn), "
        "set_vs_charge (double damage), into_melee (a ranged attack, shot or thrown, at a foe engaged in melee: -4, "
        "none with Precise Shot); rear and fleeing give nothing in 3.5."
    )
    setup_surprise = boolean("Ignored: 3.5 has no surprise roll. Put flat-footed on the unaware (add_condition).")
    return [
        *(replace(spec, rulesets=(RULESET,)) for spec in own),
        _scoped(
            saving,
            "A Fortitude, Reflex or Will save for anyone: d20 + the save + modifier against the DC; a natural 1 fails "
            "and a natural 20 succeeds. A character from its sheet, a combatant from its numbers; in a fight it is "
            "that round's save, with the combatant's effects.",
            {"save_type": string("fort, ref or will (or Fortitude, Reflex, Will)."), "dc": dc},
            _saving_throw(saving),
        ),
        _scoped(
            skill,
            "A 3.5 skill check from the character's sheet: d20 + the skill's total + modifier against the DC (no DC: "
            "the total, for you to judge). A trained-only skill without ranks can't be tried.",
            skill_props,
            _skill_check,
        ),
        _scoped(resolve, resolve.description, {"condition": condition}, resolve.fn),
        _scoped(
            update,
            "Set a combatant's numbers to what the module or your ruling says: hit points and morale in stats, and "
            "its 3.5 numbers (AC, touch and flat-footed AC, the held attack's bonus, damage and critical, saves). A "
            "PC's come from its sheet (set_build).",
            OVERRIDE_PROPS,
            _update_combatant(update),
            required=("id",),
        ),
        _scoped(
            setup, setup.description, {"enemies": setup_enemies, "surprise": setup_surprise}, _setup_combat(setup)
        ),
        _scoped(
            add,
            "Monsters joining the live fight (reinforcements), as setup_combat's enemy groups, each with its 3.5 "
            "numbers from its SRD row. They act from the next initiative.",
            {},
            _add_combatant(add),
        ),
        _scoped(_core("surprise_check"), f"Not in 3.5. {NO_SURPRISE}", {}, _not_in_3_5(NO_SURPRISE)),
        _scoped(_core("morale_check"), f"Not in 3.5. {NO_MORALE}", {}, _not_in_3_5(NO_MORALE)),
        _scoped(_core("reaction"), f"Not in 3.5. {NO_REACTION}", {}, _not_in_3_5(NO_REACTION)),
        _scoped(_core("council"), f"Not in 3.5. {NO_REACTION}", {}, _not_in_3_5(NO_REACTION)),
    ]
