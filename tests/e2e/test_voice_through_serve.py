"""Voice through `delve serve` (table voice and fixes Task V1.3): the relay on Delve's own port and process, over real
sockets with the `websockets` client that `uvicorn[standard]` installs. Two seats join, one frame is relayed, and a
handshake from another origin is refused before the app accepts it."""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import time

import httpx
import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from delve.config import Config
from delve.modules.dscn import Bundle
from delve.storage import open_storage
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures import SAMPLES
from tests.fixtures.rulesets import install_test_packs

FORBIDDEN_PORTS = {5000, 7777, 7790, 7810, 8000}
CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


def free_port() -> int:
    """A free high port on loopback, never one of the owner's."""
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in FORBIDDEN_PORTS and port > 10000:
            return port


def until(sock, kind: str) -> dict:
    while True:
        message = sock.recv(timeout=5)
        if isinstance(message, str) and json.loads(message)["type"] == kind:
            return json.loads(message)


@pytest.fixture
def served(tmp_path):
    install_test_packs(Config(data_dir=tmp_path).packs_dir)
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "delve", "serve", "--host", "127.0.0.1", "--port", str(port)],
        env={**os.environ, "DELVE_DATA_DIR": str(tmp_path)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                httpx.get(f"{base}/api/health", timeout=1)
                break
            except httpx.TransportError:
                assert process.poll() is None, process.stdout.read()
                assert time.monotonic() < deadline, "delve serve did not answer within 10 s"
                time.sleep(0.1)
        yield base, tmp_path
    finally:
        process.terminate()
        process.communicate(timeout=10)


@pytest.mark.slow
def test_voice_through_serve(served):
    base, data_dir = served
    with httpx.Client(base_url=base, timeout=10) as http:
        module = http.post(
            "/api/modules/import", content=Bundle.load(CRYPT).to_zip(), headers={"Content-Type": "application/zip"}
        )
        assert module.status_code in (200, 201), module.text
        campaign = http.post("/api/campaigns", json={"name": "Vellis", "module_id": module.json()["id"]})
        assert campaign.status_code == 201, campaign.text
    campaign_id = campaign.json()["id"]
    token = new_seat_token()
    storage = open_storage(Config(data_dir=data_dir))
    try:
        player = storage.seats.create(campaign_id, "Mira", "en", "player", token_hash=token_hash(token))
    finally:
        storage.close()

    url = base.replace("http://", "ws://") + f"/api/campaigns/{campaign_id}/voice"
    with connect(url, origin=base) as host:  # this machine: the owner's seat
        assert json.loads(host.recv(timeout=5))["type"] == "welcome"
        host.send(json.dumps({"type": "state", "muted": False, "listening_only": False}))
        with connect(url, origin=base, additional_headers={"Cookie": f"{SEAT_COOKIE}={token}"}) as guest:
            welcome = json.loads(guest.recv(timeout=5))
            assert (welcome["type"], welcome["you"]) == ("welcome", player.id)
            guest.send(json.dumps({"type": "state", "muted": False, "listening_only": False}))
            until(host, "peer")
            until(host, "peer")
            sent = struct.pack(">BBHI", 1, 1, 1, 20) + b"opus" * 30
            guest.send(sent)
            while isinstance(got := host.recv(timeout=5), str):
                pass
            assert got == bytes([welcome["slot"]]) + sent
        assert until(host, "left")["seat_id"] == player.id

    with pytest.raises(InvalidStatus) as refused:
        connect(url, origin="http://evil.example")
    assert refused.value.response.status_code == 403
