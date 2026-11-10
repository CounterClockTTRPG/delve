"""Join requests (DEL-204 part B): asking to join a public table, talking on the request, and the hosts' answer.

An account that finds a public table asks to join it with a short note (which may be empty). Until a host or a co-host
answers, the two sides talk on the request: a short thread of at most `MOST_MESSAGES` messages, each 1 to
`MESSAGE_LENGTH` characters; table talk opens once the player has a seat. The account may withdraw the request. A host
accepts it, which gives the account a `player` seat as the join link would (`seats.seat_account`), or declines it, with
a reason that goes into the thread first. An account has one pending request per table; once one is decided, it may
ask again. A full table takes no request, and an accept there is refused.

A request may also ask to watch (DEL-215): an `observer`'s, which a table whose watchers a host lets in
(`Campaign.observers` `approved`) asks for even from its join link, and which a full table takes too (an observer
takes no place). A table that takes no observers (`nobody`) refuses one. Accepting gives the account the role it
asked for.

The note and the messages are for people only: the DM never reads them, so they go into no prompt.

Refusals are `PlayError`s: `RequestConflict` (409) for the request's or the table's state, `seats.TableFull` (409)
for a full table, a plain `PlayError` (422) for a message that isn't allowed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Literal

from delve.domain.accounts import Account
from delve.domain.campaigns import Campaign, JoinRequest, Seat, SeatAsk
from delve.play import seats
from delve.play.context import NotFound, PlayError
from delve.storage import Storage

MESSAGE_LENGTH = 1000
MOST_MESSAGES = 50
RECENT_DAYS = 14
"""The host's list shows the requests decided in the last this many days, after the pending ones."""
SEATED_ALREADY = "You're at this table already."
ASKED_ALREADY = "You asked already: wait for the host."
TALK_AT_THE_TABLE = "Talk at the table once you're seated."
DECIDED = "This request is answered already."
NO_SUCH_REQUEST = "No such request."
NO_OBSERVERS = "This table takes no observers."

Sender = Literal["player", "host"]


class RequestConflict(PlayError):
    """The request's or the table's state refuses it: decided already, asked already, seated already, or the thread
    is full (409)."""


def _text(raw: str, *, empty: bool = False) -> str:
    """The text stripped, of 1 (or, with `empty`, 0) to `MESSAGE_LENGTH` characters; a `PlayError` otherwise."""
    text = raw.strip()
    if len(text) > MESSAGE_LENGTH or (not text and not empty):
        raise PlayError(f"A message has 1 to {MESSAGE_LENGTH} characters.")
    return text


def _message(sender: Sender, name: str, text: str, at: datetime) -> dict[str, str]:
    return {"from": sender, "name": name, "text": text, "at": at.isoformat()}


def _pending(storage: Storage, request_id: str) -> JoinRequest:
    request = storage.join_requests.get(request_id)
    if request is None:
        raise NotFound(NO_SUCH_REQUEST)
    if request.status != "pending":
        raise RequestConflict(DECIDED)
    return request


def is_seated(storage: Storage, campaign_id: str, account: Account) -> bool:
    """Whether the account has a live seat at the table; the owner's account has one at every table."""
    return account.owner or storage.seats.for_account(account.id, campaign_id) is not None


def ask(
    storage: Storage, campaign: Campaign, account: Account, note: str, now: datetime, role: SeatAsk = "player"
) -> JoinRequest:
    """The account asks to join the table as a `role`, with `note` as the thread's first message (none when it is
    empty). Refused when the account is seated there or has a pending request there (`RequestConflict`), when a
    player's table is full (`seats.TableFull`), or when an observer's takes none (`RequestConflict`). Whether the
    table is public, or the asker came by its link, is the caller's to check."""
    text = _text(note, empty=True)
    if is_seated(storage, campaign.id, account):
        raise RequestConflict(SEATED_ALREADY)
    if role == "observer" and campaign.observers == "nobody":
        raise RequestConflict(NO_OBSERVERS)
    if any(r.status == "pending" for r in storage.join_requests.of_campaign(campaign.id) if r.account_id == account.id):
        raise RequestConflict(ASKED_ALREADY)
    seats.make_room_for(storage, campaign, role)
    messages = (_message("player", account.profile.display_name, text, now),) if text else ()
    try:
        return storage.join_requests.create(campaign.id, account.id, messages, now.isoformat(), role=role)
    except ValueError:  # another request asked meanwhile
        raise RequestConflict(ASKED_ALREADY) from None


def say(storage: Storage, request_id: str, sender: Sender, name: str, text: str, now: datetime) -> JoinRequest:
    """Add a message to a pending request's thread: the player's, or a host's under their seat's name. Refused past
    `MOST_MESSAGES` (`RequestConflict`)."""
    with storage.transaction():
        request = _pending(storage, request_id)
        message = _message(sender, name, _text(text), now)
        if len(request.messages) >= MOST_MESSAGES:
            raise RequestConflict(TALK_AT_THE_TABLE)
        return storage.join_requests.save(replace(request, messages=(*request.messages, message)))


def withdraw(storage: Storage, request_id: str, now: datetime) -> JoinRequest:
    """The account takes its pending request back."""
    with storage.transaction():
        request = _pending(storage, request_id)
        return storage.join_requests.save(replace(request, status="withdrawn", decided_at=now.isoformat()))


def accept(storage: Storage, request_id: str, now: datetime) -> tuple[JoinRequest, Seat, bool]:
    """A host accepts the pending request: the account gets a seat in the role it asked for (a `player`'s or an
    `observer`'s), named as the join link names one (its display name, made unique at the table) in its profile's
    language, and the request is `accepted` with it.
    Answers the request, the seat and whether the seat is new: an account seated meanwhile keeps its seat, full table
    or not. A new player at a full table is refused (`seats.TableFull`), and the request stays pending."""
    with storage.transaction():
        request = _pending(storage, request_id)
        campaign = storage.campaigns.get(request.campaign_id)
        account = storage.accounts.get(request.account_id)
        if campaign is None or account is None:
            raise NotFound(NO_SUCH_REQUEST)
        seat, made = seats.seat_account(storage, campaign, account, request.role)
        accepted = replace(request, status="accepted", decided_at=now.isoformat(), seat_id=seat.id)
        return storage.join_requests.save(accepted), seat, made


def decline(storage: Storage, request_id: str, name: str, reason: str, now: datetime) -> JoinRequest:
    """A host declines the pending request; a reason that isn't empty goes into the thread first, as a host's message
    under `name`, past `MOST_MESSAGES` too: it is the last word."""
    with storage.transaction():
        request = _pending(storage, request_id)
        text = _text(reason, empty=True)
        messages = (*request.messages, _message("host", name, text, now)) if text else request.messages
        declined = replace(request, status="declined", messages=messages, decided_at=now.isoformat())
        return storage.join_requests.save(declined)


def for_host(storage: Storage, campaign_id: str, now: datetime) -> list[JoinRequest]:
    """The table's requests as its hosts read them: the pending ones, oldest first, then those decided in the last
    `RECENT_DAYS` days, the most recently decided first."""
    requests = storage.join_requests.of_campaign(campaign_id)
    since = (now - timedelta(days=RECENT_DAYS)).isoformat()
    pending = [r for r in requests if r.status == "pending"]
    recent = [r for r in requests if r.status != "pending" and r.decided_at is not None and r.decided_at >= since]
    return pending + sorted(recent, key=lambda r: r.decided_at or "", reverse=True)
