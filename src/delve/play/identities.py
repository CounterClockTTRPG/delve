"""Outside identities (DEL-206): an account logs in with a provider's identity (Google's, through OpenID Connect,
`delve.web.oidc`) beside or instead of its password. Plain storage and rules, without HTTP: what the provider
vouched for comes in as `Claims`, already checked.

An identity is matched by its provider's `subject` alone, never by email: an address can change hands, or be one
the provider never checked, and matching it would hand an account to whoever holds the address now. So an identity
is linked only by its account itself, logged in (`link`), or made with a new account at sign-up (`sign_up`), which
waits for approval as every sign-up does (DEL-156). An account keeps a way to log in: its last identity is never
unlinked from an account without a password (`unlink`).

The address Google verified becomes the account's own, confirmed, when it has none yet (`addresses.from_google`,
DEL-314): on linking and signing up, never on logging in, so an address the player removed stays removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from delve.domain.accounts import Account, Identity
from delve.mail import addresses
from delve.play import accounts
from delve.play.context import NotFound, PlayError
from delve.storage import Storage

UNKNOWN = "No Delve account is linked to that account: sign up with it, or log in and link it from your profile."
DISABLED = "This account is disabled: ask the owner."
LINKED_ELSEWHERE = accounts.IDENTITY_TAKEN
HAS_ONE = "Your account has one linked already: unlink it first."
LAST_WAY_IN = "It is the only way you log in: set a password first."
NOT_LINKED = "Your account has none linked."


@dataclass(frozen=True)
class Claims:
    """What a provider vouched for, its ID token checked (`delve.web.oidc`): its id (`google`), the `subject` (its
    `sub`), and the email and name it gave, which are shown, never matched."""

    provider: str
    subject: str
    email: str = ""
    name: str = ""


class UnknownIdentity(PlayError):
    """No account is linked to the identity."""


class IdentityConflict(PlayError):
    """The identity is another account's, or the account has one of that provider (409)."""


def log_in(storage: Storage, claims: Claims) -> Account:
    """The account the identity logs in to; `UnknownIdentity`, `accounts.AccountPending` for a sign-up that waits for
    approval, or a refusal for a disabled account."""
    found = storage.account_identities.get(claims.provider, claims.subject)
    account = storage.accounts.get(found.account_id) if found is not None else None
    if account is None:
        raise UnknownIdentity(UNKNOWN)
    if account.disabled_at is not None:
        raise PlayError(DISABLED)
    if account.pending:
        raise accounts.AccountPending(accounts.PENDING)
    return account


def link(storage: Storage, account_id: str, claims: Claims, now: datetime) -> Identity:
    """Link the identity to the account, which is logged in; `IdentityConflict` when it is another account's or the
    account has one of that provider already. Linking the one it has already is no change."""
    if storage.accounts.get(account_id) is None:
        raise NotFound("There is no such account.")
    with storage.transaction():
        found = storage.account_identities.get(claims.provider, claims.subject)
        if found is not None:
            if found.account_id != account_id:
                raise IdentityConflict(LINKED_ELSEWHERE)
            return found
        if any(i.provider == claims.provider for i in storage.account_identities.list(account_id)):
            raise IdentityConflict(HAS_ONE)
        linked = storage.account_identities.add(_identity(claims, account_id, now))
        addresses.from_google(storage, storage.accounts.get(account_id), claims.email)
        return linked


def sign_up(
    storage: Storage,
    claims: Claims,
    username: str,
    now: datetime,
    *,
    display_name: str | None = None,
    language: str = "en",
    note: str = "",
) -> Account:
    """Ask for a player's account that logs in with the identity, without a password: pending until it is approved,
    as `accounts.request_account`'s refusals say. An identity linked already is `IdentityConflict`: it logs in."""
    if storage.account_identities.get(claims.provider, claims.subject) is not None:
        raise IdentityConflict(LINKED_ELSEWHERE)
    name = display_name if display_name and display_name.strip() else (claims.name.strip() or None)
    try:
        account = accounts.request_account(
            storage,
            username,
            None,
            display_name=name,
            language=language,
            note=note,
            identity=_identity(claims, "", now),
        )
    except accounts.AccountConflict as conflict:
        if conflict.message == accounts.IDENTITY_TAKEN:
            raise IdentityConflict(LINKED_ELSEWHERE) from None
        raise
    addresses.from_google(storage, account, claims.email)
    return storage.accounts.get(account.id)


def unlink(storage: Storage, account_id: str, provider: str) -> None:
    """Unlink the account's identity of `provider`; refused when it has none, or when it is the account's only way
    to log in (no password, no other identity)."""
    account = storage.accounts.get(account_id)
    if account is None:
        raise NotFound("There is no such account.")
    with storage.transaction():
        linked = storage.account_identities.list(account_id)
        if not any(i.provider == provider for i in linked):
            raise PlayError(NOT_LINKED)
        if not account.has_password and len(linked) == 1:
            raise PlayError(LAST_WAY_IN)
        storage.account_identities.remove(account_id, provider)


def _identity(claims: Claims, account_id: str, now: datetime) -> Identity:
    return Identity(claims.provider, claims.subject, account_id, claims.email.strip()[:320], now.isoformat())
