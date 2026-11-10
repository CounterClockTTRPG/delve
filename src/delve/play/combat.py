"""Combat in a campaign (spec §6.5): the `delve.rules.classic.combat` state machine, stored in `combats`, one live fight
per campaign, on the map the party is on.

The tracker is where a fight's hit points, conditions and effects live. Every change to a character in it is written
through to the character's state, so its sheet follows the fight, and a change made through `play.characters` while it
fights (a potion, a trap) goes through the tracker, so nothing is lost. `end_combat` writes each character's hit
points, conditions and effects back through `play.characters`.

Every function takes the `CampaignContext` of the tool call first; a fight's rules errors become `PlayError`, and an
unknown or ambiguous name `NotFound` with the candidates.

Initiative is rolled in the campaign's mode (`campaigns.initiative`, per combatant or per side) at the start of each
round, so a change takes effect at the next one. Each round's order and outcomes are recorded in `combat_rounds` (table
voice and fixes Task B1.3): `setup_combat` puts round 1 once its initiative is rolled, `combat_round` puts the round
it resolves, with its outcomes; `delve.play.timeline` releases them to the table after the DM's text.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from delve.dice import Dice
from delve.domain.campaigns import Character, CombatRound, InitiativeMode
from delve.domain.characters import Effect
from delve.domain.data import to_dict
from delve.maps import state as map_state
from delve.maps.tokens import Token
from delve.play import characters
from delve.play import spells as play_spells
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.play.stated_stats import stated_differences
from delve.rules.classic import checks
from delve.rules.classic import combat as rules
from delve.storage.interfaces import Storage

__all__ = [
    "add_combatant",
    "add_condition",
    "adjudicate",
    "apply_effect",
    "combat_round",
    "combat_status",
    "combatant",
    "damage",
    "end_combat",
    "heal",
    "interrupt",
    "remove_combatant",
    "remove_condition",
    "remove_effect",
    "resolve_attack",
    "saving_throw",
    "setup_combat",
    "tokens",
]


def _rules[T](command: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a rules command, its refusals as `PlayError` and its unknown names as `NotFound`."""
    try:
        return command(*args, **kwargs)
    except rules.UnknownCombatant as error:
        raise NotFound(error.message, error.candidates, error.hint) from None
    except rules.CombatError as error:
        raise PlayError(error.message, error.hint) from None


def _live(ctx: CampaignContext) -> tuple[str, rules.Combat] | None:
    live = ctx.storage.combats.live(ctx.campaign_id)
    return None if live is None else (live[0], rules.from_json(live[1]))


def _fight(ctx: CampaignContext) -> tuple[str, rules.Combat]:
    live = _live(ctx)
    if live is None:
        raise PlayError("No combat is under way.", hint="Start one with setup_combat.")
    return live


def _dice(ctx: CampaignContext, id: str) -> Dice:
    """The fight's dice: the beat's, keyed by the beat and the fight's id, so a second fight in one beat rolls fresh
    while a roll repeated within a fight is the stored one (spec §6.5)."""
    return Dice(ctx.dice.rng, ctx.storage.rolls, ctx.campaign_id, f"{ctx.beat}/{id}")


def _surprise_dice(ctx: CampaignContext) -> Dice:
    """The dice of a fight's surprise: keyed by the beat and the number of fights played to their end in it, so a
    fight set up and ended before any round or attack (a correction) and set up again finds the surprise it rolled,
    while the fight after a played one rolls fresh (review F3). Only the beat's own events are read."""
    events = ctx.storage.events.list(ctx.campaign_id, types=["combat", "combat_round", "attack"], beat=ctx.beat)
    played = {e.data.get("combat_id") for e in events if e.type in ("combat_round", "attack")}
    ended = {e.data.get("combat_id") for e in events if e.type == "combat" and e.data.get("outcome") == "ended"}
    return Dice(ctx.dice.rng, ctx.storage.rolls, ctx.campaign_id, f"{ctx.beat}/surprise-{len(ended & played)}")


