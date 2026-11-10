"""The Players page's API (players and tavern Task C6): organisers list and add accounts, make reset links, and
disable or enable player accounts; only an owner grants owner or organiser rights, or disables an owner's or an
organiser's account (the human's ruling of 2026-10-24)."""

import pytest
from fastapi.testclient import TestClient

from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, PASSWORD, log_in, make_account
from tests.web.test_preferences_api import published
from tests.web.test_seats_identity import make_campaign

NEW_PASSWORD = "a brand new password"


@pytest.fixture
def browser(app):
    clients = []

    def make():
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def organiser(storage, browser):
    """A LAN browser logged in as the organiser account `otto`."""
    make_account(storage, "otto", organiser=True)
    client = browser()
    log_in(client, "otto")
    return client


@pytest.fixture
def owner(storage, browser):
    """A LAN browser logged in as the owner account `olga`."""
    make_account(storage, "olga", owner=True)
    client = browser()
    log_in(client, "olga")
    return client


def accounts_events(app):
    return [event for event in published(app) if event.type == "accounts"]


def test_list_needs_an_organiser(app, storage, browser, local, organiser):
    make_account(storage)
    player = browser()
    log_in(player)
    refused = player.get("/api/accounts")
    assert refused.status_code == 403 and refused.json() == {"error": "This needs the organiser role."}
    token = new_seat_token()
    storage.seats.create(make_campaign(storage).id, "Bo", "en", "player", token_hash=token_hash(token))
    seated = browser()
    seated.cookies.set(SEAT_COOKIE, token)
    assert seated.get("/api/accounts").status_code == 403
    assert organiser.get("/api/accounts").status_code == 200
    listed = local.get("/api/accounts")
    assert listed.status_code == 200
    assert [a["username"] for a in listed.json()] == ["otto", "ana"], "oldest first"
    assert browser().get("/api/accounts").status_code == 401


def test_the_list(storage, local):
    ana = make_account(storage)
    campaign, other = make_campaign(storage), make_campaign(storage, "Friday")
    storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    storage.seats.create(other.id, "Ana", "en", "player", account_id=ana.id)
    [listed] = local.get("/api/accounts").json()
    assert listed == {
        "id": ana.id,
        "username": "ana",
        "display_name": "ana",
        "organiser": False,
        "owner": False,
        "disabled": False,
        "has_password": True,
        "has_email": False,
        "created_at": ana.created_at,
        "tables": 2,
        "pending": False,
        "request_note": "",
        "reset_asked_at": None,
    }


def test_add_gives_a_set_password_link(app, storage, organiser, browser):
    response = organiser.post("/api/accounts", json={"username": " Cy.R ", "display_name": "Cy", "language": "nl"})
    assert response.status_code == 201
    made = response.json()
    assert made["account"]["username"] == "cy.r" and made["account"]["display_name"] == "Cy"
    assert made["account"]["has_password"] is False and made["account"]["organiser"] is False
    assert storage.accounts.by_username("cy.r").profile.language == "nl"
    url, expires_at = made["link"]["url"], made["link"]["expires_at"]
    assert url.startswith("http://localhost:7810/account/link/") and expires_at
    token = url.rsplit("/", 1)[1]
    assert accounts_events(app)[-1].scope == "organisers"

    cy = browser()
    assert cy.get(f"/api/account-links/{token}").json() == {"username": "cy.r", "kind": "set-password"}
    assert cy.post(f"/api/account-links/{token}", json={"password": NEW_PASSWORD}).status_code == 200
    assert cy.get("/api/me").json()["account"]["username"] == "cy.r", "logged in"
    assert organiser.post("/api/accounts", json={"username": "cy.r"}).status_code == 409
    assert organiser.post("/api/accounts", json={"username": "x"}).status_code == 422


def test_from_this_machine_the_link_uses_the_lan_address(local, monkeypatch):
    from delve.web import guard

    monkeypatch.setattr(guard, "lan_addresses", lambda: ["192.168.1.20"])
    made = local.post("/api/accounts", json={"username": "ana"}).json()
    assert made["link"]["url"].startswith("http://192.168.1.20:7810/account/link/")


def test_reset_link_replaces_the_old(app, storage, organiser, browser):
    ana = make_account(storage)
    first = organiser.post(f"/api/accounts/{ana.id}/reset-link", json={})
    assert first.status_code == 200
    second = organiser.post(f"/api/accounts/{ana.id}/reset-link", json={}).json()
    old, new = first.json()["url"].rsplit("/", 1)[1], second["url"].rsplit("/", 1)[1]
    client = browser()
    assert client.get(f"/api/account-links/{old}").status_code == 404, "the old unused link stops"
    assert client.get(f"/api/account-links/{new}").json() == {"username": "ana", "kind": "reset-password"}
    assert organiser.post("/api/accounts/acc_000000000000/reset-link", json={}).status_code == 404


