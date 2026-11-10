"""`delve serve` behind a proxy on this machine (players and tavern Task C2/C4): uvicorn runs with
`proxy_headers=False`, so Delve itself reads the proxy's headers (`delve.web.guard`). Through a real server, a
tunnel's visitor isn't the owner, the login throttle counts the visitor's address (not the tunnel's, and not a forged
`X-Forwarded-For` entry), the session cookie is `Secure` only when the proxy says HTTPS, and the access log holds no
link token and no password."""

import os
import subprocess
import sys
import time

import httpx
import pytest

from delve.config import Config
from delve.play.accounts import create_account
from delve.storage import open_storage
from tests.fixtures.rulesets import install_test_packs
from tests.test_serve import free_port

PASSWORD = "correct horse battery"
WRONG = "not the password at all"


@pytest.fixture
def served(tmp_path):
    config = Config(data_dir=tmp_path)
    install_test_packs(config.packs_dir)
    storage = open_storage(config)
    try:
        create_account(storage, "zed", PASSWORD)
    finally:
        storage.close()
    port = free_port()
    env = {**os.environ, "DELVE_DATA_DIR": str(tmp_path)}
    process = subprocess.Popen(
        [sys.executable, "-m", "delve", "serve", "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while True:
        try:
            httpx.get(f"{base}/api/health", timeout=1)
            break
        except httpx.TransportError:
            assert process.poll() is None, process.stdout.read()
            assert time.monotonic() < deadline, "delve serve did not answer within 15 s"
            time.sleep(0.1)

    def stop() -> str:
        """Stop the server; its output."""
        if process.poll() is None:
            process.terminate()
        return process.communicate(timeout=10)[0]

    try:
        yield base, stop
    finally:
        if process.poll() is None:
            stop()


def _login(client, username, password, **headers):
    return client.post(
        "/api/login",
        json={"username": username, "password": password},
        headers={"Host": "localhost", **headers},
    )


@pytest.mark.slow
def test_a_proxy_here_under_real_uvicorn(served):
    base, stop = served
    tunnel = {"X-Forwarded-For": "203.0.113.9"}
    with httpx.Client(base_url=base, timeout=10) as client:
        assert client.get("/api/modules", headers={"Host": "localhost"}).status_code == 200, "this machine: the owner"
        assert client.get("/api/modules", headers={"Host": "localhost", **tunnel}).status_code == 401
        https = {**tunnel, "X-Forwarded-Proto": "https"}
        assert (
            client.get("/api/modules", headers={"Host": "localhost", "X-Forwarded-Proto": "https"}).status_code == 401
        )

        secure = _login(client, "zed", PASSWORD, **https)
        assert secure.status_code == 200
        assert "secure" in [part.strip().lower() for part in secure.headers["set-cookie"].split(";")]
        plain = _login(client, "zed", PASSWORD, **tunnel)
        assert "secure" not in [part.strip().lower() for part in plain.headers["set-cookie"].split(";")]

        # 20 failures from one visitor, each with another forged leftmost entry: the rightmost one counts.
        for n in range(20):
            forged = {"X-Forwarded-For": f"10.9.8.{n}, 203.0.113.9"}
            assert _login(client, f"nobody{n:02}", WRONG, **forged).status_code == 401
        refused = _login(client, "zed", PASSWORD, **tunnel)
        assert refused.status_code == 429 and refused.json() == {"error": "Too many tries: wait 15 minutes."}
        assert _login(client, "zed", PASSWORD, **{"X-Forwarded-For": "198.51.100.4"}).status_code == 200
        assert _login(client, "zed", PASSWORD).status_code == 200, "the tunnel's own address isn't the visitor's"

        # A visitor who sends a fresh CF-Connecting-IP each try, through a tunnel that appends them to
        # X-Forwarded-For (as cloudflared does): CF-Connecting-IP isn't read, so they stay one address.
        for n in range(20):
            rotating = {"CF-Connecting-IP": f"10.7.7.{n}", "X-Forwarded-For": f"10.7.7.{n}, 192.0.2.50"}
            assert _login(client, f"someone{n:02}", WRONG, **rotating).status_code == 401
        rotated = _login(client, "zed", PASSWORD, **{"CF-Connecting-IP": "10.7.7.99", "X-Forwarded-For": "192.0.2.50"})
        assert rotated.status_code == 429, "the visitor's address is the one the tunnel appended"

        assert client.get("/api/account-links/LINKTOKEN123", headers={"Host": "localhost"}).status_code == 404

    output = stop()
    assert "LINKTOKEN123" not in output and PASSWORD not in output and WRONG not in output
    assert "/api/account-links/…" in output, "the access log is on, with the token taken out"
