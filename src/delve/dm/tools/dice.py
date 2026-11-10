"""Dice and checks: a free roll, saving throws for anyone (monsters in the fight too), skill and ability checks,
reaction, morale, surprise, encounters, system shock and resurrection (ttrpg2 `tools/dice.py`). Every roll goes
through the beat's dice and is logged; the same roll again in the beat is the stored one (spec §6.5)."""

from __future__ import annotations

import re
from typing import Any

from delve.dice import roll_json
from delve.dm.tools.schema import ToolSpec, boolean, integer, params, plain, string, tool
from delve.domain.campaigns import Character
from delve.play import characters, combat, factions, wandering
from delve.play.context import CampaignContext, PlayError
from delve.rules.classic import checks

SPECS: list[ToolSpec] = []

_ABILITIES = {
    "str": ("str", "strength"),
    "dex": ("dex", "dexterity"),
    "con": ("con", "constitution"),
    "int": ("int", "intelligence"),
    "wis": ("wis", "wisdom"),
    "cha": ("cha", "charisma"),
}
_NAMES = {name: short for short, names in _ABILITIES.items() for name in names}

OCCASION = string(
    "What this check is for this time ('jump the gap', 'tie the knot'); a new occasion rolls fresh, the same one again"
    " is the stored roll."
)
HIDDEN = boolean(
    "A roll the players mustn't know failed: a search, listening, finding traps. It leaves no row in the story."
)
SECRET = boolean(
    "A check the character can't know the result of: a thief's Hide in Shadows, Move Silently or Detect Noise, a "
    "check to notice something. Its dice are never shown to the players; the row stays."
)
"""(DEL-270) The story shows each seat the dice it may read; a secret check's reach the host alone."""


def game_time(ctx: CampaignContext) -> str:
    """The campaign's game time, `day 3 14:10`: the occasion of a check made once per interval."""
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    return f"day {state.day} {state.hour:02d}:{state.minute:02d}"


def _who(character: Character) -> dict[str, Any]:
    return {"character_id": character.id, "character": character.name}


def _score(character: Character, ability: str) -> int | None:
    """The character's score in an ability, its whole number ("18/76" is 18); None when the sheet has none."""
    short = _NAMES.get(ability.strip().lower())
    if short is None:
        raise PlayError(f"Unknown ability '{ability}'.", hint="Use str, dex, con, int, wis or cha.")
    scores = character.sheet.ability_scores
    value = next((scores[k] for k in _ABILITIES[short] if k in scores), None)
    if value is None:
        return None
    whole = re.match(r"\s*(\d+)", str(value))
    return int(whole.group(1)) if whole else None


def _constitution(character: Character) -> int:
    """The Constitution, 10 when the sheet has none (as ttrpg2)."""
    con = _score(character, "con")
    return 10 if con is None else con


@tool(
    SPECS,
    "roll",
    params(
        "notation",
        "purpose",
        notation=string("Dice notation: 1d20, 3d6+2, 4d6dl1 (drop the lowest), 2d20kh1 (keep the highest), d%."),
        purpose=string("What the roll is for, for the log: 'find the hidden lever', 'wandering monster'."),
        actor=string(
            "Who rolls, by id or exact name, when it is a character's own roll (a PC's contest, an NPC's try): the "
            "party's dice show to the players. Leave it out for the DM's own rolls."
        ),
        hidden=HIDDEN,
    ),
    mutates=True,
    areas=(),
)
def roll(ctx: CampaignContext, notation: str, purpose: str, actor: str = "", hidden: bool = False) -> dict[str, Any]:
    """Roll dice for anything the other tools don't cover. Every roll is logged; the same purpose again in this beat
    is the same roll, never a re-roll. At most 100 dice of at most 1000 sides. With `actor`, the roll is that
    character's: a PC's dice show to the players, as their other checks do (DEL-274)."""
    who = characters.get(ctx, actor).id if actor.strip() else None
    return roll_json(ctx.dice.roll(notation, purpose=purpose, actor=who))


