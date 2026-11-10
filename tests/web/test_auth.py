import stat
from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient

from delve import __version__
from delve.domain.modules import ModuleMap
from delve.play import logins
from delve.web import guard
from delve.web.auth import (
    ChainedIdentity,
    OwnerTokenIdentity,
    Principal,
    SeatTokenIdentity,
    ThisMachineIdentity,
    current_principal,
    load_or_create_token,
    require,
)
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, make_account, session_for

NEEDS_TOKEN = {"error": "Log in to go on."}


def add_probe(app):
    """A route only an organiser may call, so the tests don't depend on later routes."""

    @app.get("/api/probe")
    def probe(principal: Annotated[Principal, Depends(require("organiser"))]):
        return {"id": principal.id, "roles": sorted(principal.roles)}

    @app.get("/api/probe-host")
    def probe_host(principal: Annotated[Principal, Depends(require("host"))]):
        return {"id": principal.id}


def test_health_open(lan):
    response = lan.get("/api/health")
    assert response.status_code == 200
    # The test app has only the fake DM, so the real one is unavailable.
    assert response.json() == {"ok": True, "name": "delve", "version": __version__, "dm": "unavailable"}


def test_lan_without_token_401_json(app, lan):
    add_probe(app)
    response = lan.get("/api/probe")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == NEEDS_TOKEN


def test_loopback_is_owner(app, local):
    add_probe(app)
    response = local.get("/api/probe")
    assert response.status_code == 200
    assert response.json() == {"id": "owner", "roles": ["organiser"]}


