"""Characters, NPCs and the party; inventory, encumbrance and spells; treasure and the loot pile (ttrpg2
`tools/party.py`, `tools/world.py`, `tools/survival.py` and the treasure tools of `tools/lookup.py`).

A character is named by its id or its exact name. An NPC's story (`notes_md`) is DM-only: the character tools mark
it, so the players' feed never shows it. Creating a character brings the campaign's character-creation house rules,
and adding an item the house rules about it (spec §9).
"""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, array, boolean, integer, obj, params, string, strings, tool
from delve.domain.campaigns import DEPARTURES, Character
from delve.domain.characters import Sheet, pronouns_of
from delve.domain.data import to_dict
from delve.play import characters, combat, departures, factions, house_rules, inventory, seats, treasure
from delve.play import spells as loadouts
from delve.play.context import CampaignContext, PlayError
from delve.play.days import MAX_DAYS

SPECS: list[ToolSpec] = []

NPC_STORY = ("notes_md",)
CLOCKS = ("clocks",)
"""The clocks that tick when days pass (plan 6 Task 5): DM-only."""
"""The DM-only keys of a character's result: an NPC's story."""


def character_json(character: Character) -> dict[str, Any]:
    return {
        "id": character.id,
        "name": character.name,
        "kind": character.kind,
        "order": character.order,
        "sheet": to_dict(character.sheet),
        "state": to_dict(character.state),
    }


def _with_npc_portrait(ctx: CampaignContext, character: Character) -> dict[str, Any]:
    """`character_json` of a character just made; an NPC without a portrait gets one first, as Preferences choose for
    NPCs (DEL-248: they weren't drawn unless the DM asked), and `portrait_painting` while a painter makes it."""
    # Here, not at the top: delve.play.images reaches the table, whose batch reaches these tools again.
    from delve.play import images

    drawn = None
    if character.kind == "npc" and character.sheet.portrait is None:
        drawn = images.npc_portrait(ctx, character)
        character = ctx.storage.characters.get(character.id) or character
    out = character_json(character)
    if drawn is not None and "image_id" in drawn:
        out["portrait_painting"] = drawn
    return out


def _who(sheet: Sheet) -> dict[str, str]:
    """The character's pronouns and deity, for the narration to keep to (DEL-327); what the sheet doesn't say is left
    out."""
    found = {"pronouns": pronouns_of(sheet), "deity": sheet.deity.strip()}
    return {key: value for key, value in found.items() if value}


def _brief(character: Character) -> dict[str, Any]:
    sheet, state = character.sheet, character.state
    return {
        "id": character.id,
        "name": character.name,
        "kind": character.kind,
        **_who(sheet),
        "race": sheet.race,
        "cls": sheet.cls,
        "levels": dict(sheet.levels),
        "hp": state.hp,
        "hp_max": sheet.hp_max,
        "ac": sheet.ac,
        "thac0": sheet.thac0,
        "xp": state.xp,
        "conditions": list(state.conditions),
        "effects": [to_dict(e) for e in state.effects],
    }


# --- characters --------------------------------------------------------------------------------------------------

_COUNTS = {"type": "object", "additionalProperties": {"type": "integer"}}

# The collection fields are typed, so the DM sees their shape and a wrong guess is refused naming the field; the
# others are checked by `Sheet.from_dict`, whose hint lists every field.
SHEET_FIELDS: dict[str, Any] = {
    "levels": {**_COUNTS, "description": "The level per lowercase class: {'fighter': 1, 'thief': 1}."},
    "saves": {**_COUNTS, "description": "Save targets by type; missing saves come from the class table."},
    "ability_scores": {
        "type": "object",
        "additionalProperties": {"type": ["integer", "string"]},
        "description": "{'str': 16, 'dex': 12, …}; exceptional strength as '18/52'.",
    },
    "attacks": array(
        "Each attack: {name, speed, attacks (per round), thac0, damage_sm, damage_l, range}.", {"type": "object"}
    ),
    "weapon_profs": strings("Weapon proficiencies, by weapon: ['long sword', 'sling']."),
    "nwps": strings("Nonweapon proficiencies: ['riding, land-based', 'healing']."),
    "natural_abilities": strings("Racial and class abilities in words: ['infravision 60 ft', '+4 save vs poison']."),
    "skills": {**_COUNTS, "description": "Percentile skills: thief skills, dwarven detection: {'open locks': 25}."},
    "spell_slots": {**_COUNTS, "description": "Spell slots per spell level: {'1': 2, '2': 1}."},
}

