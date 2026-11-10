"""Voice at the table (table voice and fixes, workstream V1): the WebSocket relay of a campaign's voice, on Delve's own
port, under the same identity and guard as every route. Nothing of it is stored.

`WS /api/campaigns/{campaign_id}/voice` (table voice and fixes Task V1.2; the protocol is pinned in
`docs/superpowers/plans/2026-10-25-table-voice-and-fixes.md`). The guard has already refused a handshake of a host
Delve doesn't answer to (4421) or from another origin (4403); this route refuses, before `accept`, nobody known (4401),
no such campaign (4404), no live seat at its table (4403) and voice switched off (4403). After it, the socket is a
member of the campaign's `VoiceHub`, checked every `check_every` seconds, on each `ping`, and at once when a route
changes who sits at the table (`table_changed`): a seat's role, a seat leaving, a browser logging out."""

from __future__ import annotations

import asyncio
import json
import logging

from anyio import from_thread
from fastapi import APIRouter, FastAPI, HTTPException, WebSocket

from delve.domain.campaigns import Seat
from delve.web import voice
from delve.web.auth import identify
from delve.web.seats import connection_seat

router = APIRouter()
log = logging.getLogger(__name__)


async def disconnect_campaign(app: FastAPI, campaign_id: str, reason: str = "off") -> int:
    """Close every voice socket of the campaign, telling each why (`bye` with `reason`), and answer how many were
    closed. The campaign page's voice switch calls it when the host switches voice off."""
    return await voice.hub(app).close_campaign(campaign_id, voice.CLOSE_OFF, reason)


def _refusal(websocket: WebSocket, campaign_id: str) -> Seat | int:
    """The caller's seat at the table, or the close code that refuses the handshake."""
    if identify(websocket) is None:
        return 4401
    campaign = websocket.app.state.storage.campaigns.get(campaign_id)
    if campaign is None:
        return 4404
    try:
        seat = connection_seat(websocket, campaign_id)
    except HTTPException as refused:  # 403: a seat of another table, or one that left
        return 4000 + refused.status_code
    if campaign.voice == "off":
        return 4403
    return seat


def _still_allowed(websocket: WebSocket, member: voice.Member) -> tuple[int, str] | Seat:
    """Why the member must go now (a close code and the `bye` reason), or its seat as it is now while the socket's
    caller, identified again as at the handshake, still has it at the table and its campaign's voice is allowed. A
    caller who logged out, or whose seat is another one now, has left the table as far as this socket goes."""
    storage = websocket.app.state.storage
    campaign = storage.campaigns.get(member.campaign_id)
    if campaign is None or campaign.voice == "off":
        return voice.CLOSE_OFF, "off"
    try:
        seat = connection_seat(websocket, member.campaign_id)
    except HTTPException:
        return voice.CLOSE_LEFT_TABLE, "left-table"
    if seat.id != member.seat.id or seat.left_at is not None:
        return voice.CLOSE_LEFT_TABLE, "left-table"
    return seat


def _check(websocket: WebSocket, member: voice.Member) -> None:
    found = _still_allowed(websocket, member)
    if isinstance(found, tuple):
        member.close(*found)
    else:
        voice.hub(websocket.app).set_talk(member, found.role != "observer")


def recheck(app: FastAPI, campaign_id: str | None = None) -> None:
    """Check every voice socket of the campaign (without one, of every campaign) now, on the event loop."""
    for member in voice.hub(app).members(campaign_id):
        if not member.closing:
            _check(member.socket, member)  # the hub's sockets are this route's WebSockets


def table_changed(app: FastAPI, campaign_id: str | None = None) -> None:
    """After a change to who sits at a table (a seat's role, a seat leaving, a browser logging out): check the voice
    sockets of the campaign (or of every campaign) at once, rather than at their next check. From a sync route's
    worker thread it runs on the event loop and waits for it; on the loop, it runs there and then."""
    if getattr(app.state, "voice", None) is None:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        from_thread.run_sync(recheck, app, campaign_id)
    else:
        recheck(app, campaign_id)


async def _watch(websocket: WebSocket, hub: voice.VoiceHub, member: voice.Member) -> None:
    while not member.closing:
        await asyncio.sleep(hub.check_every)
        _check(websocket, member)


def _text(websocket: WebSocket, hub: voice.VoiceHub, member: voice.Member, data: str) -> dict | None:
    """The client's message, or None to drop it (over its size or rate); `ValueError` for one the protocol doesn't
    know."""
    if not hub.text_allowed(member, data):
        return None
    message = json.loads(data)  # a JSONDecodeError is a ValueError
    if not isinstance(message, dict):
        raise ValueError("a voice message is a JSON object")  # noqa: TRY004 (a protocol error, closed with 4008)
    return message


@router.websocket("/api/campaigns/{campaign_id}/voice")
async def voice_socket(websocket: WebSocket, campaign_id: str) -> None:
    found = _refusal(websocket, campaign_id)
    if isinstance(found, int):
        await websocket.close(found)
        return
    await websocket.accept()
    hub = voice.hub(websocket.app)
    try:
        member = await hub.join(campaign_id, found, websocket)
    except voice.Full:
        await websocket.send_text(json.dumps({"type": "bye", "reason": "full"}))
        await websocket.close(voice.CLOSE_FULL)
        return
    watcher = asyncio.create_task(_watch(websocket, hub, member))
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if member.closing:
                continue  # the close is on its way; what the client still sends is moot
            try:
                if message.get("bytes") is not None:
                    await hub.relay(member, message["bytes"])
                elif message.get("text") is not None:
                    await _handle(websocket, hub, member, message["text"])
            except ValueError as bad:
                log.info("voice: %s broke the protocol in %s: %s", found.id, campaign_id, bad)
                member.close(voice.CLOSE_PROTOCOL)
            if member.closing:
                await member.sent()
                break
    finally:
        watcher.cancel()
        await hub.leave(member)


async def _handle(websocket: WebSocket, hub: voice.VoiceHub, member: voice.Member, data: str) -> None:
    message = _text(websocket, hub, member, data)
    if message is None:
        return
    kind = message.get("type")
    if kind == "ping":
        member.send_json({"type": "pong"})
        _check(websocket, member)
    elif kind == "state":
        muted, listening_only = message.get("muted"), message.get("listening_only")
        if not isinstance(muted, bool) or not isinstance(listening_only, bool):
            raise ValueError("a state message has a muted and a listening_only, each true or false")
        await hub.set_state(member, muted, listening_only)
    else:
        raise ValueError(f"no voice message of type {kind!r}")
