"""The voice relay's hub (table voice and fixes Task V1.2): one set of members per campaign, in the server process.
Each member is one seat's socket; its binary frames go to every other member, prefixed by its slot, and nothing of
them is kept after forwarding. The protocol is pinned in `docs/superpowers/plans/2026-10-25-table-voice-and-fixes.md`.

Every change to a campaign's members happens in code without an `await`, so it is atomic on the event loop: two
joins, a leave and a relay can't interleave inside one. Each member sends from its own task, through a bounded outbox
that drops its oldest audio when a slow listener falls behind, so one slow member never holds up the others. Joins,
leaves and, at leave, a socket's frame and byte counts are logged; never a frame's bytes."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from delve.domain.campaigns import Seat

log = logging.getLogger(__name__)

VOICE_CAP = 8
"""Sockets in one campaign's voice; one more is closed with 4029."""
FRAME_BYTES = 1024
FRAMES_PER_S = 60
BYTES_PER_S = 8000
"""A socket's audio budget: a token bucket of 60 frames and 8000 bytes a second, with bursts of twice that."""
TEXT_BYTES = 1024
TEXT_PER_S = 10
"""A socket's text messages: at most 1024 bytes each and 10 a second (no burst beyond that); the rest are dropped."""
OUTBOX_FRAMES = 50
"""The audio frames waiting for one listener; past it the oldest is dropped."""
CHECK_EVERY = 20.0
"""Seconds between a socket's checks that its seat is still at the table and the campaign's voice still allowed."""
HEADER = struct.Struct(">BBHI")
VERSION = 1
SLOTS = 256

CLOSE_OFF = 4000
CLOSE_LEFT_TABLE = 4001
CLOSE_PROTOCOL = 4008
CLOSE_REPLACED = 4009
CLOSE_FULL = 4029


@dataclass(frozen=True)
class Frame:
    """A client's binary frame: the 8-byte header's fields and the Opus packet."""

    version: int
    speaking: bool
    seq: int
    ts_ms: int
    payload: bytes


def parse_frame(data: bytes) -> Frame:
    """The frame in `data`; `ValueError` for a bad header (a version other than 1, or under 9 bytes)."""
    if len(data) <= HEADER.size:
        raise ValueError(f"a voice frame is a {HEADER.size}-byte header and a packet; this one is {len(data)} bytes")
    version, flags, seq, ts_ms = HEADER.unpack_from(data)
    if version != VERSION:
        raise ValueError(f"voice frame version {version}; this server speaks {VERSION}")
    return Frame(version, bool(flags & 1), seq, ts_ms, bytes(data[HEADER.size :]))


class Bucket:
    """A token bucket: `rate` a second, holding at most `burst`."""

    def __init__(self, rate: float, burst: float, now: float) -> None:
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.at = now

    def refill(self, now: float) -> None:
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now

    def take(self, amount: float, now: float) -> bool:
        self.refill(now)
        if self.tokens < amount:
            return False
        self.tokens -= amount
        return True


class Socket(Protocol):
    """What the hub needs of a WebSocket."""

    async def send_bytes(self, data: bytes) -> None: ...

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class Full(Exception):
    """The campaign's voice already has `VOICE_CAP` sockets."""


class Outbox:
    """A member's messages waiting to be sent, in order: text and a close are never dropped; past `OUTBOX_FRAMES` the
    oldest audio frame is."""

    def __init__(self, limit: int = OUTBOX_FRAMES) -> None:
        self.limit = limit
        self.items: deque[tuple[str, Any]] = deque()
        self.audio = 0
        self.ready = asyncio.Event()
        self.closing = False
        self.stopped = False

    def put(self, kind: str, value: Any) -> None:
        if self.closing or self.stopped:
            return
        if kind == "bytes":
            if self.audio >= self.limit:
                self._drop_oldest_audio()
            self.audio += 1
        elif kind == "close":
            self.closing = True
        self.items.append((kind, value))
        self.ready.set()

    def _drop_oldest_audio(self) -> None:
        for index, (kind, _) in enumerate(self.items):
            if kind == "bytes":
                del self.items[index]
                self.audio -= 1
                return

    def stop(self) -> None:
        """Send nothing more: the socket is gone."""
        self.stopped = True
        self.items.clear()
        self.audio = 0
        self.ready.set()


