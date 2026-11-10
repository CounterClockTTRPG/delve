"""A character leaves the party, and comes back (table voice and fixes Task C1, spec "A character leaves the party").

A PC leaves as one of `DEPARTURES`: it `died`, `retired` or `left`. It keeps its sheet, its items and its story, and is
still found by name; it is only out of the party (`characters.party`), so it holds no beat up, gets no fallback line
and joins no new fight. Leaving during a fight leaves the fight. The departure changes only through
`CharacterRepository.set_departure`, never `save`, so a stale character saved by another service can't bring it back.
"""

from __future__ import annotations

from typing import Any

from delve.domain.campaigns import DEPARTURES, Character
from delve.play import characters, combat
from delve.play.context import CampaignContext, PlayError

__all__ = ["leave_party", "rejoin_party", "set_departure"]


def leave_party(ctx: CampaignContext, ref: str, departure: str) -> dict[str, Any]:
    """The PC `ref` leaves the party as `departure`, and the live fight if it fights in it; one `departure` event.
    `PlayError` for an NPC, one already departed, or another reason."""
    if departure not in DEPARTURES:
        raise PlayError(f"A character leaves the party as one of {', '.join(DEPARTURES)}, not {departure!r}.")
    with ctx.storage.transaction():
        character = characters.get(ctx, ref)
        if character.kind != "pc":
            raise PlayError(f"{character.name} is an NPC, not in the party.", hint="Only a PC leaves the party.")
        if character.departure is not None:
            raise PlayError(
                f"{character.name} has already left the party ({character.departure}).",
                hint="rejoin_party brings them back.",
            )
        fighting = combat.combatant(ctx, character.id)
        left_fight = fighting is not None and "removed" not in fighting.conditions
        if left_fight:
            combat.remove_combatant(ctx, character.id, "left the party")
        saved = ctx.storage.characters.set_departure(character.id, departure)  # type: ignore[arg-type]
        ctx.log(
            "departure",
            character_id=saved.id,
            name=saved.name,
            departure=departure,
            left_fight=left_fight,
        )
    return {"character_id": saved.id, "name": saved.name, "departure": departure, "left_fight": left_fight}


def rejoin_party(ctx: CampaignContext, ref: str) -> dict[str, Any]:
    """The departed PC `ref` is in the party again, at its place in the marching order; one `departure` event with
    no departure. It doesn't join a live fight by itself. `PlayError` when it hasn't left."""
    with ctx.storage.transaction():
        character = characters.get(ctx, ref)
        if character.departure is None:
            raise PlayError(f"{character.name} hasn't left the party.")
        saved = ctx.storage.characters.set_departure(character.id, None)
        ctx.log("departure", character_id=saved.id, name=saved.name, departure=None, left_fight=False)
    return {"character_id": saved.id, "name": saved.name, "departure": None}


def set_departure(ctx: CampaignContext, ref: str, departure: str | None) -> Character:
    """The campaign page's Leave the party and Return: the PC `ref` is departed as `departure`, or in the party for
    None. Leaving is `leave_party` and returning `rejoin_party`; the same again changes nothing, and another reason for
    a departed PC changes only the reason (it left when it left), with one `departure` event. `PlayError` as theirs."""
    with ctx.storage.transaction():
        character = characters.get(ctx, ref)
        if departure is None:
            if character.departure is not None:
                rejoin_party(ctx, character.id)
        elif character.departure is None:
            leave_party(ctx, character.id, departure)
        elif character.departure != departure:
            if departure not in DEPARTURES:
                raise PlayError(f"A character leaves the party as one of {', '.join(DEPARTURES)}, not {departure!r}.")
            ctx.storage.characters.set_departure(character.id, departure, character.departed_at)  # type: ignore[arg-type]
            ctx.log("departure", character_id=character.id, name=character.name, departure=departure, left_fight=False)
        return ctx.storage.characters.get(character.id) or character