def test_this_machine_is_the_owner_only_until_there_is_an_owner_account(app, storage, local, token):
    """Audit finding 3: a proxy here that adds no headers made every visitor the owner. Once an owner account exists,
    the owner here logs in, or uses the owner token."""
    add_probe(app)
    make_account(storage, "ana")
    assert local.get("/api/probe").status_code == 200, "a player's account changes nothing"
    make_account(storage, "olga", owner=True)
    for client in (("127.0.0.1", 50000), ("::1", 50000)):
        with TestClient(app, base_url=BASE_URL, client=client) as here:
            refused = here.get("/api/probe")
            assert refused.status_code == 401 and refused.json() == NEEDS_TOKEN
            assert here.get("/api/me").status_code == 401
            assert here.get("/api/probe", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    olga = storage.accounts.by_username("olga")
    storage.accounts.set_disabled(olga.id, "2026-10-24T12:00:00+00:00")
    assert local.get("/api/probe").status_code == 401, "a disabled owner account still is one"


def test_ipv6_loopback_is_owner(app):
    add_probe(app)
    with TestClient(app, base_url=BASE_URL, client=("::1", 50000)) as client:
        assert client.get("/api/probe").status_code == 200


def test_bearer_token_ok(app, lan, token):
    add_probe(app)
    response = lan.get("/api/probe", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["id"] == "owner"


def test_cookie_token_ok(app, lan, token):
    add_probe(app)
    lan.cookies.set("delve_token", token)
    assert lan.get("/api/probe").status_code == 200


def test_wrong_token_401(app, lan, token):
    add_probe(app)
    assert lan.get("/api/probe", headers={"Authorization": "Bearer nope"}).status_code == 401
    lan.cookies.set("delve_token", token[:-1])
    response = lan.get("/api/probe")
    assert response.status_code == 401
    assert response.json() == NEEDS_TOKEN


def test_missing_role_403(app, local):
    add_probe(app)
    response = local.get("/api/probe-host")
    assert response.status_code == 403
    assert "host" in response.json()["error"]


def test_token_file_created_0600_and_reused(config):
    token = load_or_create_token(config)
    assert len(token) == 48 and int(token, 16) >= 0
    assert stat.S_IMODE(config.token_path.stat().st_mode) == 0o600
    assert load_or_create_token(config) == token


def test_empty_token_file_is_replaced(config):
    config.data_dir.mkdir(parents=True)
    config.token_path.write_text("\n")
    token = load_or_create_token(config)
    assert len(token) == 48
    assert config.token_path.read_text().strip() == token
    assert stat.S_IMODE(config.token_path.stat().st_mode) == 0o600


class FakeRequest:
    def __init__(self, client_host, headers=None, cookies=None):
        self.client = type("Address", (), {"host": client_host})() if client_host else None
        self.headers = headers or {}
        self.cookies = cookies or {}


def test_identity_without_client_address_is_nobody(storage):
    assert OwnerTokenIdentity("abc").resolve(FakeRequest(None)) is None
    assert OwnerTokenIdentity("abc").resolve(FakeRequest(None, cookies={"delve_token": "abc"})) is not None
    assert ThisMachineIdentity(storage).resolve(FakeRequest(None)) is None


def test_owner_token_identity_is_the_token_only():
    """Plateau 0 let the owner token's identity decide this machine and seat tokens too; now each is its own."""
    assert OwnerTokenIdentity("abc").resolve(FakeRequest("127.0.0.1", {"host": "localhost"})) is None


# ----- the identity chain (players and tavern Task C2) -----


def add_principal_probe(app):
    @app.get("/api/probe-principal")
    def probe_principal(principal: Annotated[Principal, Depends(current_principal)]):
        return {
            "id": principal.id,
            "roles": sorted(principal.roles),
            "owner": principal.owner,
            "account": principal.account and principal.account.username,
        }


def _campaign(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    return storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )


def test_chain_order(app, storage, token):
    add_principal_probe(app)
    ana = make_account(storage)
    seat_token = new_seat_token()
    seat = storage.seats.create(_campaign(storage).id, "Bo", "en", "player", token_hash=token_hash(seat_token))
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as here:
        session_for(storage, ana, here)
        here.cookies.set(SEAT_COOKIE, seat_token)
        owner = here.get("/api/probe-principal", headers={"Authorization": f"Bearer {token}"}).json()
        assert owner["id"] == "owner", "the owner token beats a session"
        assert here.get("/api/probe-principal").json()["id"] == f"account:{ana.id}", "a session beats a seat token"
        here.cookies.delete("delve_session")
        assert here.get("/api/probe-principal").json()["id"] == f"seat:{seat.id}", "a seat token beats this machine"
        here.cookies.delete(SEAT_COOKIE)
        assert here.get("/api/probe-principal").json()["id"] == "owner", "then this machine"
    with TestClient(app, base_url=BASE_URL) as lan:
        assert lan.get("/api/probe-principal").json() == NEEDS_TOKEN, "nothing is nobody"


def test_chain_is_the_first_answer():
    class Fixed:
        def __init__(self, answer):
            self.answer = answer
            self.asked = 0

        def resolve(self, request):
            self.asked += 1
            return self.answer

    first, second, third = Fixed(None), Fixed(Principal("a", frozenset())), Fixed(Principal("b", frozenset()))
    assert ChainedIdentity(first, second, third).resolve(FakeRequest("10.0.0.1")).id == "a"
    assert third.asked == 0
    assert ChainedIdentity(Fixed(None)).resolve(FakeRequest("10.0.0.1")) is None
    assert SeatTokenIdentity(lambda token: None).resolve(FakeRequest("127.0.0.1", cookies={SEAT_COOKIE: "x"})) is None


def test_session_cookie_is_the_account(app, storage, lan):
    add_principal_probe(app)
    ana = make_account(storage, organiser=True)
    session_for(storage, ana, lan)
    assert lan.get("/api/probe-principal").json() == {
        "id": f"account:{ana.id}",
        "roles": ["organiser"],
        "owner": False,
        "account": "ana",
    }


def test_player_account_has_no_role(app, storage, lan):
    add_principal_probe(app)
    session_for(storage, make_account(storage), lan)
    assert lan.get("/api/probe-principal").json()["roles"] == []
    assert lan.get("/api/modules").status_code == 403


def test_ended_session_is_nobody_from_outside(app, storage, lan):
    add_principal_probe(app)
    ana = make_account(storage)
    token = session_for(storage, ana, lan)
    logins.end(storage, token)
    response = lan.get("/api/probe-principal")
    assert response.status_code == 401 and response.json() == NEEDS_TOKEN
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as proxied:
        proxied.cookies.set("delve_session", token)
        response = proxied.get("/api/probe-principal", headers={"X-Forwarded-For": "203.0.113.9"})
        assert response.status_code == 401 and response.json() == NEEDS_TOKEN


def test_organiser_account_is_not_the_owner(app, storage, lan):
    session_for(storage, make_account(storage, organiser=True), lan)
    assert lan.get("/api/connections").status_code == 403
    assert lan.get("/api/connections").json() == {"error": "Only the install's owner can do this."}
    response = lan.post("/api/novels", json={"source": "campaign", "id": "cmp_nope"})
    assert response.status_code == 403
    assert lan.get("/api/campaigns").status_code == 200


def test_owner_account_is_the_owner(app, storage, lan):
    """The human's ruling of 2026-10-24: an owner account's session has every right of the owner, from any device."""
    add_principal_probe(app)
    olga = make_account(storage, "olga", owner=True)
    session_for(storage, olga, lan)
    probed = lan.get("/api/probe-principal").json()
    assert probed == {"id": f"account:{olga.id}", "roles": ["organiser"], "owner": True, "account": "olga"}
    assert lan.get("/api/connections").status_code == 200
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        session_for(storage, olga, tunnel)
        assert tunnel.get("/api/connections", headers={"CF-Connecting-IP": "203.0.113.9"}).status_code == 200


def test_disabled_account_session_is_nobody(app, storage, lan):
    add_principal_probe(app)
    ana = make_account(storage)
    session_for(storage, ana, lan)
    storage.accounts.set_disabled(ana.id, "2026-10-24T12:00:00+00:00")
    assert lan.get("/api/probe-principal").status_code == 401


def _connection(client_host, headers=None, scheme="http"):
    from starlette.requests import HTTPConnection

    raw = [(k.lower().encode(), v.encode()) for k, v in {"host": "localhost", **(headers or {})}.items()]
    scope = {"type": "http", "client": (client_host, 50000), "headers": raw, "scheme": scheme, "path": "/"}
    return HTTPConnection(scope)


def test_client_address_trusts_only_a_proxy_here():
    cf = {"CF-Connecting-IP": "203.0.113.9"}
    assert guard.client_address(_connection("127.0.0.1", cf)) == "127.0.0.1", "CF-Connecting-IP isn't read"
    assert guard.client_address(_connection("192.168.1.20", cf)) == "192.168.1.20"
    xff = {"X-Forwarded-For": "1.1.1.1, 203.0.113.9"}
    assert guard.client_address(_connection("127.0.0.1", xff)) == "203.0.113.9"
    assert guard.client_address(_connection("::1", xff)) == "203.0.113.9"
    assert guard.client_address(_connection("127.0.0.1", {"X-Real-IP": "198.51.100.4", **xff})) == "203.0.113.9"
    assert guard.client_address(_connection("127.0.0.1", {"X-Real-IP": "198.51.100.4"})) == "198.51.100.4"
    assert guard.client_address(_connection("127.0.0.1", {**cf, **xff, "X-Real-IP": "198.51.100.4"})) == "203.0.113.9"
    rotated = {"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "10.0.0.1"}
    assert guard.client_address(_connection("127.0.0.1", rotated)) == "10.0.0.1", "the rightmost entry, not Cloudflare's"
    spoofed = {"True-Client-IP": "10.0.0.5", "X-Forwarded-For": "203.0.113.9"}
    assert guard.client_address(_connection("127.0.0.1", spoofed)) == "203.0.113.9", "True-Client-IP isn't read"
    forwarded = {"Forwarded": 'for=1.1.1.1;proto=https, for="[2001:db8::7]:4711"'}
    assert guard.client_address(_connection("127.0.0.1", forwarded)) == "2001:db8::7"
    assert guard.client_address(_connection("127.0.0.1")) == "127.0.0.1"
    assert guard.client_address(_connection("127.0.0.1", {"X-Forwarded-For": " "})) == "127.0.0.1"


def test_came_over_https():
    assert guard.came_over_https(_connection("127.0.0.1", {"X-Forwarded-Proto": "https"})) is True
    assert guard.came_over_https(_connection("127.0.0.1", {"Forwarded": "for=1.1.1.1;proto=https"})) is True
    assert guard.came_over_https(_connection("192.168.1.20", {"X-Forwarded-Proto": "https"})) is False
    assert guard.came_over_https(_connection("127.0.0.1")) is False
    assert guard.came_over_https(_connection("127.0.0.1", {"X-Forwarded-Proto": "http"})) is False
    assert guard.came_over_https(_connection("192.168.1.20", scheme="https")) is True


def test_forwarded_proto_alone_is_a_proxy():
    """A proxy here that says only how the request came is a proxy too: not this machine."""
    assert guard.is_this_machine(_connection("127.0.0.1")) is True
    assert guard.is_this_machine(_connection("127.0.0.1", {"X-Forwarded-Proto": "https"})) is False