@dataclass(eq=False)
class Member:
    """One socket in a campaign's voice: its seat, its slot (the byte its frames are prefixed with) and its state."""

    campaign_id: str
    seat: Seat
    socket: Socket
    slot: int
    talk: bool
    muted: bool = False
    listening_only: bool = False
    frames: int = 0
    bytes: int = 0
    audio: Bucket | None = None
    audio_bytes: Bucket | None = None
    text: Bucket | None = None
    outbox: Outbox = field(default_factory=Outbox)
    sender: asyncio.Task[None] | None = None

    def peer(self) -> dict[str, Any]:
        return {
            "seat_id": self.seat.id,
            "name": self.seat.name,
            "slot": self.slot,
            "talk": self.talk,
            "muted": self.muted,
            "listening_only": self.listening_only,
        }

    @property
    def closing(self) -> bool:
        return self.outbox.closing

    def send_json(self, message: dict[str, Any]) -> None:
        self.outbox.put("text", json.dumps(message))

    def close(self, code: int, reason: str | None = None) -> None:
        """Say `bye` with `reason` (when there is one), then close with `code`, after what is already queued."""
        if reason is not None:
            self.send_json({"type": "bye", "reason": reason})
        self.outbox.put("close", code)

    async def sent(self, timeout: float = 5.0) -> None:
        """Wait until the sender has sent what was queued (a close included), at most `timeout` seconds."""
        if self.sender is not None and not self.sender.done():
            await asyncio.wait([self.sender], timeout=timeout)

    async def _send_all(self) -> None:
        box = self.outbox
        try:
            while not box.stopped:
                await box.ready.wait()
                while box.items:
                    kind, value = box.items.popleft()
                    if kind == "bytes":
                        box.audio -= 1
                        await self.socket.send_bytes(value)
                    elif kind == "text":
                        await self.socket.send_text(value)
                    else:
                        await self.socket.close(value)
                        return
                box.ready.clear()
        except Exception as error:  # noqa: BLE001 (the socket went away under us: the route's leave follows)
            log.debug("voice: sending to %s stopped: %s", self.seat.id, type(error).__name__)


