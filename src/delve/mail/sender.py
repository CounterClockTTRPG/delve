"""The sender (DEL-314): a pass hands each due message of the outbox to the provider, at most two a second, with the
address its account has right then; one nobody should get now is dropped. A temporary failure waits longer each time
(`RETRY_S`), then gives up; a rate limit waits as long as asked and doesn't count; a refusal fails at once, in Delve's
words. While Emailit is chosen but not set up, the mail waits; once email is switched off (the log provider), mail left
in the outbox fails as `SWITCHED_OFF` and only a test goes to the log. `sender_loop` runs a pass every `tick` seconds.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from delve.domain.mail import Outgoing
from delve.mail import outbox, settings
from delve.mail.providers import Accepted, Envelope, Failed, LogProvider, Retry, provider_for

log = logging.getLogger(__name__)

PACE_S = 0.5
"""The wait between two sends: at most two a second."""
RETRY_S = (60, 300, 900, 3600, 3600, 3600)
"""The waits after the first, second, ... temporary failure; the one after the last gives up."""
BATCH = 20
"""The most messages one pass takes."""
KEEP_SENT = timedelta(days=30)
PRUNE_EVERY = timedelta(hours=1)
"""How often a pass forgets the mail sent over `KEEP_SENT` ago: at most once an hour, not every pass."""
GAVE_UP = "gave up"
SWITCHED_OFF = "not sent: email was switched off"
"""Why mail left in the outbox when email was switched off (Stop sending email, or Log only) is not sent."""
_LINE_BREAKS = re.compile(r"[\r\n]+")


async def _pace() -> None:
    await asyncio.sleep(PACE_S)


async def send_due(app: Any, now: datetime) -> int:
    """One pass at `now`: how many messages it handed to the provider."""
    storage = app.state.storage
    data_dir = app.state.config.data_dir
    due = storage.mail.due(outbox.iso(now), BATCH)
    provider = provider_for(app) if due else None
    if due and provider is None:
        return 0  # Emailit is chosen but not set up: the mail waits, due, until it is
    _prune(app, now)
    if provider is None:
        return 0
    if isinstance(provider, LogProvider):
        # Email is off: nothing is queued now but the test, so the rest was left from before (queued, held or backing
        # off). It isn't sent, so it isn't marked sent either.
        for message in [m for m in due if m.kind != "test"]:
            storage.mail.failed(message.id, outbox.iso(now), SWITCHED_OFF)
        due = [m for m in due if m.kind == "test"]
    mail = settings.load(data_dir)
    public_url = settings.public_url(data_dir)
    handed = 0
    try:
        for message in due:
            try:
                envelope = _envelope(storage, message, mail.sender, public_url, now)
                if envelope is None:
                    continue
                if handed:
                    await _pace()
                handed += 1
                _record(storage, message, await provider.send(envelope), now)
            except Exception as error:  # noqa: BLE001 (one broken message never holds up the others)
                # One message that breaks the pass backs off as a temporary failure; the others still go. Its id and
                # the error's type alone in the log: never the envelope, nor an error's words that might quote it.
                log.warning("mail %s couldn't be handed on (%s)", message.id, type(error).__name__)
                try:
                    _back_off(storage, message, now)
                except Exception as stuck:  # noqa: BLE001 (the pass goes on to the next message)
                    log.warning("mail %s couldn't be put back (%s)", message.id, type(stuck).__name__)
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
    return handed


def _prune(app: Any, now: datetime) -> None:
    """Forget the mail sent over `KEEP_SENT` ago, when the last time was `PRUNE_EVERY` ago or more."""
    last = getattr(app.state, "mail_pruned_at", None)
    if last is not None and now - last < PRUNE_EVERY:
        return
    app.state.storage.mail.prune_sent(outbox.iso(now - KEEP_SENT))
    app.state.mail_pruned_at = now


def _back_off(storage: Any, message: Outgoing, now: datetime, after_s: float = 0.0) -> None:
    """A temporary failure: the next wait of `RETRY_S` (at least `after_s`), or "gave up" past the last."""
    at = outbox.iso(now)
    attempts = message.attempts + 1
    if attempts > len(RETRY_S):
        storage.mail.retry(message.id, attempts, at)  # the attempt counts on the failed row
        storage.mail.failed(message.id, at, GAVE_UP)
    else:
        wait = max(after_s, RETRY_S[attempts - 1])
        storage.mail.retry(message.id, attempts, outbox.iso(now + timedelta(seconds=wait)))


def _envelope(storage: Any, message: Outgoing, sender: str, public_url: str | None, now: datetime) -> Envelope | None:
    """The message with the address its account has now; None, the message dropped, when nobody should get it."""
    at = outbox.iso(now)
    account = storage.accounts.get(message.account_id)
    to = None if account is None else outbox.address_for(account, message.kind)
    if to is None:
        storage.mail.dropped(message.id, at)
        return None
    headers = {}
    if message.unsubscribe and public_url:
        headers = {
            "List-Unsubscribe": f"<{public_url}/api/mail/off/{message.unsubscribe}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    return Envelope(
        id=message.id,
        to=to,
        sender=sender,
        subject=_LINE_BREAKS.sub(" ", message.subject),
        text=message.text,
        html=message.html,
        reply_to=message.reply_to,
        headers=headers,
        kind=message.kind,
        account_id=message.account_id,
    )


def _record(storage: Any, message: Outgoing, result: Accepted | Retry | Failed, now: datetime) -> None:
    """What the provider answered, kept on the message."""
    at = outbox.iso(now)
    if isinstance(result, Accepted):
        storage.mail.sent(message.id, at)
    elif isinstance(result, Retry) and result.rate_limited:
        # Slower, not broken: wait as asked, and the wait doesn't count toward giving up.
        wait = max(result.after_s, 1.0)
        storage.mail.retry(message.id, message.attempts, outbox.iso(now + timedelta(seconds=wait)))
        log.warning("mail %s waits: %s", message.id, result.reason)
    elif isinstance(result, Retry):
        _back_off(storage, message, now, result.after_s)
        log.warning("mail %s waits: %s", message.id, result.reason)
    elif isinstance(result, Failed):
        storage.mail.failed(message.id, at, result.reason)
        log.warning("mail %s failed: %s", message.id, result.reason)


async def sender_loop(app: Any, *, tick: float = 2.0) -> None:
    """A pass at once and then every `tick` seconds, by the app's clock, until cancelled."""
    while True:
        try:
            await send_due(app, app.state.clock.now())
        except Exception:
            log.exception("a pass of the mail sender failed")
        await asyncio.sleep(tick)