@tool(
    SPECS,
    "saving_throw",
    params(
        "character",
        "save_type",
        character=string("A character, or a combatant of the live fight by id or exact name (mon_1, Goblin 2)."),
        save_type=string("One of the ruleset's saves, by its short name (para, poly, rsw, breath, spell) or its name."),
        modifier=integer("Added to the d20: magic items, spells, the DM's ruling."),
    ),
    mutates=True,
    areas=("combat",),
)
def saving_throw(ctx: CampaignContext, character: str, save_type: str, modifier: int = 0) -> dict[str, Any]:
    """A saving throw for anyone: a character from its sheet, or the ruleset's save table by class and level when the
    sheet lacks it; a monster by its Hit Dice. In a fight it is that round's save, with the combatant's
    effects. Success is a d20 at or above the number needed."""
    fighting = combat.combatant(ctx, character)
    if fighting is not None:
        return combat.saving_throw(ctx, fighting.id, save_type, modifier)
    who = characters.get(ctx, character)
    base = checks.save_base_for(who.sheet, save_type, ctx.lookups, rules=ctx.rules)
    result = checks.saving_throw(
        ctx.dice,
        save_type=save_type,
        base=base,
        modifier=modifier,
        effects=who.state.effects,
        actor=who.id,
        rules=ctx.rules,
    )
    return {**_who(who), **plain(result)}


@tool(
    SPECS,
    "skill_check",
    params(
        "character",
        "skill",
        character=string("The character."),
        skill=string("Part of the skill's name on the sheet: 'move silently', 'climb', 'pick'."),
        occasion=OCCASION,
        hidden=HIDDEN,
        secret=SECRET,
    ),
    mutates=True,
    areas=(),
)
def skill_check(
    ctx: CampaignContext, character: str, skill: str, occasion: str = "", hidden: bool = False, secret: bool = False
) -> dict[str, Any]:
    """A thief's or other percentile skill from the character's sheet: d100 at or under the percentage."""
    who = characters.get(ctx, character)
    name = checks.match_skill(who.sheet.skills, skill)
    if name is None:
        raise PlayError(
            f"Skill '{skill}' not found for {who.name}.",
            hint=f"Available: {', '.join(who.sheet.skills) or 'none'}.",
        )
    result = checks.skill_check(
        ctx.dice, skill=name, percent=int(who.sheet.skills[name]), actor=who.id, occasion=occasion.strip()
    )
    return {**_who(who), "skill": name, **plain(result)}


@tool(
    SPECS,
    "ability_check",
    params(
        "character",
        "ability",
        character=string("The character."),
        ability=string("str, dex, con, int, wis or cha."),
        modifier=integer("Added to the score: +2 for an easy task, -4 for a hard one."),
        occasion=OCCASION,
        hidden=HIDDEN,
        secret=SECRET,
    ),
    mutates=True,
    areas=(),
)
def ability_check(
    ctx: CampaignContext,
    character: str,
    ability: str,
    modifier: int = 0,
    occasion: str = "",
    hidden: bool = False,
    secret: bool = False,
) -> dict[str, Any]:
    """An ability check: a d20 at or under the ability score plus the modifier."""
    who = characters.get(ctx, character)
    score = _score(who, ability)
    if score is None:
        raise PlayError(f"{who.name}'s sheet has no {ability}.", hint="Set ability_scores with update_character.")
    name = _NAMES[ability.strip().lower()]
    result = checks.ability_check(
        ctx.dice, ability=name, score=score, modifier=modifier, actor=who.id, occasion=occasion.strip()
    )
    return {**_who(who), "ability": name, "score": score, "modifier": modifier, **plain(result)}


@tool(
    SPECS,
    "reaction",
    params(
        npc=string("The NPC reacting; their disposition towards the party, and their faction's reputation, are added."),
        modifier=integer("The situation: a bribe, a threat, the party's Charisma reaction adjustment."),
    ),
    mutates=True,
    areas=(),
)
def reaction(ctx: CampaignContext, npc: str = "", modifier: int = 0) -> dict[str, Any]:
    """An encounter reaction: the ruleset's reaction roll plus the modifier, the NPC's disposition and their faction's
    reputation with the party (each scaled to the roll, truncated towards zero), read against the ruleset's bands from
    attacks to friendly."""
    who = characters.get(ctx, npc) if npc else None
    disposition = who.sheet.disposition if who is not None else 0
    reputation = factions.reputation_of(ctx, who.sheet.faction) if who is not None else 0
    result = checks.reaction(
        ctx.dice,
        modifier=modifier,
        disposition=disposition,
        reputation=reputation,
        npc=who.id if who else None,
        rules=ctx.rules,
    )
    out = {"result": result.band, **plain(result)}
    return {"npc_id": who.id, "npc": who.name, **out} if who is not None else out


