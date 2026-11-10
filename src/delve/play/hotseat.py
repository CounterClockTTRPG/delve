"""Hotseat play (DEL-365): several people around one screen, the host's, each playing characters of their own.

The host turns it on in the host's options (play settings `hotseat`) and names the players at that screen
(`hotseat_players`): each has an id, a name and the PCs they play. The players are the host's seat's: their
characters are PCs the host's seat plays (its own, or those nobody has claimed), and a character another seat claims
is that seat's again, whatever the list says (`players`).

In a beat, the host's screen sends one act or pass for each hotseat player (`delve.play.beats.submit` with `player`),
marked with the player, and one for the host's other characters if it has any. The beat waits for the host's seat
until every hotseat player has had their turn; at its close, a hotseat player who didn't act gets the fallback, as an
absent seat would. The DM reads each act under the player's name (`delve.play.table.dm_message`), and the story shows
it so.

The screen is shared, so nothing on it is private: a hotseat player's act can't be for the DM alone.

This module reads the stored settings itself, so that `delve.play.table`, which validates them, can import it.
"""

from __future__ import annotations

import secrets
from typing import Any

from delve.domain.campaigns import Seat
from delve.play.audience import seat_controls
from delve.play.context import PlayError
from delve.storage import Storage

__all__ = [
    "MAX_PLAYERS",
    "NAME_CHARS",
    "PRIVATE",
    "SubmissionKey",
    "host_seat",
    "is_on",
    "player",
    "players",
    "rest",
    "state",
    "validated",
]

MAX_PLAYERS = 8
NAME_CHARS = 40
PRIVATE = "On a shared screen nothing is for the DM alone."

SubmissionKey = tuple[str | None, str | None]
"""What one submission of a beat stands for: its seat, and the hotseat player it is for (None: the seat itself). A
second submission with the same key replaces the first."""


def is_on(storage: Storage, campaign_id: str) -> bool:
    return (storage.play_settings.get(campaign_id) or {}).get("hotseat") is True


def host_seat(storage: Storage, campaign_id: str) -> Seat | None:
    """The seat whose screen the hotseat players share: the table's host, while it hasn't left."""
    return next(
        (s for s in storage.seats.list(campaign_id) if s.role == "host" and s.left_at is None),
        None,
    )


def players(storage: Storage, campaign_id: str) -> list[dict[str, Any]]:
    """The hotseat players as they play now: none while hotseat is off or the table has no host; each with only the
    characters the host's seat plays and that are in the party, and only those with a character left, as
    `{id, name, characters}`."""
    if not is_on(storage, campaign_id):
        return []
    host = host_seat(storage, campaign_id)
    if host is None:
        return []
    controlled = seat_controls(storage, host)
    in_party = {
        c.id for c in storage.characters.list(campaign_id) if c.kind == "pc" and c.departure is None and c.id in controlled
    }
    stored = (storage.play_settings.get(campaign_id) or {}).get("hotseat_players") or []
    live = []
    for raw in stored:
        characters = [cid for cid in raw.get("characters") or [] if cid in in_party]
        if characters:
            live.append({"id": raw["id"], "name": raw["name"], "characters": characters})
    return live


def player(storage: Storage, campaign_id: str, seat: Seat, player_id: str) -> dict[str, Any]:
    """The hotseat player `player_id`, for an act from `seat`: `PlayError` when hotseat is off, the seat isn't the
    host's (whose screen it is), or there is no such player playing a character now."""
    if not is_on(storage, campaign_id):
        raise PlayError("Hotseat is off at this table.", "The host turns it on in the host's options.")
    host = host_seat(storage, campaign_id)
    if host is None or host.id != seat.id:
        raise PlayError("Only the host's screen plays the hotseat.")
    found = next((p for p in players(storage, campaign_id) if p["id"] == player_id), None)
    if found is None:
        raise PlayError("No such hotseat player, or they play no character now.", "Read the table's state again.")
    return found


def rest(storage: Storage, campaign_id: str, seat: Seat, own: list[str]) -> list[str]:
    """`own`, the characters a seat's submission would be for by default, without the hotseat players' characters
    when the seat is the host's: those are the players' to act for."""
    taken = {cid for p in players(storage, campaign_id) for cid in p["characters"]}
    if not taken:
        return own
    host = host_seat(storage, campaign_id)
    if host is None or host.id != seat.id:
        return own
    return [cid for cid in own if cid not in taken]


def state(storage: Storage, campaign_id: str) -> dict[str, Any]:
    """Hotseat for the play screen: whether it is on, the host's seat, and its players as they play now."""
    on = is_on(storage, campaign_id)
    host = host_seat(storage, campaign_id) if on else None
    return {
        "on": on,
        "seat_id": host.id if host is not None else None,
        "players": players(storage, campaign_id),
    }


def validated(storage: Storage, campaign_id: str, raw: Any) -> list[dict[str, Any]]:
    """The hotseat players to store, from what the host sent: a list of at most `MAX_PLAYERS` of
    `{id?, name, characters}`. A name is stripped, 1 to `NAME_CHARS` characters, and no two alike (case aside); a
    character is a PC of the campaign, played by one hotseat player at most. A player without an id gets a new one.
    `PlayError` for anything else."""
    if not isinstance(raw, list):
        raise PlayError("The hotseat players are a list.")
    if len(raw) > MAX_PLAYERS:
        raise PlayError(f"A hotseat has at most {MAX_PLAYERS} players.")
    pcs = {c.id: c.name for c in storage.characters.list(campaign_id) if c.kind == "pc"}
    names: set[str] = set()
    ids: set[str] = set()
    taken: dict[str, str] = {}
    out = []
    for item in raw:
        if not isinstance(item, dict) or set(item) - {"id", "name", "characters"}:
            raise PlayError("A hotseat player is a name and the characters they play.")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PlayError("A hotseat player needs a name.")
        name = " ".join(name.split())
        if len(name) > NAME_CHARS:
            raise PlayError(f"A hotseat player's name is at most {NAME_CHARS} characters.")
        if name.casefold() in names:
            raise PlayError(f"Two hotseat players are called {name}.", "Give each a name of their own.")
        names.add(name.casefold())
        player_id = item.get("id") or f"hs_{secrets.token_hex(4)}"
        if not isinstance(player_id, str) or player_id in ids:
            raise PlayError("Each hotseat player has an id of their own.")
        ids.add(player_id)
        characters = item.get("characters", [])
        if not isinstance(characters, list) or not all(isinstance(cid, str) for cid in characters):
            raise PlayError("A hotseat player's characters are a list of ids.")
        for cid in characters:
            if cid not in pcs:
                raise PlayError(f"No such PC in this campaign: {cid}.")
            if cid in taken and taken[cid] != name:
                raise PlayError(f"{pcs[cid]} is played by {taken[cid]} already.", "One player plays each character.")
            taken[cid] = name
        out.append({"id": player_id, "name": name, "characters": list(dict.fromkeys(characters))})
    return out
