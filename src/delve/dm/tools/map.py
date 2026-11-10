"""The map in play (spec §7.4, feature review "must not regress"): moving updates the map state in code, so the map
can't be forgotten; rooms come split into what the characters perceive and what only the DM knows (ttrpg2
`tools/rooms.py`). The DM's notes about a room (`room_notes`) are DM-only."""

from __future__ import annotations

from typing import Any

from delve.dm.tools.schema import ToolSpec, boolean, params, string, strings, tool
from delve.play import moves
from delve.play.context import CampaignContext

SPECS: list[ToolSpec] = []

ROOM_NOTES = ("room_notes",)

CHARACTERS = strings("Who: names or ids. The whole party when not given; name some to split the party.")


@tool(
    SPECS,
    "move_party",
    params(
        "to",
        to=string("The room: its id (room.entry_hall), bare name (entry_hall) or label (Entry Hall)."),
        characters=CHARACTERS,
        map=string("Another map of the module to go to; the map they are on when empty."),
    ),
    mutates=True,
    areas=("map_state",),
    dm_only_keys=ROOM_NOTES,
)
def move_party(ctx: CampaignContext, to: str, characters: list[str] | None = None, map: str = "") -> dict[str, Any]:
    """Move the party, or some of its characters, into a room: adjacent or not (a chute is a move too). The map state
    is updated here, so they discover the room and its visible doors. Returns the room as they perceive it, what only
    you know (dm_only), your notes on the room, and where every group now is. Narrate from perceived only."""
    return moves.move(ctx, to=to, characters=characters, map=map or None)


@tool(
    SPECS,
    "room",
    params(
        query=string("A room by id, bare name or label; the characters' room when empty."),
        characters=CHARACTERS,
    ),
    mutates=False,
    player_visible=False,
    dm_only_keys=ROOM_NOTES,
)
def room(ctx: CampaignContext, query: str = "", characters: list[str] | None = None) -> dict[str, Any]:
    """A room of the characters' map as they know it, read-only: the one they are in, or any by name, for "what's
    through that door" or the room again after a break. Undiscovered rooms have nothing perceived."""
    return moves.room(ctx, query, characters)


@tool(
    SPECS,
    "door",
    params(
        "door",
        door=string(
            "The door's key from a room's exits ('15,10'), or the room it leads to from the party's room; with found,"
            " also a secret exit's or feature's key from a room's dm_only secrets."
        ),
        state=string("What happened to it: open, closed, locked, barred, forced, broken."),
        found=boolean(
            "A secret door found: it becomes known to the characters at it. A secret exit or feature found: it is"
            " revealed on the players' map."
        ),
    ),
    mutates=True,
    areas=("map_state",),
)
def door(ctx: CampaignContext, door: str, state: str = "", found: bool = False) -> dict[str, Any]:
    """Record a door opened, forced, locked or barred (the world's state, for everyone), a secret door found, or a
    secret exit or feature found (a trapdoor, a hidden way to another map), revealed on the players' map."""
    return moves.door(ctx, door, state, found)


@tool(
    SPECS,
    "note_room",
    params(
        "text",
        text=string("What the party changed: cleared it, left the horse, barricaded a door, looted the chest."),
        query=string("Another room than the party's."),
    ),
    mutates=True,
    areas=(),
    player_visible=False,
)
def note_room(ctx: CampaignContext, text: str, query: str = "") -> dict[str, Any]:
    """Remember what the party changed in a room. A DM-only note, returned by move_party and room every time."""
    return moves.note_room(ctx, text, query)
