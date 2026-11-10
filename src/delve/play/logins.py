"""Login sessions (players and tavern Task C1): a browser logged in to an account.

A session's token is `secrets.token_urlsafe(32)`, sent in the `delve_session` cookie and stored only as its SHA-256 hex
digest. It is alive until `SESSION_DAYS` after its last use; `resolve` ends it then, and touches it at most once every
`TOUCH_EVERY_S`. A disabled account has no session. Changing the password ends the account's other sessions; using a
reset link, or disabling the account, ends them all."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from delve.domain.accounts import Account, LoginSession
from delve.play import accounts
from delve.storage import Storage

SESSION_DAYS = 30
TOUCH_EVERY_S = 60
DEVICE_LENGTH = 200


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start(storage: Storage, account_id: str, device: str, address: str, now: datetime) -> str:
    """A new login session for the account; its token, which only the browser keeps."""
    token = secrets.token_urlsafe(32)
    storage.login_sessions.create(account_id, token_hash(token), device[:DEVICE_LENGTH], address, now.isoformat())
    return token


def resolve(storage: Storage, token: str, now: datetime) -> tuple[Account, LoginSession] | None:
    """The account and session of the token, or None: unknown, unused for `SESSION_DAYS` (then it ends), or its
    account disabled."""
    login = storage.login_sessions.by_token_hash(token_hash(token))
    if login is None:
        return None
    last_used = datetime.fromisoformat(login.last_used_at)
    if now - last_used >= timedelta(days=SESSION_DAYS):
        storage.login_sessions.end(login.id)
        return None
    account = storage.accounts.get(login.account_id)
    if account is None or account.disabled_at is not None:
        return None
    if now - last_used >= timedelta(seconds=TOUCH_EVERY_S):
        storage.login_sessions.touch(login.id, now.isoformat())
        login = LoginSession(login.id, login.account_id, login.created_at, now.isoformat(), login.device, login.address)
    return account, login


def end(storage: Storage, token: str) -> None:
    """Log the token's browser out; nothing for an unknown token."""
    login = storage.login_sessions.by_token_hash(token_hash(token))
    if login is not None:
        storage.login_sessions.end(login.id)


def change_password(storage: Storage, account_id: str, old: str, new: str, *, keep: str) -> None:
    """Change the password (`NotAllowed` for a wrong `old`) and end every other session but `keep`'s."""
    with storage.transaction():
        accounts.change_password(storage, account_id, old, new)
        storage.login_sessions.end_all(account_id, but=keep)


def disable(storage: Storage, account_id: str, disabled: bool, now: datetime, *, by_owner: bool) -> Account:
    """Disable the account, ending every session of it, or enable it (`accounts.set_disabled`'s rights)."""
    with storage.transaction():
        account = accounts.set_disabled(storage, account_id, disabled, now, by_owner=by_owner)
        if disabled:
            storage.login_sessions.end_all(account_id)
    return account


def use_link(storage: Storage, token: str, password: str, now: datetime) -> Account:
    """Set the password through a one-time link, ending every session of the account."""
    with storage.transaction():
        account = accounts.use_link(storage, token, password, now)
        storage.login_sessions.end_all(account.id)
    return account
