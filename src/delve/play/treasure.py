"""Treasure in play: rolling a hoard, awarding it, and the party's loot pile.

`generate_treasure` rolls a hoard for the DM to describe and awards nothing; `award_treasure` rolls it (the same hoard,
in the same beat and for the same source) and, in one transaction, adds its coins to the party's coin and the rest
to the loot pile. A hoard is awarded once: the same types and source again in the same beat are refused. Characters
take things off the pile with `claim_loot`, or `inventory.transfer` from `"loot"`.

A lair's hoard (the ruleset's `lair_types`; the others are what individuals carry) is rolled only where the creatures
live (`in_lair`), for a named `monster`, and never for one whose intelligence keeps none (`no_hoard`): its lair holds
what its victims left. Treasure the module's own text places (`from_module`) is rolled as given.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from delve.domain.campaigns import COINS, LootItem
from delve.domain.characters import Item
from delve.domain.data import to_dict
from delve.play.characters import award_xp, get, party
from delve.play.context import CampaignContext, NotFound, PlayError
from delve.play.inventory import loot_notes, with_item
from delve.rules.classic.treasure import Treasure, TreasureResult, TreasureTypeError

__all__ = ["award_treasure", "claim_loot", "generate_treasure", "loot_pile"]


def _treasure(ctx: CampaignContext) -> Treasure:
    """The campaign's ruleset's treasure; refused for a ruleset without one."""
    treasure = ctx.ruleset.treasure if ctx.ruleset is not None else None
    if treasure is None:
        raise PlayError("This campaign's ruleset has no treasure tables.", hint="Describe the treasure yourself.")
    return treasure


def _lair_rule(ctx: CampaignContext, types: str, in_lair: bool, monster: str, from_module: bool) -> None:
    """Refuse a lair's hoard (the ruleset's `lair_codes`) rolled outside the lair, without its monster, or for a
    monster that keeps none. A line of several groups is left to `_generate`, which asks for one."""
    if from_module:
        return
    treasure = _treasure(ctx)
    groups = treasure.parse_types(types)["groups"]
    if len(groups) != 1:
        return
    lair = treasure.lair_codes(groups[0]["codes"])
    if not lair:
        return
    named = ", ".join(lair)
    if not in_lair:
        raise PlayError(
            f"{named} {'is' if len(lair) == 1 else 'are'} a lair's hoard ({treasure.lair_name}): it lies where the "
            "creatures live, not on the ones the party meets or kills.",
            hint=f"After a fight, roll what the defeated carry ({treasure.individual_name}), if any. For the hoard of "
            "their lair, pass "
            "in_lair and monster; for treasure the module's text places, from_module.",
        )
    if not monster.strip():
        raise PlayError(
            "A lair's hoard is its monster's.", hint="Pass monster: whose lair it is, as monster_lookup names it."
        )
    rows = ctx.lookups.monster(monster.strip())
    if rows:
        wits = str(rows[0].get("intelligence") or "")
        if wits.strip().lower().startswith(treasure.no_hoard):
            raise PlayError(
                f"The {rows[0].get('name', monster)} ({wits} intelligence) keep no hoard: their lair holds only what "
                "their victims left.",
                hint="Describe the leavings. Award treasure there only where the module's text places it (from_module).",
            )


def _source(types: str, source: str) -> str:
    return source.strip() or types.strip()


def _generate(ctx: CampaignContext, types: str, source: str) -> TreasureResult:
    try:
        return _treasure(ctx).generate(ctx.dice, types, source=_source(types, source))
    except TreasureTypeError as error:
        if error.groups:
            raise NotFound(str(error), error.groups, hint="Pass the types of one group.") from None
        raise PlayError(str(error), hint="Pass treasure type letters A-Z, as 'L,M' or 'Qx5 S'.") from None


def _hoard(result: TreasureResult) -> dict[str, Any]:
    return {
        "rolled": list(result.types),
        "coins": dict(result.coins),
        "gems": [to_dict(g) for g in result.gems],
        "art": [to_dict(a) for a in result.art],
        "magic": [to_dict(m) for m in result.magic],
        "checks": [to_dict(c) for c in result.checks],
        "dice_rolled": len(result.rolls),
    }


def _counts(result: TreasureResult) -> dict[str, int]:
    return {"gems": len(result.gems), "art": len(result.art), "magic": len(result.magic)}


def generate_treasure(
    ctx: CampaignContext,
    types: str,
    source: str = "",
    *,
    in_lair: bool = False,
    monster: str = "",
    from_module: bool = False,
) -> dict[str, Any]:
    """Roll the hoard of a treasure line ('A', 'L,M', 'Qx5 S'; 'Nil' is none) without awarding it, for the DM to
    describe. `source` names the hoard (the defeated group or the place); without it the types do. Asking again in the
    same beat gives the same hoard, and so does `award_treasure` with the same types and source. A lair's hoard follows
    the module's lair rule (`_lair_rule`)."""
    _lair_rule(ctx, types, in_lair, monster, from_module)
    result = _generate(ctx, types, source)
    hoard = _hoard(result)
    ctx.log(
        "treasure_generated",
        types=types.strip(),
        source=_source(types, source),
        rolled=hoard["rolled"],
        coins=hoard["coins"],
        **_counts(result),
    )
    return {"types": types.strip(), "source": _source(types, source), **hoard}


