"""The event stream: what changed, in order, to every browser that may see it, with replay after a reconnect.

Who gets an event is decided here, per listener (plan 4 Task 3, spec §7.5). An event has a scope:
- `organisers` (modules, conversions, Preferences, house rules) goes to the organisers only;
- `table` (beats, the story, fights, characters, map states) goes to the seats of its campaign that may see its
  audience (`delve.play.audience.can_see`), and to the organisers who aren't seated at that table. The table
  publishes an entry with its stored audience, already resolved to seats (`delve.play.audience.resolve`). The owner is
  seated at every table, as their owner seat: their play screen is a seat's view too. An entry for some roles only
  (a tool row: `delve.play.audience.roles_for`) is published with those `roles`, and goes only to seats of them.
- `board` (the message board, DEL-297) names its zone, and goes to whoever may read that zone as the board's rights
  say (`delve.play.board_rights.rights`), asked as each event is delivered: a member taken out of a zone hears nothing
  more of it. A seat token without an account reads as a visitor (or an organiser, while its seat holds the role). The
  event of a zone that is gone (deleted) goes to the organisers only. Without tables, nobody hears it.
A translation (plan 4 Task 7) also names its language: it goes only to the seats of that language that may see its
audience, never to an organiser who isn't seated there.
The replay buffer keeps each event's scope, campaign, zone, audience and language, and replays to a listener only what it
may see.

An account (players and tavern Task C3) listens at one table: the one its `?campaign=` names, where it has a live
seat. It gets that table's events as its seat would, `organisers` events while the account is an organiser, `board` events
of the zones it may read, and no other table's, ever. It gets nothing once its login session has ended or its account is disabled. An owner account
listens as the owner does.

The bus also knows who is at a table (plan 4 Task 4): a seat is present while its browser listens, or did in the last
`PRESENCE_GRACE_S` seconds, so a reload or a short loss of signal doesn't count as going away. The owner is present at
every table, as their owner seat, while they listen. A change publishes `seats` to the table, and calls `on_presence`
with the campaign (None for the owner's), so that an open beat no longer waits for a seat that went away.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import Counter, deque
from collections.abc import AsyncIterator, Callable, Hashable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, Header, Query, Request
from starlette.responses import StreamingResponse

from delve.domain.accounts import Account
from delve.domain.campaigns import Seat
from delve.play.audience import Audience, can_see, seat_controls
from delve.play.board_rights import caller_of, rights
from delve.play.clock import Clock, SystemClock
from delve.storage import Storage
from delve.web.auth import Principal, current_principal

BUFFER_SIZE = 500
MAX_BEHIND = 1000
PING_SECONDS = 20
PRESENCE_GRACE_S = 30
OWNER = "owner"  # the presence key of the owner's listeners


Scope = Literal["organisers", "table", "board"]
SCOPES = ("organisers", "table", "board")


@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    data: dict
    scope: Scope = "organisers"
    campaign_id: str | None = None
    audience: Audience = None
    language: str | None = None
    roles: tuple[str, ...] | None = None
    zone_id: str | None = None


@dataclass(frozen=True)
class Viewer:
    """Who listens: the principal, and the seat it listens as (None for the owner, and for an account listening at no
    table). `login_hash` is an account's login session, which must stay alive for it to hear anything."""

    principal: Principal
    seat: Seat | None = None
    login_hash: str | None = None

    @classmethod
    def of(cls, principal: Principal, seat: Seat | None = None) -> Viewer:
        return cls(principal, seat or principal.seat, principal.login_hash)

    @property
    def account(self) -> Account | None:
        """The account listening, unless it listens as the owner."""
        account = self.principal.account
        return None if account is None or account.owner else account


def viewer_of(storage: Storage, principal: Principal, campaign_id: str | None) -> Viewer:
    """The viewer for a stream: an account's seat is its live seat at `campaign_id` (none without one)."""
    account = principal.account
    if account is not None and not account.owner:
        seat = storage.seats.for_account(account.id, campaign_id) if campaign_id is not None else None
        return Viewer(principal, seat, principal.login_hash)
    return Viewer.of(principal)


