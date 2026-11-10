"""A forgotten password without mail (DEL-268): the player asks on the login page, the request waits on the Players
page until an organiser makes the reset link (or dismisses it), and the answer never says which usernames exist."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from delve.mail.settings import MailSettings, save, save_key
from delve.play import accounts
from delve.play.clock import FakeClock
from delve.web.routes import password_help
from tests.web.conftest import BASE_URL, PASSWORD, log_in, make_account
from tests.web.test_players_api import accounts_events

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


@pytest.fixture
def organiser(app, storage):
    app.state.clock = FakeClock(NOW)
    make_account(storage, "otto", organiser=True)
    with TestClient(app, base_url=BASE_URL) as client:
        log_in(client, "otto")
        yield client


def listed(organiser, username):
    return next(a for a in organiser.get("/api/accounts").json() if a["username"] == username)


def test_asking_records_the_request_for_the_organisers(app, lan, storage, organiser):
    ana = make_account(storage, "ana")
    assert listed(organiser, "ana")["reset_asked_at"] is None
    before = len(accounts_events(app))

    asked = lan.post("/api/password-help", json={"username": " Ana "})

    assert asked.status_code == 202 and asked.json() == {"asked": True}
    assert storage.accounts.get(ana.id).reset_asked_at == NOW.isoformat()
    assert listed(organiser, "ana")["reset_asked_at"] == NOW.isoformat()
    assert len(accounts_events(app)) == before + 1


def test_the_answer_is_the_same_for_a_username_with_no_account(app, lan, storage):
    before = len(accounts_events(app))
    for username in ("nobody", "not a username!"):
        answer = lan.post("/api/password-help", json={"username": username})
        assert (answer.status_code, answer.json()) == (202, {"asked": True})
    assert len(accounts_events(app)) == before, "nothing is published for an account that isn't there"
    assert lan.post("/api/password-help", json={}).status_code == 422


def test_a_disabled_account_or_a_waiting_sign_up_records_nothing(lan, storage):
    gone = make_account(storage, "gone")
    storage.accounts.set_disabled(gone.id, NOW.isoformat())
    waiting = accounts.request_account(storage, "wait", PASSWORD)
    for username in ("gone", "wait"):
        assert lan.post("/api/password-help", json={"username": username}).status_code == 202
    assert storage.accounts.get(gone.id).reset_asked_at is None
    assert storage.accounts.get(waiting.id).reset_asked_at is None


def test_a_reset_link_answers_the_request(lan, storage, organiser):
    ana = make_account(storage, "ana")
    lan.post("/api/password-help", json={"username": "ana"})
    link = organiser.post(f"/api/accounts/{ana.id}/reset-link", json={}).json()
    assert storage.accounts.get(ana.id).reset_asked_at is None
    assert listed(organiser, "ana")["reset_asked_at"] is None

    lan.post("/api/password-help", json={"username": "ana"})
    token = link["url"].rsplit("/", 1)[1]
    accounts.use_link(storage, token, "a brand new password", NOW)
    assert storage.accounts.get(ana.id).reset_asked_at is None, "using an older link answers a later request too"


def test_dismissing_the_request(app, lan, storage, organiser):
    ana = make_account(storage, "ana")
    lan.post("/api/password-help", json={"username": "ana"})
    assert organiser.request("DELETE", f"/api/accounts/{ana.id}/reset-request", json={}).status_code == 204
    assert storage.accounts.get(ana.id).reset_asked_at is None
    assert organiser.request("DELETE", f"/api/accounts/{ana.id}/reset-request", json={}).status_code == 204, (
        "once dismissed, again is fine"
    )
    assert organiser.request("DELETE", "/api/accounts/acc_000000000000/reset-request", json={}).status_code == 404
    assert lan.request("DELETE", f"/api/accounts/{ana.id}/reset-request", json={}).status_code == 401


def test_a_request_lapses_after_a_week(app, lan, storage, organiser):
    make_account(storage, "ana")
    lan.post("/api/password-help", json={"username": "ana"})
    app.state.clock = FakeClock(NOW + timedelta(days=accounts.RESET_ASK_DAYS, seconds=1))
    assert listed(organiser, "ana")["reset_asked_at"] is None


def test_so_many_requests_from_one_address(lan, storage):
    make_account(storage, "ana")
    for _ in range(password_help.PER_ADDRESS):
        assert lan.post("/api/password-help", json={"username": "ana"}).status_code == 202
    slow = lan.post("/api/password-help", json={"username": "ana"})
    assert slow.status_code == 429 and "new password often" in slow.json()["error"] and "Retry-After" in slow.headers


# By email (DEL-314): a confirmed address gets the reset link itself; the owner's request is the way without one.

FAR = "2100-01-01T00:00:00+00:00"
LINK = r"https://delve\.example/account/link/([\w-]+)"


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.delenv("DELVE_ALLOWED_HOSTS", raising=False)


@pytest.fixture
def mail_on(config):
    save(
        config.data_dir,
        MailSettings(provider="emailit", sender="delve@example.org", public_url="https://delve.example"),
    )
    save_key(config.data_dir, "k-1")


def with_address(storage, username, address, **rights):
    account = make_account(storage, username, **rights)
    storage.accounts.set_email(account.id, email=address, email_pending=None)
    return storage.accounts.get(account.id)


def resets(storage):
    return [m for m in storage.mail.due(FAR, 50) if m.kind == "reset"]


def link_in(message) -> str:
    [token] = re.findall(LINK, message.text)
    return token


@pytest.mark.parametrize("mail", [True, False], ids=["mail on", "mail off"])
@pytest.mark.parametrize(
    "value",
    [
        "nobody",
        "bob",
        "ana",
        "ana@example.org",
        "who@example.org",
        "gone",
        "gone@example.org",
        "wait",
        "wait@example.org",
        "cyra",
        "cyra@example.org",
    ],
)
def test_the_answer_is_the_same_whoever_asks(request, local, storage, value, mail):
    """A disabled account, a sign-up still waiting, an address waiting for its confirmation: the same answer as any,
    with mail and without."""
    if mail:
        request.getfixturevalue("mail_on")
    with_address(storage, "ana", "ana@example.org")
    make_account(storage, "bob")
    gone = with_address(storage, "gone", "gone@example.org")
    storage.accounts.set_disabled(gone.id, NOW.isoformat())
    waiting = accounts.request_account(storage, "wait", PASSWORD)
    storage.accounts.set_email(waiting.id, email="wait@example.org", email_pending=None)
    cyra = make_account(storage, "cyra")
    storage.accounts.set_email(cyra.id, email=None, email_pending="cyra@example.org")
    answer = local.post("/api/password-help", json={"username": value})
    assert (answer.status_code, answer.json()) == (202, {"asked": True})


@pytest.mark.parametrize("value", ["ana", " ANA@Example.org "])
def test_a_confirmed_address_gets_the_link_and_no_request_waits(app, mail_on, local, storage, value):
    ana = with_address(storage, "ana", "ana@example.org")
    before = len(accounts_events(app))

    assert local.post("/api/password-help", json={"username": value}).status_code == 202

    [message] = resets(storage)
    assert message.account_id == ana.id and "ana@example.org" not in message.text
    assert storage.accounts.get(ana.id).reset_asked_at is None
    assert len(accounts_events(app)) == before, "no request for the organisers"
    found = accounts.link_for(storage, link_in(message), datetime.now(UTC))
    assert found is not None and found[1].kind == "reset-password"


def test_every_account_with_the_address_gets_its_own_link(mail_on, local, storage):
    ana = with_address(storage, "ana", "us@example.org")
    bob = with_address(storage, "bob", "us@example.org")
    gone = with_address(storage, "gone", "us@example.org")
    storage.accounts.set_disabled(gone.id, NOW.isoformat())

    local.post("/api/password-help", json={"username": "us@example.org"})

    assert sorted(m.account_id for m in resets(storage)) == sorted([ana.id, bob.id])


def test_an_account_without_an_address_still_asks_the_owner(app, mail_on, local, storage):
    bob = make_account(storage, "bob")
    before = len(accounts_events(app))
    local.post("/api/password-help", json={"username": "bob"})
    assert storage.accounts.get(bob.id).reset_asked_at is not None
    assert len(accounts_events(app)) == before + 1
    assert resets(storage) == []


def test_an_address_that_matches_nothing_does_nothing(app, mail_on, local, storage):
    bob = make_account(storage, "bob")
    before = len(accounts_events(app))
    local.post("/api/password-help", json={"username": "bob@example.org"})
    assert resets(storage) == [] and storage.accounts.get(bob.id).reset_asked_at is None
    assert len(accounts_events(app)) == before


def test_without_mail_it_asks_the_owner_as_before(app, local, storage):
    ana = with_address(storage, "ana", "ana@example.org")
    local.post("/api/password-help", json={"username": "ana@example.org"})
    assert storage.accounts.get(ana.id).reset_asked_at is None, "an address matches nothing"
    local.post("/api/password-help", json={"username": "ana"})
    assert storage.accounts.get(ana.id).reset_asked_at is not None
    assert resets(storage) == []


def test_an_owners_account_resets_itself_by_email(mail_on, local, storage):
    otto = with_address(storage, "otto", "otto@example.org", owner=True)
    local.post("/api/password-help", json={"username": "otto@example.org"})
    [message] = resets(storage)
    assert message.account_id == otto.id
    assert accounts.use_link(storage, link_in(message), "a brand new password", datetime.now(UTC)).id == otto.id


def test_a_flood_of_resets_sends_three_mails(mail_on, local, storage):
    with_address(storage, "ana", "ana@example.org")
    for _ in range(password_help.PER_ADDRESS):
        assert local.post("/api/password-help", json={"username": "ana"}).status_code == 202
    assert len(resets(storage)) == password_help.MAILS_PER_ACCOUNT == 3
    assert local.post("/api/password-help", json={"username": "ana"}).status_code == 429