def _loot(result: TreasureResult) -> list[LootItem]:
    """Everything but the coins, for the loot pile: the description without the category tag ttrpg2's text had."""
    return [
        *(LootItem("gem", g.name, g.value_gp, g.tier) for g in result.gems),
        *(LootItem("art", a.name, a.value_gp) for a in result.art),
        *(LootItem("magic", m.name, 0, m.category) for m in result.magic),
    ]


GP_PER_COIN = {"pp": 5.0, "gp": 1.0, "ep": 0.5, "sp": 0.1, "cp": 0.01}
"""What each coin is worth in gold pieces (PHB Table 43)."""


def _gold_xp(ctx: CampaignContext, result: TreasureResult) -> dict[str, Any] | None:
    """With gold among the campaign's XP awards (DEL-113; first-edition and OSR games): 1 XP per gp the hoard's coins, gems
    and art are worth, split evenly among the living PCs (what doesn't split evenly is lost). Magic items earn
    none. None with gold off."""
    from delve.play import table  # here: `delve.play.table` imports the DM's tools, which import this module

    if "gold" not in table.play_settings(ctx.storage, ctx.campaign_id)["xp_awards"]:
        return None
    coins = sum(GP_PER_COIN[coin] * amount for coin, amount in result.coins.items())
    gp = int(coins + sum(g.value_gp for g in result.gems) + sum(a.value_gp for a in result.art))
    living = [c for c in party(ctx) if "dead" not in c.state.conditions]
    each = gp // len(living) if living else 0
    awards = [award_xp(ctx, c.id, each) for c in living] if each else []
    return {"gp_value": gp, "xp_each": each, "awards": awards}


def award_treasure(
    ctx: CampaignContext,
    types: str,
    note: str = "",
    source: str = "",
    *,
    in_lair: bool = False,
    monster: str = "",
    from_module: bool = False,
) -> dict[str, Any]:
    """Roll a hoard and award it, all in one transaction: its coins go to the party's coin, its gems, art and magic
    items to the loot pile, and it is logged as `treasure_awarded`. The same types and source in the same beat are
    the same hoard, and are awarded once. A lair's hoard follows the lair rule (`_lair_rule`). With gold among the
    campaign's XP awards, its value is the living PCs' XP too (`gold_xp`)."""
    _lair_rule(ctx, types, in_lair, monster, from_module)
    hoard_source = _source(types, source)
    with ctx.storage.transaction():
        done = ctx.storage.events.list(ctx.campaign_id, types=["treasure_awarded"], beat=ctx.beat)  # DEL-172
        if any(e.data.get("source") == hoard_source for e in done):
            raise PlayError("already awarded", hint="name a different source, or use e.g. Jx2")
        result = _generate(ctx, types, source)
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        purse = {**dict.fromkeys(COINS, 0), **state.coin}
        for coin, amount in result.coins.items():
            purse[coin] += amount
        added = _loot(result)
        ctx.storage.campaign_states.put(replace(state, coin=purse, loot=(*state.loot, *added)))
        gold_xp = _gold_xp(ctx, result)
        ctx.log(
            "treasure_awarded",
            types=types.strip(),
            source=hoard_source,
            notes=note or f"Types: {types.strip()}",
            coin=dict(result.coins),
            **_counts(result),
        )
    out = {
        "types": types.strip(),
        "source": hoard_source,
        **_hoard(result),
        "coin_added": dict(result.coins),
        "coin_total": purse,
        "loot_added": [to_dict(item) for item in added],
        "loot_pile_size": len(state.loot) + len(added),
    }
    if gold_xp is not None:
        out["gold_xp"] = gold_xp
    return out


def loot_pile(ctx: CampaignContext) -> dict[str, Any]:
    """The party's loot pile, gems, art, magic items and things put down, by index, for `claim_loot`."""
    pile = ctx.storage.campaign_states.get(ctx.campaign_id).loot
    return {"loot_pile": [{"index": i, **to_dict(item)} for i, item in enumerate(pile)]}


def claim_loot(ctx: CampaignContext, index: int, ref: str) -> dict[str, Any]:
    """Give the loot pile's entry `index` (see `loot_pile`) to a character, into its inventory."""
    character = get(ctx, ref)
    with ctx.storage.transaction():
        state = ctx.storage.campaign_states.get(ctx.campaign_id)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(state.loot):
            raise PlayError(
                f"Index {index} out of range (pile has {len(state.loot)} items).", hint="See loot_pile for the indexes."
            )
        claimed = state.loot[index]
        ctx.storage.campaign_states.put(replace(state, loot=(*state.loot[:index], *state.loot[index + 1 :])))
        items, _ = with_item(
            ctx, character.state.inventory, Item(claimed.description, claimed.qty, notes=loot_notes(claimed))
        )
        ctx.storage.characters.save_state(replace(character, state=replace(character.state, inventory=items)))
        ctx.log(
            "loot_claimed", character_id=character.id, name=character.name, item=claimed.description, kind=claimed.kind
        )
    return {"claimed_by": character.name, "character_id": character.id, "item": to_dict(claimed)}
