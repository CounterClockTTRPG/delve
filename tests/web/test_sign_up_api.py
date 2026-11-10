"""Sign-up with approval (DEL-156): while the owner or an organiser has opened it, anyone may ask for a player's
account, which waits until one of them approves it (or rejects it, which deletes it); a pending account can't log in,
except that logging in on a table's join page approves it, since the host vouched for whoever has the link."""

import re

import pytest
from fastapi.testclient import TestClient

from delve.mail.settings import MailSettings, save, save_key
from delve.play import accounts
from delve.web.routes import sign_up
from tests.web.conftest import BASE_URL, PASSWORD, log_in, make_account
from tests.web.test_players_api import accounts_events
from tests.web.test_seats_identity import make_campaign

ASK = {"username": "Cyra", "password": PASSWORD, "display_name": "Cyra", "note": "Bo's friend from Tuesday."}


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
    make_account(storage, "otto", organiser=True)
    client = browser()
    log_in(client, "otto")
    return client


@pytest.fixture
def opened(organiser):
    assert organiser.put("/api/sign-up", json={"open": True}).json() == {"open": True}
    return organiser


def test_sign_up_is_closed_until_an_organiser_opens_it(app, lan, organiser, browser, storage):
    assert lan.get("/api/sign-up").json() == {"open": False}
    refused = lan.post("/api/sign-up", json=ASK)
    assert refused.status_code == 403 and "closed" in refused.json()["error"]
    assert storage.accounts.by_username("cyra") is None

    make_account(storage, "pia")
    player = browser()
    log_in(player, "pia")
    assert player.put("/api/sign-up", json={"open": True}).status_code == 403, "a player can't open it"
    assert lan.put("/api/sign-up", json={"open": True}).status_code == 401

    assert organiser.put("/api/sign-up", json={"open": True}).json() == {"open": True}
    assert lan.get("/api/sign-up").json() == {"open": True}
    assert organiser.put("/api/sign-up", json={"open": "yes"}).status_code == 422
    assert organiser.put("/api/sign-up", json={"open": False}).json() == {"open": False}


def test_the_switch_outlives_a_preferences_save(opened, storage):
    """It is kept beside the preferences, which a save of them leaves alone."""
    prefs = opened.get("/api/preferences").json()
    assert opened.put("/api/preferences", json={"choices": prefs["choices"], "language": "en"}).status_code == 200
    assert storage.settings.load()[sign_up.SETTING] is True


def test_a_sign_up_waits_for_approval(app, opened, lan, storage):
    made = lan.post("/api/sign-up", json=ASK)
    assert made.status_code == 201 and made.json() == {"username": "cyra", "pending": True}
    assert "delve_session" not in made.cookies, "nobody is logged in"
    cyra = storage.accounts.by_username("cyra")
    assert cyra.pending and cyra.request_note == "Bo's friend from Tuesday."
    assert accounts_events(app), "the organisers are told"

    refused = lan.post("/api/login", json={"username": "cyra", "password": PASSWORD})
    assert refused.status_code == 403 and "waits for approval" in refused.json()["error"]
    wrong = lan.post("/api/login", json={"username": "cyra", "password": "not the password"})
    assert wrong.status_code == 401, "a wrong password learns nothing"

    listed = {a["username"]: a for a in opened.get("/api/accounts").json()}
    assert listed["cyra"]["pending"] is True and listed["cyra"]["request_note"] == "Bo's friend from Tuesday."

    assert opened.post(f"/api/accounts/{cyra.id}/approve", json={}).json()["pending"] is False
    assert lan.post("/api/login", json={"username": "cyra", "password": PASSWORD}).status_code == 200
    again = opened.post(f"/api/accounts/{cyra.id}/approve", json={})
    assert again.status_code == 409


def test_a_rejected_sign_up_is_gone(opened, lan, storage, browser):
    lan.post("/api/sign-up", json=ASK)
    cyra = storage.accounts.by_username("cyra")
    make_account(storage, "pia")
    player = browser()
    log_in(player, "pia")
    assert player.request("DELETE", f"/api/accounts/{cyra.id}", json={}).status_code == 403
    assert player.post(f"/api/accounts/{cyra.id}/approve", json={}).status_code == 403

    assert opened.request("DELETE", f"/api/accounts/{cyra.id}", json={}).status_code == 204
    assert storage.accounts.get(cyra.id) is None
    assert opened.request("DELETE", f"/api/accounts/{cyra.id}", json={}).status_code == 404
    pia = storage.accounts.by_username("pia")
    assert opened.request("DELETE", f"/api/accounts/{pia.id}", json={}).status_code == 409, "only a sign-up is ever deleted"
    assert lan.post("/api/sign-up", json=ASK).status_code == 201, "its name is free again"


def test_sign_up_refusals(opened, lan, storage):
    make_account(storage, "ana")
    assert lan.post("/api/sign-up", json={**ASK, "username": "ANA"}).status_code == 409
    assert lan.post("/api/sign-up", json={**ASK, "password": "short"}).status_code == 422
    assert lan.post("/api/sign-up", json={**ASK, "note": "x" * 301}).status_code == 422
    assert lan.post("/api/sign-up", json={**ASK, "username": 7}).status_code == 422
    assert lan.post("/api/sign-up", json={**ASK, "language": "klingon"}).status_code == 422
    assert storage.accounts.by_username("cyra") is None


def test_a_sign_up_s_language_is_its_own(opened, lan, storage):
    assert lan.post("/api/sign-up", json={**ASK, "language": "nl"}).status_code == 201
    assert storage.accounts.by_username("cyra").profile.language == "nl"


