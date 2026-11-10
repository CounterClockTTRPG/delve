"""Seats (spec §7.2, §11): the people at a campaign's table, their roles, and the characters they play.

A campaign has exactly one host. The host, or a co-host with the same table rights, gives roles, hands the host role
over (the old host becomes a co-host) and gives any character to any seat. A player claims a free PC; an observer
plays nothing. A seat that leaves frees its characters; the host hands over first. The install's owner always has a
seat at every table, which is made, or taken back, when they come to it (a table an organiser's account made is
theirs to host, and the owner's seat is made there when the owner comes); nobody else makes it a player or an
observer, and the owner can always take the host role back.

A table may limit its places for players (DEL-204): a live player or co-host takes one, the host and observers none.
A full table seats no new player, and makes no observer a player or a co-host. The host, or a co-host, removes a seat
from the table as if it left; only the host removes a co-host.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from delve.domain.accounts import Account
from delve.domain.campaigns import SEAT_ROLES, Campaign, Character, Seat
from delve.play.context import NotFound, PlayError
from delve.storage import Storage

TABLE_RIGHTS = frozenset({"host", "cohost"})
PLACE_ROLES = frozenset({"player", "cohost"})
"""The roles that take one of the table's places for players (DEL-204)."""
ONLY_THE_HOST = "Only the host can do that."
OBSERVERS = "Observers don't act."
ONLY_THE_OWNER = "Only the owner can change the owner's seat to that role."
ONLY_THE_HOST_HANDS_OVER = "Only the host can hand the host role over."
TABLE_FULL = "The table is full."
HAND_OVER_FIRST = "Hand the host role over first."
LEAVE_INSTEAD = "Leave the table instead."
ONLY_THE_HOST_REMOVES_A_COHOST = "Only the host can remove a co-host."


class NotAllowed(PlayError):
    """The seat's role doesn't allow it (403)."""


class SeatConflict(PlayError):
    """The table's state refuses it: another seat plays the character, or the table would have no host (409)."""


class TableFull(SeatConflict):
    """Every place for players at the table is taken (409)."""

    def __init__(self) -> None:
        super().__init__(TABLE_FULL)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_owner_seat(storage: Storage, campaign_id: str) -> Seat:
    """The owner's seat at a table: named after the owner's account ("Host" while there is none), in the install's
    language, with organiser rights and no token. The host of a new table; an observer at one an organiser hosts,
    which the owner comes to later (and can take the host role back at)."""
    owner = owner_account(storage)
    name = owner.profile.display_name if owner is not None and owner.profile.display_name.strip() else "Host"
    hosted = any(s.role == "host" and s.left_at is None for s in storage.seats.list(campaign_id))
    role = "observer" if hosted else "host"
    return storage.seats.create(campaign_id, name, install_language(storage), role, organiser=True, owner=True)


def create_organiser_seat(storage: Storage, campaign_id: str, account: Account) -> Seat:
    """The host's seat at a new table an organiser's account made: theirs, with organiser rights. The owner's seat is
    made when the owner comes to the table."""
    profile = account.profile
    return storage.seats.create(
        campaign_id, profile.display_name, profile.language, "host", organiser=True, account_id=account.id
    )


def owner_account(storage: Storage) -> Account | None:
    """The install owner's account, the first made when there are several; None while there is none."""
    return next((account for account in storage.accounts.list() if account.owner and account.disabled_at is None), None)


def shown_account(storage: Storage, seat: Seat, accounts: Mapping[str, Account] | None = None) -> Account | None:
    """Whose profile the table shows for the seat: its account, or for the owner's seat (which has none) the owner's
    account. `accounts` are every account by id, when the caller has read them (DEL-172)."""
    if accounts is None:
        if seat.account_id is not None:
            return storage.accounts.get(seat.account_id)
        return owner_account(storage) if seat.owner else None
    if seat.account_id is not None:
        return accounts.get(seat.account_id)
    owner = (a for a in accounts.values() if a.owner and a.disabled_at is None)
    return next(owner, None) if seat.owner else None


def is_listed(campaign: Campaign | None) -> bool:
    """Whether the table is on Find a table: public and not complete."""
    return campaign is not None and campaign.visibility == "public" and campaign.status != "complete"


