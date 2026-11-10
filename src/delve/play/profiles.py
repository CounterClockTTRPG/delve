"""Profiles (players and tavern Task D1): changing an account's profile within its limits, and who may read it.

A profile is plain text. `updated` strips each text and takes out its control characters (a line break stays), and
refuses a key it doesn't know, so a client can't reach `avatar_sha` or anything outside the profile.

Who reads what (`card`) is decided here only, from the viewer's tables (`ProfileViewer`):
- the account itself reads every field;
- an organiser, and anyone with a live seat at a table where the account has one, reads its summary and `about`;
- any logged-in account reads the same of an account seated (not as an observer) at a public table, which Find a
  table shows (DEL-218);
- the hosts and co-hosts of the account's tables read its `host_note` and `time_zone` too;
- anyone else reads nothing, not even whether the account exists.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from delve.domain.accounts import COLOURS, EMBLEMS, Account, Profile
from delve.domain.campaigns import Seat
from delve.play.context import PlayError
from delve.play.seats import TABLE_RIGHTS, at_the_table, is_listed, shown_account, tables_of
from delve.storage import Storage

__all__ = [
    "EMBLEMS",
    "LANGUAGE",
    "NAME_LENGTH",
    "PRONOUNS_LENGTH",
    "TEXT_LENGTH",
    "ProfileViewer",
    "card",
    "summary",
    "updated",
    "viewer_of_account",
    "viewer_of_owner",
    "viewer_of_seat",
]

NAME_LENGTH = 40
PRONOUNS_LENGTH = 40
TEXT_LENGTH = 500
LANGUAGE = re.compile(r"[a-z]{2,3}")
FIELDS = ("display_name", "pronouns", "avatar_emblem", "colour", "language", "about", "host_note", "time_zone")


def _text(key: str, value: Any) -> str:
    if not isinstance(value, str):
        raise PlayError(f"The profile's {key} is text.")
    kept = "".join(c for c in value if c == "\n" or unicodedata.category(c) != "Cc")
    return kept.strip()


def _at_most(text: str, limit: int, message: str) -> str:
    if len(text) > limit:
        raise PlayError(message)
    return text


#: The regions whose zones the pickers offer; the database's other names (US/Eastern, GB, Etc/GMT+5) are aliases.
ZONE_REGIONS = (
    "Africa",
    "America",
    "Antarctica",
    "Arctic",
    "Asia",
    "Atlantic",
    "Australia",
    "Europe",
    "Indian",
    "Pacific",
)


def time_zones() -> list[str]:
    """The time zones this server knows, as the pickers offer them (DEL-239): each region's, then UTC. The browser's
    own list can't stand in, its names are ICU's and some (Africa/Asmera) are gone from the tz database."""
    known = available_timezones()
    return sorted(zone for zone in known if zone.split("/", 1)[0] in ZONE_REGIONS) + ["UTC"]


def _time_zone(value: Any) -> str | None:
    if value is None:
        return None
    key = _text("time_zone", value)
    try:
        ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise PlayError("That isn't a time zone, such as Europe/Brussels.") from None
    return key


def updated(profile: Profile, changes: dict[str, Any]) -> Profile:
    """The profile with `changes`, each within its limits; a `PlayError` for the first that isn't. Choosing an
    emblem takes the uploaded picture away."""
    for key in changes:
        if key not in FIELDS:
            raise PlayError(f"A profile has no field {key!r}.")
    fields: dict[str, Any] = {}
    if "display_name" in changes:
        name = _text("display_name", changes["display_name"])
        if not 1 <= len(name) <= NAME_LENGTH:
            raise PlayError(f"A display name has 1 to {NAME_LENGTH} characters.")
        fields["display_name"] = name
    if "pronouns" in changes:
        fields["pronouns"] = _at_most(
            _text("pronouns", changes["pronouns"]),
            PRONOUNS_LENGTH,
            f"Pronouns have at most {PRONOUNS_LENGTH} characters.",
        )
    if "about" in changes:
        fields["about"] = _at_most(
            _text("about", changes["about"]), TEXT_LENGTH, f"About you has at most {TEXT_LENGTH} characters."
        )
    if "host_note" in changes:
        fields["host_note"] = _at_most(
            _text("host_note", changes["host_note"]),
            TEXT_LENGTH,
            f"A note for the host has at most {TEXT_LENGTH} characters.",
        )
    if "avatar_emblem" in changes:
        if changes["avatar_emblem"] not in EMBLEMS:
            raise PlayError(f"An emblem is one of {', '.join(EMBLEMS)}.")
        fields["avatar_emblem"], fields["avatar_sha"] = changes["avatar_emblem"], None
    if "colour" in changes:
        if changes["colour"] not in COLOURS:
            raise PlayError(f"A colour is one of {', '.join(COLOURS)}.")
        fields["colour"] = changes["colour"]
    if "language" in changes:
        language = changes["language"]
        if not isinstance(language, str) or not LANGUAGE.fullmatch(language):
            raise PlayError("A language is a code of 2 or 3 letters, such as en or nl.")
        fields["language"] = language
    if "time_zone" in changes:
        fields["time_zone"] = _time_zone(changes["time_zone"])
    return replace(profile, **fields)


@dataclass(frozen=True)
class ProfileViewer:
    """Who reads a profile: their account (if any), the campaigns where they have a live seat, those where that seat
    is the host or a co-host, and whether they have the organiser's rights."""

    account_id: str | None
    campaigns: frozenset[str]
    hosting: frozenset[str]
    organiser: bool


