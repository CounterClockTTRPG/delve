"""Combat on the map (spec §6.5): a state machine with surprise, initiative re-rolled every round (per combatant or
per side, as the campaign says), ongoing actions that carry over and can be interrupted, attacks, saves, morale and
the end of the fight, one live fight per campaign (ttrpg2 `tools/combat.py`). Combatants are named by id (`chr_…`,
`mon_1`) or exact name; a name several share answers with the candidates, never a guess.

The DM's guidance for ongoing actions and `interrupt` is in these descriptions (table voice and fixes Decision 11)."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, array, boolean, integer, obj, params, string, tool
from delve.play import combat
from delve.play.context import CampaignContext

SPECS: list[ToolSpec] = []

COMBATANT = string("A combatant by id (chr_…, mon_1) or exact name ('Goblin 2').")


@tool(
    SPECS,
    "setup_combat",
    params(
        "enemies",
        enemies=array(
            'The enemy groups: [{"name": "goblin", "count": 3, "node": "room.guardroom"}]. node defaults to where the '
            "party is; a group may override hp, ac, thac0, dmg, dmg_large, morale, weapon_speed, label, size and "
            'attacks_per_round, and take side "ally". When the module states a monster\'s numbers (the notes say so), '
            "pass them here: ac, hp, thac0. Pass weapon_speed for a monster wielding a weapon its entry doesn't name; "
            "without it, one fighting with claws or bites acts on its size.",
            {"type": "object"},
            minItems=1,
        ),
        party_modifier=integer("The party's surprise adjustment: positive is harder to surprise."),
        enemy_modifier=integer("The enemies' surprise adjustment: positive is harder to surprise."),
        surprise=boolean("Roll surprise (default true)."),
        spells=array(
            'Spells declared for round 1, before its initiative: [{"caster": "Corwin", "spell": "sleep"}].',
            {"type": "object"},
        ),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def setup_combat(
    ctx: CampaignContext,
    enemies: list[dict[str, Any]],
    party_modifier: int = 0,
    enemy_modifier: int = 0,
    surprise: bool = True,
    spells: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Start a fight in one call: the party where it stands on its map, the monsters looked up and added (each with
    its own id, mon_1 …), surprise, round 1's spell declarations, and round 1's initiative, in the campaign's mode
    (per combatant, or per side: one d10 a side plus each one's own modifier). Tokens appear on the map. When the notes
    say the module states other numbers for a monster than the reference (AC 5 zombies), set it up again with the
    module's ac, hp or thac0 in its group. A spell can still be declared for round 1 in combat_round. Refused while a
    fight is live: end it first."""
    return combat.setup_combat(ctx, enemies, party_modifier, enemy_modifier, surprise, spells)