def test_only_an_owner_resets_an_owner_or_an_organiser(storage, organiser, owner, browser):
    """Audit finding 1: an organiser made a reset link for the owner account and took it over."""
    olga, otto = storage.accounts.by_username("olga"), storage.accounts.by_username("otto")
    make_account(storage, "ivy", organiser=True)
    ivy = storage.accounts.by_username("ivy")
    for target in (olga, ivy, otto):
        refused = organiser.post(f"/api/accounts/{target.id}/reset-link", json={})
        assert refused.status_code == 403 and refused.json() == {"error": "Only an owner can do that."}
    token = new_seat_token()
    campaign = make_campaign(storage)
    storage.seats.create(campaign.id, "Sly", "en", "player", organiser=True, token_hash=token_hash(token))
    seated = browser()
    seated.cookies.set(SEAT_COOKIE, token)
    assert seated.get("/api/accounts").status_code == 200, "an organiser seat"
    assert seated.post(f"/api/accounts/{olga.id}/reset-link", json={}).status_code == 403
    assert seated.post(f"/api/accounts/{ivy.id}/reset-link", json={}).status_code == 403
    assert owner.post(f"/api/accounts/{ivy.id}/reset-link", json={}).status_code == 200
    assert owner.post(f"/api/accounts/{olga.id}/reset-link", json={}).status_code == 200
    ana = make_account(storage)
    assert organiser.post(f"/api/accounts/{ana.id}/reset-link", json={}).status_code == 200
    assert seated.post(f"/api/accounts/{ana.id}/reset-link", json={}).status_code == 200


def test_disable_ends_logins_and_login(app, storage, organiser, browser):
    ana = make_account(storage)
    client = browser()
    log_in(client)
    response = organiser.put(f"/api/accounts/{ana.id}", json={"disabled": True})
    assert response.status_code == 200 and response.json()["disabled"] is True
    assert client.get("/api/me").status_code == 401, "its open session"
    assert storage.login_sessions.list(ana.id) == []
    again = browser().post("/api/login", json={"username": "ana", "password": PASSWORD})
    assert again.status_code == 401 and again.json() == {"error": "Wrong username or password."}
    enabled = organiser.put(f"/api/accounts/{ana.id}", json={"disabled": False})
    assert enabled.json()["disabled"] is False
    assert browser().post("/api/login", json={"username": "ana", "password": PASSWORD}).status_code == 200
    assert [e.scope for e in accounts_events(app)] == ["organisers", "organisers"]


def test_only_the_owner_grants_organiser(storage, organiser, owner, browser):
    ana = make_account(storage)
    refused = organiser.put(f"/api/accounts/{ana.id}", json={"organiser": True})
    assert refused.status_code == 403 and refused.json() == {"error": "Only the owner of this Delve makes organisers."}
    assert storage.accounts.get(ana.id).organiser is False
    assert organiser.put(f"/api/accounts/{ana.id}", json={"owner": True}).status_code == 403
    made = owner.put(f"/api/accounts/{ana.id}", json={"organiser": True})
    assert made.status_code == 200 and made.json()["organiser"] is True
    assert owner.put(f"/api/accounts/{ana.id}", json={"organiser": False}).json()["organiser"] is False
    client = browser()
    log_in(client)
    assert client.get("/api/modules").status_code == 403


def test_only_the_owner_disables_an_organiser(storage, organiser, owner):
    otto = storage.accounts.by_username("otto")
    olga = storage.accounts.by_username("olga")
    make_account(storage, "ivy", organiser=True)
    ivy = storage.accounts.by_username("ivy")
    assert organiser.put(f"/api/accounts/{ivy.id}", json={"disabled": True}).status_code == 403
    assert organiser.put(f"/api/accounts/{olga.id}", json={"disabled": True}).status_code == 403
    assert owner.put(f"/api/accounts/{ivy.id}", json={"disabled": True}).json()["disabled"] is True
    own = organiser.put(f"/api/accounts/{otto.id}", json={"disabled": True})
    assert own.status_code == 422 and own.json() == {"error": "You can't disable your own account."}


def test_owner_rights(storage, owner, token, browser):
    olga = storage.accounts.by_username("olga")
    ana = make_account(storage)
    last = owner.put(f"/api/accounts/{olga.id}", json={"owner": False})
    assert last.status_code == 409, "the last owner account stays one"
    made = owner.put(f"/api/accounts/{ana.id}", json={"owner": True})
    assert made.status_code == 200 and made.json()["owner"] is True
    by_token = browser()
    by_token.headers["Authorization"] = f"Bearer {token}"
    assert by_token.put(f"/api/accounts/{olga.id}", json={"owner": False}).json()["owner"] is False
    assert by_token.put("/api/accounts/acc_000000000000", json={"disabled": True}).status_code == 404


def test_a_change_happens_whole_or_not_at_all(storage, organiser):
    ana = make_account(storage)
    refused = organiser.put(f"/api/accounts/{ana.id}", json={"disabled": True, "organiser": True})
    assert refused.status_code == 403
    assert storage.accounts.get(ana.id).disabled_at is None


def test_no_password_hash_in_the_list(storage, local):
    make_account(storage)
    stored = storage.accounts.password_hash(storage.accounts.by_username("ana").id)
    text = local.get("/api/accounts").text
    assert stored not in text and "scrypt" not in text and PASSWORD not in text


def test_a_refused_body_isnt_echoed(storage, owner):
    """Audit finding 9: a validation error's details held the value sent, such as a password in a wrong field."""
    ana = make_account(storage)
    refused = owner.put(f"/api/accounts/{ana.id}", json={"disabled": "pw-XYZZY-secret words"})
    assert refused.status_code == 422 and refused.json()["error"] == "invalid request"
    assert "XYZZY" not in refused.text
    [detail] = refused.json()["details"]
    assert detail["loc"] == ["body", "disabled"] and "input" not in detail
