"""Carrying the party on (carry-the-party-on plan Task 2): the chosen PCs of one campaign are copied into another,
with all the party owns. Each PC gets a new id and keeps its sheet and state, less what only makes sense mid-fight:
every effect (they're all round-timed) and the `FIGHT_CONDITIONS`. Its faction, a thing of the old world, and its
seat are not carried. The possessions of the carried PCs and the party's own go too, as copies, and so do the party's
coin and loot pile, added to the new campaign's. A painted portrait names a picture of the old campaign, which the
new one wouldn't serve, so the picture's row is copied (the same blob) and the portrait renamed to it.

When both campaigns count days in one calendar, the calendar goes on (DEL-104): the new campaign's day 1 is the old
one's today, at the old one's time of day. In another setting's calendar the days start again.

Nothing of the old campaign is moved or deleted: it gets the carry recorded and its status set to `complete`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from delve.domain import new_id
from delve.domain.campaigns import Character
from delve.domain.world import Calendar, ImageKind, ImagePortrait, Portrait, StartDate
from delve.play.context import PlayError
from delve.storage import Storage

FIGHT_CONDITIONS: tuple[str, ...] = ("casting", "surprised", "prone", "stunned")


class FightLive(PlayError):
    """The old campaign is in a fight: carrying on waits for its end."""

    def __init__(self) -> None:
        super().__init__("End the fight first.")


class NotCarried(PlayError):
    """An id that isn't a PC of the old campaign, or no id at all."""


def check_carry(storage: Storage, from_campaign_id: str, character_ids: Sequence[str]) -> None:
    """Refuse a carry before anything is made: `FightLive` while the old campaign has a live fight, `NotCarried` for
    an empty party or an id that isn't one of its PCs. A dead PC may go when it is asked for."""
    if storage.combats.live(from_campaign_id) is not None:
        raise FightLive()
    if not character_ids:
        raise NotCarried("Choose at least one character to carry on.")
    for id in character_ids:
        character = storage.characters.get(id)
        if character is None or character.campaign_id != from_campaign_id or character.kind != "pc":
            raise NotCarried(f"{id} is not a PC of this campaign.", "Choose the campaign's own PCs.")


def carry_into(
    storage: Storage,
    from_campaign_id: str,
    to_campaign_id: str,
    character_ids: Sequence[str],
    calendar: Calendar | None = None,
) -> dict[str, str]:
    """Copy the chosen PCs, their possessions, the party's possessions, coin and loot into the new campaign, record
    the carry and set the old campaign to `complete`, in one transaction (the caller's, when it has one). Given the
    `calendar` both campaigns share, the new one goes on from the old one's date and time. Answer the new id of each
    old character."""
    character_ids = list(dict.fromkeys(character_ids))
    with storage.transaction():
        check_carry(storage, from_campaign_id, character_ids)
        chosen = sorted((storage.characters.get(id) for id in character_ids), key=_marching)
        mapping = {old.id: _copy_character(storage, old, to_campaign_id).id for old in chosen}
        for possession in storage.possessions.list(from_campaign_id):
            if possession.owner_id is not None and possession.owner_id not in mapping:
                continue
            copy = replace(
                possession,
                campaign_id=to_campaign_id,
                id=new_id("pos"),
                owner_id=mapping.get(possession.owner_id) if possession.owner_id is not None else None,
                created_at="",
                updated_at="",
            )
            portrait = _copy_portrait(storage, possession.portrait, to_campaign_id, "possession", copy.id)
            storage.possessions.put(replace(copy, portrait=portrait))
        _carry_wealth(storage, from_campaign_id, to_campaign_id)
        if calendar is not None:
            _carry_calendar(storage, from_campaign_id, to_campaign_id, calendar)
        storage.carries.add(from_campaign_id, to_campaign_id, character_ids)
        storage.campaigns.set_status(from_campaign_id, "complete")
    return mapping


def _marching(character: Character | None) -> tuple[int, str]:
    assert character is not None  # check_carry found each one
    return (character.order if character.order is not None else 1 << 30, character.created_at)


def _copy_character(storage: Storage, old: Character, to_campaign_id: str) -> Character:
    state = replace(
        old.state, effects=(), conditions=tuple(c for c in old.state.conditions if c not in FIGHT_CONDITIONS)
    )
    copy = storage.characters.create(
        to_campaign_id, old.name, sheet=replace(old.sheet, faction="", portrait=None), state=state, order=old.order
    )
    portrait = _copy_portrait(storage, old.sheet.portrait, to_campaign_id, "portrait", copy.id)
    if portrait is None:
        return copy
    return storage.characters.save_sheet(replace(copy, sheet=replace(copy.sheet, portrait=portrait)))


def _copy_portrait(
    storage: Storage, portrait: Portrait | None, to_campaign_id: str, kind: ImageKind, subject_id: str
) -> Portrait | None:
    """The portrait for the copy: a traits portrait as it is; a painted one renamed to a copy of its picture in the
    new campaign, or None when the picture isn't done."""
    if not isinstance(portrait, ImagePortrait):
        return portrait
    image = storage.campaign_images.get(portrait.image_id)
    if image is None or image.status != "done" or image.blob is None:
        return None
    copy = storage.campaign_images.put(
        replace(image, id=new_id("img"), campaign_id=to_campaign_id, kind=kind, subject_id=subject_id, created_at="")
    )
    return ImagePortrait(copy.id)


def _carry_wealth(storage: Storage, from_campaign_id: str, to_campaign_id: str) -> None:
    """Add the party's coin to the new campaign's, and put its loot pile after the new campaign's."""
    old = storage.campaign_states.get(from_campaign_id)
    new = storage.campaign_states.get(to_campaign_id)
    assert old is not None and new is not None  # both campaigns exist
    coin = {name: new.coin.get(name, 0) + old.coin.get(name, 0) for name in {**new.coin, **old.coin}}
    storage.campaign_states.put(replace(new, coin=coin, loot=new.loot + old.loot))


def _carry_calendar(storage: Storage, from_campaign_id: str, to_campaign_id: str, calendar: Calendar) -> None:
    """Start the new campaign on the old one's today, at its time of day: day 1 is that date (DEL-104)."""
    old = storage.campaign_states.get(from_campaign_id)
    new = storage.campaign_states.get(to_campaign_id)
    assert old is not None and new is not None  # both campaigns exist
    start = old.start_date.as_tuple() if old.start_date is not None else calendar.default_start
    today = calendar.date(start, old.day)
    storage.campaign_states.put(
        replace(new, day=1, hour=old.hour, minute=old.minute, start_date=StartDate(today.year, today.day_of_year))
    )
