"""Connections (portraits plan Task 3): the owner's Replicate token and assetgen, owner only. A token goes into the
data dir's files and never comes back out: not in a response, the log or an event, a failed Test included (Review
Focus 1). Replicate and assetgen are `httpx.MockTransport`s; never a real call."""

import json
import logging
import stat

import httpx
import pytest

from delve.images.connections import ASSETGEN_FILE, load_assetgen
from delve.images.replicate import API_URL, REPLICATE, TOKEN_ENV, TOKEN_FILE
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL
from tests.web.test_preferences_api import published
from tests.web.test_seats_identity import make_campaign

TOKEN = "tok-SECRET-XYZZY"
ASSETGEN = "http://127.0.0.1:47899"


@pytest.fixture(autouse=True)
def no_environment_token(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)


@pytest.fixture(autouse=True)
def no_mail_environment(monkeypatch):
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.delenv("DELVE_ALLOWED_HOSTS", raising=False)


@pytest.fixture(autouse=True)
def every_log(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


class Remote:
    """Replicate and assetgen in one fake: each answers with `status`, echoing the request's headers back, as a
    careless server's error page would."""

    def __init__(self, replicate=200, assetgen=200, models=None) -> None:
        self.replicate, self.assetgen = replicate, assetgen
        self.models = models if models is not None else [{"id": "flux-schnell", "kind": "image"}]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        echoed = f"Traceback: request headers {dict(request.headers)}"
        url = str(request.url)
        if url == f"{API_URL}/account":
            if self.replicate != 200:
                return httpx.Response(self.replicate, json={"detail": echoed})
            return httpx.Response(200, json={"type": "user", "username": "owner"})
        if url.split("?")[0] == f"{ASSETGEN}/api/models":
            if self.assetgen != 200:
                return httpx.Response(self.assetgen, text=echoed)
            return httpx.Response(200, json=self.models)
        return httpx.Response(404, text=echoed)


@pytest.fixture(autouse=True)
def nothing_answers(app):
    """No test reaches a socket: until `remote` plays them, Replicate and assetgen are down."""

    def down(request):
        raise httpx.ConnectError("down", request=request)

    app.state.connections_transport = httpx.MockTransport(down)


@pytest.fixture
def remote(app, nothing_answers):
    fake = Remote()
    app.state.connections_transport = httpx.MockTransport(fake)
    return fake


def assert_no_token(*texts):
    for text in texts:
        assert TOKEN not in text


def put(client, path, body):
    return client.put(path, json=body)


def delete(client, path):
    return client.request("DELETE", path, json={})


def test_get_says_nothing_is_set(local):
    response = local.get("/api/connections")
    assert response.status_code == 200
    body = response.json()
    assert {name: body[name] for name in ("replicate", "assetgen")} == {
        "replicate": {"state": "unset"},
        "assetgen": {"url": None, "token": "unset"},
    }
    assert {name: body["google"][name] for name in ("client_id", "secret")} == {"client_id": None, "secret": "unset"}


def test_saving_the_replicate_token_writes_its_file_and_answers_set(local, config, every_log):
    response = put(local, "/api/connections/replicate", {"token": TOKEN})
    assert response.status_code == 200
    assert response.json() == {"state": "set"}
    path = config.data_dir / TOKEN_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert path.read_text().strip() == TOKEN
    got = local.get("/api/connections")
    assert got.json()["replicate"] == {"state": "set"}
    assert_no_token(response.text, got.text, every_log.text)


def test_replicate_is_offered_and_withdrawn_without_a_restart(local, app):
    def ids():
        return [provider["id"] for provider in local.get("/api/backends").json()["providers"]]

    assert REPLICATE not in ids()
    assert put(local, "/api/connections/replicate", {"token": TOKEN}).status_code == 200
    assert REPLICATE in ids()
    assert put(local, "/api/connections/replicate", {"token": "r8_another"}).status_code == 200
    assert ids().count(REPLICATE) == 1, "a new token replaces the provider"
    response = delete(local, "/api/connections/replicate")
    assert response.status_code == 200
    assert response.json() == {"state": "unset"}
    assert REPLICATE not in ids()


def test_a_new_token_reaches_replicate_at_once(local, app, remote):
    put(local, "/api/connections/replicate", {"token": TOKEN})
    provider = app.state.registries.images.get(REPLICATE)
    put(local, "/api/connections/replicate", {"token": "r8_another"})
    assert app.state.registries.images.get(REPLICATE) is not provider, "the old one, with the old token, is gone"
    local.post("/api/connections/replicate/test", json={})
    assert remote.requests[-1].headers["authorization"] == "Bearer r8_another"


def test_the_environment_wins_and_delete_leaves_it_registered(local, config, monkeypatch, every_log):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    assert local.get("/api/connections").json()["replicate"] == {"state": "environment"}
    put(local, "/api/connections/replicate", {"token": "r8_file"})
    assert local.get("/api/connections").json()["replicate"] == {"state": "environment"}
    response = delete(local, "/api/connections/replicate")
    assert response.json() == {"state": "environment"}
    assert not (config.data_dir / TOKEN_FILE).exists(), "the file is removed all the same"
    providers = [provider["id"] for provider in local.get("/api/backends").json()["providers"]]
    assert REPLICATE in providers
    assert_no_token(response.text, every_log.text)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"token": ""},
        {"token": "   "},
        {"token": 42},
        {"token": [TOKEN]},
        {"token": f"{TOKEN} two"},
        {"token": TOKEN, "extra": 1},
    ],
)
def test_a_token_that_is_not_one_is_refused_without_an_echo(local, config, body, every_log):
    response = put(local, "/api/connections/replicate", body)
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert not (config.data_dir / TOKEN_FILE).exists()
    assert_no_token(response.text, every_log.text)


