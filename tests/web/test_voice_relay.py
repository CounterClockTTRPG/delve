"""The voice relay (table voice and fixes Task V1.2): a hub per campaign on Delve's own port that forwards each
seat's Opus frames to the other seats in voice, prefixed by the sender's slot, and holds nothing after forwarding.
The protocol is pinned in `docs/superpowers/plans/2026-10-25-table-voice-and-fixes.md`.

Every socket here goes through the one `local` client, so they share its event loop as they share uvicorn's; a seat
is told apart by the `delve_seat` cookie its handshake sends, which comes before this machine in the identity chain.
"""

import json
import logging
import struct
from dataclasses import replace

import pytest
from starlette.websockets import WebSocketDisconnect

from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.web import voice
from delve.web.auth import SESSION_COOKIE
from delve.web.routes.voice import disconnect_campaign
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, make_account, session_for

WS_BASE = BASE_URL.replace("http://", "ws://")
PAYLOAD = bytes(range(60)) * 2  # an Opus packet's size at 24 kbit/s and 20 ms


def frame(seq: int = 1, *, speaking: bool = True, payload: bytes = PAYLOAD, version: int = 1) -> bytes:
    """A client's frame: version, flags, sequence number, timestamp, then the Opus packet."""
    return struct.pack(">BBHI", version, 1 if speaking else 0, seq % 65536, (seq * 20) % 2**32) + payload


def make_campaign(storage, name="Tuesday"):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create(name, module.id, revision.number, ruleset="osric", setting="greyhawk")


@pytest.fixture
def campaign(storage):
    return make_campaign(storage)


@pytest.fixture
def sit(storage):
    """`sit(campaign_id, role="player", name="Ana")`: a new seat at that table and the handshake headers that carry
    its token."""

    def make(campaign_id, role="player", name="Ana"):
        token = new_seat_token()
        seat = storage.seats.create(campaign_id, name, "nl", role, token_hash=token_hash(token))
        return seat, {"cookie": f"{SEAT_COOKIE}={token}"}

    return make


def url(campaign_id: str) -> str:
    return f"{WS_BASE}/api/campaigns/{campaign_id}/voice"


def joined(socket, *, muted=False, listening_only=False) -> dict:
    """Read the welcome and send the client's state, as V2 does on join."""
    welcome = socket.receive_json()
    assert welcome["type"] == "welcome"
    socket.send_json({"type": "state", "muted": muted, "listening_only": listening_only})
    return welcome


def until(socket, kind: str) -> dict:
    """The next text message of that type, skipping the others (binary frames included)."""
    while True:
        message = socket.receive()
        if message.get("text") is not None:
            data = json.loads(message["text"])
            if data["type"] == kind:
                return data


def met(socket, count: int = 1) -> list[dict]:
    """The `peer` messages of `count` newcomers: each one's join, then the state it sent on joining."""
    return [until(socket, "peer") for _ in range(2 * count)]


def synced(sender, receiver) -> list[bytes]:
    """The binary frames the receiver got before the sender's next state change reached it: the hub keeps each
    socket's messages in order, so the `peer` message marks the end of what the sender sent before it."""
    sender.send_json({"type": "state", "muted": False, "listening_only": False})
    got = []
    while True:
        message = receiver.receive()
        if message.get("bytes") is not None:
            got.append(message["bytes"])
        elif json.loads(message["text"])["type"] == "peer":
            return got


def refused(local, campaign_id, headers=None) -> int:
    with pytest.raises(WebSocketDisconnect) as closed, local.websocket_connect(url(campaign_id), headers=headers or {}):
        pass
    return closed.value.code


def test_parse_frame():
    parsed = voice.parse_frame(frame(7, payload=b"opus"))
    assert parsed == voice.Frame(version=1, speaking=True, seq=7, ts_ms=140, payload=b"opus")
    assert voice.parse_frame(frame(65543, speaking=False, payload=b"x")).seq == 7
    for bad in (frame(version=2), frame(payload=b""), b"\x01"):
        with pytest.raises(ValueError):
            voice.parse_frame(bad)