def at_the_table(storage: Storage, campaign_id: str, listed: Sequence[Seat] | None = None) -> list[Seat]:
    """Who sits at the table, as its cards show them: its live host, co-hosts and players (observers take no place),
    the host first, then in the order they came. `listed` is the table's seats, when the caller has them."""
    listed = storage.seats.list(campaign_id) if listed is None else listed
    live = [s for s in listed if s.left_at is None and s.role in TABLE_RIGHTS | PLACE_ROLES]
    return sorted(live, key=lambda s: s.role != "host")


def tables_of(storage: Storage, account: Account) -> set[str]:
    """The campaigns the account has a live seat at: its own seats, and for the owner's account the owner's seats
    (which have no account, `shown_account`)."""
    tables = {s.campaign_id for s in storage.seats.of_account(account.id)}
    owner = owner_account(storage)
    if owner is not None and owner.id == account.id:
        for campaign in storage.campaigns.list():
            seat = storage.seats.owner_seat(campaign.id)
            if seat is not None and seat.account_id is None and seat.left_at is None:
                tables.add(campaign.id)
    return tables


def install_language(storage: Storage) -> str:
    """The interface language of the install (Preferences, the side bar's menu): the owner's."""
    return str(storage.settings.load().get("language") or "en")


def follow_install_language(storage: Storage) -> list[Seat]:
    """The owner's seats take the install's language, so the story is translated into the language the owner reads
    Delve in: a seat's language is what its story is translated into. Answers the seats changed."""
    language = install_language(storage)
    changed = []
    for campaign in storage.campaigns.list():
        seat = storage.seats.owner_seat(campaign.id)
        if seat is not None and seat.language != language:
            changed.append(storage.seats.save(replace(seat, language=language)))
    return changed


def owner_seat(storage: Storage, campaign_id: str) -> Seat:
    """The owner's seat at the campaign's table: made when the campaign has none yet (one made outside the API), and
    taken back when the owner left it, so the owner is never locked out of a table on their own install."""
    seat = storage.seats.owner_seat(campaign_id)
    if seat is None:
        try:
            return create_owner_seat(storage, campaign_id)
        except ValueError:  # another request made it at the same moment
            seat = storage.seats.owner_seat(campaign_id)
            if seat is None:
                raise
    if seat.left_at is not None:
        return storage.seats.save(replace(seat, left_at=None, joined_at=_now()))
    return seat


def controls(storage: Storage, seat_id: str) -> set[str]:
    """The ids of the characters the seat plays."""
    return set(storage.seats.controlled(seat_id))


def _seat_at(storage: Storage, campaign_id: str, seat_id: str) -> Seat:
    """A seat of this campaign that hasn't left."""
    seat = storage.seats.get(seat_id)
    if seat is None or seat.campaign_id != campaign_id:
        raise NotFound(f"No seat '{seat_id}' at this table.")
    if seat.left_at is not None:
        raise PlayError(f"{seat.name} has left this table.")
    return seat


def _require_table_rights(seat: Seat) -> None:
    if seat.role not in TABLE_RIGHTS or seat.left_at is not None:
        raise NotAllowed(ONLY_THE_HOST)


def set_role(storage: Storage, campaign_id: str, seat_id: str, role: str, by: Seat) -> Seat:
    """Give the seat `role`, as the host or a co-host. Making a seat the host hands the role over: the old host
    becomes a co-host. The host can't take another role otherwise, since the table needs one. An observer plays
    nothing, so a seat that becomes one frees its characters. An observer made a player or a co-host takes a place:
    at a full table, that is refused (`TableFull`).

    Only the host, or the owner, makes a seat the host: a co-host can't make itself the host, which would demote the
    host quietly and give it what only the host sees (DEL-149).

    The owner is never locked out: only the owner makes their own seat a player or an observer, and the owner may
    always take the host role back, with or without table rights."""
    by = storage.seats.get(by.id) or by  # as it is now: a host who handed over is a co-host
    if by.campaign_id != campaign_id:
        raise NotAllowed(ONLY_THE_HOST)
    if not (by.owner and seat_id == by.id and role == "host" and by.left_at is None):
        _require_table_rights(by)
    if role not in SEAT_ROLES:
        raise PlayError(f"No role '{role}'.", f"Choose one of {', '.join(SEAT_ROLES)}.")
    seat = _seat_at(storage, campaign_id, seat_id)
    if role == "host" and seat.role != "host" and not (by.owner or by.role == "host"):
        raise NotAllowed(ONLY_THE_HOST_HANDS_OVER)
    if seat.owner and not by.owner and role in ("player", "observer"):
        raise NotAllowed(ONLY_THE_OWNER)
    if seat.role == role:
        return seat
    campaign = storage.campaigns.get(campaign_id)
    if seat.role == "observer" and campaign is not None:
        make_room_for(storage, campaign, role)  # an observer takes no place; a player or a co-host does
    with storage.transaction():
        if role == "host":
            for old in storage.seats.list(campaign_id):
                if old.role == "host":
                    storage.seats.save(replace(old, role="cohost"))
        elif seat.role == "host":
            raise SeatConflict("A table needs a host.", "Make another seat the host first.")
        if role == "observer":
            for character_id in storage.seats.controlled(seat.id):
                storage.seats.set_controller(character_id, None)
        return storage.seats.save(replace(seat, role=role))


