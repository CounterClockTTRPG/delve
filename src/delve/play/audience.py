"""Who may see what at a table (spec §7.5, plan 4 Task 3): an audience, and the one rule that decides it per seat.

An audience is None (everyone at the table), `{"characters": [ids]}` (the seats that play any of those characters) or
`{"seats": [ids]}` (those seats). An observer sees only what is for everyone. Anything else, such as an audience of a
shape Delve doesn't know, is seen by nobody: when in doubt, a seat sees less.

An audience of characters is resolved when what it is for is stored (`resolve`): it becomes the seats that play those
characters at that moment, so claiming or releasing a PC later shows nobody what was told before. `can_see` still
reads an audience of characters, for what was stored before, against the characters the seat plays now.

The host plays, besides their own characters, every PC nobody has claimed (the party's decision for plateau 4): in
solo play the owner's PCs are free, and what the DM tells them is for the owner.

Some entries are for roles as well (`roles_for`, walkthrough fixes Task 5): a tool row is for the host and the
co-hosts, and a refused one for the host alone. The players and observers get only what the characters perceive.
"""

from __future__ import annotations

from typing import Any

from delve.domain.campaigns import Seat, SeatRole
from delve.play import seats
from delve.storage import Storage

__all__ = ["Audience", "can_see", "for_characters", "for_seats", "resolve", "roles_for", "seat_controls"]

Audience = dict[str, list[str]] | None


def for_characters(character_ids: list[str]) -> dict[str, list[str]]:
    return {"characters": list(character_ids)}


def for_seats(seat_ids: list[str]) -> dict[str, list[str]]:
    return {"seats": list(seat_ids)}


TOOL_ROWS: tuple[SeatRole, ...] = ("host", "cohost")
REFUSED_TOOL_ROWS: tuple[SeatRole, ...] = ("host",)


def roles_for(kind: str, payload: dict[str, Any]) -> tuple[SeatRole, ...] | None:
    """The roles a story entry of `kind` is for, besides its audience: None for every role. A refusal is a row with
    `failed`, or, stored before the allow-list, an `error`."""
    if kind != "tool":
        return None
    return REFUSED_TOOL_ROWS if payload.get("failed") is True or "error" in payload else TOOL_ROWS


def can_see(seat: Seat, audience: Any, controls: set[str], roles: tuple[str, ...] | None = None) -> bool:
    """Whether `seat`, which plays the characters `controls`, may see what is for `audience` (and for `roles`, when
    it is for some roles only)."""
    if seat.left_at is not None:
        return False
    if roles is not None and seat.role not in roles:
        return False
    if audience is None:
        return True
    if seat.role == "observer" or not isinstance(audience, dict) or len(audience) != 1:
        return False
    ((key, ids),) = audience.items()
    if not isinstance(ids, list):
        return False
    if key == "characters":
        return not controls.isdisjoint(ids)
    if key == "seats":
        return seat.id in ids
    return False


def seat_controls(storage: Storage, seat: Seat) -> set[str]:
    """The characters the seat plays, for `can_see`: its own, and for the host every PC nobody has claimed."""
    own = seats.controls(storage, seat.id)
    if seat.role != "host":
        return own
    free = {c.id for c in storage.characters.list(seat.campaign_id) if c.kind == "pc" and c.controller_id is None}
    return own | free


def resolve(storage: Storage, campaign_id: str, audience: Any) -> Any:
    """The audience to store: one of characters becomes the seats that play any of them now (not those that left,
    nor observers); any other is as it is."""
    if not isinstance(audience, dict) or set(audience) != {"characters"} or not isinstance(audience["characters"], list):
        return audience
    told = set(audience["characters"])
    return for_seats(
        [
            seat.id
            for seat in storage.seats.list(campaign_id)
            if seat.left_at is None and seat.role != "observer" and not seat_controls(storage, seat).isdisjoint(told)
        ]
    )
