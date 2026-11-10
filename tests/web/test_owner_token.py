"""The owner token (DEL-154, audit finding 9): a new one at once, from the CLI or the owner's Preferences, the old one
refused from the next request on, without a restart; never taken through a proxy on this machine (a tunnel's
visitor logs in with the owner account instead); and kept by the browser in an `HttpOnly` cookie, which the page asks
for by posting the link's `#token=` once."""

import stat

import pytest
from fastapi.testclient import TestClient

from delve.web import guard
from delve.web.auth import OwnerTokenIdentity, new_token
from tests.web.conftest import BASE_URL, make_account, session_for
from tests.web.test_auth import FakeRequest, add_probe

PUBLIC_HOST = "delve.example.org"
NOT_HERE = {
    "error": "The owner token works only on this machine and its network: over the internet, log in with your owner "
    "account."
}
NEEDS_LOGIN = {"error": "Log in to go on."}


@pytest.fixture
def app(config, storage, registries, static_dir, monkeypatch):
    from delve.web.app import create_app

    monkeypatch.setenv("DELVE_ALLOWED_HOSTS", PUBLIC_HOST)
    monkeypatch.setattr(guard, "lan_addresses", lambda: ["192.168.1.20"])
    app = create_app(config, storage, registries, static_dir=static_dir)
    add_probe(app)
    return app


@pytest.fixture
def tunnel(app):
    """A visitor from outside, through cloudflared on this machine."""
    with TestClient(app, base_url=f"https://{PUBLIC_HOST}", client=("127.0.0.1", 50002)) as client:
        client.headers.update({"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"})
        yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _cookie(response, name="delve_token") -> str:
    (header,) = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]
    return header


def _flags(header: str) -> set[str]:
    return {part.strip().lower() for part in header.split(";")[1:]}


# ----- making a new one -----


def test_new_token_replaces_the_file(config):
    from delve.web.auth import load_or_create_token

    old = load_or_create_token(config)
    made = new_token(config)
    assert made != old and len(made) == 48 and int(made, 16) >= 0
    assert config.token_path.read_text().strip() == made
    assert stat.S_IMODE(config.token_path.stat().st_mode) == 0o600
    assert load_or_create_token(config) == made


def test_the_server_follows_the_token_file_without_a_restart(app, config, lan, token):
    """`delve token --new` writes the file; the running Delve reads it again once it changed."""
    assert lan.get("/api/probe", headers=bearer(token)).status_code == 200
    made = new_token(config)
    refused = lan.get("/api/probe", headers=bearer(token))
    assert refused.status_code == 401 and refused.json() == NEEDS_LOGIN, "the old one at once"
    assert lan.get("/api/probe", headers=bearer(made)).status_code == 200


def test_the_identity_keeps_the_token_it_had_when_the_file_is_gone(config):
    token = new_token(config)
    identity = OwnerTokenIdentity(token, config.token_path)
    config.token_path.unlink()
    assert identity.resolve(FakeRequest(None, cookies={"delve_token": token})) is not None


def test_the_cli_makes_a_new_token(tmp_path, monkeypatch, capsys):
    from delve.__main__ import main

    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(guard, "lan_addresses", lambda: ["192.168.1.20"])
    assert main(["token"]) == 0
    old = (tmp_path / "token").read_text().strip()
    capsys.readouterr()
    assert main(["token", "--new"]) == 0
    made = (tmp_path / "token").read_text().strip()
    captured = capsys.readouterr()
    assert made != old
    assert captured.out.splitlines() == [f"http://192.168.1.20:7810/#token={made}"]
    assert "old token no longer works" in captured.err


def test_the_owner_makes_a_new_token_from_the_web(app, lan, token):
    made = lan.post("/api/owner-token/new", json={}, headers=bearer(token))
    assert made.status_code == 200
    new = made.json()["token"]
    assert new != token
    assert made.json()["links"] == [f"http://192.168.1.20:7810/#token={new}", f"http://localhost:7810/#token={new}"]
    assert lan.get("/api/probe", headers=bearer(token)).status_code == 401, "the old one stops at once"
    assert lan.get("/api/probe", headers=bearer(new)).status_code == 200


def test_the_browser_that_made_it_keeps_the_owner_token(app, lan, token):
    """A browser of the owner token: its cookie is the new token's, so it isn't logged out by its own button."""
    lan.cookies.set("delve_token", token)
    made = lan.post("/api/owner-token/new", json={})
    header = _cookie(made)
    assert header.startswith(f"delve_token={made.json()['token']};")
    assert _flags(header) >= {"httponly", "samesite=strict", "path=/"}
    lan.cookies.set("delve_token", made.json()["token"])
    assert lan.get("/api/probe").status_code == 200


