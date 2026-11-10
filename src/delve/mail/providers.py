"""What hands a message on (DEL-314): the log provider, which writes the message's kind, account and subject to the log
and sends nothing, and Emailit (`POST https://api.emailit.com/v2/emails`).

A provider answers `Accepted`, `Retry` (a temporary failure, after a wait) or `Failed` (a refusal, in Delve's words:
never the remote body, never the key). One message has one recipient, never a cc or bcc, and no tracking.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from delve.mail import settings

log = logging.getLogger(__name__)

EMAILIT_URL = "https://api.emailit.com/v2/emails"
TIMEOUT_S = 30.0
DOWN_RETRY_S = 60.0
"""The wait after a 5xx, a timeout or a connection that failed."""
RETRY_AFTER_MAX_S = 3600.0
"""The longest wait a rate limit gets, whatever it asks; one that isn't a finite number is a second."""


@dataclass(frozen=True)
class Envelope:
    """One message to hand on. `to` is the address the account has now; `kind` and `account_id` are for the log."""

    id: str
    to: str = field(repr=False)
    sender: str
    subject: str
    text: str
    html: str
    reply_to: str | None = field(repr=False)
    headers: dict[str, str]
    kind: str
    account_id: str


@dataclass(frozen=True)
class Accepted:
    pass


@dataclass(frozen=True)
class Retry:
    """Try again after `after_s`. `rate_limited` is the provider asking for a slower pace (a 429): that wait doesn't
    count toward giving up."""

    after_s: float
    reason: str
    rate_limited: bool = False


@dataclass(frozen=True)
class Failed:
    reason: str


class MailProvider(Protocol):
    async def send(self, envelope: Envelope) -> Accepted | Retry | Failed: ...


class LogProvider:
    """Mail that goes nowhere: its kind, account and subject in the log (never the address or the words)."""

    async def send(self, envelope: Envelope) -> Accepted | Retry | Failed:
        log.info("mail %s (%s) to account %s: %s", envelope.id, envelope.kind, envelope.account_id, envelope.subject)
        return Accepted()


def _retry_after(response: httpx.Response) -> float:
    try:
        wait = response.json().get("retry_after")
    except (ValueError, AttributeError):
        wait = None
    if wait is None:
        wait = response.headers.get("Retry-After")
    try:
        wait = float(wait)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(wait) or wait <= 0:
        return 1.0
    return min(wait, RETRY_AFTER_MAX_S)


def _outcome(response: httpx.Response) -> Accepted | Retry | Failed:
    status = response.status_code
    if 200 <= status < 300:
        return Accepted()
    if status == 429:
        return Retry(_retry_after(response), "Emailit is limiting how fast mail goes", rate_limited=True)
    if status >= 500:
        return Retry(DOWN_RETRY_S, f"Emailit is unavailable (HTTP {status})")
    if status == 402:
        return Failed("Emailit has no credits left")
    if status == 401:
        return Failed("Emailit refused the API key")
    if status == 403 and "unverified_workspace_recipient" in response.text:
        return Failed("Emailit's workspace is still in sandbox")
    if status == 403:  # e.g. "Domain not authorized": the key's workspace doesn't own the sender's domain
        return Failed("Emailit's key may not send from this sender's domain")
    if status == 422:
        return Failed("Emailit hasn't verified the sending domain")
    return Failed(f"Emailit refused the message (HTTP {status})")


class EmailitProvider:
    """Emailit's API, with `key`, over `client`; `aclose` closes the client."""

    def __init__(self, key: str, client: httpx.AsyncClient) -> None:
        self._key = key
        self._client = client

    async def send(self, envelope: Envelope) -> Accepted | Retry | Failed:
        body: dict[str, Any] = {
            "from": envelope.sender,
            "to": envelope.to,
            "subject": envelope.subject,
            "text": envelope.text,
            "html": envelope.html,
            "tracking": False,
            "meta": {"delve_id": envelope.id},
        }
        if envelope.reply_to:
            body["reply_to"] = envelope.reply_to
        if envelope.headers:
            body["headers"] = envelope.headers
        headers = {"Authorization": f"Bearer {self._key}", "Idempotency-Key": envelope.id}
        try:
            response = await self._client.post(EMAILIT_URL, json=body, headers=headers, timeout=TIMEOUT_S)
        except httpx.TimeoutException:
            return Retry(DOWN_RETRY_S, "Emailit didn't answer in time")
        except httpx.TransportError:
            return Retry(DOWN_RETRY_S, "Delve couldn't reach Emailit")
        return _outcome(response)

    async def aclose(self) -> None:
        await self._client.aclose()


def provider_for(app: Any) -> MailProvider | None:
    """The provider the settings name now: the log provider for `log`; Emailit when mail is enabled
    (`settings.mail_enabled`); None when Emailit is chosen but lacks a key, a sender or a public URL, so the outbox
    holds its mail rather than lose it. A test's `app.state.mail_transport` stands in for Emailit."""
    data_dir = app.state.config.data_dir
    if settings.load(data_dir).provider == "log":
        return LogProvider()
    if not settings.mail_enabled(data_dir):
        return None
    key = settings.load_key(data_dir)
    assert key is not None  # mail_enabled checked it
    transport = getattr(app.state, "mail_transport", None)
    return EmailitProvider(key, httpx.AsyncClient(transport=transport))