def _mode(ctx: CampaignContext) -> InitiativeMode:
    """The campaign's initiative mode, as it is now: the round about to be rolled uses it."""
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    return campaign.initiative if campaign is not None else "combatant"


def _record(
    ctx: CampaignContext,
    id: str,
    round: int,
    mode: InitiativeMode,
    slots: Iterable[dict[str, Any]],
    outcomes: dict[str, Any] | None = None,
) -> None:
    """The round's row in `combat_rounds`: its order once its initiative is rolled, and its outcomes once resolved."""
    now = ctx.clock.now().isoformat()
    before = ctx.storage.combat_rounds.get(id, round)
    ctx.storage.combat_rounds.put(
        CombatRound(
            combat_id=id,
            round=round,
            campaign_id=ctx.campaign_id,
            mode=mode,
            slots=tuple(slots),
            outcomes=outcomes,
            beat_id=ctx.beat,
            rolled_at=before.rolled_at if before is not None else now,
            resolved_at=now if outcomes is not None else None,
        )
    )


def _durable(conditions: Iterable[str]) -> tuple[str, ...]:
    return tuple(c for c in conditions if c not in rules.COMBAT_ONLY)


def _write_through(ctx: CampaignContext, fight: rules.Combat) -> None:
    """Each character's hit points, conditions and effects from the tracker into its state, where they changed."""
    for c in fight.combatants.values():
        character = ctx.storage.characters.get(c.character_id) if c.character_id else None
        if character is None:
            continue
        conditions = characters.life_conditions(_durable(c.conditions), c.hp)
        state = replace(character.state, hp=c.hp, conditions=conditions, effects=c.effects)
        if state != character.state:
            ctx.storage.characters.save_state(replace(character, state=state))


def _store(ctx: CampaignContext, id: str, fight: rules.Combat) -> None:
    ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))
    _write_through(ctx, fight)


def _change(ctx: CampaignContext, command: Callable[..., tuple[rules.Combat, dict]], *args: Any, **kwargs: Any) -> dict:
    """Apply a rules command to the live fight and store it."""
    id, fight = _fight(ctx)
    fight, out = _rules(command, fight, *args, **kwargs)
    _store(ctx, id, fight)
    return out


def _positions(ctx: CampaignContext, party: list[Character]) -> tuple[str | None, dict[str, str]]:
    """The map most of the party is on, and where each of them stands on it."""
    best: tuple[str | None, dict[str, str]] = (None, {})
    for name, raw in ctx.storage.map_states.list(ctx.campaign_id).items():
        state = map_state.from_json(raw)
        here = {
            c.id: view.location
            for c in party
            if (view := state.characters.get(c.id)) is not None and view.location is not None
        }
        if len(here) > len(best[1]):
            best = (name, here)
    return best


def _party_node(fight: rules.Combat) -> str | None:
    """Where most of the party stands: the node a monster given none joins the fight in."""
    nodes = Counter(c.node for c in fight.combatants.values() if c.character_id and c.node)
    return nodes.most_common(1)[0][0] if nodes else None


