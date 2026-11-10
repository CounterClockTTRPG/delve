"""The uvicorn server's settings (Priya's voice review): a WebSocket message is refused by its size as it comes in,
not after it is whole in memory, and no message is compressed, so a small compressed one can't inflate to a big one."""

from delve.web.app import server_config


def test_websocket_messages_are_small_and_uncompressed(app):
    config = server_config(app)
    assert config.ws_max_size == 64 * 1024
    assert config.ws_per_message_deflate is False
    assert config.proxy_headers is False
