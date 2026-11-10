"""Logging in, linking and signing up with Google through the API (DEL-206), over a fake provider: the browser is sent
to the provider and back, and lands on Delve's page with a code, or logged in."""

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from delve.web import oidc
from delve.web.routes.oidc import LOCAL_PATH, offered_here
from tests.fixtures.oidc import CLIENT, ISSUER, SPEC, FakeProvider
from tests.web.conftest import BASE_URL, PASSWORD, log_in, make_account


@pytest.fixture
def provider(app, config):
    fake = FakeProvider()
    app.state.oidc_providers = {"google": SPEC}
    app.state.oidc = fake.client()
    oidc.save_client(config.data_dir, "google", CLIENT.client_id, CLIENT.client_secret)
    return fake


@pytest.fixture
def browser(app):
    """A browser on another device, logged in to nothing."""
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


def link_url(client, password=PASSWORD) -> str:
    """Linking's start, its ticket got with the account's password, as Profile gets it."""
    answer = client.post("/api/auth/google/link", json={"password": password})
    assert answer.status_code == 200, answer.text
    return answer.json()["url"]


def go(client, provider, mode="login", code="code-1", **params):
    """Start the flow, let the provider send the browser back with `code`: the callback's answer. Linking starts
    with a ticket, unless the test gives `ticket` itself."""
    if mode == "link" and "ticket" not in params:
        logged_in = client.get("/api/me").json().get("account") is not None
        if logged_in:
            params["ticket"] = parse_qs(urlsplit(link_url(client)).query)["ticket"][0]
    started = client.get("/api/auth/google/start", params={"mode": mode, **params}, follow_redirects=False)
    assert started.status_code == 303, started.text
    location = started.headers["location"]
    if not location.startswith(ISSUER):
        return started  # sent back to Delve's page before the provider
    query = {name: values[0] for name, values in parse_qs(urlsplit(location).query).items()}
    assert query["redirect_uri"] == f"{BASE_URL}/api/auth/google/callback"
    provider.give_code(
        code, redirect_uri=query["redirect_uri"], challenge=query["code_challenge"], nonce=query["nonce"]
    )
    return client.get(
        "/api/auth/google/callback", params={"code": code, "state": query["state"]}, follow_redirects=False
    )


def landed(response) -> tuple[str, dict[str, str]]:
    assert response.status_code == 303, response.text
    parts = urlsplit(response.headers["location"])
    return parts.path, {name: values[0] for name, values in parse_qs(parts.query).items()}


def open_sign_up(storage):
    storage.settings.save({**storage.settings.load(), "sign_up_open": True})


# ----- which providers -----


def test_google_is_offered_once_the_owner_set_it_up(app, browser, config):
    assert browser.get("/api/auth/providers").json() == []
    app.state.oidc_providers = {"google": SPEC}
    oidc.save_client(config.data_dir, "google", "id", "secret")
    assert browser.get("/api/auth/providers").json() == [{"id": "google", "title": "Google"}]
    assert landed(browser.get("/api/auth/nope/start", follow_redirects=False)) == ("/login", {"oidc": "not-offered"})


def _request(host: str, scheme: str = "http", client: str = "192.168.1.9", headers=()) -> Request:
    raw = [(b"host", host.encode()), *((k.encode(), v.encode()) for k, v in headers)]
    scope = {"type": "http", "scheme": scheme, "headers": raw, "client": (client, 5000), "path": "/", "method": "GET"}
    return Request(scope)


def test_a_provider_sends_back_only_over_https_or_to_localhost():
    assert offered_here(_request("localhost:7810"))
    assert offered_here(_request("127.0.0.1:7810"))
    assert offered_here(_request("delve.example", scheme="https"))
    assert offered_here(_request("delve.example", client="127.0.0.1", headers=[("x-forwarded-proto", "https")]))
    assert not offered_here(_request("192.168.86.29:7810")), "the LAN address: Google won't send a browser there"
    assert not offered_here(_request("delve.example", client="10.0.0.5", headers=[("x-forwarded-proto", "https")]))


def test_next_is_a_path_on_delve():
    assert LOCAL_PATH.match("/play/cmp_1?x=1")
    for elsewhere in ("//evil.example", "/\\evil.example", "https://evil.example", "evil", "/ a"):
        assert not LOCAL_PATH.match(elsewhere)


# ----- logging in -----


def test_an_unknown_google_account_is_told_to_sign_up_or_link(provider, browser):
    assert landed(go(provider=provider, client=browser)) == ("/login", {"oidc": "unknown"})
    assert browser.get("/api/me").status_code == 401


def test_a_linked_google_account_logs_in_to_next(provider, browser, player, storage):
    assert landed(go(player, provider, "link")) == ("/preferences", {"tab": "profile", "oidc": "linked"})
    response = go(browser, provider, next="/play/cmp_00000000000a", code="code-2")
    assert response.headers["location"] == "/play/cmp_00000000000a"
    assert "delve_session" in response.headers.get("set-cookie", "")
    assert browser.get("/api/me").json()["account"]["username"] == "ana"
    elsewhere = go(browser, provider, next="//evil.example", code="code-3")
    assert elsewhere.headers["location"] == "/"


