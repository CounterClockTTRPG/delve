"""Accounts (players and tavern Task B2): making them, checking a password, one-time links that set or reset it, and
who may change an account's rights.

A username is case-folded before anything else, so `" Ana "`, `ANA` and `ana` are one account. A refusal never holds
a password, and never says whether a username exists to someone logging in (`authenticate` answers None).

Rights (the human's ruling of 2026-10-24): an account may be an owner, with every right of the install's owner, or an
organiser. Only an owner grants or withdraws either, disables or enables an owner's or an organiser's account, and
makes a link that sets or resets its password; the caller says whether it acts as an owner with `by_owner`. The last
enabled owner account is never disabled or demoted. While there is no owner account, `create_first_owner` makes one.

Sign-ups (DEL-156): anyone may ask for a player's account (`request_account`), which is `pending` until the owner or an
organiser approves it (`approve`) or rejects it (`reject`, which deletes it and frees its username). A pending account
can't log in: `authenticate` raises `AccountPending`, but only for the right password, so a stranger learns nothing."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import replace
from datetime import datetime, timedelta

from delve.domain.accounts import (
    LINK_HOURS,
    LINK_KINDS,
    PASSWORD_MAX,
    PASSWORD_MIN,
    USERNAME,
    Account,
    AccountLink,
    Identity,
    Profile,
    default_emblem,
)
from delve.play.context import NotFound, PlayError
from delve.play.passwords import check_password, dummy_check, hash_password
from delve.play.profiles import NAME_LENGTH
from delve.play.seats import NotAllowed
from delve.storage import Storage

RESET_ASK_DAYS = 7
"""How long a player's request for a new password stays on the Players page (DEL-268)."""
USERNAME_RULE = "A username has 3 to 32 characters: a to z, 0 to 9, '.', '_' and '-'."
TAKEN = "That username is taken."
LAST_OWNER = "This is the last owner account: make another account an owner first."
ONLY_AN_OWNER = "Only an owner can do that."
PROMOTED_SINCE = "This link no longer works: ask an owner for a new one."
PENDING = "Your account waits for approval by the owner or an organiser: try again once they have let you in."
NOT_PENDING = "This account isn't waiting for approval."
NOTE_MAX = 300
"""What a sign-up may tell the approver: who they are, who sent them."""
IDENTITY_TAKEN = "That account is linked to another Delve account already."
PENDING_MAX = 20
"""How many sign-ups may wait for approval at once: past it, nobody may ask until some are approved or rejected."""


class AccountConflict(PlayError):
    """The accounts' state refuses it: the username is taken, or it would leave no owner (409)."""


class AccountPending(PlayError):
    """The account is a sign-up that waits for approval: it can't log in yet (DEL-156)."""


class SignUpsFull(PlayError):
    """`PENDING_MAX` sign-ups wait already (DEL-156)."""


def username_of(raw: str) -> str:
    """The username `raw` stands for: stripped and case-folded, or a refusal."""
    username = raw.strip().casefold()
    if not USERNAME.fullmatch(username):
        raise PlayError(USERNAME_RULE)
    return username


def check_new_password(password: str) -> None:
    if len(password) < PASSWORD_MIN:
        raise PlayError(f"A password has at least {PASSWORD_MIN} characters.")
    if len(password) > PASSWORD_MAX:
        raise PlayError(f"A password has at most {PASSWORD_MAX} characters.")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _account(storage: Storage, account_id: str) -> Account:
    account = storage.accounts.get(account_id)
    if account is None:
        raise NotFound("There is no such account.")
    return account


def create_account(
    storage: Storage,
    username: str,
    password: str | None,
    *,
    display_name: str | None = None,
    language: str = "en",
    organiser: bool = False,
    owner: bool = False,
) -> Account:
    """A new account; without a password it waits for a set-password link. The display name defaults to the
    username, and the avatar to the username's emblem."""
    username = username_of(username)
    if password is not None:
        check_new_password(password)
    profile = Profile(display_name or username, language=language, avatar_emblem=default_emblem(username))
    with storage.transaction():
        if storage.accounts.by_username(username) is not None:
            raise AccountConflict(TAKEN)
        try:
            account = storage.accounts.create(username, profile, organiser=organiser, owner=owner)
        except ValueError:
            raise AccountConflict(TAKEN) from None
        if password is not None:
            storage.accounts.set_password_hash(account.id, hash_password(password))
            account = replace(account, has_password=True)
    return account


def has_owner_account(storage: Storage) -> bool:
    return storage.accounts.has_owner()


def create_first_owner(
    storage: Storage, username: str, password: str, *, display_name: str | None = None, language: str = "en"
) -> Account:
    """The install's first owner account, with its password; a refusal once there is an owner account."""
    check_new_password(password)
    with storage.transaction():
        if has_owner_account(storage):
            raise AccountConflict("There is an owner account already: log in with it.")
        return create_account(storage, username, password, display_name=display_name, language=language, owner=True)


