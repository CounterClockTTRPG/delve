"""`GET /api/mail/status` (DEL-314): whether Delve sends email, for anyone: only a flag, no settings."""

import re

import pytest
from fastapi.testclient import TestClient

from delve.mail import outbox
from delve.mail.settings import MailSettings, save, save_key
from tests.web.conftest import BASE_URL, log_in, make_account, session_for
from tests.web.test_join_api import browser, campaign, joined  # noqa: F401
from tests.web.test_preferences_api import published


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    monkeypatch.delenv("EMAILIT_API_KEY", raising=False)
    monkeypatch.delenv("DELVE_ALLOWED_HOSTS", raising=False)


def test_mail_is_off_until_provider_key_sender_and_public_url_are_set(local, lan):
    assert lan.get("/api/mail/status").json() == {"enabled": False}
    body = {"provider": "emailit", "sender": "delve@example.org"}
    assert local.put("/api/connections/email", json=body).status_code == 200
    assert lan.get("/api/mail/status").json() == {"enabled": False}
    body = {**body, "key": "k-1", "public_url": "https://delve.example"}
    assert local.put("/api/connections/email", json=body).status_code == 200
    assert lan.get("/api/mail/status").json() == {"enabled": True}
    assert local.request("DELETE", "/api/connections/email", json={}).status_code == 200
    assert lan.get("/api/mail/status").json() == {"enabled": False}


# A player's own address (DEL-314): only the account itself reads it, by its session.

FAR = "2100-01-01T00:00:00+00:00"


@pytest.fixture
def mail_on(config):
    save(
        config.data_dir,
        MailSettings(provider="emailit", sender="delve@example.org", public_url="https://delve.example"),
    )
    save_key(config.data_dir, "k-1")


def confirmation_token(storage) -> str:
    [message] = [m for m in storage.mail.due(FAR, 50) if m.kind == "confirm"][-1:]
    [token] = re.findall(r"https://delve\.example/account/email/([\w-]+)", message.text)
    return token


def test_a_typed_address_waits_for_its_link(player, storage, mail_on):
    assert player.get("/api/account/email").json() == {
        "email": None,
        "pending": None,
        "mail_host": True,
        "mail_board": True,
    }
    assert player.put("/api/account/email", json={"address": " ana@example.org "}).status_code == 202
    assert player.get("/api/account/email").json()["pending"] == "ana@example.org"
    assert [m.kind for m in storage.mail.due(FAR, 50)] == ["confirm"]


def test_the_link_confirms_without_a_login(player, storage, mail_on, app):
    player.put("/api/account/email", json={"address": "ana@example.org"})
    token = confirmation_token(storage)
    with TestClient(app, base_url=BASE_URL) as stranger:
        assert stranger.post("/api/account/email/confirm", json={"token": token}).status_code == 200
        refused = stranger.post("/api/account/email/confirm", json={"token": token})
    assert refused.status_code == 404 and refused.json()["error"] == "This link has expired or was used."
    assert player.get("/api/account/email").json()["email"] == "ana@example.org"


def test_a_bad_address_is_refused(player, mail_on):
    assert player.put("/api/account/email", json={"address": "not an address"}).status_code == 422
    assert player.put("/api/account/email", json={}).status_code == 422


def test_no_address_while_mail_isnt_set_up(player, storage):
    refused = player.put("/api/account/email", json={"address": "ana@example.org"})
    assert refused.status_code == 409 and refused.json()["error"] == "Email isn't set up on this Delve."
    assert storage.mail.due(FAR, 50) == []


def test_asking_for_links_is_limited_per_account(player, mail_on):
    for _ in range(5):
        assert player.put("/api/account/email", json={"address": "ana@example.org"}).status_code == 202
    assert player.put("/api/account/email", json={"address": "ana@example.org"}).status_code == 429


def test_removing_the_address_and_the_switches(player, storage, mail_on):
    ana = storage.accounts.by_username("ana")
    storage.accounts.set_email(ana.id, email="ana@example.org", email_pending=None)
    answer = player.put("/api/account/mail", json={"mail_board": False})
    assert answer.status_code == 200
    assert answer.json() == {"email": "ana@example.org", "pending": None, "mail_host": True, "mail_board": False}
    assert player.put("/api/account/mail", json={"mail_host": "no"}).status_code == 422
    assert player.request("DELETE", "/api/account/email", json={}).status_code == 204
    assert player.get("/api/account/email").json()["email"] is None