def test_the_flow_cookie_ends_with_the_callback(provider, browser):
    response = go(browser, provider)
    assert 'delve_oidc=""' in response.headers["set-cookie"] or "delve_oidc=;" in response.headers["set-cookie"]


def test_a_callback_without_its_flow_or_with_another_state_has_expired(provider, browser):
    lost = browser.get("/api/auth/google/callback", params={"code": "c", "state": "s"}, follow_redirects=False)
    assert landed(lost) == ("/login", {"oidc": "expired"})
    browser.get("/api/auth/google/start", follow_redirects=False)
    forged = browser.get("/api/auth/google/callback", params={"code": "c", "state": "other"}, follow_redirects=False)
    assert landed(forged) == ("/login", {"oidc": "expired"})


def test_a_login_cancelled_at_the_provider_or_refused_by_it(provider, browser):
    started = browser.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
    cancelled = browser.get(
        "/api/auth/google/callback", params={"error": "access_denied", "state": state}, follow_redirects=False
    )
    assert landed(cancelled) == ("/login", {"oidc": "cancelled"})
    provider.token_status = 500
    assert landed(go(browser, provider)) == ("/login", {"oidc": "failed"})


def test_a_disabled_or_waiting_account_doesn_t_log_in(provider, browser, player, storage):
    go(player, provider, "link")
    ana = storage.accounts.by_username("ana")
    storage.accounts.set_disabled(ana.id, "2026-10-27T10:00:00+00:00")
    assert landed(go(browser, provider, code="code-2")) == ("/login", {"oidc": "disabled"})


# ----- linking -----


def test_linking_needs_an_account_and_keeps_one_per_provider(provider, app, storage, player):
    with TestClient(app, base_url=BASE_URL) as stranger:
        assert landed(go(stranger, provider, "link")) == ("/login", {"oidc": "not-logged-in"})
    go(player, provider, "link")
    listed = player.get("/api/account/identities").json()
    assert listed["has_password"] is True
    assert [(i["provider"], i["title"], i["email"]) for i in listed["identities"]] == [
        ("google", "Google", "ana@example.org")
    ]
    provider.claims = {"sub": "other-google-account"}
    assert landed(go(player, provider, "link", code="code-2")) == (
        "/preferences",
        {"tab": "profile", "oidc": "has-one"},
    )

    make_account(storage, "bors")
    with TestClient(app, base_url=BASE_URL) as bors:
        log_in(bors, "bors")
        provider.claims = {}
        assert landed(go(bors, provider, "link", code="code-3"))[1]["oidc"] == "conflict", "Ana's Google account"
        assert bors.get("/api/account/identities").json()["identities"] == []


def test_unlinking_never_takes_the_last_way_in(provider, player, storage):
    go(player, provider, "link")
    assert player.request("DELETE", "/api/account/identities/google", json={}).status_code == 204
    assert player.get("/api/account/identities").json()["identities"] == []
    refused = player.request("DELETE", "/api/account/identities/google", json={})
    assert refused.status_code == 422


# ----- signing up -----


ASK = {"username": "cyra", "display_name": "Cyra", "note": "Bo's friend", "language": "nl"}


def test_a_google_sign_up_waits_for_approval_without_a_password(provider, browser, storage, app):
    assert landed(go(browser, provider, "signup", **ASK)) == ("/sign-up", {"oidc": "closed"})
    open_sign_up(storage)
    assert landed(go(browser, provider, "signup", code="code-2", **ASK)) == (
        "/sign-up",
        {"oidc": "waiting", "username": "cyra"},
    )
    cyra = storage.accounts.by_username("cyra")
    assert (cyra.pending, cyra.has_password, cyra.profile.display_name, cyra.profile.language) == (
        True,
        False,
        "Cyra",
        "nl",
    )
    assert cyra.request_note == "Bo's friend"
    assert storage.account_identities.get("google", "1083").account_id == cyra.id
    assert landed(go(browser, provider, code="code-3")) == ("/login", {"oidc": "pending"})
    again = go(browser, provider, "signup", code="code-4", **{**ASK, "username": "cyra2"})
    assert landed(again) == ("/login", {"oidc": "pending"}), "a second sign-up with it is a login"
    assert storage.accounts.by_username("cyra2") is None


def test_a_sign_up_s_username_is_checked_before_the_provider(provider, browser, storage):
    open_sign_up(storage)
    make_account(storage, "cyra")
    assert landed(go(browser, provider, "signup", **ASK)) == ("/sign-up", {"oidc": "taken"})
    assert landed(go(browser, provider, "signup", **{**ASK, "username": "x"})) == ("/sign-up", {"oidc": "invalid"})
    assert not any(r.url.path == "/token" for r in provider.requests)