@tool(
    SPECS,
    "combat_round",
    params(
        "actions",
        actions=array(
            'The round\'s declarations, one per combatant: {"attacker", "target", "targets"?, "weapon"?, "condition"?}, '
            '{"attacker", "target", "missile"} (a thrown flask of oil or vial of holy water), {"caster", "spell", '
            '"target"?}, {"actor", "item", "kind"} (kind potion, scroll, ring, rod, stave, wand or item; a scroll\'s '
            '"spell"), or {"actor", "action", "rounds"?} (rounds: an action that takes that long). '
            "A combatant busy with an ongoing action keeps at it unless you declare another. Empty ends the round.",
            {"type": "object"},
        ),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def combat_round(ctx: CampaignContext, actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve a whole round: the declarations, initiative rolled again in the campaign's mode (d10 plus
    weapon speed, casting time or the item's modifier; per side, one d10 a side), the actions in initiative order (ties
    act simultaneously), downed and surprised combatants skipped, every attack the rate allows, then bleeding, effects
    ticking down and morale notices. Spells, scrolls, potions and long actions are ongoing until their count: a spell
    of a round or more takes effect at the end of its last round, and a hit or a failed save before then spoils a
    spell or scroll. The result's outcomes say who acted, went down, died or fled and which ongoing actions completed
    or broke; ongoing lists what carries over. Every roll is in the result."""
    return combat.combat_round(ctx, actions)


@tool(
    SPECS,
    "resolve_attack",
    params(
        "attacker",
        "target",
        attacker=COMBATANT,
        target=COMBATANT,
        condition=string("rear (+2), charging (+2, AC penalty), set_vs_charge (double damage) or fleeing (rear +2)."),
        weapon=string("Part of the name of one of the attacker's attacks: 'bow', 'undead'."),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def resolve_attack(
    ctx: CampaignContext, attacker: str, target: str, condition: str = "", weapon: str = ""
) -> dict[str, Any]:
    """One attack in the current round, after its initiative, applied at once: the to-hit roll against the target's
    AC, the damage for its size, and the hit points. A downed or dead attacker can't swing."""
    return combat.resolve_attack(ctx, attacker, target, condition, weapon)


@tool(
    SPECS,
    "throw_missile",
    params(
        "thrower",
        "target",
        "missile",
        thrower=COMBATANT,
        target=COMBATANT,
        missile=string("What is thrown.", enum=["oil", "holy water"]),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def throw_missile(ctx: CampaignContext, thrower: str, target: str, missile: str) -> dict[str, Any]:
    """A grenade-like missile thrown in the current round, after its initiative, applied at once: the thrower's
    to-hit roll against the target's AC, then burning oil's 2d6 (and 1d6 the next round) or holy water's 2d4 to the
    undead. A miss shatters nearby: the notes say the splash for you to rule. In combat_round, declare it as
    {"attacker", "target", "missile"} instead."""
    return combat.throw_missile(ctx, thrower, target, missile)


@tool(
    SPECS,
    "update_combatant",
    params(
        "id",
        "stats",
        id=COMBATANT,
        stats=obj("What to set: hp, hp_max, ac, thac0, morale (whole numbers), dmg and dmg_large (dice, '1d6')."),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def update_combatant(ctx: CampaignContext, id: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Set a combatant's numbers to what the module or your ruling says: its hit points, AC, THAC0, morale and its
    attack's damage dice, in place of an effect that only approximates them. A PC's come from its sheet
    (update_character)."""
    return combat.update_combatant(ctx, id, stats)


@tool(
    SPECS,
    "add_combatant",
    params(
        "name",
        name=string("The monster, as monster_lookup names it: 'goblin'."),
        count=integer("How many (default 1).", minimum=1),
        node=string("The room it joins in; where the party is when empty."),
        side=string("enemy (default), ally or party.", enum=["enemy", "ally", "party"]),
        stats=obj("Overrides of its entry: hp, ac, thac0, dmg, dmg_large, morale, weapon_speed, label, size…"),
        hp_max=integer("Its full hit points, when it joins wounded (defaults to hp).", minimum=1),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def add_combatant(
    ctx: CampaignContext,
    name: str,
    count: int = 1,
    node: str = "",
    side: str = "enemy",
    stats: dict[str, Any] | None = None,
    hp_max: int | None = None,
) -> dict[str, Any]:
    """Monsters joining the live fight (reinforcements), as setup_combat's enemy groups. They act from the next
    initiative."""
    stats = {**(stats or {}), **({"hp_max": hp_max} if hp_max is not None else {})}
    return combat.add_combatant(ctx, name, count=count, node=node or None, side=side, stats=stats)  # type: ignore[arg-type]


@tool(
    SPECS,
    "remove_combatant",
    params("id", "reason", id=COMBATANT, reason=string("Why: fled the map, banished, surrendered.")),
    mutates=True,
    areas=("characters", "combat"),
)
def remove_combatant(ctx: CampaignContext, id: str, reason: str) -> dict[str, Any]:
    """Take a combatant out of the fight: it no longer acts or can be attacked. A character keeps its state."""
    return combat.remove_combatant(ctx, id, reason)


@tool(
    SPECS,
    "apply_effect",
    params(
        "target",
        "name",
        "duration",
        target=COMBATANT,
        name=string("The effect: bless, shield, prayer, poisoned…"),
        duration=integer("Rounds it lasts; 0 until removed (a worn item's).", minimum=0),
        to_hit=integer("Added to its attack rolls."),
        ac=integer("Added to its AC (negative is better)."),
        dmg=integer("Added to its damage."),
        save=integer("Added to its saving throws."),
        source=string("Who or what caused it."),
        hidden=boolean(
            "An unidentified item's: it applies, but the players don't see it and the sheet's AC and saves stay as "
            "they were, until it is identified (remove it and apply it again without hidden)."
        ),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def apply_effect(
    ctx: CampaignContext,
    target: str,
    name: str,
    duration: int,
    to_hit: int = 0,
    ac: int = 0,
    dmg: int = 0,
    save: int = 0,
    source: str = "",
    hidden: bool = False,
) -> dict[str, Any]:
    """A lasting effect on a combatant, counted down at the end of each round; its modifiers apply by themselves to
    its attacks, AC, damage and saves. It outlives the fight on a character, and outside a fight it goes on the
    character itself. A worn magic item's bonus lasts until removed (duration 0); an unidentified one's is hidden: the
    sheet the players see doesn't change."""
    return combat.apply_effect(ctx, target, name, duration, to_hit, ac, dmg, save, source, hidden)


@tool(
    SPECS,
    "remove_effect",
    params("target", "name", target=COMBATANT, name=string("The effect.")),
    mutates=True,
    areas=("characters", "combat"),
)
def remove_effect(ctx: CampaignContext, target: str, name: str) -> dict[str, Any]:
    """End an effect early: dispelled, cured; in a fight or out of one (a character's own effects)."""
    return combat.remove_effect(ctx, target, name)


@tool(
    SPECS,
    "add_condition",
    params("name", "condition", name=COMBATANT, condition=string("prone, stunned, blinded, held, fleeing…")),
    mutates=True,
    areas=("characters", "combat"),
)
def add_condition(ctx: CampaignContext, name: str, condition: str) -> dict[str, Any]:
    """Put a condition on a combatant. fleeing is attacked from the rear (+2); downed and dead come from hit points;
    stabilized on a dying PC or ally whose wounds someone bound stops its bleeding (1 HP a round otherwise).
    Rule what any other condition does (asleep, held, prone) with adjudicate, or take the combatant out with
    remove_combatant."""
    return combat.add_condition(ctx, name, condition)


@tool(
    SPECS,
    "remove_condition",
    params("name", "condition", name=COMBATANT, condition=string("The condition.")),
    mutates=True,
    areas=("characters", "combat"),
)
def remove_condition(ctx: CampaignContext, name: str, condition: str) -> dict[str, Any]:
    """Take a condition off a combatant."""
    return combat.remove_condition(ctx, name, condition)


@tool(
    SPECS,
    "adjudicate",
    params(
        "note",
        note=string("What you decided: 'Garrek grapples the goblin: it is held until it wins an opposed roll'."),
        effects=array(
            "Effects of the ruling, each as apply_effect with its target: "
            '[{"target": "mon_1", "name": "held", "duration": 2, "ac": 4}].',
            {"type": "object"},
        ),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def adjudicate(ctx: CampaignContext, note: str, effects: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Your ruling on anything the rules here don't cover: a grapple, a called shot, a stunt. It is logged, never
    refused, and its effects are applied: in a fight to its combatants, outside one to the characters named. To break
    a combatant's ongoing action, use interrupt."""
    return combat.adjudicate(ctx, note, effects or ())


@tool(
    SPECS,
    "interrupt",
    params(
        "combatant",
        "reason",
        combatant=COMBATANT,
        reason=string("Why it breaks, as the table sees it: 'Mirela was hit', 'the potion is knocked from her hand'."),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def interrupt(ctx: CampaignContext, combatant: str, reason: str) -> dict[str, Any]:
    """Break a combatant's ongoing action (a spell, a scroll, a potion, an item or a long action): it is lost, and the
    round's outcomes say why. A hit or a failed save already spoils a spell or scroll by itself; use this for what the
    rules leave to you (a potion knocked away, a caster grappled, a long action stopped). Refused when the combatant has
    nothing under way: combat_status shows each one's ongoing action."""
    return combat.interrupt(ctx, combatant, reason)


@tool(SPECS, "combat_status", params(), mutates=False)
def combat_status(ctx: CampaignContext) -> dict[str, Any]:
    """The live fight: the round, how its initiative is rolled (mode), the initiative order, and each combatant's hit
    points, AC, conditions, effects and ongoing action (what, when it started and completes, and whether it is under
    way, completed or interrupted)."""
    return combat.combat_status(ctx)


@tool(SPECS, "end_combat", params(), mutates=True, areas=("characters", "combat"))
def end_combat(ctx: CampaignContext) -> dict[str, Any]:
    """End the fight: each character's hit points, conditions and effects are written back, the tokens leave the
    map, and the defeated groups are listed for XP and treasure."""
    return combat.end_combat(ctx)
