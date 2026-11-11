"""Reference lookups: the rules, monsters, spells, items, classes, abilities, proficiencies and turning undead (ttrpg2
`tools/lookup.py` and `tools/rules.py`), over the read-only reference store. Item lookups bring the campaign's
house rules about the items they find (spec §9)."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, integer, params, plain, string, tool
from delve.play import characters, house_rules
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.rules.classic import checks

SPECS: list[ToolSpec] = []


def _answer(found: dict[str, Any]) -> dict[str, Any]:
    """A reference answer, its `error` as a refusal."""
    if "error" in found:
        raise PlayError(str(found["error"]))
    return found


MONSTERS_WHOLE = 3
"""How many of a monster lookup's matches come whole (DEL-79: "rat" answered ten entries, 45 KB)."""


@tool(
    SPECS,
    "rules_lookup",
    params(
        "query",
        query=string("Words to search the rules for: 'surprise', 'called shot', 'morale'."),
        source=string("One of the ruleset's books, as The Ruleset names them; all of them when empty."),
    ),
    mutates=False,
)
def rules_lookup(ctx: CampaignContext, query: str, source: str = "") -> dict[str, Any]:
    """Search the campaign's ruleset's rulebooks (full text) for a rule: the best paragraphs first, each with its
    book, chapter, section and a snippet with the hits in <<…>>. Read the whole section with rules_section."""
    campaign = ctx.storage.campaigns.get(ctx.campaign_id)
    ruleset = ctx.ruleset.id if ctx.ruleset is not None else ""
    if campaign is not None and campaign.ruleset != ruleset:
        raise PlayError(f"This Delve doesn't have the campaign's ruleset '{campaign.ruleset}'.")
    try:
        results = ctx.lookups.rules_search(query, source=source)
    except ValueError as refused:
        raise PlayError(f"Can't search for '{query}': {refused}", hint="Use plain words.") from None
    return {"query": query, "ruleset": ruleset, "count": len(results), "results": results}


@tool(
    SPECS,
    "rules_section",
    params(
        "source",
        "section",
        source=string("One of the ruleset's books, as The Ruleset names them."),
        section=string("Part of the section's title: 'Surprise', 'Morale'."),
    ),
    mutates=False,
)
def rules_section(ctx: CampaignContext, source: str, section: str) -> dict[str, Any]:
    """The full text of a rulebook section by its title, an exact title first."""
    sections = ctx.lookups.rules_section(source, section)
    if not sections:
        raise NotFound(f"No section '{section}' in {source}.", hint="Find it with rules_lookup first.")
    return {"source": source, "sections": sections}


@tool(
    SPECS,
    "monster_lookup",
    params("name", name=string("The monster: 'goblin', 'dragon, red'.")),
    mutates=False,
)
def monster_lookup(ctx: CampaignContext, name: str) -> dict[str, Any]:
    """A monster's entry in the ruleset's bestiary, best match first: the exact name, the family's entries, then names
    starting with or containing it. The first 3 whole; `also` names the rest (at most 10 in all): look one up by its
    name for its entry."""
    found = ctx.lookups.monster(name)
    if not found:
        raise NotFound(f"No monster '{name}'.", hint="Try the family name: 'dragon', 'giant'.")
    out: dict[str, Any] = {"query": name, "count": len(found), "monsters": found[:MONSTERS_WHOLE]}
    if len(found) > MONSTERS_WHOLE:
        out["also"] = [monster["name"] for monster in found[MONSTERS_WHOLE:]]
    return out


@tool(
    SPECS,
    "spell_lookup",
    params(
        "name",
        name=string("The spell."),
        caster=string(
            "The spell list or a class that casts from it ('wizard', 'cleric', 'magic-user'); any when empty."
        ),
    ),
    mutates=False,
)
def spell_lookup(ctx: CampaignContext, name: str, caster: str = "") -> dict[str, Any]:
    """A spell's entry (level, school, range, duration, casting time, saving throw, text): exact name first, then
    names starting with or containing it."""
    found = ctx.lookups.spell(name, caster)
    if not found:
        raise NotFound(f"No spell '{name}'" + (f" for a {caster}." if caster else "."))
    return {"query": name, "count": len(found), "spells": found}