def authenticate(storage: Storage, username: str, password: str) -> Account | None:
    """The account these let in, or None: for a username that isn't one, an unknown one, a disabled account, one
    without a password, or a wrong password. Every answer costs one scrypt check."""
    try:
        username = username_of(username)
    except PlayError:
        dummy_check(password)
        return None
    account = storage.accounts.by_username(username)
    stored = storage.accounts.password_hash(account.id) if account is not None else None
    if stored is None:
        dummy_check(password)
        return None
    if not check_password(password, stored) or account.disabled_at is not None:
        return None
    if account.pending:
        raise AccountPending(PENDING)
    return account


def request_account(
    storage: Storage,
    username: str,
    password: str | None,
    *,
    display_name: str | None = None,
    language: str = "en",
    note: str = "",
    identity: Identity | None = None,
) -> Account:
    """A sign-up: a player's account with its password, pending until it is approved (DEL-156); or, with no
    password, with the outside `identity` it logs in with (DEL-206), linked in the same transaction (its `account_id`
    is the new account's). The display name defaults to the username. A refusal for a username taken, a password or a
    name that won't do, a note past `NOTE_MAX`, an identity linked already, or `SignUpsFull`."""
    username = username_of(username)
    if password is None and identity is None:
        raise PlayError("A sign-up needs a password or an identity to log in with.")
    if password is not None:
        check_new_password(password)
    if display_name is not None:
        display_name = display_name.strip()
        if not 1 <= len(display_name) <= NAME_LENGTH:
            raise PlayError(f"A name has 1 to {NAME_LENGTH} characters.")
    note = note.strip()
    if len(note) > NOTE_MAX:
        raise PlayError(f"A note has at most {NOTE_MAX} characters.")
    profile = Profile(display_name or username, language=language, avatar_emblem=default_emblem(username))
    password_hash = hash_password(password) if password is not None else None
    with storage.transaction():
        if storage.accounts.by_username(username) is not None:
            raise AccountConflict(TAKEN)
        if sum(account.pending for account in storage.accounts.list()) >= PENDING_MAX:
            raise SignUpsFull("Many people are waiting to be let in already: try again later.")
        try:
            account = storage.accounts.create(username, profile, pending=True, request_note=note)
        except ValueError:
            raise AccountConflict(TAKEN) from None
        if password_hash is not None:
            storage.accounts.set_password_hash(account.id, password_hash)
        if identity is not None:
            try:
                storage.account_identities.add(replace(identity, account_id=account.id))
            except ValueError:
                raise AccountConflict(IDENTITY_TAKEN) from None
    return replace(account, has_password=password_hash is not None)


def _pending(storage: Storage, account_id: str) -> Account:
    account = _account(storage, account_id)
    if not account.pending:
        raise AccountConflict(NOT_PENDING)
    return account


def approve(storage: Storage, account_id: str) -> Account:
    """Let the sign-up in: it logs in from now on (DEL-156)."""
    with storage.transaction():
        _pending(storage, account_id)
        return storage.accounts.approve(account_id)


def reject(storage: Storage, account_id: str) -> None:
    """Turn the sign-up away: the account is deleted, and its username is free again (DEL-156)."""
    with storage.transaction():
        _pending(storage, account_id)
        storage.accounts.delete_pending(account_id)


def change_password(storage: Storage, account_id: str, old: str, new: str) -> None:
    if not check_password(old, storage.accounts.password_hash(_account(storage, account_id).id)):
        raise NotAllowed("Your current password is wrong.")
    check_new_password(new)
    storage.accounts.set_password_hash(account_id, hash_password(new))


def make_link(storage: Storage, account_id: str, kind: str, now: datetime, *, by_owner: bool) -> str:
    """A new one-time link's token, valid `LINK_HOURS`; the account's unused links stop working. A link for an
    owner's or an organiser's account is only an owner's to make, as whoever uses it holds the account; the link
    keeps who made it, so one an organiser made stops working if its account is promoted (`_usable`, DEL-150)."""
    if kind not in LINK_KINDS:
        raise PlayError(f"A link sets or resets a password: {', '.join(LINK_KINDS)}.")
    account = _account(storage, account_id)
    if (account.owner or account.organiser) and not by_owner:
        raise NotAllowed(ONLY_AN_OWNER)
    token = secrets.token_urlsafe(32)
    link = AccountLink(
        account_id, kind, now.isoformat(), (now + timedelta(hours=LINK_HOURS)).isoformat(), by_owner=by_owner
    )
    with storage.transaction():
        storage.account_links.drop_unused(account_id)
        storage.account_links.put(_token_hash(token), link)
        if kind == "reset-password" and account.reset_asked_at is not None:
            storage.accounts.set_reset_asked(account_id, None)  # the request is answered (DEL-268)
    return token