def test_saving_assetgen_stores_it_and_never_answers_its_token(local, config, every_log):
    response = put(local, "/api/connections/assetgen", {"url": f"{ASSETGEN}/", "token": TOKEN})
    assert response.status_code == 200
    assert response.json() == {"url": ASSETGEN, "token": "set"}
    path = config.data_dir / ASSETGEN_FILE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == {"url": ASSETGEN, "token": TOKEN}
    got = local.get("/api/connections")
    assert got.json()["assetgen"] == {"url": ASSETGEN, "token": "set"}
    assert_no_token(response.text, got.text, every_log.text)


def test_assetgen_token_absent_keeps_and_null_removes(local, config):
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    assert put(local, "/api/connections/assetgen", {"url": "http://localhost:8765"}).json() == {
        "url": "http://localhost:8765",
        "token": "set",
    }
    assert load_assetgen(config.data_dir).token == TOKEN
    assert put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": None}).json()["token"] == "unset"
    assert load_assetgen(config.data_dir).token is None
    assert put(local, "/api/connections/assetgen", {"url": ASSETGEN}).json()["token"] == "unset"


def test_assetgen_without_a_token(local):
    assert put(local, "/api/connections/assetgen", {"url": ASSETGEN}).json() == {"url": ASSETGEN, "token": "unset"}


@pytest.mark.parametrize(
    "body",
    [
        {"url": "http://169.254.169.254/"},
        {"url": "file:///etc/passwd"},
        {"url": "http://8.8.8.8"},
        {"url": "http://localhost:8765/../../"},
        {"url": f"http://{TOKEN}@127.0.0.1:8765", "token": TOKEN},
        {"url": 5},
        {},
        {"url": ASSETGEN, "token": 7},
        {"url": ASSETGEN, "token": [TOKEN]},
        {"url": ASSETGEN, "token": ""},
        {"url": ASSETGEN, "token": TOKEN, "extra": True},
    ],
)
def test_assetgen_refuses_a_bad_url_or_token_without_an_echo(local, config, body, every_log):
    response = put(local, "/api/connections/assetgen", body)
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert not (config.data_dir / ASSETGEN_FILE).exists()
    assert_no_token(response.text, every_log.text)


