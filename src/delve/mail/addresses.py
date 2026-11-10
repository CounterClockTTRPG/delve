"""A player's own email address (DEL-314): private to the account, confirmed before anything but its confirmation
goes there.

A typed-in address waits in `email_pending` while its link (`<public URL>/account/email/<token>`, `LINK_HOURS`) is
on its way; the address in use, if any, stays in use until the link confirms the new one. The token is known only
by its SHA-256, in its own table (`email_confirmations`), never among the password links (`accounts.make_link`
drops an account's other unused links, which would end a confirmation and the other way round). Google's address,
when Google verified it, is trusted as given, and fills only an account that has no address at all.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from delve.domain.accounts import LINK_HOURS, Account
from delve.domain.mail import Confirmation
from delve.mail import outbox, settings
from delve.mail.compose import compose
from delve.play.context import PlayError

ADDRESS_MAX = 254
NOT_AN_ADDRESS = "That isn't an email address."
NOT_SET_UP = "Email isn't set up on this Delve."
LINK_GONE = "This link has expired or was used."


class MailNotSetUp(PlayError):
    """Delve sends no mail, so a confirmation couldn't reach the address (409)."""


class LinkGone(PlayError):
    """The confirmation link is unknown, used, expired or replaced (404)."""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise(raw: str) -> str:
    """The address stripped; `PlayError` unless it is at most `ADDRESS_MAX` characters, without spaces, with one `@`
    and a dot inside the domain."""
    address = raw.strip() if isinstance(raw, str) else ""
    local, at, domain = address.partition("@")
    if (
        not at
        or not local
        or "@" in domain
        or len(address) > ADDRESS_MAX
        or any(char.isspace() for char in address)
        or "." not in domain.strip(".")
    ):
        raise PlayError(NOT_AN_ADDRESS)
    return address


def ask_to_confirm(storage, data_dir: Path, account: Account, address: str, now: datetime) -> None:
    """Make `address` the account's pending one and queue its confirmation link; an earlier unused link stops working.
    `MailNotSetUp` while Delve sends no mail."""
    if not settings.mail_enabled(data_dir):
        raise MailNotSetUp(NOT_SET_UP)
    url = settings.public_url(data_dir)
    token = secrets.token_urlsafe(32)
    confirmation = Confirmation(
        token_hash=_token_hash(token),
        account_id=account.id,
        address=address,
        created_at=outbox.iso(now),
        expires_at=outbox.iso(now + timedelta(hours=LINK_HOURS)),
    )
    values = {"name": account.profile.display_name, "username": account.username}
    mail = compose("confirm", account.profile.language, values, link=f"{url}/account/email/{token}", off_link=None)
    with storage.transaction():
        storage.accounts.set_email(account.id, email=account.email, email_pending=address)
        storage.mail.put_confirmation(confirmation)
        outbox.queue(storage, storage.accounts.get(account.id), "confirm", mail, now)


def confirm(storage, token: str, now: datetime) -> Account:
    """Confirm the address the link was sent to: it becomes the account's address in use. `LinkGone` for a link that
    is unknown, used, expired, of a disabled account, or whose address is no longer the one waiting."""
    token_hash = _token_hash(token)
    found = storage.mail.confirmation(token_hash)
    if found is None or found.used_at is not None or datetime.fromisoformat(found.expires_at) <= now:
        raise LinkGone(LINK_GONE)
    with storage.transaction():
        account = storage.accounts.get(found.account_id)
        if account is None or account.disabled_at is not None or account.email_pending != found.address:
            raise LinkGone(LINK_GONE)
        if not storage.mail.use_confirmation(token_hash, outbox.iso(now)):
            raise LinkGone(LINK_GONE)
        storage.accounts.set_email(account.id, email=found.address, email_pending=None)
    return storage.accounts.get(account.id)


def remove(storage, account_id: str) -> None:
    """Forget the account's address, and the one waiting: its link no longer confirms anything."""
    storage.accounts.set_email(account_id, email=None, email_pending=None)


def from_google(storage, account: Account, claims_email: str) -> None:
    """Keep the address Google verified (`claims_email`, empty when it didn't) as the account's, confirmed, when the
    account has none in use and none waiting; an address the player set is never overwritten."""
    address = claims_email.strip()
    if not address or account.email is not None or account.email_pending is not None:
        return
    try:
        address = normalise(address)
    except PlayError:
        return
    storage.accounts.set_email(account.id, email=address, email_pending=None)