@tool(
    SPECS,
    "item_lookup",
    params(
        "name",
        name=string("Part of the item's name."),
        item_type=string("Part of its type: weapon, armor, potion, ring…"),
        max_rarity=integer("The rarest to list, 0 common … 100 artifact (default 100).", minimum=0, maximum=100),
    ),
    mutates=False,
)
def item_lookup(ctx: CampaignContext, name: str, item_type: str = "", max_rarity: int = 100) -> dict[str, Any]:
    """Equipment and magic items whose name contains `name`, commonest first: cost, weight, description. house_rules
    has the campaign's house rules about the items found; they override the book."""
    found = ctx.lookups.item(name, item_type=item_type, max_rarity=max_rarity)
    rules = house_rules.item_rules(ctx, [name, *(row["name"] for row in found)])
    return {
        "query": name,
        "count": len(found),
        "items": found,
        "house_rules": house_rules.given(ctx, rules),
    }


@tool(
    SPECS,
    "class_lookup",
    params(
        "class_name",
        class_name=string("The class: fighter, cleric, mage…"),
        level=integer("One level's row (XP, hit dice, THAC0, saves, spell slots); every level when 0.", minimum=0),
    ),
    mutates=False,
)
def class_lookup(ctx: CampaignContext, class_name: str, level: int = 0) -> dict[str, Any]:
    """A class: its description, hit die, prime requisite and special abilities, with its level table or one level's
    row."""
    found = ctx.lookups.char_class(class_name)
    if found is None:
        raise NotFound(f"No class '{class_name}'.")
    rows = ctx.lookups.class_levels(found["name"])
    if level:
        rows = [row for row in rows if row.get("level") == level]
        if not rows:
            raise PlayError(f"{found['name']} has no level {level} in the table.")
    return {"class": found, "levels": rows}


@tool(
    SPECS,
    "race_lookup",
    params("race", race=string("The race or ancestry: 'elf', 'half-orc'.")),
    mutates=False,
)
def race_lookup(ctx: CampaignContext, race: str) -> dict[str, Any]:
    """A race of the ruleset: its ability adjustments and ranges, the classes and multi-classes it may take with their
    level limits, its features. A ruleset that keeps its races in its rules text answers none: look them up there."""
    found = ctx.lookups.race(race)
    if found is None:
        return {"race": None, "note": f"No race '{race}' in this ruleset's tables: search the rules with rules_lookup."}
    return {"race": found}


@tool(
    SPECS,
    "ability_lookup",
    params(
        "ability",
        ability=string("strength, dexterity, constitution, intelligence, wisdom, charisma (or str, dex…)."),
        score=string("The score: '15', '18/76'; every row when empty."),
    ),
    mutates=False,
)
def ability_lookup(ctx: CampaignContext, ability: str, score: str = "") -> dict[str, Any]:
    """An ability's table: what each column means, and the row for a score (hit and damage adjustments, weight
    allowance, system shock, bonus spells and so on)."""
    return _answer(ctx.lookups.ability(ability, score))


@tool(
    SPECS,
    "proficiency_lookup",
    params(
        name=string("Part of the proficiency's name."),
        group=string("general, priest, rogue, warrior or wizard."),
        ability=string("The ability it checks against."),
    ),
    mutates=False,
)
def proficiency_lookup(ctx: CampaignContext, name: str = "", group: str = "", ability: str = "") -> dict[str, Any]:
    """Nonweapon proficiencies, in a ruleset that has them: slots, the ability checked and its modifier, by name, group
    or ability."""
    try:
        found = ctx.lookups.proficiency(name, group, ability)
    except ValueError as refused:
        raise PlayError(str(refused), hint="Groups: general, priest, rogue, warrior, wizard.") from None
    return {"count": len(found), "proficiencies": found}


@tool(
    SPECS,
    "turning_undead",
    params(
        "level",
        level=integer("The priest's (or paladin's) level.", minimum=1),
        undead=string("The undead by name: skeleton, ghoul, wight…"),
        hd=integer("Or its Hit Dice, when it has no name in the table.", minimum=0),
        role=string("priest (default) or paladin, who turns as a priest two levels lower."),
        character=string("Who turns, for the roll log."),
    ),
    mutates=True,
    areas=("combat",),
)
def turning_undead(
    ctx: CampaignContext, level: int, undead: str = "", hd: int = 0, role: str = "priest", character: str = ""
) -> dict[str, Any]:
    """Turn undead by the ruleset's turning table: the table's entry for the level, and the roll when one is needed. A
    number is the d20 to equal or beat; T turns and D destroys some of them, D* more; the result says how many."""
    actor = characters.get(ctx, character).id if character else None
    return plain(
        checks.turning_undead(
            ctx.dice, ctx.lookups, level=level, undead=undead, hd=hd, role=role, actor=actor, rules=ctx.rules
        )
    )