def test_assetgen_is_offered_and_withdrawn_without_a_restart(local, remote):
    """Saving its URL registers assetgen, live: `/api/backends` lists it with the models it answers; removing it
    drops it."""
    remote.models = [
        {"id": "flux-schnell", "kind": "image", "backend": "replicate", "price": "~$0.003 / image"},
        {"id": "pixel-local", "kind": "image", "backend": "local", "price": "free (local CPU)"},
    ]
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    (offered,) = [p for p in local.get("/api/backends").json()["providers"] if p["id"] == "assetgen"]
    assert offered["models"] == ["flux-schnell", "pixel-local"]
    assert offered["model_info"]["pixel-local"] == {
        "label": "pixel-local",
        "backend": "local",
        "price": "free (local CPU)",
        "paid": False,
    }
    assert offered["problem"] is None
    assert [r.headers["Authorization"] for r in remote.requests] == [f"Bearer {TOKEN}"]
    delete(local, "/api/connections/assetgen")
    assert "assetgen" not in [p["id"] for p in local.get("/api/backends").json()["providers"]]


def test_assetgen_down_is_offered_with_its_problem(local):
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    (offered,) = [p for p in local.get("/api/backends").json()["providers"] if p["id"] == "assetgen"]
    assert offered["models"] == []
    assert offered["problem"] == f"assetgen isn't answering at {ASSETGEN}"


def test_a_new_url_reaches_assetgen_at_once(local, app, remote):
    put(local, "/api/connections/assetgen", {"url": "http://127.0.0.1:47897"})
    first = app.state.registries.images.get("assetgen")
    put(local, "/api/connections/assetgen", {"url": ASSETGEN})
    assert app.state.registries.images.get("assetgen") is not first
    assert app.state.registries.images.get("assetgen").url == ASSETGEN


def test_delete_assetgen(local, config):
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    response = delete(local, "/api/connections/assetgen")
    assert response.status_code == 200
    assert response.json() == {"url": None, "token": "unset"}
    assert not (config.data_dir / ASSETGEN_FILE).exists()


def test_each_change_publishes_preferences_without_a_token(local, app):
    put(local, "/api/connections/replicate", {"token": TOKEN})
    delete(local, "/api/connections/replicate")
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    delete(local, "/api/connections/assetgen")
    events = [event for event in published(app) if event.type == "preferences"]
    assert len(events) == 4
    assert_no_token(*(json.dumps(event.data) for event in events))


def test_replicate_test_succeeds(local, remote, every_log):
    put(local, "/api/connections/replicate", {"token": TOKEN})
    response = local.post("/api/connections/replicate/test", json={})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Replicate accepted the token."}
    assert remote.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    assert_no_token(response.text, every_log.text)


@pytest.mark.parametrize("status", [401, 403, 500])
def test_a_refused_test_holds_no_token(local, remote, status, every_log):
    remote.replicate = status
    put(local, "/api/connections/replicate", {"token": TOKEN})
    response = local.post("/api/connections/replicate/test", json={})
    assert response.status_code == 200
    answer = response.json()
    assert answer["ok"] is False
    assert str(status) in answer["message"]
    if status in (401, 403):
        assert answer["message"] == f"Replicate refused the token (HTTP {status})."
    assert_no_token(response.text, every_log.text)


def test_replicate_test_without_a_token(local, remote):
    response = local.post("/api/connections/replicate/test", json={})
    assert response.json() == {"ok": False, "message": "No Replicate token is set."}
    assert remote.requests == []


def test_replicate_test_when_it_cant_be_reached(local, app, every_log):
    def unreachable(request):
        raise httpx.ConnectError(f"refused, headers {dict(request.headers)}")

    app.state.connections_transport = httpx.MockTransport(unreachable)
    put(local, "/api/connections/replicate", {"token": TOKEN})
    response = local.post("/api/connections/replicate/test", json={})
    assert response.json() == {"ok": False, "message": "Replicate can't be reached (ConnectError)."}
    assert_no_token(response.text, every_log.text)


def test_assetgen_test_reads_its_models(local, remote, every_log):
    remote.models = [
        {"id": "flux-schnell", "kind": "image", "backend": "replicate"},
        {"id": "flux-dev", "kind": "image", "backend": "replicate"},
        {"id": "sao-small", "kind": "audio", "backend": "local"},
    ]
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    response = local.post("/api/connections/assetgen/test", json={})
    assert response.json() == {"ok": True, "message": "assetgen answered, with 2 image models."}
    assert remote.requests[-1].headers["authorization"] == f"Bearer {TOKEN}"
    assert_no_token(response.text, every_log.text)