def test_only_the_account_reads_its_address(player, storage, local, lan):
    ana = storage.accounts.by_username("ana")
    storage.accounts.set_email(ana.id, email="ana@example.org", email_pending="next@example.org")
    bors = make_account(storage, "bors")
    session_for(storage, bors, local)
    assert local.get("/api/account/email").json()["email"] is None
    assert "ana@example.org" not in local.get("/api/account/email").text
    with TestClient(lan.app, base_url=BASE_URL) as nobody:
        assert nobody.get("/api/account/email").status_code == 401


def test_me_and_the_players_listing_carry_no_address(player, storage, app):
    ana = storage.accounts.by_username("ana")
    storage.accounts.set_email(ana.id, email="ana@example.org", email_pending="next@example.org")
    assert "@example.org" not in player.get("/api/me").text
    olga = make_account(storage, "olga", organiser=True)
    with TestClient(app, base_url=BASE_URL) as organiser:
        session_for(storage, olga, organiser)
        listing = organiser.get("/api/accounts")
    assert listing.status_code == 200 and "@example.org" not in listing.text
    marks = {each["username"]: each["has_email"] for each in listing.json()}
    assert marks == {"ana": True, "olga": False}


def test_an_off_link_turns_board_mail_off_without_a_session(player, storage, config, app):
    ana = storage.accounts.by_username("ana")
    token = outbox.off_token(config.data_dir, ana.id, "board")
    with TestClient(app, base_url=BASE_URL) as mail_client:
        assert mail_client.get(f"/api/mail/off/{token}").json() == {"group": "board"}
        one_click = mail_client.post(
            f"/api/mail/off/{token}",
            content="List-Unsubscribe=One-Click",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert one_click.status_code == 200 and one_click.json() == {"group": "board"}
        assert mail_client.post(f"/api/mail/off/{ana.id}.board.forged").status_code == 404
        assert mail_client.get(f"/api/mail/off/{ana.id}.board.forged").status_code == 404
    ana = storage.accounts.get(ana.id)
    assert (ana.mail_board, ana.mail_host) == (False, True)


def test_an_off_link_takes_no_other_body(lan, storage, config):
    ana = make_account(storage)
    token = outbox.off_token(config.data_dir, ana.id, "host")
    refused = lan.post(f"/api/mail/off/{token}", content="hi", headers={"content-type": "text/plain"})
    assert refused.status_code == 415
    assert storage.accounts.get(ana.id).mail_host is True
    assert lan.post(f"/api/mail/off/{token}").status_code == 200
    assert storage.accounts.get(ana.id).mail_host is False


# ----- a host writes to the table (DEL-314) -----


@pytest.fixture
def table(storage, campaign, joined, mail_on, browser):  # noqa: F811
    """The owner at the host's seat, five players with addresses, a quiet one (host mail off), one without an address
    and an observer; `table["host"]` is the owner's browser, `table["seats"]` the seats by name."""
    owner = make_account(storage, "boss", owner=True)
    found = {"seats": {}, "accounts": {}}
    people = [(name, "player") for name in ("Ana", "Bob", "Cy", "Di", "Ed", "Quiet", "Nomail")] + [("Obs", "observer")]
    for name, role in people:
        client, seat = joined(name, "en", role)
        account = storage.accounts.get(storage.seats.get(seat["id"]).account_id)
        if name != "Nomail":
            storage.accounts.set_email(account.id, email=f"{name.lower()}@example.org", email_pending=None)
        found["seats"][name], found["accounts"][name], found[name] = seat["id"], account, client
    storage.accounts.set_mail_switches(found["accounts"]["Quiet"].id, mail_host=False, mail_board=True)
    found["owner"] = owner
    log_in(host := browser("10.0.0.99"), "boss")
    found["host"] = host
    return found


def mail_path(campaign, end=""):  # noqa: F811
    return f"/api/campaigns/{campaign.id}/mail{end}"


def host_mail(storage):
    return [m for m in storage.mail.due(FAR, 50) if m.kind == "host"]


def test_a_message_to_five_players_is_five_mails_with_no_address_in_sight(app, storage, campaign, table):  # noqa: F811
    body = {"subject": "Your character", "message": "A question\nfor you", "reply_to_me": False}
    answer = table["host"].post(mail_path(campaign), json=body)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"sent": 5}
    rows = host_mail(storage)
    assert len(rows) == 5 and len({r.account_id for r in rows}) == 5
    assert table["accounts"]["Obs"].id not in {r.account_id for r in rows}
    mail = rows[0]
    assert mail.subject == f"{campaign.name}: Your character"
    assert "A question\nfor you" in mail.text and "aren't read" in mail.text
    assert f"https://delve.example/play/{campaign.id}" in mail.text
    assert all(r.unsubscribe and r.reply_to is None for r in rows)
    assert "@" not in answer.text and "example.org" not in repr(published(app))
    assert all("example.org" not in repr(r) for r in rows), "no address in the outbox"