OWNER_VIEWER = Viewer(Principal(id="owner", roles=frozenset({"organiser"})))


class Tables(Protocol):
    """What the bus asks about the tables, as they are when an event is delivered."""

    def current(self, seat: Seat) -> Seat:
        """The seat as it is now: one that has left, or lost the organiser role, gets nothing more."""
        ...

    def owner_seat(self, campaign_id: str) -> Seat | None:
        """The owner's seat at that campaign's table."""
        ...

    def controls(self, seat: Seat) -> set[str]:
        """The characters the seat plays, for an audience of characters."""
        ...

    def account(self, account_id: str) -> Account | None:
        """The account as it is now."""
        ...

    def login_alive(self, token_hash: str) -> bool:
        """Whether the login session is still alive."""
        ...

    def may_read_zone(self, principal: Principal, zone_id: str) -> bool:
        """Whether the principal may read the board zone; a zone that is gone, for the organisers only."""
        ...


class StoredTables:
    """The tables in storage."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def current(self, seat: Seat) -> Seat:
        # A seat that is gone counts as having left.
        return self._storage.seats.get(seat.id) or replace(seat, left_at=seat.left_at or "gone")

    def owner_seat(self, campaign_id: str) -> Seat | None:
        seat = self._storage.seats.owner_seat(campaign_id)
        # The owner is never off their own table: their seat is taken back as soon as they come to it.
        return None if seat is None else replace(seat, left_at=None)

    def controls(self, seat: Seat) -> set[str]:
        return seat_controls(self._storage, seat)

    def account(self, account_id: str) -> Account | None:
        return self._storage.accounts.get(account_id)

    def login_alive(self, token_hash: str) -> bool:
        return self._storage.login_sessions.by_token_hash(token_hash) is not None

    def may_read_zone(self, principal: Principal, zone_id: str) -> bool:
        caller = caller_of(principal.account, "organiser" in principal.roles, principal.owner)
        zone = self._storage.board.get_zone(zone_id)
        if zone is None:
            return caller.organiser or caller.owner
        return rights(self._storage, caller, zone).read


class _Answers:
    """The tables as one batch of events sees them (DEL-172): each question asked once, however many events and
    listeners ask it. A replay of 500 events to one account asked 1,504 queries; now a handful. The answers are those of
    one moment, as the bus decides a batch at once on the event loop."""

    def __init__(self, tables: Tables) -> None:
        self._tables = tables
        self._answers: dict[tuple[str, Hashable], object] = {}

    def _ask(self, question: str, about: Hashable, answer: Callable[[], object]) -> object:
        key = (question, about)
        if key not in self._answers:
            self._answers[key] = answer()
        return self._answers[key]

    def current(self, seat: Seat) -> Seat:
        return self._ask("current", seat, lambda: self._tables.current(seat))  # type: ignore[return-value]

    def owner_seat(self, campaign_id: str) -> Seat | None:
        return self._ask("owner_seat", campaign_id, lambda: self._tables.owner_seat(campaign_id))  # type: ignore[return-value]

    def controls(self, seat: Seat) -> set[str]:
        return self._ask("controls", seat, lambda: self._tables.controls(seat))  # type: ignore[return-value]

    def account(self, account_id: str) -> Account | None:
        return self._ask("account", account_id, lambda: self._tables.account(account_id))  # type: ignore[return-value]

    def login_alive(self, token_hash: str) -> bool:
        return self._ask("login_alive", token_hash, lambda: self._tables.login_alive(token_hash))  # type: ignore[return-value]

    def may_read_zone(self, principal: Principal, zone_id: str) -> bool:
        return self._ask(  # type: ignore[return-value]
            "may_read_zone", (principal, zone_id), lambda: self._tables.may_read_zone(principal, zone_id)
        )


@dataclass(eq=False)
class _Subscriber:
    viewer: Viewer = OWNER_VIEWER
    pending: deque[Event] = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    dropped: bool = False


class EventBus:
    """Numbers each event, keeps the last `BUFFER_SIZE` for replay, and hands each event to the subscribers that may
    see it.

    A subscriber more than `MAX_BEHIND` events behind is dropped: its stream ends, and the browser reconnects with the
    last id it saw. Without `tables` (the app gives it `StoredTables`), the owner has no seat and sees every `table`
    event, as an organiser seated elsewhere.

    `publish` may be called from any thread (DEL-166): a sync route runs in the threadpool. It numbers the event at
    once, under a lock, and puts it in an outbox; the outbox is handed on in order on the event loop (`bind`), where
    the buffer, the subscribers and presence live. Called on the loop, it hands the outbox on before it returns; from
    another thread, it asks the loop to, and when no loop runs, it does so itself.
    """

    def __init__(self, tables: Tables | None = None, clock: Clock | None = None) -> None:
        self._seq = 0
        self._lock = threading.Lock()
        """Guards `_seq` and `_outbox`, which `publish` touches from any thread."""
        self._outbox: deque[Event] = deque()
        """Numbered events not yet in the buffer, in order."""
        self._handing_on = threading.RLock()
        """One hand-on at a time, so the buffer and the subscribers get the events in order."""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._buffer: deque[Event] = deque(maxlen=BUFFER_SIZE)
        self._subscribers: set[_Subscriber] = set()
        self._tables = tables
        self._clock = clock or SystemClock()
        self._listening: Counter[str] = Counter()
        self._last_seen: dict[str, datetime] = {}
        self._campaign_of: dict[str, str | None] = {}
        self._expiry: dict[str, asyncio.Task] = {}
        self.on_presence: Callable[[str | None], None] = lambda campaign_id: None

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        """The event loop the subscribers listen on; the app binds its own as it starts. A publish on a running loop
        binds that one too."""
        self._loop = loop

    # ----- presence -----

    def present(self, campaign_id: str) -> set[str]:
        """The seats of the campaign that are at the table now: listening, or within the grace after they stopped."""
        here = {key for key in self._campaign_of if self._campaign_of[key] == campaign_id and self._is_present(key)}
        if self._is_present(OWNER) and self._tables is not None:
            owner = self._tables.owner_seat(campaign_id)
            if owner is not None:
                here.add(owner.id)
        return here

    def _is_present(self, key: str) -> bool:
        if self._listening[key] > 0:
            return True
        seen = self._last_seen.get(key)
        return seen is not None and self._clock.now() - seen < timedelta(seconds=PRESENCE_GRACE_S)

    def _arrive(self, viewer: Viewer) -> str | None:
        if viewer.seat is None and viewer.account is not None:
            return None  # an account listening at no table is at none
        key = OWNER if viewer.seat is None else viewer.seat.id
        was = self._is_present(key)
        self._campaign_of[key] = None if viewer.seat is None else viewer.seat.campaign_id
        self._listening[key] += 1
        if not was:
            self._presence_changed(key)
        return key

    def _depart(self, key: str | None) -> None:
        if key is None:
            return
        self._listening[key] -= 1
        if self._listening[key] > 0:
            return
        self._last_seen[key] = self._clock.now()
        old = self._expiry.pop(key, None)
        if old is not None:
            old.cancel()
        try:
            self._expiry[key] = asyncio.get_running_loop().create_task(self._expire(key))
        except RuntimeError:  # the loop is closing: nobody is left to tell
            return

    async def _expire(self, key: str) -> None:
        """Tell the table once the grace after the seat's last listener has passed, unless it came back."""
        until = self._last_seen[key] + timedelta(seconds=PRESENCE_GRACE_S)
        await self._clock.sleep((until - self._clock.now()).total_seconds())
        if self._expiry.get(key) is asyncio.current_task():
            del self._expiry[key]
        if not self._is_present(key):
            self._presence_changed(key)

    def _presence_changed(self, key: str) -> None:
        campaign_id = self._campaign_of.get(key)
        if campaign_id is not None:
            self.publish("seats", {"campaign_id": campaign_id}, scope="table", campaign_id=campaign_id)
        self.on_presence(campaign_id)

    # ----- events -----

    def publish(
        self,
        type: str,
        data: dict,
        *,
        scope: Scope = "organisers",
        campaign_id: str | None = None,
        audience: Audience = None,
        language: str | None = None,
        roles: tuple[str, ...] | None = None,
        zone_id: str | None = None,
    ) -> int:
        """Put an event on the stream; its seq. A `table` event names its campaign; with a `language`, it goes to the
        seats of that language only, and with `roles`, to the seats of those roles only. A `board` event names its
        zone."""
        if scope not in SCOPES:
            raise ValueError(f"an event's scope is one of {', '.join(SCOPES)}, not {scope!r}")
        if scope == "table" and campaign_id is None:
            raise ValueError("a table event names its campaign")
        if scope == "board" and zone_id is None:
            raise ValueError("a board event names its zone")
        with self._lock:
            self._seq += 1
            event = Event(self._seq, type, data, scope, campaign_id, audience, language, roles, zone_id)
            self._outbox.append(event)
        try:
            running: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            self._loop = running
            self._hand_on()
            return event.seq
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._hand_on)
                return event.seq
            except RuntimeError:  # the loop closed meanwhile
                pass
        self._hand_on()
        return event.seq

    def _hand_on(self) -> None:
        """Put the outbox's events in the buffer and hand each to the subscribers that may see it, in order; the tables
        are asked once for the whole batch (`_Answers`, DEL-172)."""
        with self._handing_on:
            with self._lock:
                batch = list(self._outbox)
                self._outbox.clear()
            if not batch:
                return
            tables = self._answers()
            for event in batch:
                self._buffer.append(event)
                for subscriber in list(self._subscribers):
                    if not self.may_see(subscriber.viewer, event, tables):
                        continue
                    subscriber.pending.append(event)
                    if len(subscriber.pending) > MAX_BEHIND:
                        subscriber.dropped = True
                        subscriber.pending.clear()
                        self._subscribers.discard(subscriber)
                    subscriber.wake.set()

    def _answers(self) -> Tables | None:
        return None if self._tables is None else _Answers(self._tables)

    def close(self) -> None:
        """End every stream, as the server shuts down: each browser reconnects, to the server that comes next, with the
        last id it saw. A stream open while the server waits for its connections would keep it from stopping."""
        for subscriber in list(self._subscribers):
            subscriber.dropped = True
            subscriber.pending.clear()
            subscriber.wake.set()
        self._subscribers.clear()

    def may_see(self, viewer: Viewer, event: Event, tables: Tables | None = None) -> bool:
        """Whether the event goes to `viewer`; when in doubt, it doesn't. `tables` answers for the bus's own tables
        within a batch (`_Answers`)."""
        tables = tables if tables is not None else self._tables
        if viewer.principal.account is not None:
            if tables is None or viewer.login_hash is None or not tables.login_alive(viewer.login_hash):
                return False
            account = tables.account(viewer.principal.account.id)
            if account is None or account.disabled_at is not None:
                return False
            if not account.owner:
                return self._account_may_see(viewer, account, event, tables)
        seat = viewer.seat
        if seat is not None and tables is not None:
            seat = tables.current(seat)
        organiser = "organiser" in viewer.principal.roles and (
            seat is None or (seat.organiser and seat.left_at is None)
        )
        if event.scope == "organisers":
            return organiser
        if event.scope == "board":
            # The seat's organiser role as it is now; a seat token's own account doesn't come with it.
            principal = replace(viewer.principal, roles=frozenset({"organiser"}) if organiser else frozenset())
            return tables is not None and event.zone_id is not None and tables.may_read_zone(principal, event.zone_id)
        if event.scope != "table" or event.campaign_id is None:
            return False
        if seat is not None:  # a seat token: its own table only
            at = seat if seat.campaign_id == event.campaign_id else None
        elif not viewer.principal.owner:
            return False
        elif event.audience is None and event.language is None and event.roles is None:
            return True  # the owner, seated at every table
        else:
            at = tables.owner_seat(event.campaign_id) if tables is not None else None
        if event.language is not None and (at is None or at.language != event.language):
            return False
        if at is None:
            return organiser
        controls = tables.controls(at) if tables is not None and _of_characters(event) else set()
        return can_see(at, event.audience, controls, event.roles)

    def _account_may_see(self, viewer: Viewer, account: Account, event: Event, tables: Tables) -> bool:
        """An account's: `organisers` events while it is an organiser, `board` events of the zones it may read, and its
        own table's as its seat there. Its rights are the account's as it is now."""
        if event.scope == "organisers":
            return account.organiser
        if event.scope == "board":
            roles = frozenset({"organiser"}) if account.organiser else frozenset()
            principal = replace(viewer.principal, account=account, roles=roles)
            return event.zone_id is not None and tables.may_read_zone(principal, event.zone_id)
        if event.scope != "table" or viewer.seat is None:
            return False
        seat = tables.current(viewer.seat)
        if seat.left_at is not None or seat.account_id != account.id or seat.campaign_id != event.campaign_id:
            return False
        if event.language is not None and seat.language != event.language:
            return False
        controls = tables.controls(seat) if _of_characters(event) else set()
        return can_see(seat, event.audience, controls, event.roles)

    async def subscribe(self, since: int | None, viewer: Viewer = OWNER_VIEWER) -> AsyncIterator[Event]:
        """The buffered events after `since` that `viewer` may see, then the live ones it may see. With `since`
        None, only live ones.

        A `since` beyond the newest event comes from before a restart, when numbering began again: the whole buffer
        is replayed.
        """
        self._loop = asyncio.get_running_loop()
        self._hand_on()
        subscriber = _Subscriber(viewer)
        if since is not None:
            after = since if since <= self._seq else 0
            tables = self._answers()
            subscriber.pending.extend(e for e in self._buffer if e.seq > after and self.may_see(viewer, e, tables))
        self._subscribers.add(subscriber)
        presence = self._arrive(viewer)
        try:
            while True:
                while subscriber.pending:
                    yield subscriber.pending.popleft()
                if subscriber.dropped:
                    return
                subscriber.wake.clear()
                await subscriber.wake.wait()
        finally:
            self._subscribers.discard(subscriber)
            self._depart(presence)