def test_two_seats_hear_each_other(local, campaign, sit, storage):
    player, headers = sit(campaign.id, name="Mira")
    owner = seats.owner_seat(storage, campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        welcome = joined(host_socket)
        assert welcome == {
            "type": "welcome",
            "you": owner.id,
            "slot": 0,
            "talk": True,
            "peers": [],
            "limits": {"frame_bytes": 1024, "frames_per_s": 60, "bytes_per_s": 8000},
        }
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            player_welcome = joined(player_socket)
            assert player_welcome["you"] == player.id and player_welcome["slot"] == 1
            assert player_welcome["peers"] == [
                {"seat_id": owner.id, "name": "Host", "slot": 0, "talk": True, "muted": False, "listening_only": False}
            ]
            met(host_socket)
            sent = frame(3)
            player_socket.send_bytes(sent)
            assert synced(player_socket, host_socket) == [bytes([1]) + sent]
            # Never back to the sender: the host's frame reaches the player, and the player's own frame never did.
            host_socket.send_bytes(frame(4))
            assert synced(host_socket, player_socket) == [bytes([0]) + frame(4)]


def test_observer_is_listen_only(local, campaign, sit):
    _, headers = sit(campaign.id, role="observer")
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as observer_socket:
            assert joined(observer_socket)["talk"] is False
            assert [peer["talk"] for peer in met(host_socket)] == [False, False]
            observer_socket.send_bytes(frame())
            assert synced(observer_socket, host_socket) == []
            host_socket.send_bytes(frame(2))
            assert synced(host_socket, observer_socket) == [bytes([0]) + frame(2)]


def test_muted_frames_dropped(local, campaign, sit):
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket, muted=True)
            assert [peer["muted"] for peer in met(host_socket)] == [False, True]
            player_socket.send_bytes(frame())
            player_socket.send_json({"type": "state", "muted": False, "listening_only": True})
            peer = until(host_socket, "peer")
            assert (peer["muted"], peer["listening_only"]) == (False, True)
            player_socket.send_bytes(frame(2))
            assert synced(player_socket, host_socket) == []
            player_socket.send_bytes(frame(3))
            assert synced(player_socket, host_socket) == [bytes([1]) + frame(3)]


def test_voice_off_refuses_join(local, campaign, storage):
    storage.campaigns.set_voice(campaign.id, "off")
    assert refused(local, campaign.id) == 4403


def test_handshake_refusals(lan, local, campaign, storage):
    assert refused(lan, campaign.id) == 4401  # nobody known
    assert refused(local, "cmp_000000000000") == 4404


def test_disconnect_campaign_closes_everyone(app, local, campaign, sit):
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket)
            met(host_socket)
            assert local.portal.call(disconnect_campaign, app, campaign.id) == 2
            for socket in (host_socket, player_socket):
                assert until_closed(socket) == ({"type": "bye", "reason": "off"}, 4000)
    assert voice.hub(app).members(campaign.id) == []


def until_closed(socket) -> tuple[dict | None, int]:
    """The last text message before the server closed the socket, and the close code."""
    last = None
    while True:
        message = socket.receive()
        if message["type"] == "websocket.close":
            return last, message["code"]
        if message.get("text") is not None:
            last = json.loads(message["text"])


def test_left_seat_refused(local, campaign, sit, storage):
    seat, headers = sit(campaign.id)
    seats.leave(storage, seat)
    assert refused(local, campaign.id, headers) == 4403


def test_other_tables_seat_refused(local, campaign, sit, storage):
    other = make_campaign(storage, "Friday")
    _, headers = sit(other.id)
    assert refused(local, campaign.id, headers) == 4403


def test_ninth_socket_is_full(local, campaign, sit):
    headers = [sit(campaign.id, name=f"P{n}")[1] for n in range(9)]
    sockets = [local.websocket_connect(url(campaign.id), headers=h) for h in headers]
    entered = [socket.__enter__() for socket in sockets[:8]]
    try:
        for socket in entered:
            joined(socket)
        ninth = sockets[8].__enter__()
        try:
            assert until_closed(ninth) == ({"type": "bye", "reason": "full"}, 4029)
        finally:
            sockets[8].__exit__(None, None, None)
    finally:
        for socket in reversed(sockets[:8]):
            socket.__exit__(None, None, None)