def test_so_many_sign_ups_from_one_address(opened, lan, storage):
    for n in range(sign_up.PER_ADDRESS):
        assert lan.post("/api/sign-up", json={**ASK, "username": f"cyra{n}"}).status_code == 201
    slow = lan.post("/api/sign-up", json={**ASK, "username": "cyra9"})
    assert slow.status_code == 429 and "Retry-After" in slow.headers
    assert storage.accounts.by_username("cyra9") is None


def test_no_more_than_so_many_wait(opened, lan, storage, monkeypatch):
    monkeypatch.setattr(accounts, "PENDING_MAX", 1)
    assert lan.post("/api/sign-up", json=ASK).status_code == 201
    full = lan.post("/api/sign-up", json={**ASK, "username": "dora"})
    assert full.status_code == 429 and "try again later" in full.json()["error"]


def test_logging_in_on_a_join_page_approves_a_sign_up(opened, lan, storage):
    """The host shared the link: whoever has it may sit at the table, so a pending account that logs in there is let
    in. Any other link, or none, leaves it waiting."""
    lan.post("/api/sign-up", json=ASK)
    campaign = make_campaign(storage)
    bad = lan.post("/api/login", json={"username": "cyra", "password": PASSWORD, "join_token": "not-a-link"})
    assert bad.status_code == 403 and storage.accounts.by_username("cyra").pending
    wrong = lan.post("/api/login", json={"username": "cyra", "password": "not it", "join_token": campaign.join_token})
    assert wrong.status_code == 401 and storage.accounts.by_username("cyra").pending

    joined = lan.post("/api/login", json={"username": "cyra", "password": PASSWORD, "join_token": campaign.join_token})
    assert joined.status_code == 200 and joined.json()["account"]["username"] == "cyra"
    assert not storage.accounts.by_username("cyra").pending


# An address at sign-up (DEL-314): confirmed while the account waits, "You're in" once it is approved.

FAR = "2100-01-01T00:00:00+00:00"


@pytest.fixture
def mail_on(config, monkeypatch):
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.delenv("DELVE_ALLOWED_HOSTS", raising=False)
    save(
        config.data_dir,
        MailSettings(provider="emailit", sender="delve@example.org", public_url="https://delve.example"),
    )
    save_key(config.data_dir, "k-1")


def kinds(storage):
    return [m.kind for m in storage.mail.due(FAR, 50)]


def confirm_token(storage) -> str:
    [message] = [m for m in storage.mail.due(FAR, 50) if m.kind == "confirm"]
    [token] = re.findall(r"https://delve\.example/account/email/([\w-]+)", message.text)
    return token


def test_a_sign_up_with_an_address_gets_a_confirmation_and_stays_pending(opened, lan, storage, mail_on):
    made = lan.post("/api/sign-up", json={**ASK, "email": " cyra@example.org "})
    assert made.status_code == 201 and made.json() == {"username": "cyra", "pending": True}
    cyra = storage.accounts.by_username("cyra")
    assert cyra.pending and cyra.email is None and cyra.email_pending == "cyra@example.org"
    assert kinds(storage) == ["confirm"]
    assert "cyra@example.org" not in made.text


def test_the_link_confirms_before_approval_and_approval_says_you_are_in(opened, lan, storage, mail_on):
    lan.post("/api/sign-up", json={**ASK, "email": "cyra@example.org", "language": "nl"})
    assert lan.post("/api/account/email/confirm", json={"token": confirm_token(storage)}).status_code == 200
    cyra = storage.accounts.by_username("cyra")
    assert cyra.pending and cyra.email == "cyra@example.org"
    assert kinds(storage) == ["confirm"], "a pending account gets nothing else"

    assert opened.post(f"/api/accounts/{cyra.id}/approve", json={}).status_code == 200
    assert sorted(kinds(storage)) == ["approved", "confirm"]
    approved = next(m for m in storage.mail.due(FAR, 50) if m.kind == "approved")
    assert "https://delve.example/login" in approved.text and "cyra" in approved.text
    assert approved.subject == "Je bent binnen", "in the sign-up's language"


def test_approval_without_a_confirmed_address_queues_nothing(opened, lan, storage, mail_on):
    lan.post("/api/sign-up", json=ASK)
    cyra = storage.accounts.by_username("cyra")
    assert opened.post(f"/api/accounts/{cyra.id}/approve", json={}).status_code == 200
    assert kinds(storage) == []

    lan.post("/api/sign-up", json={**ASK, "username": "Dov", "email": "dov@example.org"})
    dov = storage.accounts.by_username("dov")
    assert opened.post(f"/api/accounts/{dov.id}/approve", json={}).status_code == 200
    assert kinds(storage) == ["confirm"], "an address never confirmed gets no approval mail"


def test_rejecting_voids_the_confirmation_link(opened, lan, storage, mail_on):
    lan.post("/api/sign-up", json={**ASK, "email": "cyra@example.org"})
    token = confirm_token(storage)
    cyra = storage.accounts.by_username("cyra")
    assert opened.request("DELETE", f"/api/accounts/{cyra.id}", json={}).status_code == 204
    assert lan.post("/api/account/email/confirm", json={"token": token}).status_code == 404


def test_a_bad_address_is_refused_before_the_account_is_made(opened, lan, storage, mail_on):
    refused = lan.post("/api/sign-up", json={**ASK, "email": "not an address"})
    assert refused.status_code == 422
    assert storage.accounts.by_username("cyra") is None


def test_the_address_is_ignored_while_mail_is_off(opened, lan, storage, monkeypatch):
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    made = lan.post("/api/sign-up", json={**ASK, "email": "cyra@example.org"})
    assert made.status_code == 201
    cyra = storage.accounts.by_username("cyra")
    assert cyra.email is None and cyra.email_pending is None and kinds(storage) == []