def _of_characters(event: Event) -> bool:
    return isinstance(event.audience, dict) and "characters" in event.audience


def sse_frame(event: Event) -> str:
    return f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(event.data)}\n\n"


router = APIRouter()


@router.get("/api/events")
async def events(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    since: Annotated[int | None, Query()] = None,
    last_event_id: Annotated[int | None, Header()] = None,
    campaign: Annotated[str | None, Query(max_length=64)] = None,
) -> StreamingResponse:
    """The stream; an account names the table it listens at with `campaign`."""
    bus: EventBus = request.app.state.events
    start = last_event_id if last_event_id is not None else since
    viewer = viewer_of(request.app.state.storage, principal, campaign)
    return StreamingResponse(
        _stream(bus.subscribe(start, viewer)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(events: AsyncIterator[Event]) -> AsyncIterator[str]:
    """SSE frames for `events`, and a ping comment whenever it has been quiet for `PING_SECONDS`."""
    next_event = asyncio.ensure_future(anext(events))
    try:
        while True:
            done, _ = await asyncio.wait({next_event}, timeout=PING_SECONDS)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                event = next_event.result()
            except StopAsyncIteration:
                return
            yield sse_frame(event)
            next_event = asyncio.ensure_future(anext(events))
    finally:
        next_event.cancel()
        await asyncio.gather(next_event, return_exceptions=True)
        await events.aclose()