def test_an_approved_google_sign_up_logs_in(provider, browser, storage):
    open_sign_up(storage)
    go(browser, provider, "signup", **ASK)
    storage.accounts.approve(storage.accounts.by_username("cyra").id)
    response = go(browser, provider, code="code-2")
    assert response.headers["location"] == "/"
    assert browser.get("/api/me").json()["account"]["username"] == "cyra"
    refused = browser.request("DELETE", "/api/account/identities/google", json={})
    assert refused.status_code == 422 and "set a password first" in refused.text
    assert PASSWORD  # the account has none: its Google account is its only way in


def test_the_callback_is_a_cross_site_navigation_the_guard_lets_through(provider, browser, player):
    """Google sends the browser back with a top-level GET from its own site: no `Origin`, `Sec-Fetch-Site:
    cross-site`. The guard refuses a request whose `Origin` isn't Delve's; this one has none and must pass."""
    started = player.get(link_url(player), follow_redirects=False)
    query = {name: values[0] for name, values in parse_qs(urlsplit(started.headers["location"]).query).items()}
    provider.give_code("c", redirect_uri=query["redirect_uri"], challenge=query["code_challenge"], nonce=query["nonce"])
    back = player.get(
        "/api/auth/google/callback",
        params={"code": "c", "state": query["state"]},
        headers={
            "sec-fetch-site": "cross-site",
            "sec-fetch-mode": "navigate",
            "referer": "https://accounts.google.com/",
        },
        follow_redirects=False,
    )
    assert landed(back) == ("/preferences", {"tab": "profile", "oidc": "linked"})


# ----- linking needs the password; start needs Delve's own page (the review of DEL-206) -----


def test_linking_asks_the_account_s_password(provider, player, storage):
    refused = player.post("/api/auth/google/link", json={"password": "not it at all"})
    assert refused.status_code == 401
    assert player.post("/api/auth/google/link", json={}).status_code == 422
    no_ticket = player.get("/api/auth/google/start", params={"mode": "link"}, follow_redirects=False)
    assert landed(no_ticket) == ("/preferences", {"tab": "profile", "oidc": "expired"})
    forged = player.get("/api/auth/google/start", params={"mode": "link", "ticket": "x.y"}, follow_redirects=False)
    assert landed(forged)[1]["oidc"] == "expired"
    assert storage.account_identities.list(storage.accounts.by_username("ana").id) == []


def test_a_link_ticket_is_the_account_s_own(provider, app, player, storage):
    ticket = parse_qs(urlsplit(link_url(player)).query)["ticket"][0]
    make_account(storage, "bors")
    with TestClient(app, base_url=BASE_URL) as bors:
        log_in(bors, "bors")
        stolen = bors.get("/api/auth/google/start", params={"mode": "link", "ticket": ticket}, follow_redirects=False)
        assert landed(stolen)[1]["oidc"] == "expired"


def test_wrong_link_passwords_count_against_the_login_throttle(provider, player):
    answers = [player.post("/api/auth/google/link", json={"password": f"wrong {n}"}).status_code for n in range(6)]
    assert answers[:5] == [401] * 5 and answers[5] == 429


def test_an_account_without_a_password_links_without_one(provider, browser, storage):
    storage.settings.save({"sign_up_open": True})
    go(browser, provider, "signup", **ASK)
    storage.accounts.approve(storage.accounts.by_username("cyra").id)
    go(browser, provider, code="code-2")
    assert browser.get("/api/account/identities").json()["has_password"] is False
    assert browser.post("/api/auth/google/link", json={}).status_code == 200


def test_another_site_can_t_start_a_flow(provider, player, browser):
    for mode, page in (("login", "/login"), ("signup", "/sign-up")):
        sent = browser.get(
            "/api/auth/google/start",
            params={"mode": mode},
            headers={"sec-fetch-site": "cross-site"},
            follow_redirects=False,
        )
        assert landed(sent) == (page, {"oidc": "elsewhere"})
    url = link_url(player)
    sent = player.get(url, headers={"sec-fetch-site": "same-site"}, follow_redirects=False)
    assert landed(sent) == ("/preferences", {"tab": "profile", "oidc": "elsewhere"})
    typed = browser.get("/api/auth/google/start", headers={"sec-fetch-site": "none"}, follow_redirects=False)
    assert typed.headers["location"].startswith(ISSUER), "an address typed or a bookmark"


def test_a_reset_link_unlinks_the_outside_accounts(provider, player, storage, app):
    from datetime import UTC, datetime

    from delve.play import accounts

    go(player, provider, "link")
    ana = storage.accounts.by_username("ana")
    owner = make_account(storage, "olga", owner=True)
    token = accounts.make_link(storage, ana.id, "reset-password", datetime.now(UTC), by_owner=True)
    accounts.use_link(storage, token, "a brand new password", datetime.now(UTC))
    assert storage.account_identities.list(ana.id) == [], "whoever linked it may not hold the account now"
    assert owner.owner