def test_same_seat_replaces_its_socket(app, local, campaign, sit):
    seat, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as old:
            slot = joined(old)["slot"]
            met(host_socket)
            with local.websocket_connect(url(campaign.id), headers=headers) as new:
                assert joined(new)["slot"] == slot
                assert until_closed(old) == ({"type": "bye", "reason": "replaced"}, 4009)
                assert {peer["seat_id"] for peer in met(host_socket)} == {seat.id}
                new.send_bytes(frame(9))
                assert synced(new, host_socket) == [bytes([slot]) + frame(9)]
                assert [m.seat.id for m in voice.hub(app).members(campaign.id)].count(seat.id) == 1


def test_oversized_frame_dropped(local, campaign, sit):
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket)
            met(host_socket)
            player_socket.send_bytes(frame(payload=bytes(1025 - 8)))
            assert synced(player_socket, host_socket) == []
            player_socket.send_bytes(frame(payload=bytes(1024 - 8)))
            assert len(synced(player_socket, host_socket)) == 1


def test_rate_limited_frames_dropped(app, local, campaign, sit):
    voice.hub(app).clock = lambda: 1000.0  # no refill while the frames come in
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket)
            met(host_socket)
            for seq in range(200):
                player_socket.send_bytes(frame(seq, payload=bytes(40)))
            got = synced(player_socket, host_socket)
            assert 0 < len(got) <= 2 * voice.FRAMES_PER_S


def test_bucket_refills():
    bucket = voice.Bucket(rate=60, burst=120, now=0.0)
    assert sum(bucket.take(1, 0.0) for _ in range(200)) == 120
    assert not bucket.take(1, 0.0)
    assert sum(bucket.take(1, 0.5) for _ in range(200)) == 30


def test_bad_header_closes_4008(local, campaign, sit):
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
        joined(player_socket)
        player_socket.send_bytes(frame(version=2))
        assert until_closed(player_socket)[1] == 4008


@pytest.mark.parametrize("text", ["not json", '{"type": "shout"}', '{"type": "state", "muted": "yes"}', "[]"])
def test_bad_message_closes_4008(local, campaign, text):
    with local.websocket_connect(url(campaign.id)) as socket:
        joined(socket)
        socket.send_text(text)
        assert until_closed(socket)[1] == 4008


def test_ping_is_answered(local, campaign):
    with local.websocket_connect(url(campaign.id)) as socket:
        joined(socket)
        socket.send_json({"type": "ping"})
        assert until(socket, "pong") == {"type": "pong"}


def test_too_many_text_messages_dropped(local, campaign, sit):
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)  # its state message took one of its ten
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket)
            met(host_socket)
            for _ in range(20):
                host_socket.send_json({"type": "ping"})
            host_socket.send_text("x" * 2000)  # over TEXT_BYTES: dropped, not a protocol error
            host_socket.send_bytes(frame())
            while player_socket.receive().get("bytes") is None:  # every message before the frame was read
                pass
            player_socket.send_json({"type": "state", "muted": False, "listening_only": False})
            pongs = 0
            while (message := host_socket.receive_json())["type"] != "peer":
                pongs += message["type"] == "pong"
            assert pongs in (voice.TEXT_PER_S - 1, voice.TEXT_PER_S)


def test_peer_and_left_messages(local, campaign, sit):
    seat, headers = sit(campaign.id, name="Mira")
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket, listening_only=True)
            assert until(host_socket, "peer") == {
                "type": "peer",
                "seat_id": seat.id,
                "name": "Mira",
                "slot": 1,
                "talk": True,
                "muted": False,
                "listening_only": False,
            }
            assert until(host_socket, "peer")["listening_only"] is True
        assert until(host_socket, "left") == {"type": "left", "seat_id": seat.id, "slot": 1}


def test_seat_leaving_the_table_closes_4001(app, local, campaign, sit, storage):
    seat, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
        joined(player_socket)
        seats.leave(storage, seat)
        player_socket.send_json({"type": "ping"})
        assert until_closed(player_socket) == ({"type": "bye", "reason": "left-table"}, 4001)


def test_voice_switched_off_closes_4000_on_the_next_check(app, local, campaign, storage):
    with local.websocket_connect(url(campaign.id)) as socket:
        joined(socket)
        storage.campaigns.set_voice(campaign.id, "off")
        socket.send_json({"type": "ping"})
        assert until_closed(socket) == ({"type": "bye", "reason": "off"}, 4000)


