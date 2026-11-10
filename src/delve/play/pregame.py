"""The pregame (players and tavern Task F1): the table before the session's first act, while the players arrive.

A campaign is in its pregame when no beat is open or running and no `player_act` has been sent since the last
`recap`, the end of a session (or ever). The web opens the tavern, table talk full screen, while it lasts.
"""

from __future__ import annotations

from delve.storage.interfaces import Storage

__all__ = ["PAGE", "in_pregame"]

PAGE = 200
"""How many story entries `in_pregame` reads back at a time."""


def in_pregame(storage: Storage, campaign_id: str) -> bool:
    """Whether the campaign is in its pregame: no current beat, and, reading the story back from its end, a `recap`
    before any `player_act`, or no `player_act` at all."""
    if storage.beats.current(campaign_id) is not None:
        return False
    before: int | None = None
    while entries := storage.story.list(campaign_id, before_seq=before, limit=PAGE):
        for entry in reversed(entries):
            if entry.kind == "recap":
                return True
            if entry.kind == "player_act":
                return False
        before = entries[0].seq
    return True
