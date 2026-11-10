"""Who may do what on the message board (DEL-297): the one function that decides, for a caller and a zone, whether
they may read, write, moderate and manage it. Every route and the events stream ask it; nothing else decides. It takes
plain values (an account and two flags, as `caller_of` maps them), not a web principal, so `delve.play` stays clear of
`delve.web`."""

from __future__ import annotations

from dataclasses import dataclass

from delve.domain.accounts import Account
from delve.domain.board import Level, Zone
from delve.storage import Storage


@dataclass(frozen=True)
class Caller:
    """Who is asking: an account (None for a visitor, or for the owner's token alone), and whether they hold the
    organiser's or the owner's rights."""

    account: Account | None = None
    organiser: bool = False
    owner: bool = False


VISITOR = Caller()


@dataclass(frozen=True)
class Rights:
    """What a caller may do in one zone. `manage_wide` is what only organisers may: levels wider than `members` and
    `table`, and a zone not tied to a campaign."""

    read: bool
    write: bool
    moderate: bool
    manage: bool
    manage_wide: bool


def caller_of(account: Account | None, organiser: bool, owner: bool) -> Caller:
    """The caller for a principal's parts; a disabled account is a visitor."""
    if account is not None and account.disabled_at is not None:
        return VISITOR
    return Caller(account, organiser, owner)


def rights(storage: Storage, caller: Caller, zone: Zone) -> Rights:
    """What the caller may do in the zone; the owner counts as an organiser."""
    account = caller.account
    if account is not None and account.disabled_at is not None:
        account = None
        caller = VISITOR
    wide = caller.organiser or caller.owner
    seat = None
    if account is not None and zone.campaign_id is not None:
        seat = storage.seats.for_account(account.id, zone.campaign_id)
    role = None if seat is None else seat.role
    runs_table = role in ("host", "cohost")
    moderate = wide or runs_table or (account is not None and account.id in zone.moderators)
    manage = wide or role == "host"

    def admits(level: Level) -> bool:
        if level == "everybody":
            return True
        if account is None:
            return False
        if level == "accounts":
            return True
        if level == "members":
            return account.id in zone.members
        return role is not None

    read = moderate or admits(zone.read)
    write = False
    if account is not None or caller.owner:
        write = moderate or (account is not None and _writes(zone.write, account, zone, role))
    return Rights(read=read, write=write, moderate=moderate, manage=manage, manage_wide=wide)


def _writes(level: Level, account: Account, zone: Zone, role: str | None) -> bool:
    if level == "accounts":
        return True
    if level == "members":
        return account.id in zone.members
    return role in ("host", "cohost", "player")


def valid_levels(read: Level, write: Level, campaign_id: str | None) -> str | None:
    """None when the read and write levels may go together on the zone, else the refusal's message."""
    if write == "everybody":
        return "Nobody may write to everybody: write is for accounts, members or the table."
    if read in ("members", "table") and write != read:
        return f"A zone read by {read} is written by {read} only."
    if "table" in (read, write) and campaign_id is None:
        return "The table level needs a zone tied to a campaign."
    return None


def badges(storage: Storage, zone: Zone, account_id: str | None) -> list[str]:
    """The badges a post's author wears in the zone: organiser, moderator, host, cohost."""
    if account_id is None:
        return []
    found: list[str] = []
    account = storage.accounts.get(account_id)
    if account is not None and (account.organiser or account.owner):
        found.append("organiser")
    if account_id in zone.moderators:
        found.append("moderator")
    if zone.campaign_id is not None:
        seat = storage.seats.for_account(account_id, zone.campaign_id)
        if seat is not None and seat.role in ("host", "cohost"):
            found.append(seat.role)
    return found