@tool(
    SPECS,
    "morale_check",
    params(
        "rating",
        rating=integer("The morale rating, as the monster's entry gives it: 2-20 on 2d10, or a percentage on 1d100."),
        modifier=integer("Situational adjustments: leader slain +2, outnumbered +2…"),
        group=string("Who checks, for the log: 'the goblins'."),
    ),
    mutates=True,
    areas=("combat",),
)
def morale_check(ctx: CampaignContext, rating: int, modifier: int = 0, group: str = "") -> dict[str, Any]:
    """A morale check: the ruleset's morale roll plus the modifier; it holds at or under the rating and breaks above
    it."""
    return plain(checks.morale(ctx.dice, rating=rating, modifier=modifier, actor=group or None, rules=ctx.rules))


@tool(
    SPECS,
    "surprise_check",
    params(
        party_modifier=integer("The party's adjustment: positive makes them harder to surprise."),
        enemy_modifier=integer("The enemies' adjustment: positive makes them harder to surprise."),
    ),
    mutates=True,
    areas=(),
)
def surprise_check(ctx: CampaignContext, party_modifier: int = 0, enemy_modifier: int = 0) -> dict[str, Any]:
    """Surprise: each side rolls the ruleset's surprise die, adjusted by its own modifier. A surprised side loses the
    first round. setup_combat rolls this itself; use this outside a fight."""
    return plain(
        checks.surprise(ctx.dice, party_modifier=party_modifier, enemy_modifier=enemy_modifier, rules=ctx.rules)
    )


@tool(
    SPECS,
    "encounter_check",
    params(
        "terrain",
        terrain=string("dungeon, wilderness, road, urban, forest, hills…"),
        level=integer("The party's average level, for the table band.", minimum=0),
        dungeon_level=integer("The dungeon level, when the party's level isn't given.", minimum=0),
        table=string(
            "The module's table to roll on, by its id, when the check names several (`choose`); 'ruleset' for the"
            " ruleset's tables. Leave it out otherwise."
        ),
    ),
    mutates=True,
    areas=(),
    player_visible=False,
)
def encounter_check(
    ctx: CampaignContext, terrain: str, level: int = 0, dungeon_level: int = 0, table: str = ""
) -> dict[str, Any]:
    """Check for a wandering encounter (a d6 at or under 1, a d20 in towns) and, when one comes, determine it, in one
    call: from the module's own wandering table for where the party is when it has one (`source` "module", its line's
    `creature` a ref for monster_lookup), else from the ruleset's tables for the terrain and the party's level. When
    several of the module's tables may apply, it names them in `choose`: call again with `table`. One check per
    interval of game time: a check after advance_time rolls fresh, a second at the same time is the stored one. The
    players never see it."""
    picked = wandering.choice(ctx, terrain, table)
    return plain(
        checks.encounter_check(
            ctx.dice,
            ctx.lookups,
            terrain=terrain,
            level=level,
            dungeon_level=dungeon_level,
            occasion=game_time(ctx),
            rules=ctx.rules,
            encounters=ctx.ruleset.encounters if ctx.ruleset is not None else None,
            module_table=picked.table,
            choose=picked.choose,
            world=wandering.world(ctx),
        )
    )


@tool(
    SPECS,
    "system_shock",
    params("character", character=string("The character.")),
    mutates=True,
    areas=("characters",),
)
def system_shock(ctx: CampaignContext, character: str) -> dict[str, Any]:
    """System shock: d100 at or under the Constitution's percentage, for polymorph, petrification,
    magical ageing. Failing it kills."""
    who = characters.get(ctx, character)
    con = _constitution(who)
    return {**_who(who), "con": con, **plain(checks.system_shock(ctx.dice, con=con, actor=who.id, rules=ctx.rules))}


@tool(
    SPECS,
    "resurrection_check",
    params("character", character=string("The dead character.")),
    mutates=True,
    areas=("characters",),
)
def resurrection_check(ctx: CampaignContext, character: str) -> dict[str, Any]:
    """Resurrection survival: d100 at or under the Constitution's percentage. Each attempt costs a point
    of Constitution, whatever the roll; the sheet is updated. On a success set hp with update_character."""
    who = characters.get(ctx, character)
    result = checks.resurrection(ctx.dice, con=_constitution(who), actor=who.id, rules=ctx.rules)
    scores = dict(who.sheet.ability_scores)
    key = next((k for k in _ABILITIES["con"] if k in scores), "con")
    scores[key] = result.con_after
    characters.update(ctx, who.id, {"ability_scores": scores}, reason="resurrection attempt")
    return {**_who(who), **plain(result)}
