"""Mail waiting to go, and the confirmation of an address (DEL-314). The outbox keeps no recipient address: the sender
looks it up from the account when it sends."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Outgoing:
    """One email in the outbox. `unsubscribe` is the off token of a switchable kind; `reply_to` is a host's own
    address, for a host message the host asked replies for, and is cleared once sent."""

    id: str
    kind: str
    account_id: str
    language: str
    subject: str
    text: str
    html: str
    reply_to: str | None
    unsubscribe: str | None
    created_at: str
    next_at: str
    attempts: int = 0
    sent_at: str | None = None
    failed_at: str | None = None
    failure: str = ""


@dataclass(frozen=True)
class Confirmation:
    """A one-time link that confirms `address` for an account, known only by its token's SHA-256 hex digest."""

    token_hash: str
    account_id: str
    address: str
    created_at: str
    expires_at: str
    used_at: str | None = None