def test_an_owner_account_makes_a_new_token_too(app, storage, tunnel):
    olga = make_account(storage, "olga", owner=True)
    session_for(storage, olga, tunnel)
    made = tunnel.post("/api/owner-token/new", json={})
    assert made.status_code == 200 and made.json()["token"]
    assert "delve_token" not in made.headers.get("set-cookie", ""), "an account keeps its session, not a token"


def test_only_the_owner_makes_a_new_token(app, storage, lan, token, config):
    assert lan.post("/api/owner-token/new", json={}).status_code == 401
    organiser = make_account(storage, "ana", organiser=True)
    session_for(storage, organiser, lan)
    refused = lan.post("/api/owner-token/new", json={})
    assert refused.status_code == 403
    assert config.token_path.read_text().strip() == token


# ----- not through a proxy on this machine -----


def test_the_owner_token_is_refused_through_a_proxy_here(tunnel, token):
    refused = tunnel.get("/api/probe", headers=bearer(token))
    assert refused.status_code == 401 and refused.json() == NOT_HERE
    tunnel.cookies.set("delve_token", token)
    refused = tunnel.get("/api/connections")
    assert refused.status_code == 401 and refused.json() == NOT_HERE
    assert tunnel.get("/api/me").status_code == 401


@pytest.mark.parametrize("name", ["Forwarded", "X-Forwarded-For", "X-Real-IP", "X-Forwarded-Host"])
def test_any_proxy_header_from_loopback_refuses_the_owner_token(app, token, name):
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as here:
        refused = here.get("/api/probe", headers={**bearer(token), name: "203.0.113.9"})
        assert refused.status_code == 401 and refused.json() == NOT_HERE


def test_through_a_proxy_the_owner_account_still_works(app, storage, tunnel, token):
    olga = make_account(storage, "olga", owner=True)
    session_for(storage, olga, tunnel)
    tunnel.cookies.set("delve_token", token)  # an old cookie beside the session changes nothing
    assert tunnel.get("/api/probe").status_code == 200
    assert tunnel.get("/api/connections").status_code == 200


def test_lan_and_this_machine_keep_the_owner_token(app, storage, lan, token):
    make_account(storage, "olga", owner=True)  # so this machine alone isn't the owner
    assert lan.get("/api/probe", headers=bearer(token)).json()["id"] == "owner"
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as here:
        assert here.get("/api/probe", headers=bearer(token)).json()["id"] == "owner"
        here.cookies.set("delve_token", token)
        assert here.get("/api/probe").json()["id"] == "owner"


def test_a_websocket_through_a_proxy_is_refused_the_owner_token(app, token):
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app, base_url=f"http://{PUBLIC_HOST}", client=("127.0.0.1", 50002)) as tunnel:
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            tunnel.websocket_connect(f"ws://{PUBLIC_HOST}/api/campaigns/nope/voice", headers=bearer(token)),
        ):
            pass
        assert closed.value.code == 4401


# ----- the HttpOnly cookie -----


def test_the_page_trades_the_link_for_an_httponly_cookie(app, lan, token):
    answer = lan.post("/api/owner-token/cookie", json={"token": token})
    assert answer.status_code == 204
    header = _cookie(answer)
    assert header.startswith(f"delve_token={token};")
    assert _flags(header) == {"httponly", "samesite=strict", "path=/", "max-age=31536000"}, "no Secure over http"
    assert lan.get("/api/probe").json()["id"] == "owner"


def test_a_wrong_token_gets_no_cookie(app, lan, token):
    answer = lan.post("/api/owner-token/cookie", json={"token": token[:-1] + "x"})
    assert answer.status_code == 401 and answer.json() == {"error": "That isn't the owner token: ask for a new link."}
    assert "set-cookie" not in answer.headers
    assert token[:-1] not in answer.text
    assert lan.post("/api/owner-token/cookie", json={"token": ["x"]}).status_code == 422


def test_no_cookie_through_a_proxy_here(app, tunnel, token):
    answer = tunnel.post("/api/owner-token/cookie", json={"token": token})
    assert answer.status_code == 403 and answer.json() == NOT_HERE
    assert "set-cookie" not in answer.headers