class VoiceHub:
    """The members of each campaign's voice."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.check_every = CHECK_EVERY
        self._members: dict[str, list[Member]] = {}

    def members(self, campaign_id: str | None = None) -> list[Member]:
        """The members of the campaign's voice; without one, of every campaign's."""
        if campaign_id is None:
            return [m for current in self._members.values() for m in current]
        return list(self._members.get(campaign_id, []))

    async def join(self, campaign_id: str, seat: Seat, socket: Socket) -> Member:
        """Add the seat's socket, replacing its older one (closed with 4009), and send it the `welcome`; the others get
        a `peer`. `Full` when the campaign already has `VOICE_CAP` sockets."""
        current = self._members.setdefault(campaign_id, [])
        older = next((m for m in current if m.seat.id == seat.id), None)
        if older is None and len(current) >= VOICE_CAP:
            raise Full
        if older is not None:
            current.remove(older)
            older.close(CLOSE_REPLACED, "replaced")
            slot = older.slot
        else:
            taken = {m.slot for m in current}
            slot = next(n for n in range(SLOTS) if n not in taken)
        now = self.clock()
        member = Member(
            campaign_id,
            seat,
            socket,
            slot,
            talk=seat.role != "observer",
            audio=Bucket(FRAMES_PER_S, 2 * FRAMES_PER_S, now),
            audio_bytes=Bucket(BYTES_PER_S, 2 * BYTES_PER_S, now),
            text=Bucket(TEXT_PER_S, TEXT_PER_S, now),
        )
        member.send_json(
            {
                "type": "welcome",
                "you": seat.id,
                "slot": slot,
                "talk": member.talk,
                "peers": [m.peer() for m in current],
                "limits": {"frame_bytes": FRAME_BYTES, "frames_per_s": FRAMES_PER_S, "bytes_per_s": BYTES_PER_S},
            }
        )
        for other in current:
            other.send_json({"type": "peer", **member.peer()})
        current.append(member)
        member.sender = asyncio.create_task(member._send_all(), name=f"voice {seat.id}")
        log.info("voice: %s joined %s (slot %d)", seat.id, campaign_id, slot)
        return member

    async def leave(self, member: Member) -> None:
        """Take the member out (the others get `left`, unless a newer socket of its seat replaced it or its campaign's
        voice was closed) and stop its sender. Holds no `await`, so it completes in a cancelled task too."""
        current = self._members.get(member.campaign_id, [])
        if member in current:
            current.remove(member)
            for other in current:
                other.send_json({"type": "left", "seat_id": member.seat.id, "slot": member.slot})
        if not current:
            self._members.pop(member.campaign_id, None)
        if not member.closing:
            member.outbox.stop()
        elif member.sender is not None and not member.sender.done():
            # Its close is queued; give the sender a moment to send it, then nothing more.
            asyncio.get_running_loop().call_later(5.0, member.outbox.stop)
        log.info(
            "voice: %s left %s after %d frames (%d bytes)",
            member.seat.id,
            member.campaign_id,
            member.frames,
            member.bytes,
        )

    async def relay(self, member: Member, data: bytes) -> int:
        """Forward the member's frame to every other member, prefixed by its slot, and answer how many it was sent to.
        Dropped (0) when it is over `FRAME_BYTES`, from a member that may not talk, is muted or listens only, or over
        the rate budget. A frame over `FRAME_BYTES` still costs its bytes, so a flood of them is held to the budget
        too; the socket stays open. `ValueError` for a bad header."""
        now = self.clock()
        assert member.audio is not None and member.audio_bytes is not None
        member.audio.refill(now)
        member.audio_bytes.refill(now)
        if len(data) > FRAME_BYTES:
            member.audio.tokens = max(0.0, member.audio.tokens - 1)
            member.audio_bytes.tokens = max(0.0, member.audio_bytes.tokens - len(data))
            return 0
        parse_frame(data)
        if not member.talk or member.muted or member.listening_only or member.closing:
            return 0
        if member.audio.tokens < 1 or member.audio_bytes.tokens < len(data):
            return 0
        member.audio.tokens -= 1
        member.audio_bytes.tokens -= len(data)
        member.frames += 1
        member.bytes += len(data)
        out = bytes([member.slot]) + data
        others = [m for m in self._members.get(member.campaign_id, []) if m is not member]
        for other in others:
            other.outbox.put("bytes", out)
        return len(others)

    def text_allowed(self, member: Member, data: str) -> bool:
        """Whether a text message is within `TEXT_BYTES` and the member's ten a second."""
        assert member.text is not None
        return len(data.encode()) <= TEXT_BYTES and member.text.take(1, self.clock())

    async def set_state(self, member: Member, muted: bool, listening_only: bool) -> None:
        """The member's microphone state; the others get a `peer`."""
        member.muted = muted
        member.listening_only = listening_only
        for other in self._members.get(member.campaign_id, []):
            if other is not member:
                other.send_json({"type": "peer", **member.peer()})

    def set_talk(self, member: Member, talk: bool) -> None:
        """Whether the member may talk, as its seat's role says now (an observer may not); on a change the others get a
        `peer`. Holds no `await`."""
        if member.talk == talk:
            return
        member.talk = talk
        for other in self._members.get(member.campaign_id, []):
            if other is not member:
                other.send_json({"type": "peer", **member.peer()})
        log.info("voice: %s in %s may %s", member.seat.id, member.campaign_id, "talk" if talk else "only listen")

    async def close_campaign(self, campaign_id: str, code: int, reason: str) -> int:
        """Close every socket of the campaign's voice with `code`, after a `bye` with `reason`; answer how many."""
        closing = self._members.pop(campaign_id, [])
        for member in closing:
            member.close(code, reason)
        if closing:
            log.info("voice: closed %d sockets of %s (%s)", len(closing), campaign_id, reason)
        return len(closing)


def hub(app: Any) -> VoiceHub:
    """The app's voice hub, made on first use."""
    found = getattr(app.state, "voice", None)
    if found is None:
        found = app.state.voice = VoiceHub()
    return found
