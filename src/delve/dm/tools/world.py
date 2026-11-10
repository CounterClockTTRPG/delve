"""The campaign's world maps (ttrpg2 `tools/world_map.py`): the party's place, distances, what is near, and what the
party knows. `world_map` is the DM's: it shows the hidden places and the `dm_notes`. The players see a map through
the seats' view: the land the party knows, without its hidden places, until `reveal_place`. The DM
adds a place (`add_place`), and reveals or hides a feature or an area (`reveal_place`, `hide_place`, `reveal_area`);
editing the map itself is the organiser's."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, boolean, integer, params, string, tool
from delve.maps.geo.knowledge import SIGHT_KM
from delve.maps.geo.routing import MODES
from delve.maps.geo.terrain import PLACE_KINDS
from delve.play import travel, world_maps
from delve.play.context import CampaignContext

SPECS: list[ToolSpec] = []

_MAP = string("The world map, by name; empty for the one the party is on.")


@tool(
    SPECS,
    "place_party",
    params("at", at=string("A place on the map, by name or label, or 'x,y'."), map=_MAP),
    mutates=True,
    areas=("world",),
)
def place_party(ctx: CampaignContext, at: str, map: str = "") -> dict[str, Any]:
    """Put the party at a place of a world map, without travelling: the start of a campaign, a teleport, a ship's
    landfall. The whole party shares one place on the world map."""
    return world_maps.place_party(ctx, at, map)


@tool(
    SPECS,
    "distance",
    params(
        "a",
        "b",
        a=string("A place, by id or name, or 'x,y' in km."),
        b=string("Another place."),
        map=_MAP,
        mode=string("A mode, for the length of its route; empty for the straight line.", enum=["", *MODES]),
    ),
    mutates=False,
)
def distance(ctx: CampaignContext, a: str, b: str, map: str = "", mode: str = "") -> dict[str, Any]:
    """The distance between two places of a world map, in km and miles: the straight line, or with a mode the length
    of the route it would take (route gives its days and slowest stretches)."""
    return travel.distance(ctx, a, b, map, mode)


@tool(
    SPECS,
    "nearest",
    params(
        kind=string("What kind of place to look for.", enum=list(PLACE_KINDS)),
        n=integer("How many.", minimum=1, maximum=20),
        map=_MAP,
    ),
    mutates=False,
)
def nearest(ctx: CampaignContext, kind: str = "city", n: int = 3, map: str = "") -> dict[str, Any]:
    """The places of a kind nearest the party, as the crow flies, but the one it is at. A place the players don't
    see yet is marked hidden."""
    return travel.nearest(ctx, kind, n, map)


@tool(
    SPECS,
    "world_map",
    params(name=_MAP, feature=string("One feature, by id or name: its description and your notes.")),
    mutates=False,
    player_visible=False,
)
def world_map(ctx: CampaignContext, name: str = "", feature: str = "") -> dict[str, Any]:
    """A world map of the campaign: its features, each marked hidden (yours until reveal_place) and known (on the
    players' map), and where the party is; or one feature with its description and its dm_notes, which are yours."""
    return world_maps.describe(ctx, name, feature)


@tool(
    SPECS,
    "reveal_place",
    params(
        "feature",
        feature=string("Any feature, by id or name: a place, a road, a river, or a region (its land becomes known)."),
        map=_MAP,
    ),
    mutates=True,
    areas=("world",),
)
def reveal_place(ctx: CampaignContext, feature: str, map: str = "") -> dict[str, Any]:
    """The party learns of a feature, wherever it lies: a hidden place, a road on a map they bought, a region whose
    land they now know. From now on their world map shows it."""
    return world_maps.reveal(ctx, feature, map)


@tool(
    SPECS,
    "hide_place",
    params("feature", feature=string("A place or a road, by id or name."), map=_MAP),
    mutates=True,
    areas=("world",),
    player_visible=False,
)
def hide_place(ctx: CampaignContext, feature: str, map: str = "") -> dict[str, Any]:
    """The party forgets a place or a road: their world map no longer shows it, even where they know the land, until
    reveal_place."""
    return world_maps.hide(ctx, feature, map)


@tool(
    SPECS,
    "reveal_area",
    params(
        "at",
        at=string("The middle of the area: a place, by id or name, or 'x,y' in km from the map's top left."),
        radius_km={
            "type": "number",
            "description": "How far around it, in km.",
            "exclusiveMinimum": 0,
            "maximum": 1000,
        },
        map=_MAP,
        forget=boolean("Hide the area instead: the party forgets it, or it was never theirs to know."),
    ),
    mutates=True,
    areas=("world",),
    player_visible=False,
)
def reveal_area(
    ctx: CampaignContext, at: str, radius_km: float = SIGHT_KM, map: str = "", forget: bool = False
) -> dict[str, Any]:
    """The party learns the land around a place (a map bought in a city, a rumour heard, a view from a tower): the
    places printed there come into sight, but never a hidden one. With forget, the area goes back into the fog. Travel
    reveals the land along the way by itself."""
    return world_maps.reveal_area(ctx, at, radius_km, map, forget=forget)


@tool(
    SPECS,
    "add_place",
    params(
        "name",
        "kind",
        "at",
        name=string("The place's name."),
        kind=string("What it is.", enum=list(PLACE_KINDS)),
        at=string("Where: a place, by id or name, or 'x,y' in km from the map's top left."),
        description=string("What the characters may learn of it."),
        notes=string("Yours alone: the players never see them."),
        hidden=boolean("Keep it off the players' map until reveal_place."),
        map=_MAP,
    ),
    mutates=True,
    areas=("world",),
    player_visible=False,
)
def add_place(
    ctx: CampaignContext,
    name: str,
    kind: str,
    at: str,
    description: str = "",
    notes: str = "",
    hidden: bool = False,
    map: str = "",
) -> dict[str, Any]:
    """Add a place the campaign needs to its world map: a village you make up, a ruin. It shows on the players' map
    where they know the land; make it hidden when the party shouldn't know of it yet."""
    return world_maps.add_place(ctx, name, kind, at, description=description, notes=notes, hidden=hidden, map=map)