def test_the_timer_checks_too(app, local, campaign, sit, storage):
    voice.hub(app).check_every = 0.05
    seat, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
        joined(player_socket)
        storage.seats.save(replace(storage.seats.get(seat.id), left_at="2026-10-25T00:00:00+00:00"))
        assert until_closed(player_socket) == ({"type": "bye", "reason": "left-table"}, 4001)


def test_nothing_of_audio_is_logged(local, campaign, sit, caplog):
    seat, headers = sit(campaign.id)
    caplog.set_level(logging.DEBUG)
    marker = b"SECRET-OPUS-" * 8
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket)
            met(host_socket)
            for seq in range(3):
                player_socket.send_bytes(frame(seq, payload=marker))
            assert len(synced(player_socket, host_socket)) == 3
        until(host_socket, "left")
    text = caplog.text
    assert "SECRET-OPUS" not in text and marker.hex() not in text and repr(marker)[:20] not in text
    assert f"voice: {seat.id} left {campaign.id} after 3 frames" in text


def test_demoted_seat_stops_talking_at_once(app, local, campaign, sit):
    """The host makes a player an observer: the others hear at once that it can't talk, and its frames are
    dropped, without waiting for the next check (Priya's review)."""
    seat, headers = sit(campaign.id, name="Mira")
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket)
            met(host_socket)
            response = local.put(f"/api/campaigns/{campaign.id}/seats/{seat.id}", json={"role": "observer"})
            assert response.status_code == 200, response.text
            peer = until(host_socket, "peer")
            assert (peer["seat_id"], peer["talk"]) == (seat.id, False)
            player_socket.send_bytes(frame(5))
            assert synced(player_socket, host_socket) == []


def test_role_is_read_again_on_each_check(app, local, campaign, sit, storage):
    """A role changed elsewhere (here in storage) takes effect at the socket's next check: an observer made a player
    talks from then on."""
    seat, headers = sit(campaign.id, role="observer")
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as observer_socket:
            assert joined(observer_socket)["talk"] is False
            met(host_socket)
            storage.seats.save(replace(storage.seats.get(seat.id), role="player"))
            observer_socket.send_json({"type": "ping"})
            peer = until(host_socket, "peer")
            assert (peer["seat_id"], peer["talk"]) == (seat.id, True)
            observer_socket.send_bytes(frame(6))
            assert synced(observer_socket, host_socket) == [bytes([1]) + frame(6)]


def test_leaving_the_table_closes_at_once(app, local, campaign, sit):
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
        joined(player_socket)
        response = local.post(f"/api/campaigns/{campaign.id}/leave", json={}, headers=headers)
        assert response.status_code == 204, response.text
        assert until_closed(player_socket) == ({"type": "bye", "reason": "left-table"}, 4001)


def test_logging_out_closes_that_browsers_voice_at_once(app, local, campaign, storage):
    """An account's browser logs out: its voice socket closes as one that left the table, at once (this browser is
    no longer at it); the account's seat stays."""
    account = make_account(storage, "mira")
    storage.seats.create(campaign.id, "Mira", "nl", "player", account_id=account.id)
    token = session_for(storage, account)
    headers = {"cookie": f"{SESSION_COOKIE}={token}"}
    with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
        joined(player_socket)
        response = local.post("/api/logout", json={}, headers=headers)
        assert response.status_code == 204, response.text
        assert until_closed(player_socket) == ({"type": "bye", "reason": "left-table"}, 4001)


def test_oversized_frame_counts_against_the_budget(app, local, campaign, sit):
    """A frame over `FRAME_BYTES` is dropped and the socket stays open, but its bytes are taken from the sender's
    budget, so a flood of oversized frames can't cost the server more than the budget allows."""
    now = [1000.0]
    voice.hub(app).clock = lambda: now[0]
    _, headers = sit(campaign.id)
    with local.websocket_connect(url(campaign.id)) as host_socket:
        joined(host_socket)
        with local.websocket_connect(url(campaign.id), headers=headers) as player_socket:
            joined(player_socket)
            met(host_socket)
            player_socket.send_bytes(frame(payload=bytes(2 * voice.BYTES_PER_S)))
            player_socket.send_bytes(frame(2))
            assert synced(player_socket, host_socket) == []
            now[0] += 1.0
            player_socket.send_bytes(frame(3))
            assert synced(player_socket, host_socket) == [bytes([1]) + frame(3)]
