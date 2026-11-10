"""This machine is not the owner behind a proxy (players-and-tavern design, "Must"): a request is from this machine only
when its client is loopback, it carries no proxy header, and its `Host` is a loopback or machine address. A tunnel on
this machine (such as `cloudflared`) forwards every outside visitor from loopback, so these must log in, and are refused
the owner token (DEL-154); the internal bridge routes and the invite's LAN address follow the same rule."""

import pytest
from fastapi.testclient import TestClient
from starlette.requests import HTTPConnection

from delve.dm.bridge import BRIDGE_HEADER
from delve.play import seats
from delve.web import guard
from delve.web.app import create_app
from delve.web.guard import is_this_machine
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, PASSWORD, make_account, session_for
from tests.web.test_auth import NEEDS_TOKEN, add_probe
from tests.web.test_seats_identity import make_campaign

PUBLIC_HOST = "delve.example.org"
PROXY_HEADERS = ["Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP", "CF-Connecting-IP", "True-Client-IP"]
PROXY_VALUES = {
    "Forwarded": "for=203.0.113.9;proto=https;host=delve.example.org",
    "X-Forwarded-Host": PUBLIC_HOST,
}


def proxy_header(name: str) -> dict[str, str]:
    return {name: PROXY_VALUES.get(name, "203.0.113.9")}


@pytest.fixture
def app(config, storage, registries, static_dir, monkeypatch):
    """The test app, answering to a public name too, as an owner with a tunnel configures it."""
    monkeypatch.setenv("DELVE_ALLOWED_HOSTS", PUBLIC_HOST)
    app = create_app(config, storage, registries, static_dir=static_dir)
    add_probe(app)
    return app


@pytest.fixture
def tunnel(app):
    """A visitor from outside, forwarded by a tunnel on this machine: loopback, with the public host."""
    with TestClient(app, base_url=f"https://{PUBLIC_HOST}", client=("127.0.0.1", 50002)) as client:
        yield client


@pytest.fixture
def campaign(storage):
    campaign = make_campaign(storage)
    seats.owner_seat(storage, campaign.id)
    return campaign


def connection(client: str | None, host: str = "localhost:7810", headers: dict[str, str] | None = None):
    raw = [(b"host", host.encode())] + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "headers": raw, "client": (client, 50000) if client else None}
    return HTTPConnection(scope)


# ----- the helper -----


@pytest.mark.parametrize("host", ["localhost:7810", "127.0.0.1:7810", "[::1]:7810", "127.0.0.1", "LOCALHOST:7810"])
@pytest.mark.parametrize("client", ["127.0.0.1", "::1", "::ffff:127.0.0.1", "127.0.0.2"])
def test_loopback_to_a_loopback_host_is_this_machine(client, host):
    assert is_this_machine(connection(client, host))


def test_loopback_to_a_machine_address_is_this_machine(monkeypatch):
    monkeypatch.setattr(guard, "machine_addresses", lambda: {"127.0.0.1", "192.168.1.20"})
    assert is_this_machine(connection("127.0.0.1", "192.168.1.20:7810"))
    assert not is_this_machine(connection("127.0.0.1", "192.168.1.99:7810"))


@pytest.mark.parametrize("client", [None, "testclient", "10.0.0.7", "192.168.1.20", "fe80::1"])
def test_another_client_is_not_this_machine(client):
    assert not is_this_machine(connection(client))


@pytest.mark.parametrize("name", PROXY_HEADERS)
def test_a_proxy_header_is_not_this_machine(name):
    assert not is_this_machine(connection("127.0.0.1", headers=proxy_header(name)))
    assert not is_this_machine(connection("127.0.0.1", headers={name: ""})), "present, even empty"


@pytest.mark.parametrize("host", [PUBLIC_HOST, f"{PUBLIC_HOST}:443", "delve.local", ""])
def test_a_name_is_not_this_machine(host):
    assert not is_this_machine(connection("127.0.0.1", host))


# ----- the owner -----


def test_plain_loopback_is_still_the_owner(app):
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        assert local.get("/api/probe").json() == {"id": "owner", "roles": ["organiser"]}
        assert local.get("/api/connections").status_code == 200


@pytest.mark.parametrize("name", PROXY_HEADERS)
def test_loopback_with_a_proxy_header_is_not_the_owner(app, name):
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        local.headers.update(proxy_header(name))
        response = local.get("/api/probe")
        assert response.status_code == 401 and response.json() == NEEDS_TOKEN
        assert local.get("/api/connections").status_code == 401, "the owner's own routes too"
        assert local.get("/api/me").status_code == 401


def test_loopback_with_the_allowed_public_host_is_not_the_owner(tunnel):
    response = tunnel.get("/api/probe")
    assert response.status_code == 401 and response.json() == NEEDS_TOKEN
    assert tunnel.get("/api/connections").status_code == 401
    assert tunnel.get("/api/health").status_code == 200, "the host itself is allowed"