def test_the_count_and_chosen_seats_only(storage, campaign, table):  # noqa: F811
    """Only the whole table is counted: a count or a send over chosen seats would say, player by player, who has an
    address."""
    host = table["host"]
    assert host.get(mail_path(campaign, "/count")).json() == {"count": 5}
    one = table["seats"]["Nomail"]
    assert host.get(mail_path(campaign, "/count"), params={"seats": one}).json() == {"count": 5}, "seats are ignored"
    chosen = [table["seats"]["Ana"], table["seats"]["Bob"], one]
    body = {"subject": "Hi", "message": "Just you two", "seats": chosen, "reply_to_me": False}
    assert host.post(mail_path(campaign), json=body).json() == {"sent": None}
    wanted = {table["accounts"]["Ana"].id, table["accounts"]["Bob"].id}
    assert {r.account_id for r in host_mail(storage)} == wanted


def test_no_count_while_mail_isnt_set_up(campaign, table, config):  # noqa: F811
    from delve.mail.settings import remove_key

    remove_key(config.data_dir)
    refused = table["host"].get(mail_path(campaign, "/count"))
    assert refused.status_code == 409 and refused.json()["error"] == "Email isn't set up on this Delve."


def test_reply_to_me_uses_the_hosts_confirmed_address_and_needs_one(storage, campaign, table):  # noqa: F811
    body = {"subject": "Hi", "message": "Write back", "reply_to_me": True}
    refused = table["host"].post(mail_path(campaign), json=body)
    assert refused.status_code == 422 and refused.json()["error"] == "Add and confirm your own address first."
    storage.accounts.set_email(table["owner"].id, email=None, email_pending="boss@example.org")
    assert table["host"].post(mail_path(campaign), json=body).status_code == 422, "a pending address isn't enough"
    assert host_mail(storage) == []
    storage.accounts.set_email(table["owner"].id, email="boss@example.org", email_pending=None)
    answer = table["host"].post(mail_path(campaign), json=body)
    assert answer.json() == {"sent": 5} and "@" not in answer.text
    rows = host_mail(storage)
    assert {r.reply_to for r in rows} == {"boss@example.org"}
    assert "Reply to this email" in rows[0].text


def test_a_player_seat_may_not_write(storage, campaign, table):  # noqa: F811
    body = {"subject": "Hi", "message": "Me too", "reply_to_me": False}
    assert table["Ana"].post(mail_path(campaign), json=body).status_code == 403
    assert table["Ana"].get(mail_path(campaign, "/count")).status_code == 403
    assert host_mail(storage) == []


def test_subject_message_and_seats_are_checked(storage, campaign, table):  # noqa: F811
    good = {"subject": "Hi", "message": "Hello", "reply_to_me": False}
    for bad in (
        {**good, "subject": ""},
        {**good, "subject": "x" * 121},
        {**good, "message": "  "},
        {**good, "message": "x" * 5001},
        {**good, "seats": "all"},
        {**good, "seats": [3]},
        {**good, "seats": []},
        {**good, "reply_to_me": "yes"},
        {"message": "Hello"},
    ):
        assert table["host"].post(mail_path(campaign), json=bad).status_code == 422, bad
    assert host_mail(storage) == []
    long = {**good, "subject": "x" * 120, "message": "x" * 5000}
    assert table["host"].post(mail_path(campaign), json=long).status_code == 200


def test_a_subject_is_one_line(storage, campaign, table):  # noqa: F811
    body = {"subject": "Two\r\nBcc: lines", "message": "Hello", "reply_to_me": False}
    assert table["host"].post(mail_path(campaign), json=body).status_code == 200
    assert {r.subject for r in host_mail(storage)} == {f"{campaign.name}: Two Bcc: lines"}


def test_the_eleventh_message_of_the_day_is_refused(storage, campaign, table):  # noqa: F811
    body = {"subject": "Hi", "message": "Again", "reply_to_me": False}
    for _ in range(10):
        assert table["host"].post(mail_path(campaign), json=body).status_code == 200
    refused = table["host"].post(mail_path(campaign), json=body)
    assert refused.status_code == 429
    assert refused.json()["error"] == "This table has sent its 10 messages for today: write again tomorrow."
    assert len(host_mail(storage)) == 50


def test_no_message_while_mail_isnt_set_up(storage, campaign, table, config):  # noqa: F811
    from delve.mail.settings import remove_key

    remove_key(config.data_dir)
    refused = table["host"].post(mail_path(campaign), json={"subject": "Hi", "message": "Hello", "reply_to_me": False})
    assert refused.status_code == 409 and refused.json()["error"] == "Email isn't set up on this Delve."
    assert host_mail(storage) == []