def ask_for_reset(storage: Storage, username: str, now: datetime) -> Account | None:
    """A player's request for a new password from the login page (DEL-268): the account, its request recorded, or
    None for a username that names no account, a disabled one or a sign-up still waiting. The caller answers the same
    either way, so the request tells nobody which usernames exist."""
    try:
        account = storage.accounts.by_username(username_of(username))
    except PlayError:
        return None
    if account is None or account.disabled_at is not None or account.pending:
        return None
    return storage.accounts.set_reset_asked(account.id, now.isoformat())


def reset_targets(storage: Storage, name_or_address: str) -> list[Account]:
    """The accounts a forgotten password's link goes to by email (DEL-314): for a value with `@`, every enabled,
    approved account whose confirmed address it is; for a username, its account when that is enabled, approved and
    has a confirmed address. Empty otherwise: the caller then asks the owner (`ask_for_reset`) for a username."""
    value = name_or_address.strip()
    if "@" in value:
        return storage.accounts.with_email(value)
    try:
        account = storage.accounts.by_username(username_of(value))
    except PlayError:
        return []
    if account is None or account.disabled_at is not None or account.pending or account.email is None:
        return []
    return [account]


def open_reset_request(account: Account, now: datetime) -> str | None:
    """When the account asked for a new password, while that request is open: at most `RESET_ASK_DAYS` old."""
    asked = account.reset_asked_at
    if asked is None or datetime.fromisoformat(asked) <= now - timedelta(days=RESET_ASK_DAYS):
        return None
    return asked


def _usable(storage: Storage, token: str, now: datetime) -> tuple[Account, AccountLink]:
    link = storage.account_links.get(_token_hash(token))
    if link is None:
        raise PlayError("This link isn't known: ask for a new one.")
    if link.used_at is not None:
        raise PlayError("This link has been used: ask for a new one.")
    if datetime.fromisoformat(link.expires_at) <= now:
        raise PlayError("This link has expired: ask for a new one.")
    account = storage.accounts.get(link.account_id)
    if account is None or account.disabled_at is not None:
        raise PlayError("This account is disabled.")
    if (account.owner or account.organiser) and not link.by_owner:
        raise PlayError(PROMOTED_SINCE)
    return account, link


def link_for(storage: Storage, token: str, now: datetime) -> tuple[Account, AccountLink] | None:
    """The link's account and link, or None when it is unknown, used, expired or its account disabled."""
    try:
        return _usable(storage, token, now)
    except PlayError:
        return None


def use_link(storage: Storage, token: str, password: str, now: datetime) -> Account:
    """Set the account's password through the link, which then stops working. A reset link also unlinks the account's
    outside identities (DEL-206): a reset takes an account back, and whoever linked one may not hold it now."""
    check_new_password(password)
    account, link = _usable(storage, token, now)
    password_hash = hash_password(password)
    with storage.transaction():
        if not storage.account_links.use(_token_hash(token), now.isoformat()):
            raise PlayError("This link has been used: ask for a new one.")
        storage.accounts.set_password_hash(account.id, password_hash)
        if account.reset_asked_at is not None:
            storage.accounts.set_reset_asked(account.id, None)
        if link.kind == "reset-password":
            for identity in storage.account_identities.list(account.id):
                storage.account_identities.remove(account.id, identity.provider)
    return replace(account, has_password=True)


def _enabled_owners(storage: Storage) -> list[Account]:
    return [account for account in storage.accounts.list() if account.owner and account.disabled_at is None]


def _keeps_an_owner(storage: Storage, account: Account) -> None:
    if account.owner and account.disabled_at is None and _enabled_owners(storage) == [account]:
        raise AccountConflict(LAST_OWNER)


def set_disabled(storage: Storage, account_id: str, disabled: bool, now: datetime, *, by_owner: bool) -> Account:
    """Disable the account (from `now`) or enable it. A player's account is any organiser's to change; an owner's or
    an organiser's only an owner's."""
    with storage.transaction():
        account = _account(storage, account_id)
        if (account.owner or account.organiser) and not by_owner:
            raise NotAllowed(ONLY_AN_OWNER)
        if disabled:
            _keeps_an_owner(storage, account)
            if account.disabled_at is not None:
                return account
        return storage.accounts.set_disabled(account_id, now.isoformat() if disabled else None)


def set_organiser(storage: Storage, account_id: str, organiser: bool, *, by_owner: bool) -> Account:
    if not by_owner:
        raise NotAllowed(ONLY_AN_OWNER)
    with storage.transaction():
        _account(storage, account_id)
        if organiser:
            storage.account_links.drop_unused(account_id)  # whoever made them may not hold the account now (DEL-150)
        return storage.accounts.set_organiser(account_id, organiser)


def set_owner(storage: Storage, account_id: str, owner: bool, *, by_owner: bool) -> Account:
    if not by_owner:
        raise NotAllowed(ONLY_AN_OWNER)
    with storage.transaction():
        account = _account(storage, account_id)
        if not owner:
            _keeps_an_owner(storage, account)
        else:
            storage.account_links.drop_unused(account_id)  # whoever made them may not hold the account now (DEL-150)
        return storage.accounts.set_owner(account_id, owner)