def test_assetgen_test_sends_no_token_without_one(local, remote):
    put(local, "/api/connections/assetgen", {"url": ASSETGEN})
    assert local.post("/api/connections/assetgen/test", json={}).json()["ok"] is True
    assert "authorization" not in remote.requests[-1].headers


def test_assetgen_failing_holds_no_token(local, remote, every_log):
    remote.assetgen = 500
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    response = local.post("/api/connections/assetgen/test", json={})
    assert response.json() == {"ok": False, "message": "assetgen failed (500)."}
    assert_no_token(response.text, every_log.text)


def test_assetgen_test_without_assetgen(local, remote):
    response = local.post("/api/connections/assetgen/test", json={})
    assert response.json() == {"ok": False, "message": "assetgen isn't set up."}
    assert remote.requests == []


def test_assetgen_test_checks_the_url_again(local, config, remote):
    """Saved, then made to point elsewhere behind Delve's back: the guard runs at each connection too."""
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    (config.data_dir / ASSETGEN_FILE).write_text(json.dumps({"url": "http://8.8.8.8", "token": TOKEN}))
    remote.requests.clear()  # saving read the models from the URL as it was
    response = local.post("/api/connections/assetgen/test", json={})
    assert response.json()["ok"] is False
    assert remote.requests == []
    assert_no_token(response.text)


def test_an_unknown_connection_is_404(local):
    assert local.post("/api/connections/dropbox/test", json={}).status_code == 404


