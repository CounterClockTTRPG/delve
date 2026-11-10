"""Mail waiting to go (DEL-314): who may get a message of a kind, queuing it, and the off tokens of its one-click off
link. The outbox keeps no address: the sender looks it up from the account right before it sends.

An off token is `<account id>.<group>.<signature>`, the signature an HMAC-SHA256 of the account and the group with a
secret of this install's (`<data dir>/mail-secret`, made on first use).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from delve.domain import new_id
from delve.domain.accounts import Account
from delve.domain.mail import Outgoing
from delve.images.connections import write_secret
from delve.mail import settings
from delve.mail.compose import ALWAYS, SWITCH, Composed, Kind

SECRET_FILE = "mail-secret"
GROUPS = ("host", "board")

Group = Literal["host", "board"]


def iso(at: datetime) -> str:
    """A time as the outbox keeps it: UTC, to the second, so its text sorts as its time does."""
    return at.astimezone(UTC).isoformat(timespec="seconds")


def address_for(account: Account, kind: Kind) -> str | None:
    """Where a message of `kind` to `account` goes now: the address waiting for confirmation for `confirm`, else the
    confirmed one. None when the account is disabled, or its kind's switch is off; a sign-up still waiting for approval
    gets its confirmation only."""
    if account.disabled_at is not None:
        return None
    if kind == "confirm":
        return account.email_pending
    if account.pending:
        return None
    if kind not in ALWAYS and not getattr(account, SWITCH[kind]):
        return None
    return account.email


def queue(
    storage,
    account: Account,
    kind: Kind,
    mail: Composed,
    now: datetime,
    *,
    reply_to: str | None = None,
    unsubscribe: str | None = None,
) -> str | None:
    """Put a message in the outbox, due now; its id, or None (nothing queued) when the account has no address for
    `kind` now. `unsubscribe` is the message's off token, `reply_to` a host's own address."""
    if address_for(account, kind) is None:
        return None
    at = iso(now)
    outgoing = Outgoing(
        id=new_id("mail"),
        kind=kind,
        account_id=account.id,
        language=account.profile.language,
        subject=mail.subject,
        text=mail.text,
        html=mail.html,
        reply_to=reply_to,
        unsubscribe=unsubscribe,
        created_at=at,
        next_at=at,
    )
    storage.mail.add(outgoing)
    return outgoing.id


def _secret(data_dir: Path) -> bytes:
    """The install's secret, made on first use. A request thread and the sender may both find none at once: the new
    one is written whole beside it and linked in place only if none is there yet (`os.link` refuses an existing
    name), so the first one made is the one kept, and the other caller reads it back."""
    path = data_dir / SECRET_FILE
    secret = _read_secret(path)
    if secret:
        return secret.encode()
    made = path.with_name(f".{SECRET_FILE}.{secrets.token_hex(8)}")
    write_secret(made, secrets.token_hex(32) + "\n")
    try:
        os.link(made, path)
    except FileExistsError:
        pass  # another caller made it first: theirs is kept
    finally:
        made.unlink(missing_ok=True)
    return _read_secret(path).encode()


def _read_secret(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _signature(data_dir: Path, account_id: str, group: str) -> str:
    digest = hmac.new(_secret(data_dir), f"{account_id}.{group}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def off_token(data_dir: Path, account_id: str, group: Group) -> str:
    """The token that turns `group`'s mail off for the account, the same each time."""
    return f"{account_id}.{group}.{_signature(data_dir, account_id, group)}"


def read_off_token(data_dir: Path, token: str) -> tuple[str, str] | None:
    """The account and group an off token names; None for one this install didn't make."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    account_id, group, signature = parts
    if group not in GROUPS or not account_id:
        return None
    if not hmac.compare_digest(signature.encode(), _signature(data_dir, account_id, group).encode()):
        return None
    return account_id, group


def off_link(data_dir: Path, account_id: str, group: Group) -> tuple[str, str] | None:
    """The off token and the page that uses it (`<public URL>/mail/off/<token>`); None without a public URL."""
    url = settings.public_url(data_dir)
    if url is None:
        return None
    token = off_token(data_dir, account_id, group)
    return token, f"{url}/mail/off/{token}"