SHEET = obj(
    "The character's sheet: race, gender, pronouns (when not the gender's: 'they/them'), deity, cls ('Fighter/Thief'), level or levels, hp_max, ac, thac0, saves, "
    "ability_scores, attacks, weapon (the one in hand), weapon_profs, nwps, natural_abilities, skills, size ('S', 'M', "
    "'L'), ac_vs_larger, movement_rate, alignment, background, portrait_prompt, spell_slots, spell_loadout, faction "
    "(its faction's id); an NPC's notes_md (its story, DM-only) and disposition (-100 to 100). The portrait tool sets "
    "its portrait.",
    properties=SHEET_FIELDS,
)


@tool(
    SPECS,
    "create_character",
    params(
        "sheet",
        name=string(
            "The name the player or the book gives. Leave it out and the dice name the character for its sheet's race "
            "and gender."
        ),
        kind=string("pc (default) or npc.", enum=["pc", "npc"]),
        sheet=SHEET,
        player=string(
            "A PC's player, by their name as their act gives it. By default the one player in this beat who asked "
            "while playing no character; with several such, name each one's."
        ),
    ),
    mutates=True,
    areas=("characters",),
    dm_only_keys=NPC_STORY,
)
def create_character(
    ctx: CampaignContext, sheet: dict[str, Any], name: str = "", kind: str = "pc", player: str = ""
) -> dict[str, Any]:
    """Create a PC (at the back of the marching order) or an NPC, at full hit points. house_rules has the campaign's
    character-creation house rules for its race and class: apply them (ability rolls, starting hit points, races and
    classes the book doesn't have). A PC a player asked for is theirs to play at once (`played_by`); one nobody
    asked for is the host's until a player takes it. An NPC gets its portrait at once, as Preferences choose."""
    if kind == "npc" and player.strip():
        raise PlayError("An NPC is yours to play.", "Leave out player, or make a pc.")
    created = characters.create(ctx, name=name, kind=kind, sheet=sheet)  # type: ignore[arg-type]
    played_by = seats.give_new_pc(ctx.storage, created, ctx.beat, player) if created.kind == "pc" else None
    rules = house_rules.creation_rules(ctx, created)
    named_by = "given" if name.strip() else "dice"
    return {
        **_with_npc_portrait(ctx, created),
        "named_by": named_by,
        **({"played_by": played_by.name} if played_by is not None else {}),
        "house_rules": house_rules.given(ctx, rules),
    }


@tool(
    SPECS,
    "get_character",
    params(
        "ref",
        ref=string("The character's id or exact name."),
        brief=boolean("Only the numbers that matter in play: hp, AC, THAC0, levels, conditions."),
    ),
    mutates=False,
    dm_only_keys=NPC_STORY,
)
def get_character(ctx: CampaignContext, ref: str, brief: bool = False) -> dict[str, Any]:
    """A character's sheet and state: everything, or with brief the numbers that matter in play."""
    found = characters.get(ctx, ref)
    return _brief(found) if brief else character_json(found)


@tool(
    SPECS,
    "update_character",
    params(
        "ref",
        "patch",
        ref=string("The character's id or exact name."),
        patch=obj(
            "The fields to change: name, level (or levels), any sheet field (race, gender, pronouns, deity, cls, hp_max, "
            "ac, thac0, saves, ability_scores, attacks, weapon, weapon_profs, nwps, natural_abilities, skills, size, "
            "ac_vs_larger, movement_rate, alignment, background, portrait_prompt, spell_slots, spell_loadout, notes_md, "
            "disposition, faction), or hp, xp, conditions, effects. The portrait tool sets the portrait.",
            properties=SHEET_FIELDS,
        ),
        reason=string("Why, for the log."),
    ),
    mutates=True,
    areas=("characters",),
    dm_only_keys=NPC_STORY,
)
def update_character(ctx: CampaignContext, ref: str, patch: dict[str, Any], reason: str = "") -> dict[str, Any]:
    """Change a character's sheet or state: a level gained, new ability scores, a curse among its conditions. In a
    fight its hit points, conditions and effects change in the fight too."""
    if isinstance(patch.get("faction"), str) and patch["faction"].strip():
        patch = {**patch, "faction": factions.get(ctx, patch["faction"]).id}
    return character_json(characters.update(ctx, ref, patch, reason))