ROUTES = [
    ("GET", "/api/connections", None),
    ("PUT", "/api/connections/replicate", {"token": TOKEN}),
    ("DELETE", "/api/connections/replicate", {}),
    ("PUT", "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN}),
    ("DELETE", "/api/connections/assetgen", {}),
    ("POST", "/api/connections/replicate/test", {}),
    ("POST", "/api/connections/assetgen/test", {}),
    ("PUT", "/api/connections/email", {"provider": "log"}),
    ("DELETE", "/api/connections/email", {}),
    ("POST", "/api/connections/email/test", {}),
]


@pytest.fixture
def seat_client(app, storage):
    """A browser on the LAN holding a seat's token; `organiser=True` gives it the install's organiser rights."""
    from fastapi.testclient import TestClient

    clients = []

    def make(role="host", *, organiser=False):
        campaign = make_campaign(storage)
        token = new_seat_token()
        storage.seats.create(campaign.id, "Ana", "en", role, organiser=organiser, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_an_organiser_seat_gets_403(seat_client, config, method, path, body, every_log):
    client = seat_client(organiser=True)
    assert client.get("/api/preferences").status_code == 200, "the seat is an organiser"
    response = client.request(method, path, json=body)
    assert response.status_code == 403, path
    assert response.json() == {"error": "Only the install's owner can do this."}
    assert not (config.data_dir / TOKEN_FILE).exists()
    assert not (config.data_dir / ASSETGEN_FILE).exists()
    assert_no_token(response.text, every_log.text)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_a_player_seat_gets_403(seat_client, method, path, body):
    response = seat_client(role="player").request(method, path, json=body)
    assert response.status_code == 403, path


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_nobody_gets_401(lan, method, path, body):
    assert lan.request(method, path, json=body).status_code == 401, path


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_the_owner_gets_200(lan, token, remote, method, path, body):
    lan.headers["Authorization"] = f"Bearer {token}"
    response = lan.request(method, path, json=body)
    assert response.status_code == 200, path
    assert_no_token(response.text)


def test_a_planted_token_never_leaves_through_any_route(local, app, config, remote, every_log):
    """Both connections saved with the planted token: every Connections answer, the backends, the preferences and
    the published events hold none of it."""
    put(local, "/api/connections/replicate", {"token": TOKEN})
    put(local, "/api/connections/assetgen", {"url": ASSETGEN, "token": TOKEN})
    texts = [
        local.get("/api/connections").text,
        local.get("/api/backends").text,
        local.get("/api/preferences").text,
        local.post("/api/connections/replicate/test", json={}).text,
        local.post("/api/connections/assetgen/test", json={}).text,
    ]
    remote.replicate = remote.assetgen = 401
    texts += [
        local.post("/api/connections/replicate/test", json={}).text,
        local.post("/api/connections/assetgen/test", json={}).text,
    ]
    texts += [json.dumps(event.data) for event in published(app)]
    assert_no_token(*texts, every_log.text)



# ----- Google's login client (DEL-206) -----


def test_the_google_client_is_saved_kept_and_never_answered(local, config, every_log, monkeypatch):
    monkeypatch.setenv("DELVE_ALLOWED_HOSTS", "delve.example")
    response = put(local, "/api/connections/google", {"client_id": "id-1.apps", "client_secret": "GOCSPX-SECRET"})
    assert response.status_code == 200
    body = response.json()
    assert (body["client_id"], body["secret"]) == ("id-1.apps", "set")
    assert body["redirect_uris"] == [
        "https://delve.example/api/auth/google/callback",
        f"http://localhost:{config.port}/api/auth/google/callback",
    ]
    assert "GOCSPX-SECRET" not in local.get("/api/connections").text
    assert (config.data_dir / "oidc-google.json").stat().st_mode & 0o777 == 0o600
    kept = put(local, "/api/connections/google", {"client_id": "id-2.apps"})
    assert kept.json()["client_id"] == "id-2.apps"
    assert "GOCSPX-SECRET" in (config.data_dir / "oidc-google.json").read_text(), "the secret kept"
    refused = put(local, "/api/connections/google", {"client_id": "id 3", "client_secret": "a b"})
    assert refused.status_code == 422 and "a b" not in refused.text
    gone = delete(local, "/api/connections/google")
    assert gone.json()["secret"] == "unset" and not (config.data_dir / "oidc-google.json").exists()
    assert "GOCSPX-SECRET" not in every_log.text


def test_only_the_owner_sets_up_google(lan):
    assert put(lan, "/api/connections/google", {"client_id": "x", "client_secret": "y"}).status_code in (401, 403)


# ----- The Email connection (DEL-314) -----

MAIL_KEY = "em_SECRET_KEY_123"
EMAIL = {"provider": "emailit", "sender": "Delve <delve@example.org>", "public_url": "https://delve.example/", "key": MAIL_KEY}


def test_the_owner_reads_the_email_connection_unset(local):
    email = local.get("/api/connections").json()["email"]
    assert email == {
        "provider": "log",
        "sender": "",
        "public_url": "",
        "public_url_default": None,
        "key": "unset",
        "sent_today": 0,
        "waiting": 0,
        "failures": [],
    }


def test_the_default_public_url_is_the_one_allowed_host(local, monkeypatch):
    monkeypatch.setenv("DELVE_ALLOWED_HOSTS", "delve.example")
    email = local.get("/api/connections").json()["email"]
    assert email["public_url"] == "" and email["public_url_default"] == "https://delve.example"


def test_saving_email_says_set_and_never_echoes_the_key(local, config, every_log):
    response = put(local, "/api/connections/email", EMAIL)
    assert response.status_code == 200
    assert response.json()["key"] == "set"
    assert response.json()["public_url"] == "https://delve.example"
    got = local.get("/api/connections")
    assert got.json()["email"]["key"] == "set" and got.json()["email"]["sender"] == "Delve <delve@example.org>"
    path = config.data_dir / "emailit-key"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert MAIL_KEY not in response.text + got.text + every_log.text + json.dumps([e.data for e in published(local.app)])


def test_an_absent_key_keeps_the_stored_one(local, config):
    put(local, "/api/connections/email", EMAIL)
    answer = put(local, "/api/connections/email", {"provider": "emailit", "sender": "b@example.org"})
    assert answer.json()["key"] == "set" and answer.json()["sender"] == "b@example.org"
    assert (config.data_dir / "emailit-key").read_text().strip() == MAIL_KEY
    assert answer.json()["public_url"] == "https://delve.example", "an absent public URL is kept too"


def test_the_environment_key_wins(local, monkeypatch):
    monkeypatch.setenv("EMAILIT_API_KEY", "env-key")
    assert local.get("/api/connections").json()["email"]["key"] == "environment"


def test_email_delete_goes_back_to_log_and_removes_the_key(local, config):
    put(local, "/api/connections/email", EMAIL)
    response = delete(local, "/api/connections/email")
    assert response.status_code == 200
    assert response.json()["provider"] == "log" and response.json()["key"] == "unset"
    assert not (config.data_dir / "emailit-key").exists()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"provider": "smtp"},
        {"provider": 3},
        {"provider": "emailit", "sender": "not an address MAILSECRET"},
        {"provider": "emailit", "sender": "Delve <a@b.c>\nBcc: x@y.z"},
        {"provider": "emailit", "sender": 7},
        {"provider": "emailit", "public_url": "ftp://MAILSECRET.example"},
        {"provider": "emailit", "public_url": "MAILSECRET"},
        {"provider": "emailit", "key": "two words"},
        {"provider": "emailit", "key": 5},
        {"provider": "emailit", "extra": "MAILSECRET"},
    ],
)
def test_a_bad_email_body_is_422_and_quotes_nothing(local, config, body, every_log):
    response = put(local, "/api/connections/email", body)
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert "MAILSECRET" not in response.text + every_log.text and "two words" not in response.text
    assert not (config.data_dir / "mail.json").exists() and not (config.data_dir / "emailit-key").exists()


