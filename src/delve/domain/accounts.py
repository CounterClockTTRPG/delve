"""Accounts (players and tavern Task B1): a person who logs in to Delve with a username and a password, with their
profile, and the one-time links that set or reset a password. An account may hold the owner's rights (`owner`, the
human's ruling of 2026-10-24) or the organiser's; the owner token keeps working beside it. A password's hash is never
a field here: only the repository's two password methods read and write it."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

USERNAME = re.compile(r"[a-z0-9._-]{3,32}")
"""A username, already case-folded: 3 to 32 of a to z, 0 to 9, '.', '_' and '-'."""
PASSWORD_MIN = 10
PASSWORD_MAX = 1024

EMBLEMS = ("lion", "eagle", "stag", "boar", "wolf", "dragon", "tower", "key", "sword", "crown", "moon", "oak")
"""The heraldic emblems an avatar may be, in the web's order (`web/src/profile/emblems.tsx`)."""
COLOURS = ("teal", "jade", "gold", "ember")
"""A player's colour: the looks' accents."""

LINK_KINDS = ("set-password", "reset-password")
LINK_HOURS = 24


def default_emblem(username: str) -> str:
    """The emblem a new account starts with: always the same one for a username."""
    return EMBLEMS[int(hashlib.sha256(username.encode()).hexdigest(), 16) % len(EMBLEMS)]


@dataclass(frozen=True)
class Profile:
    """What others at a table see of an account. `avatar_sha` is an uploaded picture in the blob store and wins over
    `avatar_emblem`; `host_note` and `time_zone` are for the hosts of the account's tables only."""

    display_name: str
    pronouns: str = ""
    avatar_emblem: str | None = None
    avatar_sha: str | None = None
    colour: str = "teal"
    language: str = "en"
    about: str = ""
    host_note: str = ""
    time_zone: str | None = None


@dataclass(frozen=True)
class Account:
    """`username` is case-folded. `owner` gives every right of the install's owner, `organiser` the organiser's.
    `external_id` is reserved for an outside identity provider's subject (such as Keycloak's `sub`); nothing writes it
    yet. `has_password` is False until a set-password link is used. `pending` is a sign-up that waits for the owner's
    or an organiser's approval, with the `request_note` it came with; it can't log in (DEL-156). `reset_asked_at` is when
the player asked for a new password from the login page, until a reset link is made or the request dismissed
(DEL-268). `email` is the confirmed address, `email_pending` one typed in and not yet confirmed; `mail_host` and
`mail_board` are the switches for a host's mail and the board's (DEL-314)."""

    id: str
    username: str
    profile: Profile
    organiser: bool = False
    owner: bool = False
    created_at: str = ""
    disabled_at: str | None = None
    external_id: str | None = None
    has_password: bool = False
    pending: bool = False
    request_note: str = ""
    reset_asked_at: str | None = None
    email: str | None = None
    email_pending: str | None = None
    mail_host: bool = True
    mail_board: bool = True


@dataclass(frozen=True)
class Identity:
    """An outside identity an account logs in with (DEL-206): an OpenID Connect provider's (`google`) `subject`, its
    `sub`, which never changes, unlike the `email` it had when it was linked (shown, never matched). One identity is one
    account's; an account has at most one per provider."""

    provider: str
    subject: str
    account_id: str
    email: str = ""
    linked_at: str = ""


@dataclass(frozen=True)
class AccountLink:
    """A one-time link that sets (`set-password`) or resets (`reset-password`) an account's password. Its token is
    known only by its SHA-256 hex digest."""

    account_id: str
    kind: str
    created_at: str
    expires_at: str
    used_at: str | None = None
    by_owner: bool = False  # an owner made it: only such a link works for an owner's or an organiser's account


@dataclass(frozen=True)
class LoginSession:
    """A browser logged in to an account (players and tavern Task C1), known by its token's SHA-256 hex digest only.
    The game's evenings of play are `Session`s: this is not one. `device` is the browser's User-Agent, cut short."""

    id: str
    account_id: str
    created_at: str
    last_used_at: str
    device: str = ""
    address: str = ""