@pytest.mark.parametrize("name", PROXY_HEADERS)
def test_the_owner_token_is_refused_through_a_proxy(tunnel, token, name):
    """DEL-154, audit finding 9: through a proxy here, the owner logs in with the owner account instead."""
    tunnel.headers.update(proxy_header(name))
    assert tunnel.get("/api/probe", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    tunnel.cookies.set("delve_token", token)
    assert tunnel.get("/api/connections").status_code == 401


def owner_account(storage, client: TestClient) -> None:
    """Log the client in to an owner account, as the owner does through a proxy (DEL-154)."""
    session_for(storage, make_account(storage, "olga", owner=True), client)


def test_a_seat_token_still_works_through_a_proxy(tunnel, storage, campaign):
    token = new_seat_token()
    storage.seats.create(campaign.id, "Ana", "en", "player", token_hash=token_hash(token))
    tunnel.cookies.set(SEAT_COOKIE, token)
    me = tunnel.get("/api/me", headers={"X-Forwarded-For": "203.0.113.9"})
    assert me.status_code == 200 and me.json()["principal"]["id"].startswith("seat:")
    assert tunnel.get("/api/probe").status_code == 403, "a seat, not the owner"


def test_an_account_joins_through_a_proxy(tunnel, campaign):
    body = {"username": "ana", "password": PASSWORD, "display_name": "Ana", "language": "en", "role": "player"}
    response = tunnel.post(
        f"/api/join/{campaign.join_token}/account", json=body, headers={"X-Forwarded-For": "203.0.113.9"}
    )
    assert response.status_code == 201, response.text
    me = tunnel.get("/api/me", headers={"X-Forwarded-For": "203.0.113.9"})
    assert me.status_code == 200 and me.json()["principal"]["id"].startswith("account:")
    assert tunnel.get("/api/probe").status_code == 403, "an account, not the owner"


# ----- the bridge -----


def bridge_calls(client: TestClient, secret: str):
    return [
        client.get("/internal/dm/tools", headers={BRIDGE_HEADER: secret}),
        client.post("/internal/dm/cmp_x/call", json={"name": "roll", "args": {}}, headers={BRIDGE_HEADER: secret}),
    ]


def test_the_bridge_from_this_machine_still_works(app):
    with TestClient(app, base_url="http://127.0.0.1:7810", client=("127.0.0.1", 50001)) as bridge:
        assert bridge.get("/internal/dm/tools", headers={BRIDGE_HEADER: app.state.bridge_secret}).status_code == 200


@pytest.mark.parametrize("name", PROXY_HEADERS)
def test_the_bridge_routes_refuse_a_proxied_request(app, name):
    with TestClient(app, base_url="http://127.0.0.1:7810", client=("127.0.0.1", 50001)) as client:
        client.headers.update(proxy_header(name))
        refused = bridge_calls(client, app.state.bridge_secret)
    assert [r.status_code for r in refused] == [403, 403]
    assert all(set(r.json()) == {"error"} for r in refused)


def test_the_bridge_routes_refuse_the_public_host(app, tunnel):
    refused = bridge_calls(tunnel, app.state.bridge_secret)
    assert [r.status_code for r in refused] == [403, 403]


# ----- the invite -----


def test_through_a_proxy_the_invite_keeps_the_request_host(tunnel, storage, campaign, monkeypatch):
    monkeypatch.setattr(guard, "lan_addresses", lambda: ["192.168.1.20"])
    owner_account(storage, tunnel)
    url = tunnel.get(f"/api/campaigns/{campaign.id}/invite").json()["url"]
    assert url == f"https://{PUBLIC_HOST}/join/{campaign.join_token}", "never the LAN address to an outside visitor"
    url = tunnel.get(f"/api/campaigns/{campaign.id}/invite", headers={"X-Forwarded-For": "203.0.113.9"}).json()["url"]
    assert url == f"https://{PUBLIC_HOST}/join/{campaign.join_token}"


def test_through_a_https_proxy_the_links_say_https(app, campaign, storage):
    """Audit finding 6: a tunnel that ends TLS talks plain http to Delve, so the links it handed out said http://."""
    with TestClient(app, base_url=f"http://{PUBLIC_HOST}", client=("127.0.0.1", 50002)) as tunnel:
        owner_account(storage, tunnel)
        tunnel.headers.update({"X-Forwarded-For": "203.0.113.9"})
        secure = {"X-Forwarded-Proto": "https"}
        url = tunnel.get(f"/api/campaigns/{campaign.id}/invite", headers=secure).json()["url"]
        assert url == f"https://{PUBLIC_HOST}/join/{campaign.join_token}"
        made = tunnel.post("/api/accounts", json={"username": "ana"}, headers=secure).json()
        assert made["link"]["url"].startswith(f"https://{PUBLIC_HOST}/account/link/")
        plain = tunnel.get(f"/api/campaigns/{campaign.id}/invite").json()["url"]
        assert plain == f"http://{PUBLIC_HOST}/join/{campaign.join_token}", "a proxy that says nothing of https"


def test_from_this_machine_the_invite_still_uses_the_lan_address(app, campaign, monkeypatch):
    monkeypatch.setattr(guard, "lan_addresses", lambda: ["192.168.1.20"])
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        url = local.get(f"/api/campaigns/{campaign.id}/invite").json()["url"]
    assert url == f"http://192.168.1.20:7810/join/{campaign.join_token}"