def give_address(storage, client=None):
    """The owner account `boss` with a confirmed address; with a client, logged in as it."""
    from tests.web.conftest import log_in, make_account

    account = make_account(storage, "boss", owner=True)
    storage.accounts.set_email(account.id, email="boss@example.org", email_pending=None)
    if client is not None:
        log_in(client, "boss")
    return storage.accounts.get(account.id)


def test_the_test_email_is_queued_for_the_owners_confirmed_address(local, storage, config, every_log):
    give_address(storage, local)
    response = local.post("/api/connections/email/test", json={})
    assert response.json() == {"ok": True, "message": "A test email is on its way to your confirmed address."}
    [queued] = storage.mail.due("9999", 10)
    assert queued.kind == "test"
    assert "boss@example.org" not in response.text + every_log.text


def test_the_test_email_follows_the_caller_account(app, storage, config):
    from fastapi.testclient import TestClient

    from tests.web.conftest import BASE_URL, log_in, make_account

    give_address(storage)
    second = make_account(storage, "second", owner=True)
    storage.accounts.set_email(second.id, email="second@example.org", email_pending=None)
    with TestClient(app, base_url=BASE_URL) as client:
        log_in(client, "second")
        assert client.post("/api/connections/email/test", json={}).json()["ok"] is True
    [queued] = storage.mail.due("9999", 10)
    assert queued.account_id == second.id


def test_the_test_email_without_a_confirmed_address(local, storage):
    from tests.web.conftest import log_in, make_account

    owner = make_account(storage, "boss", owner=True)
    storage.accounts.set_email(owner.id, email=None, email_pending="typed@example.org")
    log_in(local, "boss")
    response = local.post("/api/connections/email/test", json={})
    assert response.json() == {"ok": False, "message": "Add and confirm your own address in Preferences first."}
    assert storage.mail.due("9999", 10) == []


def test_the_test_email_when_emailit_lacks_its_settings(local, storage):
    give_address(storage, local)
    put(local, "/api/connections/email", {"provider": "emailit"})
    answer = local.post("/api/connections/email/test", json={}).json()
    assert answer["ok"] is False
    assert storage.mail.due("9999", 10) == []


def test_sent_today_and_failures_are_counted_without_addresses(local, storage):
    from datetime import UTC, datetime

    from delve.mail import outbox
    from delve.mail.compose import Composed

    account = give_address(storage, local)
    put(local, "/api/connections/email", {"provider": "emailit"})  # not set up: the sender holds what is queued
    now = datetime.now(UTC)
    ids = [outbox.queue(storage, account, "test", Composed("s", "t", "h"), now) for _ in range(5)]
    storage.mail.sent(ids[0], outbox.iso(now))
    storage.mail.failed(ids[1], outbox.iso(now), "Emailit refused it (HTTP 422)")
    storage.mail.dropped(ids[2], outbox.iso(now))
    email = local.get("/api/connections").json()["email"]
    assert email["sent_today"] == 1
    assert email["waiting"] == 2, "neither sent nor failed"
    assert email["failures"] == [{"kind": "test", "at": outbox.iso(now), "failure": "Emailit refused it (HTTP 422)"}], (
        "a dropped one (nobody should get it) is no failure to show"
    )
    assert "boss@example.org" not in json.dumps(email)
