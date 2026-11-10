"""Possessions (ttrpg2 `tools/holdings.py`: its houses and mounts are one kind of thing here). Every tool but
`possession` leaves out a possession's notes, which are the DM's."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, integer, obj, params, string, strings, tool
from delve.domain.world import POSSESSION_KINDS
from delve.play import possessions
from delve.play.context import CampaignContext

SPECS: list[ToolSpec] = []

_FIELDS = {
    "name": string("Its name: 'Bess', 'The Gull', 'Oakhill Cottage'."),
    "kind": string("What it is.", enum=list(POSSESSION_KINDS)),
    "owner": string("The character who owns it, by id or exact name; empty (or 'party') for the party's."),
    "species": string(
        "A mount's species: 'riding horse', 'mule'. One the ruleset knows has defaults; any other needs stats (a refusal"
        " lists the known ones)."
    ),
    "location": string("Where it is: 'Hommlet, by the mill', 'the stable at the Welcome Wench'."),
    "value_gp": integer("Its rough value in gp.", minimum=0),
    "description": string("What it looks like, as the party knows it."),
    "notes": string("Your notes, DM-only: what the party doesn't know about it."),
    "stats": obj(
        "A mount's {hp, hp_max, ac, mv, fly, thac0, attacks, morale} (over its species' defaults); a vehicle's or a "
        "ship's {mv, capacity}; anything for the other kinds."
    ),
    "inventory": strings("What is kept in it or strapped to it: ['Saddlebags', 'Iron strongbox (locked)']."),
}


@tool(SPECS, "add_possession", params("name", "kind", **_FIELDS), mutates=True, areas=("characters",))
def add_possession(
    ctx: CampaignContext,
    name: str,
    kind: str,
    owner: str = "",
    species: str = "",
    location: str = "",
    value_gp: int = 0,
    description: str = "",
    notes: str = "",
    stats: dict[str, Any] | None = None,
    inventory: list[str] | None = None,
) -> dict[str, Any]:
    """Register something a character or the party owns: a mount, vehicle, ship, house, stronghold, domain or other.
    A mount of a species the ruleset knows gets its stats (stats overrides them); its mv and fly set the
    party's travel speed. An unknown species needs hp_max and thac0 in stats."""
    return possessions.add(
        ctx, name, kind, owner, species, location, value_gp, description, notes, stats, inventory or ()
    )


@tool(
    SPECS,
    "update_possession",
    params(
        "id",
        id=string("The possession's id, or its exact name."),
        **_FIELDS,
        hp_change=integer("Hit points lost (negative) or healed; never past hp_max."),
    ),
    mutates=True,
    areas=("characters",),
)
def update_possession(ctx: CampaignContext, id: str, **changes: Any) -> dict[str, Any]:
    """Change a possession: only the fields given. owner '' or 'party' gives it to the party; stats are merged over
    its current ones; inventory replaces the list; hp_change wounds or heals a mount."""
    return possessions.update(ctx, id, **changes)


@tool(
    SPECS,
    "remove_possession",
    params("id", id=string("The possession's id, or its exact name.")),
    mutates=True,
    areas=("characters",),
)
def remove_possession(ctx: CampaignContext, id: str) -> dict[str, Any]:
    """Remove a possession that is sold, lost or dead."""
    return possessions.remove(ctx, id)


@tool(
    SPECS,
    "possessions",
    params(owner=string("A character, by id or exact name, or 'party' for the party's own; empty for all.")),
    mutates=False,
)
def list_possessions(ctx: CampaignContext, owner: str = "") -> dict[str, Any]:
    """Everything the party and its characters own, with each one's owner, kind, location, value and stats, but not
    your notes on it (possession has them)."""
    return possessions.listing(ctx, owner)


@tool(
    SPECS,
    "possession",
    params("id", id=string("The possession's id, or its exact name.")),
    mutates=False,
    player_visible=False,
)
def possession(ctx: CampaignContext, id: str) -> dict[str, Any]:
    """The whole record of one possession, with your DM-only notes on it."""
    return possessions.detail(ctx, id)