def _character(storage: Storage, campaign_id: str, character_id: str) -> Character:
    character = storage.characters.get(character_id)
    if character is None or character.campaign_id != campaign_id:
        raise NotFound(f"No character '{character_id}' at this table.")
    return character


def fallen(character: Character) -> bool:
    """The PC is dead: at -10 hit points (its `dead` condition), or it left the party as `died`."""
    return "dead" in character.state.conditions or character.departure == "died"


def give_new_pc(storage: Storage, character: Character, beat_id: str, player: str = "") -> Seat | None:
    """The seat a PC the DM just made goes to (DEL-253: it went to nobody, and its player played no character): the
    seat named `player` (any case), else the one seat that acted in the beat `beat_id` while it played no character,
    not a host's or co-host's (they play the PCs nobody has, and ask for the pregens' party). None, and the PC stays
    the host's, when there is no such seat or more than one. `PlayError` for a `player` no seat is."""
    everyone = storage.seats.list(character.campaign_id)
    campaign_seats = [s for s in everyone if s.left_at is None and s.role != "observer"]
    if player.strip():
        named = [s for s in campaign_seats if s.name.strip().casefold() == player.strip().casefold()]
        if len(named) != 1:
            raise PlayError(
                f"No player '{player}' at the table." if not named else f"'{player}' names {len(named)} players.",
                "Name a player as their act gives them: " + ", ".join(s.name for s in campaign_seats) + ".",
            )
        to = named[0]
    else:
        beat = storage.beats.get(beat_id)
        submissions = beat.submissions if beat else ()
        acted = {s.get("seat_id", s.get("player")) for s in submissions if s.get("kind") == "act"}
        asking = [
            s for s in campaign_seats if s.id in acted and s.role not in TABLE_RIGHTS and not controls(storage, s.id)
        ]
        if len(asking) != 1:
            return None
        to = asking[0]
    storage.seats.set_controller(character.id, to.id)
    return to


def claim(storage: Storage, character_id: str, seat: Seat, *, for_seat: str | None = None) -> Character:
    """Let a seat play a PC. Without `for_seat`, the seat claims it for itself: an observer can't, and a fallen PC
    or one another seat plays is refused (DEL-190). With `for_seat`, the host (or a co-host) gives any PC to any seat
    that acts, itself included, even one another seat plays."""
    if seat.left_at is not None:
        raise PlayError("You have left this table.")
    character = _character(storage, seat.campaign_id, character_id)
    if character.kind != "pc":
        raise PlayError(f"{character.name} is the DM's to play.", "Players play PCs.")
    if for_seat is None:
        if seat.role == "observer":
            raise NotAllowed(OBSERVERS)
        if fallen(character) and character.controller_id != seat.id:
            raise PlayError(f"{character.name} has fallen.", "Pick another character, or ask the DM to make one.")
        if character.controller_id not in (None, seat.id):
            raise SeatConflict(f"Another player plays {character.name}.", "Ask the host to give it to you.")
        to = seat
    else:
        _require_table_rights(seat)
        to = _seat_at(storage, seat.campaign_id, for_seat)
        if to.role == "observer":
            raise PlayError(f"{to.name} is an observer.", "Observers play no characters.")
    storage.seats.set_controller(character.id, to.id)
    return replace(character, controller_id=to.id)