def _viewer(account_id: str | None, live: list[Seat], organiser: bool) -> ProfileViewer:
    return ProfileViewer(
        account_id,
        frozenset(s.campaign_id for s in live),
        frozenset(s.campaign_id for s in live if s.role in TABLE_RIGHTS),
        organiser,
    )


def viewer_of_seat(storage: Storage, seat: Seat, *, organiser: bool) -> ProfileViewer:
    """A seat token's viewer: its one table, while it hasn't left."""
    return _viewer(seat.account_id, [seat] if seat.left_at is None else [], organiser)


def viewer_of_owner(storage: Storage) -> ProfileViewer:
    """The install's owner: seated at every table, hosting those where the owner's seat is the host or a co-host."""
    campaigns = storage.campaigns.list()
    owned = [storage.seats.owner_seat(c.id) for c in campaigns]
    viewer = _viewer(None, [s for s in owned if s is not None and s.left_at is None], True)
    return replace(viewer, campaigns=frozenset(c.id for c in campaigns))


def viewer_of_account(storage: Storage, account: Account) -> ProfileViewer:
    """An account's viewer: its live seats; an owner account is the owner."""
    if account.owner:
        return replace(viewer_of_owner(storage), account_id=account.id)
    return _viewer(account.id, storage.seats.of_account(account.id), account.organiser)


def summary(account: Account) -> dict[str, Any]:
    """What a table shows of a player: an uploaded picture (by the start of its sha) wins over the emblem."""
    profile = account.profile
    avatar = {"picture": profile.avatar_sha[:12]} if profile.avatar_sha else {"emblem": profile.avatar_emblem}
    return {
        "account_id": account.id,
        "display_name": profile.display_name,
        "pronouns": profile.pronouns,
        "avatar": avatar,
        "colour": profile.colour,
    }


def people(
    storage: Storage,
    campaign_id: str,
    listed: Sequence[Seat] | None = None,
    accounts: Mapping[str, Account] | None = None,
) -> list[dict[str, Any]]:
    """Who sits at the table, as a table's card shows them (DEL-217): the host, co-hosts and players
    (`seats.at_the_table`), each with their name, role and profile summary (null for a seat without an account).
    `listed` and `accounts` are the table's seats and every account by id, when the caller read them (DEL-172)."""
    found = []
    for seat in at_the_table(storage, campaign_id, listed):
        account = shown_account(storage, seat, accounts)
        profile = None if account is None else summary(account)
        found.append({"seat_id": seat.id, "name": seat.name, "role": seat.role, "profile": profile})
    return found


def card(storage: Storage, account_id: str, viewer: ProfileViewer) -> dict[str, Any] | None:
    """The account's profile as `viewer` may read it, or None when they may read none of it: their own, an organiser,
    someone at a table with them, or any account when they sit at a public table (Find a table shows them; DEL-218).
    The note for the host and their time zone are for the hosts of their tables only."""
    account = storage.accounts.get(account_id)
    if account is None:
        return None
    own = viewer.account_id == account.id
    tables = tables_of(storage, account)
    if not (own or viewer.organiser or tables & viewer.campaigns or _at_a_listed_table(storage, account, viewer)):
        return None
    profile = account.profile
    found = {**summary(account), "about": profile.about}
    if own or tables & viewer.hosting:
        found |= {"host_note": profile.host_note, "time_zone": profile.time_zone}
    if own:
        found |= {"language": profile.language, "avatar_emblem": profile.avatar_emblem}
    return found


def _at_a_listed_table(storage: Storage, account: Account, viewer: ProfileViewer) -> bool:
    """Whether a logged-in viewer sees the account on Find a table: seated at a public table, not as an observer."""
    if viewer.account_id is None:
        return False
    for campaign_id in tables_of(storage, account):
        if is_listed(storage.campaigns.get(campaign_id)):
            shown = (shown_account(storage, seat) for seat in at_the_table(storage, campaign_id))
            if any(found is not None and found.id == account.id for found in shown):
                return True
    return False