@tool(
    SPECS,
    "introduce_npc",
    params(
        "race",
        race=string("human, elf, dwarf, halfling, gnome, half-orc…"),
        gender=string("female or male; the name follows it."),
        description=string("Their role or look: 'innkeeper', 'guard captain'."),
        faction=string("The faction they belong to, by id or exact name."),
    ),
    mutates=True,
    areas=("characters",),
    dm_only_keys=NPC_STORY,
)
def introduce_npc(
    ctx: CampaignContext, race: str, gender: str = "", description: str = "", faction: str = ""
) -> dict[str, Any]:
    """A new NPC the party meets, named for their race with the dice, so names don't repeat or drift. Give them stats
    with update_character when they matter. A faction's reputation with the party moves their reactions. They get
    their portrait at once, as Preferences choose for NPCs."""
    faction_id = factions.get(ctx, faction).id if faction.strip() else ""
    npc = characters.introduce_npc(ctx, race=race, gender=gender, description=description, faction=faction_id)
    return _with_npc_portrait(ctx, npc)


@tool(
    SPECS,
    "set_disposition",
    params(
        "npc",
        "value",
        npc=string("The NPC."),
        value=integer("-100 (sworn enemy) to 100 (devoted ally).", minimum=-100, maximum=100),
        reason=string("Why it changed, for the log."),
    ),
    mutates=True,
    areas=("characters",),
)
def set_disposition(ctx: CampaignContext, npc: str, value: int, reason: str = "") -> dict[str, Any]:
    """Set an NPC's disposition towards the party. It becomes a reaction modifier of disposition / 20, truncated
    towards zero."""
    return characters.set_disposition(ctx, npc, value, reason)


@tool(SPECS, "party_status", params(), mutates=False)
def party_status(ctx: CampaignContext) -> dict[str, Any]:
    """The party in marching order, each with hp, AC, THAC0, levels, XP and conditions; the PCs who left it, apart;
    the NPCs met; and the party's coin."""
    pcs = characters.party(ctx)
    everyone = ctx.storage.characters.list(ctx.campaign_id)
    npcs = [c for c in everyone if c.kind == "npc"]
    state = ctx.storage.campaign_states.get(ctx.campaign_id)
    return {
        "party": [_brief(c) for c in pcs],
        "marching_order": [c.name for c in pcs],
        "departed": [
            {"id": c.id, "name": c.name, "departure": c.departure}
            for c in everyone
            if c.kind == "pc" and c.departure is not None
        ],
        "npcs": [{"id": c.id, "name": c.name, "race": c.sheet.race} for c in npcs],
        "coin": dict(state.coin),
    }


@tool(
    SPECS,
    "set_marching_order",
    params("order", order=strings("The PCs from the front: names or ids. The others fall in behind.")),
    mutates=True,
    areas=("characters",),
)
def set_marching_order(ctx: CampaignContext, order: list[str]) -> dict[str, Any]:
    """Set the marching order: the named PCs at the front in that order, the others behind in their current order."""
    ordered = characters.set_marching_order(ctx, order)
    return {"marching_order": [{"id": c.id, "name": c.name, "order": c.order} for c in ordered]}


@tool(
    SPECS,
    "leave_party",
    params(
        "character",
        "reason",
        character=string("The PC who leaves: name or id."),
        reason=string("Why: died, retired (stays behind in the world) or left (walked away).", enum=list(DEPARTURES)),
    ),
    mutates=True,
    areas=("characters",),
)
def leave_party(ctx: CampaignContext, character: str, reason: str) -> dict[str, Any]:
    """A PC leaves the party: they died, retired or left. Their sheet, items and story stay, and they are still found by
    name, but they are no longer in the party, the marching order or a new fight; a fight they are in, they leave.
    Their player can't act for them while they are away. Call it once the story has them gone, not for a PC who is only
    downed or out of the room."""
    return departures.leave_party(ctx, character, reason)


@tool(
    SPECS,
    "rejoin_party",
    params("character", character=string("The PC who comes back: name or id.")),
    mutates=True,
    areas=("characters",),
)
def rejoin_party(ctx: CampaignContext, character: str) -> dict[str, Any]:
    """A PC who left the party comes back (raised from the dead, out of retirement, back from their errand), with the
    sheet they left with. They don't join a fight under way by themselves: add them with add_combatant."""
    return departures.rejoin_party(ctx, character)