def release(storage: Storage, character_id: str, seat: Seat) -> Character:
    """Let nobody play the character: its own player, or the host (or a co-host), may."""
    character = _character(storage, seat.campaign_id, character_id)
    if character.controller_id != seat.id:
        _require_table_rights(seat)
    storage.seats.set_controller(character.id, None)
    return replace(character, controller_id=None)


def leave(storage: Storage, seat: Seat) -> Seat:
    """The seat leaves the table and its characters are free (they follow the host's fallback until someone takes
    them over). The host hands the role over first."""
    current = storage.seats.get(seat.id) or seat
    if current.left_at is not None:
        return current
    if current.role == "host":
        raise SeatConflict("Hand the host role to another seat before you leave.")
    with storage.transaction():
        for character_id in storage.seats.controlled(current.id):
            storage.seats.set_controller(character_id, None)
        return storage.seats.save(replace(current, left_at=_now()))


def taken(storage: Storage, campaign_id: str, listed: Sequence[Seat] | None = None) -> int:
    """How many of the table's places for players are taken: its live players and co-hosts. `listed` is the table's
    seats, when the caller has them."""
    listed = storage.seats.list(campaign_id) if listed is None else listed
    return sum(1 for s in listed if s.left_at is None and s.role in PLACE_ROLES)


def is_full(storage: Storage, campaign: Campaign) -> bool:
    """Whether the table limits its places for players and every one is taken. Fewer places than are taken (an
    organiser lowered the limit) is full too: nobody is removed, and nobody more joins."""
    return campaign.slots is not None and taken(storage, campaign.id) >= campaign.slots


def make_room_for(storage: Storage, campaign: Campaign, role: str) -> None:
    """Refuse a new seat in `role` at a full table (`TableFull`); an observer takes no place and always joins."""
    if role in PLACE_ROLES and is_full(storage, campaign):
        raise TableFull()


def unique_name(name: str, taken: set[str]) -> str:
    """The name, or the name with " (2)", " (3)"… when a seat at the table has it already (`taken`, case-folded)."""
    candidate, n = name, 1
    while candidate.casefold() in taken:
        n += 1
        candidate = f"{name} ({n})"
    return candidate


def seat_account(
    storage: Storage, campaign: Campaign, account: Account, role: str, name: str | None = None
) -> tuple[Seat, bool]:
    """The account's live seat at the table, and whether it is new: one seat per account and table. A new seat is
    named `name`, or the account's display name, made unique at the table (`unique_name`), in the profile's language.
    A new player's seat at a full table is refused (`TableFull`); the seat the account has comes back, full or not.
    The join link seats an account this way, and so does accepting its join request."""
    seat = storage.seats.for_account(account.id, campaign.id)
    if seat is not None:
        return seat, False
    make_room_for(storage, campaign, role)
    taken = {s.name.casefold() for s in storage.seats.list(campaign.id) if s.left_at is None}
    wanted = name or account.profile.display_name
    try:
        seat = storage.seats.create(
            campaign.id, unique_name(wanted, taken), account.profile.language, role, account_id=account.id
        )
    except ValueError:  # another request seated the account meanwhile
        seat = storage.seats.for_account(account.id, campaign.id)
        if seat is None:
            raise
        return seat, False
    return seat, True


def remove(storage: Storage, campaign_id: str, seat_id: str, by: Seat) -> Seat:
    """The host, or a co-host, removes the seat from the table: it leaves as `leave` makes it, its characters free.
    Not the host's seat, which hands the role over first, nor the caller's own, which leaves; only the host removes a
    co-host. `NotFound` for a seat not at this table or gone already. The account can come back through the join
    link until the host makes a new one."""
    by = storage.seats.get(by.id) or by  # as it is now
    if by.campaign_id != campaign_id:
        raise NotAllowed(ONLY_THE_HOST)
    _require_table_rights(by)
    seat = storage.seats.get(seat_id)
    if seat is None or seat.campaign_id != campaign_id or seat.left_at is not None:
        raise NotFound(f"No seat '{seat_id}' at this table.")
    if seat.role == "host":
        raise SeatConflict(HAND_OVER_FIRST)
    if seat.id == by.id:
        raise SeatConflict(LEAVE_INSTEAD)
    if seat.role == "cohost" and by.role != "host":
        raise NotAllowed(ONLY_THE_HOST_REMOVES_A_COHOST)
    return leave(storage, seat)