def _summary(action: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("attacker", "caster", "actor", "target", "spell", "action", "hit", "damage", "cast", "skipped")
    return {k: action[k] for k in keys if k in action}


def setup_combat(
    ctx: CampaignContext,
    enemies: list[dict[str, Any]],
    party_modifier: int = 0,
    enemy_modifier: int = 0,
    surprise: bool = True,
    spells: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Stand up a whole encounter in one call, as ttrpg2's: the party (where it stands on its map), the monsters looked
    up and added, surprise, round 1's spell declarations, and round 1's initiative.

    enemies: `[{"name": "goblin", "count": 3, "node": "room.guardroom"}]`; `node` defaults to where the party is, and
    a spec may override the monster entry's hp, ac, thac0, dmg, dmg_large, morale, weapon_speed, label, size and
    attacks_per_round, and set side ("ally" for a third party). spells: `[{"caster": "Corwin", "spell": "sleep"}]`.

    Refused while a fight is live: end it first. One transaction: a setup refused halfway leaves no fight."""
    with ctx.storage.transaction():
        return _setup(ctx, enemies, party_modifier, enemy_modifier, surprise, spells)


def _setup(
    ctx: CampaignContext,
    enemies: list[dict[str, Any]],
    party_modifier: int,
    enemy_modifier: int,
    surprise: bool,
    spells: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    if not isinstance(enemies, list) or not enemies:
        raise PlayError("enemies must be a non-empty list of specs, e.g. [{'name': 'goblin', 'count': 3}].")
    live = _live(ctx)
    party = characters.party(ctx)
    map_name, nodes = _positions(ctx, party)
    fight, started = _rules(
        rules.start,
        party,
        map_nodes=nodes,
        live=live[1] if live else None,
        reference=ctx.lookups,
        rules=ctx.rules,
    )
    fight = replace(fight, map=map_name)
    # Checked before the fight is stored, so a spell not memorized leaves none half set up (DEL-326).
    memorized = _memorized_spells(ctx, fight, [s for s in spells or [] if isinstance(s, dict)])
    id = ctx.storage.combats.create(ctx.campaign_id, fight.phase, rules.to_json(fight))
    dice = _dice(ctx, id)
    near_party = _party_node(fight)
    groups: list[dict[str, Any]] = []
    notes: list[str] = []
    for spec in enemies:
        if not isinstance(spec, dict):
            notes.append(f"Skipped non-dict enemy spec: {spec!r}")
            continue
        spec = dict(spec)
        name = str(spec.pop("name", "") or "").strip()
        if not name:
            notes.append("Skipped enemy spec with no name.")
            continue
        count, node, side = spec.pop("count", 1), spec.pop("node", None) or near_party, spec.pop("side", "enemy")
        fight, group = _rules(
            rules.add_monsters, fight, dice, ctx.lookups, name, count, node=node, side=side, overrides=spec
        )
        notes.extend(group.pop("notes", []))
        rows = ctx.lookups.monster(name)
        notes.extend(stated_differences(ctx.storage, ctx.campaign_id, name, rows[0] if rows else None))
        groups.append(group)

    out: dict[str, Any] = {"party_loaded": started["party_loaded"], "party_attacks": started["party_attacks"]}
    if started.get("warnings"):
        out["warnings"] = started["warnings"]
    out["enemies"] = groups
    if surprise:
        result = checks.surprise(
            _surprise_dice(ctx), party_modifier=party_modifier, enemy_modifier=enemy_modifier, rules=ctx.rules
        )
        fight, out["surprise"] = _rules(rules.apply_surprise, fight, result)
    if spells:
        out["declared"] = []
        for spell in spells:
            if not isinstance(spell, dict) or not spell.get("caster") or not spell.get("spell"):
                notes.append(f"Skipped spell declaration {spell!r} — needs caster and spell.")
                continue
            fight, declared = _rules(rules.declare, fight, str(spell["caster"]), spell, ctx.lookups)
            casting_time, init, found = rules.casting_time(ctx.lookups, declared["spell"])
            declared["casting_time"] = casting_time if found else "not found in DB — defaulting to 5"
            declared["casting_time_init"] = init
            out["declared"].append(declared)
        if spent := _spend(ctx, memorized):
            out["spells_spent"] = spent
    fight, initiative = _rules(rules.roll_initiative, fight, dice, ctx.lookups, _mode(ctx), ctx.rules)
    out["order"] = initiative["order"]
    if fight.mode == "side":
        out["sides"] = initiative["sides"]
    _store(ctx, id, fight)
    _record(ctx, id, fight.round, fight.mode, rules.slots(fight))
    ctx.log(
        "combat_started",
        combat_id=id,
        map=map_name,
        combatants=[{"id": c.id, "name": c.name, "side": c.side} for c in fight.combatants.values()],
    )
    out["combat"] = rules.status(fight)
    if notes:
        out["notes"] = notes
    return out


# What a combatant's entry in `combat_round`'s status keeps (DEL-79): what the round changed, not its fixed stats
# (armour class, THAC0, size, damage, weapon, morale), which `combat_status` and `setup_combat` give in full.
ROUND_STATUS_KEYS = ("id", "name", "side", "hp", "hp_max", "status")
ROUND_STATUS_IF_ANY = ("node", "conditions", "effects", "ongoing", "attacks_remaining_this_round")


def round_status(fight: rules.Combat) -> dict[str, Any]:
    """The fight after a round, as `combat_round` answers it: the round and who stands how, the fixed stats left out
    and an empty field dropped. The round's rolls are in its actions and its initiative, so it has no list of them."""
    full = rules.status(fight)
    combatants = [
        {
            **{key: entry[key] for key in ROUND_STATUS_KEYS},
            **{key: entry[key] for key in ROUND_STATUS_IF_ANY if entry.get(key) not in (None, [], {})},
        }
        for entry in full["combatants"]
    ]
    return {**{key: full[key] for key in ("phase", "round", "current")}, "combatants": combatants}


def _memorized_spells(ctx: CampaignContext, fight: rules.Combat, declarations: Iterable[Any]) -> list[tuple[str, str]]:
    """The party casters' spells among `declarations` (a spell, not a scroll or an item), as `(character id, spell)`,
    each checked to be memorized and uncast (DEL-326): `PlayError` before anything of the round is resolved when one
    isn't. A caster whose sheet has no spell slots keeps no memorized spells, and casts as before."""
    spent: list[tuple[str, str]] = []
    for raw in declarations:
        if not isinstance(raw, dict) or not raw.get("spell") or raw.get("item"):
            continue
        if str(raw.get("kind") or "spell") != "spell":
            continue
        who = raw.get("caster") or raw.get("actor") or raw.get("attacker")
        try:
            c = rules.find(fight, str(who))
        except rules.CombatError:
            continue  # the rules refuse an unknown caster themselves
        if c.character_id is None:
            continue
        character = ctx.storage.characters.get(c.character_id)
        if character is None or not character.sheet.spell_slots:
            continue
        spell = str(raw["spell"]).strip()
        uncast = [s for s in character.state.memorized if not s.cast and s.name.casefold() == spell.casefold()]
        waiting = sum(1 for id, name in spent if id == character.id and name.casefold() == spell.casefold())
        if len(uncast) <= waiting:
            cast = any(s.name.casefold() == spell.casefold() for s in character.state.memorized)
            left = sorted({s.name for s in character.state.memorized if not s.cast})
            raise PlayError(
                f"{character.name} has {'already cast every memorized' if cast else 'not memorized'} {spell}.",
                hint=f"Memorized and uncast: {', '.join(left) or 'nothing'}. A scroll is cast with item and kind.",
            )
        spent.append((character.id, spell))
    return spent


def _spend(ctx: CampaignContext, spells: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Spend each declared spell's memorized copy: a spell is used up when it is begun, cast or spoiled (PHB ch. 7)."""
    out = []
    for character_id, spell in spells:
        cast = play_spells.cast(ctx, character_id, spell)
        out.append({"caster": cast["name"], "spell": cast["spell"], "remaining": cast["remaining"]})
    return out


def combat_round(ctx: CampaignContext, actions: list[dict[str, Any]]) -> dict[str, Any]:
    """One round: its declarations, its initiative (unless setup rolled it), the actions in initiative order, and the
    end of the round (see `rules.run_round`). With no actions it just ends the round. The result leaves out the
    rules' list of the round's rolls, which repeats its actions and initiative, and its status keeps only what a round
    changes (`round_status`): a round's result was 14–17 KB (DEL-79)."""
    id, fight = _fight(ctx)
    if not isinstance(actions, list):
        raise PlayError("actions must be a list of {attacker, target} dicts.")
    memorized = _memorized_spells(ctx, fight, actions)
    fight, result = _rules(rules.run_round, fight, _dice(ctx, id), ctx.lookups, actions, _mode(ctx), ctx.rules)
    spent = _spend(ctx, memorized)
    _store(ctx, id, fight)
    _record(ctx, id, result.round, result.mode, result.slots, result.outcomes)
    ctx.log("combat_round", combat_id=id, round=result.round, actions=[_summary(a) for a in result.actions])
    out = result.to_dict()
    del out["rolls"]
    return {**out, **({"spells_spent": spent} if spent else {}), "status": round_status(fight)}


def resolve_attack(
    ctx: CampaignContext, attacker: str, target: str, condition: str = "", weapon: str = ""
) -> dict[str, Any]:
    """One attack in the current round, applied at once (see `rules.attack`)."""
    id, fight = _fight(ctx)
    fight, out = _rules(rules.attack, fight, _dice(ctx, id), attacker, target, condition=condition, weapon=weapon)
    _store(ctx, id, fight)
    ctx.log("attack", combat_id=id, round=fight.round, **_summary(out))
    return out


def throw_missile(ctx: CampaignContext, thrower: str, target: str, missile: str) -> dict[str, Any]:
    """A flask of oil or a vial of holy water thrown in the current round, applied at once (see `rules.throw`)."""
    id, fight = _fight(ctx)
    fight, out = _rules(rules.throw, fight, _dice(ctx, id), thrower, target, missile, ctx.lookups)
    _store(ctx, id, fight)
    ctx.log("attack", combat_id=id, round=fight.round, **_summary(out))
    return out


def update_combatant(ctx: CampaignContext, ref: str, changes: Mapping[str, Any]) -> dict[str, Any]:
    return _change(ctx, rules.update_combatant, ref, changes)


def combat_status(ctx: CampaignContext) -> dict[str, Any]:
    return rules.status(_fight(ctx)[1])


def combatant(ctx: CampaignContext, ref: str) -> rules.Combatant | None:
    """The live fight's combatant with the id `ref` or exactly that name; None when no fight is live or none is
    called that. A name several combatants share raises `NotFound` with them."""
    live = _live(ctx)
    if live is None:
        return None
    fight = live[1]
    wanted = str(ref).strip()
    if wanted in fight.combatants or any(
        c.name.strip().casefold() == wanted.casefold() for c in fight.combatants.values()
    ):
        return _rules(rules.find, fight, wanted)
    return None


def end_combat(ctx: CampaignContext) -> dict[str, Any]:
    """End the fight: each character's hit points, conditions and effects are written back to its state, and one
    `combat` event records the outcome, with the defeated groups for XP and treasure."""
    id, fight = _fight(ctx)
    ended, outcome = _rules(rules.end, fight)
    ctx.storage.combats.save(id, ended.phase, rules.to_json(ended))
    for character_id, back in outcome["characters"].items():
        if ctx.storage.characters.get(character_id) is not None:
            characters.update(ctx, character_id, back, reason="end of combat")
    party_hp = {c.name: c.hp for c in fight.combatants.values() if c.side == "party"}
    ctx.log(
        "combat",
        combat_id=id,
        outcome="ended",
        rounds=outcome["rounds"],
        party_hp=party_hp,
        enemies=outcome["enemies"],
        defeated=outcome["defeated"],
    )
    return {key: outcome[key] for key in ("saved", "rounds", "defeated", "groups", "enemies", "characters")}


def add_combatant(
    ctx: CampaignContext,
    name: str,
    *,
    count: int = 1,
    node: str | None = None,
    side: rules.Side = "enemy",
    stats: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Monsters joining the live fight, as `setup_combat`'s enemy specs (`stats` may give `hp_max`, which defaults to
    `hp`); they act from the next initiative."""
    id, fight = _fight(ctx)
    node = node or _party_node(fight)
    fight, group = _rules(
        rules.add_monsters, fight, _dice(ctx, id), ctx.lookups, name, count, node=node, side=side, overrides=stats
    )
    _store(ctx, id, fight)
    return group


def remove_combatant(ctx: CampaignContext, ref: str, reason: str = "") -> dict[str, Any]:
    return _change(ctx, rules.remove, ref, reason)


def damage(ctx: CampaignContext, ref: str, amount: int) -> dict[str, Any]:
    return _change(ctx, rules.damage, ref, amount)


def heal(ctx: CampaignContext, ref: str, amount: int) -> dict[str, Any]:
    return _change(ctx, rules.heal, ref, amount)


def add_condition(ctx: CampaignContext, ref: str, condition: str) -> dict[str, Any]:
    return _change(ctx, rules.add_condition, ref, condition)


def remove_condition(ctx: CampaignContext, ref: str, condition: str) -> dict[str, Any]:
    return _change(ctx, rules.remove_condition, ref, condition)


def apply_effect(
    ctx: CampaignContext,
    ref: str,
    name: str,
    duration: int,
    to_hit: int = 0,
    ac: int = 0,
    dmg: int = 0,
    save: int = 0,
    source: str = "",
    hidden: bool = False,
) -> dict[str, Any]:
    if int(duration) < 0:
        raise PlayError("The duration is a number of rounds, or 0 for an effect that lasts until removed.")
    effect = Effect(name, int(duration), int(to_hit), int(ac), int(dmg), int(save), source, bool(hidden))
    if _live(ctx) is None:
        # Outside a fight, on the character itself (DEL-334: refused, the DM patched the sheet by hand).
        character = characters.get(ctx, ref)
        state = replace(character.state, effects=(*character.state.effects, effect))
        ctx.storage.characters.save_state(replace(character, state=state))
        ctx.log("effect", character_id=character.id, name=character.name, effect=effect.name)
        return {"target": character.name, "target_id": character.id, "effect": to_dict(effect)}
    return _change(ctx, rules.apply_effect, ref, effect)


def remove_effect(ctx: CampaignContext, ref: str, name: str) -> dict[str, Any]:
    """An effect taken off before it runs out: in a fight, the combatant's; outside one, the character's own (DEL-334:
    an invisibility left on after the fight was refused as "No combat is under way")."""
    if _live(ctx) is not None:
        return _change(ctx, rules.remove_effect, ref, name)
    character = characters.get(ctx, ref)
    effects = character.state.effects
    index = next((i for i, e in enumerate(effects) if e.name.casefold() == name.strip().casefold()), None)
    if index is None:
        raise PlayError(
            f"No active effect named '{name}' on {character.name}.",
            hint=f"Its effects: {', '.join(e.name for e in effects) or 'none'}.",
        )
    state = replace(character.state, effects=effects[:index] + effects[index + 1 :])
    ctx.storage.characters.save_state(replace(character, state=state))
    ctx.log("effect_removed", character_id=character.id, name=character.name, effect=effects[index].name)
    return {"target": character.name, "target_id": character.id, "removed": to_dict(effects[index])}


def adjudicate(ctx: CampaignContext, note: str, effects: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The DM's ruling on something unusual, logged and applied: in a fight to its combatants, outside one to the
    characters it names (backlog Fixes 10: it was refused outside a fight)."""
    if _live(ctx) is not None:
        out = _change(ctx, rules.adjudicate, note, list(effects))
    else:
        out = _ruling(ctx, note, list(effects))
    ctx.log("ruling", **out)
    return out


def _ruling(ctx: CampaignContext, note: str, effects: list[Mapping[str, Any]]) -> dict[str, Any]:
    """A ruling outside a fight: each effect on the character it names, by id or exact name."""
    if not str(note or "").strip():
        raise PlayError("A ruling needs a note saying what was decided.")
    with ctx.storage.transaction():
        applied = []
        for raw in effects:
            raw = dict(raw)
            target = raw.pop("target", None)
            if not target:
                raise PlayError("Each effect of a ruling names its target.")
            who = characters.get(ctx, str(target))
            effect = _rules(rules._effect, raw)
            listed = [rules.effect_json(e) for e in (*who.state.effects, effect)]
            characters.update(ctx, who.id, {"effects": listed}, reason="ruling")
            applied.append({"target": who.name, "target_id": who.id, "effect": rules.effect_json(effect)})
    return {"note": note.strip(), "effects": applied}


def interrupt(ctx: CampaignContext, ref: str, reason: str) -> dict[str, Any]:
    """Break a combatant's ongoing action (see `rules.interrupt`). What the characters perceive names a party
    member's spell; an enemy's stays the DM's (table voice and fixes Decision 10)."""
    id, fight = _fight(ctx)
    fight, out = _rules(rules.interrupt, fight, ref, reason)
    _store(ctx, id, fight)
    ctx.log("interrupted", combat_id=id, round=fight.round, id=out["id"], what=out["what"], reason=out["reason"])
    if out["side"] == "enemy":
        noun = {"spell": "spell", "scroll": "scroll"}.get(out["kind"], "action")
        return {
            "id": out["id"],
            "name": out["name"],
            "kind": out["kind"],
            "perceived": f"{out['reason']}; its {noun} is lost",
            "dm_only": {"what": out["what"]},
        }
    return {"id": out["id"], "name": out["name"], "kind": out["kind"], "perceived": out["lost"], "dm_only": {}}


def saving_throw(ctx: CampaignContext, ref: str, save_type: str, modifier: int = 0) -> dict[str, Any]:
    """A combatant's saving throw in the current round: a character's from its sheet, a monster's by its Hit Dice.
    The same save twice in a round, within one beat, is the stored roll."""
    id, fight = _fight(ctx)
    combatant = _rules(rules.find, fight, ref)
    character = ctx.storage.characters.get(combatant.character_id) if combatant.character_id else None
    sheet = character.sheet if character is not None else None
    fight, out = _rules(
        rules.saving_throw,
        fight,
        _dice(ctx, id),
        ctx.lookups,
        combatant.id,
        save_type,
        modifier=modifier,
        sheet=sheet,
        rules=ctx.rules,
    )
    _store(ctx, id, fight)
    return out


def tokens(storage: Storage, campaign_id: str, map_name: str) -> list[Token]:
    """The live fight's tokens on `map_name`: characters where the map state has them, monsters where they joined.
    The slain and the removed are off the board."""
    live = storage.combats.live(campaign_id)
    if live is None:
        return []
    fight = rules.from_json(live[1])
    if fight.map != map_name:
        return []
    raw = storage.map_states.get(campaign_id, map_name)
    positions = map_state.from_json(raw).characters if raw is not None else {}
    out = []
    for c in fight.combatants.values():
        state = rules.status_of(c)
        if state == "removed" or (state == "dead" and c.character_id is None):
            continue
        view = positions.get(c.character_id) if c.character_id else None
        character = storage.characters.get(c.character_id) if c.character_id else None
        rank = character.order if character is not None else None  # the marching order's front ranks (DEL-271)
        out.append(Token(c.id, c.name, view.location if view and view.location else c.node, c.side, rank=rank))
    return out


# --- a character changed through play.characters while it fights ------------------------------------------------


def _fighting(ctx: CampaignContext, character: Character) -> tuple[str, rules.Combat] | None:
    live = _live(ctx)
    if live is None or character.id not in live[1].combatants:
        return None
    return live


def tracked_damage(ctx: CampaignContext, character: Character, amount: int) -> dict[str, Any] | None:
    """`play.characters.apply_damage` for a character in the live fight, through the tracker; None when it isn't in
    one."""
    live = _fighting(ctx, character)
    if live is None:
        return None
    id, fight = live
    fight, out = _rules(rules.damage, fight, character.id, amount)
    _store(ctx, id, fight)
    ctx.log(
        "damage",
        character_id=character.id,
        name=character.name,
        amount=amount,
        hp_before=out["hp_before"],
        hp_after=out["hp_after"],
        in_combat=True,
    )
    result = {"character_id": character.id, "name": character.name, "damage": amount, "in_combat": True}
    return {**result, **{k: v for k, v in out.items() if k not in ("id", "name")}}


def tracked_heal(ctx: CampaignContext, character: Character, amount: int) -> dict[str, Any] | None:
    """`play.characters.apply_heal` for a character in the live fight, through the tracker; None when it isn't in
    one."""
    live = _fighting(ctx, character)
    if live is None:
        return None
    id, fight = live
    fight, out = _rules(rules.heal, fight, character.id, amount)
    _store(ctx, id, fight)
    ctx.log(
        "heal",
        character_id=character.id,
        name=character.name,
        amount=amount,
        hp_before=out["hp_before"],
        hp_after=out["hp_after"],
        in_combat=True,
    )
    result = {"character_id": character.id, "name": character.name, "in_combat": True}
    return {**result, **{k: v for k, v in out.items() if k not in ("id", "name")}}


def rearm(ctx: CampaignContext, character: Character) -> None:
    """A character's attacks, weapon or THAC0 changed (`play.characters.update`) while it fights: the tracker takes its
    attack blocks and THAC0 again from the sheet, keeping the weapon in hand when it has one of that name (DEL-332: a
    +1 axe handed over mid-fight still rolled as the old one)."""
    live = _fighting(ctx, character)
    if live is None:
        return
    id, fight = live
    c = fight.combatants[character.id]
    blocks, _ = rules.party_blocks(character, ctx.lookups, ctx.rules)
    held = c.attacks[c.weapon].name if 0 <= c.weapon < len(c.attacks) else ""
    weapon = next((i for i, b in enumerate(blocks) if b.name == held), 0)
    c = replace(c, attacks=tuple(blocks), weapon=weapon, thac0=character.sheet.thac0)
    fight = replace(fight, combatants={**fight.combatants, c.id: c})
    ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))


def drained(ctx: CampaignContext, character: Character, thac0_change: int) -> None:
    """A character lost levels (`play.characters.drain_level`) while it fights: the tracker takes its hit points, their
    new maximum and its conditions, and its THAC0 and each attack's move by `thac0_change`."""
    live = _fighting(ctx, character)
    if live is None:
        return
    id, fight = live
    c = fight.combatants[character.id]
    own = tuple(k for k in c.conditions if k in rules.COMBAT_ONLY and k not in character.state.conditions)
    c = replace(
        c,
        hp=character.state.hp,
        hp_max=character.sheet.hp_max,
        conditions=(*character.state.conditions, *own),
        thac0=c.thac0 + thac0_change,
        attacks=tuple(a if a.thac0 is None else replace(a, thac0=a.thac0 + thac0_change) for a in c.attacks),
    )
    fight = replace(fight, combatants={**fight.combatants, c.id: c})
    ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))


def mirror(ctx: CampaignContext, character: Character) -> None:
    """A character's state changed through `play.characters.update` while it fights: the tracker takes its hit points,
    conditions and effects, keeping the combat's own conditions."""
    live = _fighting(ctx, character)
    if live is None:
        return
    id, fight = live
    c = fight.combatants[character.id]
    own = tuple(k for k in c.conditions if k in rules.COMBAT_ONLY and k not in character.state.conditions)
    c = replace(
        c, hp=character.state.hp, conditions=(*character.state.conditions, *own), effects=character.state.effects
    )
    fight = replace(fight, combatants={**fight.combatants, c.id: c})
    ctx.storage.combats.save(id, fight.phase, rules.to_json(fight))