def _damage_target(ctx: CampaignContext, ref: str) -> str | None:
    """A monster of the live fight named `ref`: its combatant id; None for a character or no fight."""
    fighting = combat.combatant(ctx, ref)
    return fighting.id if fighting is not None and fighting.character_id is None else None


@tool(
    SPECS,
    "apply_damage",
    params(
        "character",
        "amount",
        character=string("A character, or a monster of the live fight by id or exact name."),
        amount=integer("Hit points lost.", minimum=0),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def apply_damage(ctx: CampaignContext, character: str, amount: int) -> dict[str, Any]:
    """Take hit points off a character (a trap, a fall, a poison) or a monster in the fight. 0 or below is downed,
    -10 dead. A character in the fight takes it through the fight, so nothing is lost when it ends."""
    monster = _damage_target(ctx, character)
    if monster is not None:
        return combat.damage(ctx, monster, amount)
    return characters.apply_damage(ctx, character, amount)


@tool(
    SPECS,
    "apply_heal",
    params(
        "character",
        "amount",
        character=string("A character, or a monster of the live fight by id or exact name."),
        amount=integer("Hit points healed.", minimum=0),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def apply_heal(ctx: CampaignContext, character: str, amount: int) -> dict[str, Any]:
    """Heal a character or a monster in the fight, up to its maximum. The dead (-10) aren't healed: that takes raise
    dead or resurrection."""
    monster = _damage_target(ctx, character)
    if monster is not None:
        return combat.heal(ctx, monster, amount)
    return characters.apply_heal(ctx, character, amount)


@tool(
    SPECS,
    "award_xp",
    params(
        "character",
        "amount",
        character=string("The character."),
        amount=integer("The XP."),
    ),
    mutates=True,
    areas=("characters",),
)
def award_xp(ctx: CampaignContext, character: str, amount: int) -> dict[str, Any]:
    """Award XP as earned; where the ruleset has it, the prime-requisite bonus is added (xp_bonus says so: don't
    add it yourself). A multi-class character's is split evenly between its classes. level_up_hints names each
    class that reached its next level, and then house_rules has the campaign's level-up rules. The level itself
    changes with update_character."""
    return characters.award_xp(ctx, character, amount)


@tool(
    SPECS,
    "drain_level",
    params(
        "character",
        character=string("The character drained."),
        levels=integer("Levels drained (default 1; a spectre's touch takes 2).", minimum=1, maximum=10),
        reason=string("What drained it: 'wight's touch'."),
    ),
    mutates=True,
    areas=("characters", "combat"),
)
def drain_level(ctx: CampaignContext, character: str, levels: int = 1, reason: str = "") -> dict[str, Any]:
    """An energy drain: the character loses levels from its highest class, with their hit points (off the maximum),
    and its XP, THAC0, saves and spell slots drop to the new level's as the ruleset says, in or out of a fight. Apply
    the touch's damage separately with apply_damage. Drained below 1st level it dies (2e: at 0-level first)."""
    return characters.drain_level(ctx, character, levels, reason)


@tool(
    SPECS,
    "update_coin",
    params("delta", delta=string("+450pp, +50gp, -10sp, +3ep, +100cp.")),
    mutates=True,
    areas=("characters",),
)
def update_coin(ctx: CampaignContext, delta: str) -> dict[str, Any]:
    """Add or take the party's coin, one coin type at a time."""
    return characters.update_coin(ctx, delta)


@tool(
    SPECS,
    "rest",
    params(
        character=string("One character; the whole party when empty."),
        days=integer("Days of rest (default 1).", minimum=0, maximum=MAX_DAYS),
        bed_rest=boolean("Complete bed rest, where the ruleset heals it faster than light activity."),
        full=boolean("The DM's override: everyone to maximum hit points (not the book rate)."),
        rememorize=boolean("Casters memorize their default loadout again."),
    ),
    mutates=True,
    areas=("characters", "world"),
    dm_only_keys=CLOCKS,
)
def rest(
    ctx: CampaignContext,
    character: str = "",
    days: int = 1,
    bed_rest: bool = False,
    full: bool = False,
    rememorize: bool = False,
) -> dict[str, Any]:
    """Rest and heal at the ruleset's natural rate (most: 1 hp a day; the result says the basis). A rest of
    a day or more makes memorized spells uncast again; with rememorize casters memorize their default loadout. The
    whole party's rest lets its days pass, keeping the time of day; one character's doesn't move the clock."""
    return characters.rest(ctx, character, days=days, bed_rest=bed_rest, full=full, rememorize=rememorize)


# --- inventory and spells ----------------------------------------------------------------------------------------


@tool(
    SPECS,
    "add_item",
    params(
        "character",
        "item",
        character=string("Who gets it."),
        item=string("The item: 'Long sword', 'Rope (50 ft.)', 'Potion of healing'."),
        qty=integer("How many (default 1).", minimum=1),
        notes=string("What the characters know of this one, which the players read: 'engraved with a rose'."),
        dm_notes=string(
            "What only you know of it, which the players never read: what it really is before it is identified, "
            "a curse, its charges: 'potion of neutralize poison, 2 doses'."
        ),
    ),
    mutates=True,
    areas=("characters",),
)
def add_item(
    ctx: CampaignContext, character: str, item: str, qty: int = 1, notes: str = "", dm_notes: str = ""
) -> dict[str, Any]:
    """Give a character an item; more of one it carries adds to it. Its weight comes from the equipment tables.
    house_rules has the campaign's house rules about the item: they override the book."""
    out = inventory.add_item(ctx, character, item, qty, notes, dm_notes)
    rules = house_rules.item_rules(ctx, [item, out["item"]["name"]])
    return {**out, "house_rules": house_rules.given(ctx, rules)}


@tool(
    SPECS,
    "remove_item",
    params(
        "character",
        "item",
        character=string("Who loses it."),
        item=string("The item."),
        qty=integer("How many (default 1).", minimum=1),
    ),
    mutates=True,
    areas=("characters",),
)
def remove_item(ctx: CampaignContext, character: str, item: str, qty: int = 1) -> dict[str, Any]:
    """Take an item from a character: used up, lost, sold. Nothing changes if they have fewer."""
    return inventory.remove_item(ctx, character, item, qty)


@tool(
    SPECS,
    "transfer",
    params(
        "item",
        "qty",
        "source",
        "dest",
        item=string("The item."),
        qty=integer("How many.", minimum=1),
        source=string("Who gives it, or 'loot' for the loot pile."),
        dest=string("Who takes it, or 'loot' for the loot pile."),
    ),
    mutates=True,
    areas=("characters",),
)
def transfer(ctx: CampaignContext, item: str, qty: int, source: str, dest: str) -> dict[str, Any]:
    """Move items between two characters, or between a character and the loot pile ('loot'). Nothing moves if the
    source has fewer."""
    return inventory.transfer(ctx, item, qty, source, dest)


@tool(
    SPECS,
    "inventory",
    params(character=string("One character; everyone who carries something when empty.")),
    mutates=False,
)
def inventory_tool(ctx: CampaignContext, character: str = "") -> dict[str, Any]:
    """What a character carries, or everyone."""
    return inventory.inventory(ctx, character)


@tool(SPECS, "encumbrance", params("character", character=string("The character.")), mutates=False)
def encumbrance(ctx: CampaignContext, character: str) -> dict[str, Any]:
    """What a character carries against their Strength (the ruleset's bands): the total weight, the band (unencumbered,
    light, moderate, heavy, severe), the movement left and the attack penalty, with each item's weight."""
    return inventory.encumbrance(ctx, character)


SPELLS_BY_LEVEL = obj("Spells by level: {'1': ['Sleep', 'Magic Missile'], '2': ['Web']}.")


@tool(
    SPECS,
    "set_spell_loadout",
    params(
        "character",
        character=string("The caster."),
        known=SPELLS_BY_LEVEL,
        default=SPELLS_BY_LEVEL,
    ),
    mutates=True,
    areas=("characters",),
)
def set_spell_loadout(
    ctx: CampaignContext,
    character: str,
    known: dict[str, list[str]] | None = None,
    default: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Set the spells a caster knows (a wizard's spellbook) and the ones they memorize by default, each as spells by
    level. The default fits the caster's slots. What isn't given stays as it was."""
    return loadouts.set_loadout(ctx, character, known=known, default=default)


@tool(
    SPECS,
    "memorize_spells",
    params(
        "character",
        character=string("The caster."),
        spells=strings("The spells to memorize; the default loadout when not given."),
    ),
    mutates=True,
    areas=("characters",),
)
def memorize_spells(ctx: CampaignContext, character: str, spells: list[str] | None = None) -> dict[str, Any]:
    """Memorize spells, all uncast, in place of what was memorized; without spells, the default loadout. The slots of
    each level are the cap."""
    return loadouts.memorize(ctx, character, spells)


@tool(
    SPECS,
    "cast_spell",
    params("character", "spell_name", character=string("The caster."), spell_name=string("The spell.")),
    mutates=True,
    areas=("characters", "combat"),
)
def cast_spell(ctx: CampaignContext, character: str, spell_name: str) -> dict[str, Any]:
    """Cast a memorized spell: its copy is spent until the next rest. A spell that isn't memorized, or is spent, is
    refused. In a fight, declare it in combat_round's actions instead."""
    return loadouts.cast(ctx, character, spell_name)


@tool(SPECS, "spell_status", params("character", character=string("The caster.")), mutates=False)
def spell_status(ctx: CampaignContext, character: str) -> dict[str, Any]:
    """A caster's loadout, what is memorized and what is spent, and per level the slots left."""
    return loadouts.spell_status(ctx, character)


# --- treasure ----------------------------------------------------------------------------------------------------

TREASURE_TYPES = string("The treasure as the monster's entry gives it ('L,M', 'Qx5 S', 'Hoard 2'); 'Nil' is none.")
SOURCE = string("Whose hoard it is ('the goblins', 'the crypt chest'); the types when empty.")
LAIR = {
    "in_lair": boolean("The hoard of the creatures' lair, where they live (needed for a lair's treasure)."),
    "monster": string("Whose lair it is, as monster_lookup names it (needed with in_lair)."),
    "from_module": boolean("The module's text places this treasure (its room key gives the types): rolled as given."),
}


@tool(
    SPECS,
    "generate_treasure",
    params("treasure_types", treasure_types=TREASURE_TYPES, source=SOURCE, **LAIR),
    mutates=True,
    areas=("characters",),
    player_visible=False,
)
def generate_treasure(
    ctx: CampaignContext,
    treasure_types: str,
    source: str = "",
    in_lair: bool = False,
    monster: str = "",
    from_module: bool = False,
) -> dict[str, Any]:
    """Roll a hoard without awarding it, to describe what lies there, by the ruleset's treasure types: coins, gems, art
    and magic items. The same types and source in this beat are the same hoard, and so is award_treasure's. A lair's
    types are its hoard: only with in_lair and its monster, never for a monster of animal, semi- or no intelligence
    (its lair holds victims' leavings), unless from_module."""
    return treasure.generate_treasure(
        ctx, treasure_types, source, in_lair=in_lair, monster=monster, from_module=from_module
    )


@tool(
    SPECS,
    "award_treasure",
    params(
        "treasure_types", treasure_types=TREASURE_TYPES, log_note=string("A line for the log."), source=SOURCE, **LAIR
    ),
    mutates=True,
    areas=("characters",),
)
def award_treasure(
    ctx: CampaignContext,
    treasure_types: str,
    log_note: str = "",
    source: str = "",
    in_lair: bool = False,
    monster: str = "",
    from_module: bool = False,
) -> dict[str, Any]:
    """Roll a hoard and award it in one go: the coins to the party's coin, the gems, art and magic items to the loot
    pile. Awarded once: the same source again in this beat is refused. Types A-I are a lair's hoard: after a fight,
    award what the defeated carry (J-Z); the lair's hoard only with in_lair and its monster, never for a monster of
    animal, semi- or no intelligence, unless from_module. When the campaign awards XP for gold, gold_xp says what each
    living PC was given."""
    return treasure.award_treasure(
        ctx, treasure_types, log_note, source, in_lair=in_lair, monster=monster, from_module=from_module
    )


@tool(SPECS, "loot_pile", params(), mutates=False)
def loot_pile(ctx: CampaignContext) -> dict[str, Any]:
    """The party's loot pile, by index, for claim_loot."""
    return treasure.loot_pile(ctx)


@tool(
    SPECS,
    "claim_loot",
    params(
        "index",
        "character",
        index=integer("The entry's index in loot_pile.", minimum=0),
        character=string("Who takes it."),
    ),
    mutates=True,
    areas=("characters",),
)
def claim_loot(ctx: CampaignContext, index: int, character: str) -> dict[str, Any]:
    """Give a loot-pile entry to a character, into their inventory."""
    return treasure.claim_loot(ctx, index, character)
