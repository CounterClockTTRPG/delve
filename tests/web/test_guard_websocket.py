"""The guard for WebSockets (table voice and fixes Task V1.1, Review Focus 1): browsers send cookies on a WebSocket
handshake from any origin, so a handshake whose `Origin` isn't the request's host (CSWSH), or whose `Host` isn't one
Delve answers to, is refused before the app sees it, as an HTTP request is."""

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from delve.web.guard import RequestGuard
from tests.web.conftest import BASE_URL

CORS_ORIGIN = "http://evil.example"
# TestClient's WebSocket takes the host from the URL alone, never from the client's base URL.
WS_URL = BASE_URL.replace("http://", "ws://") + "/ws"


@pytest.fixture
def echo(app):
    @app.websocket("/ws")
    async def echo_route(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text(await websocket.receive_text())
        await websocket.close()

    return app


def test_cross_origin_handshake_refused(echo, local):
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        local.websocket_connect(WS_URL, headers={"Origin": CORS_ORIGIN}),
    ):
        pass
    assert refused.value.code == 4403


def test_unknown_host_handshake_refused(echo):
    with (
        TestClient(echo, client=("127.0.0.1", 50000)) as client,
        pytest.raises(WebSocketDisconnect) as refused,
        client.websocket_connect("ws://evil.example:7810/ws"),
    ):
        pass
    assert refused.value.code == 4421


def test_same_origin_handshake_accepted(echo, local):
    with local.websocket_connect(WS_URL, headers={"Origin": BASE_URL}) as socket:
        socket.send_text("hello")
        assert socket.receive_text() == "hello"


def test_no_origin_handshake_accepted(echo, local):
    with local.websocket_connect(WS_URL) as socket:
        socket.send_text("hello")
        assert socket.receive_text() == "hello"


def test_handshake_refusal_codes():
    def scope(host: str, origin: str | None = None) -> dict:
        headers = [(b"host", host.encode())]
        if origin is not None:
            headers.append((b"origin", origin.encode()))
        return {"type": "websocket", "path": "/ws", "headers": headers}

    guard = RequestGuard(app=None, env={})
    assert guard.handshake_refusal(scope("localhost:7810")) is None
    assert guard.handshake_refusal(scope("localhost:7810", "http://localhost:7810")) is None
    assert guard.handshake_refusal(scope("localhost:7810", "null")) == 4403
    assert guard.handshake_refusal(scope("evil.example")) == 4421
