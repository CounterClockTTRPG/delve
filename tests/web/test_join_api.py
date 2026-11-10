"""Joining a table with a link, and the host's controls (plan 4 Task 2; spec §7.2, §11; Review Focus 2): the join
link's routes and its rate limit, the invite, the seats and their roles, claiming and releasing characters, leaving,
and `/api/me`. Each change publishes `seats`.

Every invite asks for an account (players and tavern Task C5, Review Focus 3): a logged-in account joins as itself,
someone without one makes one through the invite, and an old seat token's seat can be kept by an account."""

import itertools
import re

import pytest
from fastapi.testclient import TestClient

from delve.play import profiles, seats
from delve.web import guard
from delve.web.routes import join as join_routes
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, PASSWORD, SESSION_COOKIE, log_in, make_account
from tests.web.test_preferences_api import published
from tests.web.test_seats_identity import make_campaign

YEAR = 365 * 24 * 60 * 60


@pytest.fixture
def campaign(storage):
    campaign = make_campaign(storage)
    seats.owner_seat(storage, campaign.id)
    return campaign


@pytest.fixture
def garrek(storage, campaign):
    return storage.characters.create(campaign.id, "Garrek")


@pytest.fixture
def browser(app):
    """`browser(address="10.0.0.7")`: a new browser on another device of the LAN."""
    clients = []

    def make(address="10.0.0.7"):
        client = TestClient(app, base_url=BASE_URL, client=(address, 50000))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def joined(browser, campaign):
    """`joined(name="Ana", language="nl", role="player")`: a browser that made an account through the campaign's
    invite, with `name` as its display name, and its seat."""
    numbers = itertools.count(1)

    def make(name="Ana", language="nl", role="player", *, address="10.0.0.7"):
        client = browser(address)
        username = f"{re.sub(r'[^a-z0-9]', '', name.lower())[:20] or 'p'}{next(numbers)}"
        body = {"username": username, "password": PASSWORD, "display_name": name, "language": language, "role": role}
        response = client.post(f"/api/join/{campaign.join_token}/account", json=body)
        assert response.status_code == 201, response.text
        return client, response.json()["seat"]

    return make


@pytest.fixture
def token_seat(app, storage, campaign):
    """`token_seat(name="Bo")`: a seat joined with a seat token before accounts, and a LAN browser holding it."""
    clients = []

    def make(name="Bo", role="player"):
        token = new_seat_token()
        seat = storage.seats.create(campaign.id, name, "en", role, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL, client=("10.0.0.30", 50000))
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        return seat, client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def seats_events(app):
    return [event.data for event in published(app) if event.type == "seats"]


# ----- the join link -----


def test_the_join_link_names_the_table_without_a_token(browser, campaign):
    response = browser().get(f"/api/join/{campaign.join_token}")
    assert response.status_code == 200
    assert response.json() == {
        "campaign": {
            "name": "Tuesday",
            "host": "Host",
            "module_title": "The Crypt",
            "description": "",
            "slots": None,
            "observers": "anyone",
            "taken": 0,
            "full": False,
            "house_rules": [],
            "next_sessions": [],
        },
        "languages": ["en", "nl", "fr", "de", "lv"],
        "you": None,
    }


def test_the_join_link_carries_the_accounts_profile_summary(storage, browser, campaign):
    """The join page draws "You are …" from `you.profile`, without asking for the account's profile."""
    ana = make_account(storage)
    client = browser()
    log_in(client)
    assert client.put("/api/account/profile", json={"display_name": "Ana", "avatar_emblem": "oak", "colour": "ember"}).status_code == 200
    profile = client.get(f"/api/join/{campaign.join_token}").json()["you"]["profile"]
    assert profile == {
        "account_id": ana.id,
        "display_name": "Ana",
        "pronouns": "",
        "avatar": {"emblem": "oak"},
        "colour": "ember",
    }


def test_the_join_link_names_a_logged_in_account(storage, browser, campaign):
    ana = make_account(storage)
    client = browser()
    log_in(client)
    assert client.get(f"/api/join/{campaign.join_token}").json()["you"] == {
        "account_id": ana.id,
        "display_name": "ana",
        "seat_id": None,
        "profile": profiles.summary(storage.accounts.get(ana.id)),
    }
    seat = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"}).json()["seat"]
    assert client.get(f"/api/join/{campaign.join_token}").json()["you"]["seat_id"] == seat["id"]


def test_an_unknown_join_link_is_404(browser):
    response = browser().get("/api/join/no-such-token")
    assert response.status_code == 404 and "error" in response.json()
    joining = browser().post("/api/join/no-such-token", json={"role": "player"})
    assert joining.status_code == 404


def test_join_needs_an_account(app, browser, local, token, token_seat, campaign):
    needs = {"error": "Log in or make an account to join."}
    response = browser().post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert response.status_code == 401 and response.json() == needs
    response = local.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert response.status_code == 401 and response.json() == needs, "the owner from this machine too"
    owner = browser().post(
        f"/api/join/{campaign.join_token}", json={"role": "player"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert owner.status_code == 401
    _, seated = token_seat()
    assert seated.post(f"/api/join/{campaign.join_token}", json={"role": "player"}).status_code == 401


def test_an_owner_account_has_its_seat_already(storage, browser, campaign):
    make_account(storage, "olga", owner=True)
    client = browser()
    log_in(client, "olga")
    response = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert response.status_code == 409 and response.json() == {"error": "The owner has a seat at every table already."}


def test_join_as_a_logged_in_account(app, storage, browser, campaign):
    ana = make_account(storage)
    storage.accounts.save_profile(ana.id, ana.profile.__class__("Ana the Bold", language="nl"))
    client = browser()
    log_in(client)
    response = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert response.status_code == 201
    body = response.json()
    assert body["campaign_id"] == campaign.id
    seat = body["seat"]
    assert (seat["name"], seat["language"], seat["role"], seat["characters"]) == ("Ana the Bold", "nl", "player", [])
    stored = storage.seats.get(seat["id"])
    assert stored.account_id == ana.id and not stored.organiser and not stored.owner
    assert "set-cookie" not in response.headers, "no delve_seat cookie: the account is the way in"
    assert seats_events(app) == [{"campaign_id": campaign.id}]
    assert client.get(f"/api/campaigns/{campaign.id}/story").status_code == 200


def test_join_with_a_name_of_its_own(storage, browser, campaign):
    make_account(storage)
    client = browser()
    log_in(client)
    seat = client.post(f"/api/join/{campaign.join_token}", json={"role": "observer", "name": "  Watcher "}).json()
    assert (seat["seat"]["name"], seat["seat"]["role"]) == ("Watcher", "observer")


def test_join_twice_keeps_one_seat(app, storage, browser, campaign):
    ana = make_account(storage)
    client = browser()
    log_in(client)
    first = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    second = client.post(f"/api/join/{campaign.join_token}", json={"role": "observer"})
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["seat"]["id"] == second.json()["seat"]["id"]
    assert second.json()["seat"]["role"] == "player", "the seat it has, as it is"
    live = [s for s in storage.seats.list(campaign.id) if s.account_id == ana.id and s.left_at is None]
    assert len(live) == 1
    assert seats_events(app) == [{"campaign_id": campaign.id}], "nothing changed the second time"


def test_join_race_answers_the_existing_seat(storage, browser, campaign, monkeypatch):
    """Two requests at once: the second looks before the first has made the seat, then its insert hits the unique
    index, and it answers the seat the first made."""
    ana = make_account(storage)
    client = browser()
    log_in(client)
    seat = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    real = storage.seats.for_account
    looks = []

    def for_account(account_id, campaign_id):
        looks.append(account_id)
        return None if len(looks) == 1 else real(account_id, campaign_id)

    monkeypatch.setattr(storage.seats, "for_account", for_account)
    response = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert response.status_code == 200 and response.json()["seat"]["id"] == seat.id
    assert [s.id for s in storage.seats.list(campaign.id) if s.account_id == ana.id] == [seat.id]


def test_make_an_account_by_invite(app, storage, browser, campaign):
    client = browser()
    body = {"username": " Ana ", "password": PASSWORD, "display_name": "Ana", "language": "NL", "role": "player"}
    response = client.post(f"/api/join/{campaign.join_token}/account", json=body)
    assert response.status_code == 201
    made = response.json()
    account = storage.accounts.by_username("ana")
    assert made["account"]["id"] == account.id and made["account"]["display_name"] == "Ana"
    assert made["campaign_id"] == campaign.id and made["seat"]["name"] == "Ana" and made["seat"]["language"] == "nl"
    assert storage.seats.get(made["seat"]["id"]).account_id == account.id
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=") and SEAT_COOKIE not in cookie
    me = client.get(f"/api/me?campaign={campaign.id}").json()
    assert me["principal"]["id"] == f"account:{account.id}" and me["seat"]["id"] == made["seat"]["id"]
    assert PASSWORD not in response.text


def test_invite_needed_to_make_one(storage, browser):
    body = {"username": "ana", "password": PASSWORD, "display_name": "Ana", "language": "en", "role": "player"}
    assert browser().post("/api/join/no-such-token/account", json=body).status_code == 404
    assert storage.accounts.list() == []


def test_taken_username_409(storage, browser, campaign):
    make_account(storage)
    body = {"username": "ANA", "password": PASSWORD, "display_name": "Ana", "language": "en", "role": "player"}
    response = browser().post(f"/api/join/{campaign.join_token}/account", json=body)
    assert response.status_code == 409 and response.json() == {"error": "That username is taken."}
    assert [s for s in storage.seats.list(campaign.id) if not s.owner] == [], "no seat either"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"password": "short"}, "A password has at least 10 characters."),
        ({"username": "a b"}, "A username has 3 to 32 characters: a to z, 0 to 9, '.', '_' and '-'."),
        ({"display_name": " "}, "A name has 1 to 40 characters."),
        ({"language": "dutch"}, "A language is a code of 2 or 3 letters, such as en or nl."),
        ({"role": "host"}, "Join as a player or an observer."),
        ({"password": None}, "Send the fields as text."),
    ],
)
def test_making_an_account_refuses(storage, browser, campaign, change, error):
    body = {"username": "ana", "password": PASSWORD, "display_name": "Ana", "language": "en", "role": "player"}
    response = browser().post(f"/api/join/{campaign.join_token}/account", json={**body, **change})
    assert response.status_code == 422 and response.json() == {"error": error}
    assert storage.accounts.list() == []


def test_an_invite_makes_at_most_25_accounts(app, storage, browser, campaign, local):
    """Audit finding 8: one leaked join link could make accounts without end."""
    body = {"password": PASSWORD, "display_name": "Guest", "language": "en", "role": "observer"}
    for n in range(25):
        made = browser(f"10.0.{n}.7").post(f"/api/join/{campaign.join_token}/account", json={**body, "username": f"g{n:03}"})
        assert made.status_code == 201, made.text
    refused = browser("10.0.99.7").post(f"/api/join/{campaign.join_token}/account", json={**body, "username": "g999"})
    assert refused.status_code == 429
    assert refused.json() == {"error": "This join link has made 25 accounts already: ask the host for a new one."}
    assert storage.accounts.by_username("g999") is None
    fresh = local.post(f"/api/campaigns/{campaign.id}/invite", json={}).json()["join_token"]
    again = browser("10.0.99.7").post(f"/api/join/{fresh}/account", json={**body, "username": "g999"})
    assert again.status_code == 201, "a new invite counts again"


def test_join_limit_by_forwarded_address(app, campaign, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(join_routes, "clock", lambda: now[0])
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        for n in range(10):
            forged = {"X-Forwarded-For": f"10.0.0.{n}, 203.0.113.9"}
            assert tunnel.get(f"/api/join/{campaign.join_token}", headers=forged).status_code == 200
        refused = tunnel.get(f"/api/join/{campaign.join_token}", headers={"X-Forwarded-For": "203.0.113.9"})
        assert refused.status_code == 429
        other = tunnel.get(f"/api/join/{campaign.join_token}", headers={"X-Forwarded-For": "198.51.100.4"})
        assert other.status_code == 200, "another visitor through the same tunnel"


def test_keep_this_seat(app, storage, campaign, token_seat):
    old, client = token_seat()
    ana = make_account(storage)
    log_in(client)
    me = client.get(f"/api/me?campaign={campaign.id}").json()
    assert me["seat"] is None and me["keepable_seat"] == {"id": old.id, "name": "Bo"}
    response = client.post(f"/api/campaigns/{campaign.id}/seats/keep", json={})
    assert response.status_code == 200 and response.json()["id"] == old.id
    assert storage.seats.get(old.id).account_id == ana.id
    cookie = response.headers["set-cookie"]
    assert cookie.startswith((f'{SEAT_COOKIE}=""', f"{SEAT_COOKIE}=;")) and "max-age=0" in cookie.lower()
    client.cookies.delete(SEAT_COOKIE)
    me = client.get(f"/api/me?campaign={campaign.id}").json()
    assert me["seat"]["id"] == old.id and me["keepable_seat"] is None, "the old token no longer needed"
    assert client.get(f"/api/campaigns/{campaign.id}/story").status_code == 200
    assert {"campaign_id": campaign.id} in seats_events(app)


def test_a_kept_seat_s_old_token_stops_working(app, storage, campaign, token_seat):
    """Audit finding 2: a copy of the token kept the seat, even once its account was disabled."""
    old, client = token_seat()
    token = client.cookies.get(SEAT_COOKIE)
    copy = TestClient(app, base_url=BASE_URL, client=("10.0.0.31", 50000))
    copy.__enter__()
    try:
        copy.cookies.set(SEAT_COOKIE, token)
        assert copy.get("/api/me").json()["principal"]["id"] == f"seat:{old.id}"
        make_account(storage)
        log_in(client)
        assert client.post(f"/api/campaigns/{campaign.id}/seats/keep", json={}).status_code == 200
        assert storage.seats.by_token_hash(token_hash(token)) is None, "the token is gone"
        assert copy.get("/api/me").status_code == 401
        assert copy.get(f"/api/campaigns/{campaign.id}/play/state").status_code == 401
    finally:
        copy.__exit__(None, None, None)


def test_keep_refused_with_a_seat_already(storage, campaign, token_seat):
    old, client = token_seat()
    ana = make_account(storage)
    storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    log_in(client)
    assert client.get(f"/api/me?campaign={campaign.id}").json()["keepable_seat"] is None
    response = client.post(f"/api/campaigns/{campaign.id}/seats/keep", json={})
    assert response.status_code == 409 and response.json() == {"error": "You have a seat at this table already."}
    assert storage.seats.get(old.id).account_id is None


def test_keep_needs_such_a_seat(app, storage, campaign, token_seat, browser, local):
    make_account(storage)
    client = browser()
    log_in(client)
    assert client.post(f"/api/campaigns/{campaign.id}/seats/keep", json={}).status_code == 404, "no seat token"
    other = make_campaign(storage, "Friday")
    old, holder = token_seat()
    log_in(holder)
    assert holder.post(f"/api/campaigns/{other.id}/seats/keep", json={}).status_code == 404, "another table's seat"
    seats.leave(storage, old)
    assert holder.post(f"/api/campaigns/{campaign.id}/seats/keep", json={}).status_code == 404, "a seat that left"
    refused = local.post(f"/api/campaigns/{campaign.id}/seats/keep", json={})
    assert refused.status_code == 403 and refused.json() == {"error": "Log in to an account first."}


def test_rejoin_after_leaving(storage, browser, campaign):
    make_account(storage)
    client = browser()
    log_in(client)
    first = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"}).json()["seat"]
    assert client.post(f"/api/campaigns/{campaign.id}/leave", json={}).status_code == 204
    refused = client.get(f"/api/campaigns/{campaign.id}/story")
    assert refused.status_code == 403 and refused.json() == {"error": "You have no seat at this table."}
    again = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert again.status_code == 201 and again.json()["seat"]["id"] != first["id"]
    assert client.get(f"/api/campaigns/{campaign.id}/story").status_code == 200


def test_a_joined_seat_opens_the_play_routes(joined, campaign, garrek):
    ana, seat = joined()
    assert ana.get("/api/me").json()["account"]["display_name"] == "Ana"
    assert ana.get(f"/api/me?campaign={campaign.id}").json()["seat"]["id"] == seat["id"]
    assert ana.get(f"/api/campaigns/{campaign.id}/story").status_code == 200
    assert ana.get(f"/api/campaigns/{campaign.id}/play/state").status_code == 200
    assert ana.get(f"/api/campaigns/{campaign.id}/characters").status_code == 200
    assert ana.get(f"/api/campaigns/{campaign.id}/seats").status_code == 200
    assert ana.get("/api/modules").status_code == 403, "a player account is no organiser"
    assert ana.get(f"/api/campaigns/{campaign.id}/invite").status_code == 403, "a player is no host"


def test_the_same_name_twice_gets_a_number(joined):
    _, first = joined("Ana")
    _, second = joined("Ana")
    _, third = joined(" Ana ")
    assert (first["name"], second["name"], third["name"]) == ("Ana", "Ana (2)", "Ana (3)")


def test_a_name_of_forty_characters_and_any_language_tag_will_do(joined):
    _, seat = joined("x" * 40, "PT")
    assert seat["name"] == "x" * 40 and seat["language"] == "pt"
    _, observer = joined("Bo", "fil", "observer")
    assert (observer["language"], observer["role"]) == ("fil", "observer")


def test_join_requests_are_limited_per_address(browser, campaign, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(join_routes, "clock", lambda: now[0])
    client = browser("10.0.0.7")
    for _ in range(10):
        assert client.get(f"/api/join/{campaign.join_token}").status_code == 200
    refused = client.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert refused.status_code == 429 and "error" in refused.json()
    made = client.post(f"/api/join/{campaign.join_token}/account", json={})
    assert made.status_code == 429, "making an account through the invite counts too"
    assert client.get("/api/join/guessing").status_code == 429, "guessing tokens counts too"
    assert browser("10.0.0.8").get(f"/api/join/{campaign.join_token}").status_code == 200, "per address"
    now[0] += 61
    assert client.get(f"/api/join/{campaign.join_token}").status_code == 200, "a minute later"


# ----- the invite -----


def test_the_host_gets_the_invite_with_the_request_host(lan, token, campaign):
    response = lan.get(f"/api/campaigns/{campaign.id}/invite", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {
        "url": f"http://localhost:7810/join/{campaign.join_token}",
        "join_token": campaign.join_token,
    }


def test_from_this_machine_the_invite_uses_the_first_lan_address(local, campaign, monkeypatch):
    monkeypatch.setattr(guard, "lan_addresses", lambda: ["192.168.1.20", "2001:db8::5"])
    url = local.get(f"/api/campaigns/{campaign.id}/invite").json()["url"]
    assert url == f"http://192.168.1.20:7810/join/{campaign.join_token}"
    monkeypatch.setattr(guard, "lan_addresses", list)
    url = local.get(f"/api/campaigns/{campaign.id}/invite").json()["url"]
    assert url == f"http://localhost:7810/join/{campaign.join_token}", "no LAN address: the request's host"


def test_a_new_invite_replaces_the_link(app, local, browser, campaign):
    old = campaign.join_token
    response = local.post(f"/api/campaigns/{campaign.id}/invite", json={})
    assert response.status_code == 200
    new = response.json()["join_token"]
    assert new and new != old and response.json()["url"].endswith(f"/join/{new}")
    assert local.get(f"/api/campaigns/{campaign.id}/invite").json()["join_token"] == new
    client = browser()
    assert client.get(f"/api/join/{old}").status_code == 404, "the old link stops working"
    assert client.post(f"/api/join/{old}", json={"role": "player"}).status_code == 404
    assert client.get(f"/api/join/{new}").status_code == 200
    assert {"campaign_id": campaign.id} in seats_events(app)


def test_only_the_host_invites(joined, campaign):
    ana, _ = joined()
    assert ana.get(f"/api/campaigns/{campaign.id}/invite").status_code == 403
    refused = ana.post(f"/api/campaigns/{campaign.id}/invite", json={})
    assert refused.status_code == 403 and refused.json() == {"error": "Only the host can do that."}


# ----- the seats -----


def test_every_seat_lists_the_table(local, joined, storage, campaign, garrek):
    ana, seat = joined()
    _, bo = joined("Bo", "en", "observer", address="10.0.0.8")
    owner = seats.owner_seat(storage, campaign.id)
    storage.seats.set_controller(garrek.id, seat["id"])
    listed = ana.get(f"/api/campaigns/{campaign.id}/seats").json()
    assert [(s["id"], s["name"], s["role"]) for s in listed] == [
        (owner.id, "Host", "host"),
        (seat["id"], "Ana", "player"),
        (bo["id"], "Bo", "observer"),
    ]
    assert listed[1]["characters"] == [garrek.id] and listed[1]["language"] == "nl"
    assert all(isinstance(s["present"], bool) for s in listed)
    assert set(listed[0]) == {"id", "name", "language", "role", "organiser", "present", "characters", "profile"}
    assert listed[0]["profile"] is None and listed[1]["profile"]["display_name"] == "Ana"
    as_owner = local.get(f"/api/campaigns/{campaign.id}/seats").json()
    assert _without_presence(as_owner) == _without_presence(listed), "the same table, each asker present to itself"


def _without_presence(listed):
    return [{key: value for key, value in seat.items() if key != "present"} for seat in listed]


def test_the_asking_seat_is_present_before_its_stream_says_so(joined, campaign):
    """DEL-260: a seat's arrival is announced as its stream opens, often before its page listens, so its first list
    read Away for good; whoever asks is at the page, so present. Another seat isn't, until its own stream opens."""
    ana, seat = joined()
    bo, bo_seat = joined("Bo", "en", "player", address="10.0.0.8")
    as_ana = {s["id"]: s["present"] for s in ana.get(f"/api/campaigns/{campaign.id}/seats").json()}
    assert as_ana[seat["id"]] is True and as_ana[bo_seat["id"]] is False
    as_bo = {s["id"]: s["present"] for s in bo.get(f"/api/campaigns/{campaign.id}/seats").json()}
    assert as_bo[bo_seat["id"]] is True and as_bo[seat["id"]] is False


def test_a_seat_that_left_is_not_listed(joined, local, campaign):
    ana, seat = joined()
    assert ana.post(f"/api/campaigns/{campaign.id}/leave", json={}).status_code == 204
    assert seat["id"] not in [s["id"] for s in local.get(f"/api/campaigns/{campaign.id}/seats").json()]


def test_the_host_makes_a_cohost_and_hands_over(app, local, joined, storage, campaign):
    ana, seat = joined()
    owner = seats.owner_seat(storage, campaign.id)
    made = local.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"role": "cohost"})
    assert made.status_code == 200 and made.json()["role"] == "cohost"
    assert ana.get(f"/api/campaigns/{campaign.id}/invite").status_code == 200, "a co-host has the table rights"

    # A co-host can't make itself the host (DEL-149); the host hands the role over.
    taken = ana.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"role": "host"})
    assert taken.status_code == 403 and storage.seats.get(owner.id).role == "host"
    handed = local.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"role": "host"})
    assert handed.status_code == 200 and handed.json()["role"] == "host"
    assert storage.seats.get(owner.id).role == "cohost", "the old host becomes a co-host"
    assert seats_events(app).count({"campaign_id": campaign.id}) >= 3


def test_the_table_keeps_a_host(local, storage, campaign):
    owner = seats.owner_seat(storage, campaign.id)
    refused = local.put(f"/api/campaigns/{campaign.id}/seats/{owner.id}", json={"role": "player"})
    assert refused.status_code == 409 and refused.json()["error"] == "A table needs a host."


def test_a_player_gives_no_roles(joined, storage, campaign):
    ana, seat = joined()
    refused = ana.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"role": "cohost"})
    assert refused.status_code == 403 and storage.seats.get(seat["id"]).role == "player"


def test_an_unknown_seat_or_role(local, joined, campaign):
    _, seat = joined()
    assert (
        local.put(f"/api/campaigns/{campaign.id}/seats/seat_000000000000", json={"role": "cohost"}).status_code == 404
    )
    assert local.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"role": "king"}).status_code == 422


def test_only_the_owner_makes_an_organiser(local, token_seat, storage, campaign):
    """On seats joined with a seat token: an account's organiser rights are given on the Players page."""
    ana_seat, ana = token_seat("Ana")
    seat, bo = {"id": ana_seat.id}, {"id": token_seat("Bo")[0].id}
    made = local.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"role": "cohost", "organiser": True})
    assert made.status_code == 200 and made.json()["organiser"] is True and made.json()["role"] == "cohost"
    assert ana.get("/api/modules").status_code == 200, "the seat has the organiser rights now"

    refused = ana.put(f"/api/campaigns/{campaign.id}/seats/{bo['id']}", json={"organiser": True})
    assert refused.status_code == 403, "a co-host, even an organiser, is not the owner"
    assert not storage.seats.get(bo["id"]).organiser

    taken = local.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"organiser": False})
    assert taken.status_code == 200 and taken.json()["organiser"] is False
    assert ana.get("/api/modules").status_code == 403


def test_the_owners_seat_stays_an_organiser(local, storage, campaign):
    owner = seats.owner_seat(storage, campaign.id)
    refused = local.put(f"/api/campaigns/{campaign.id}/seats/{owner.id}", json={"organiser": False})
    assert refused.status_code == 422 and storage.seats.get(owner.id).organiser


def test_a_refused_change_changes_nothing(local, joined, storage, campaign):
    _, seat = joined()
    before = storage.seats.get(seat["id"])
    refused = local.put(f"/api/campaigns/{campaign.id}/seats/{seat['id']}", json={"role": "king", "organiser": True})
    assert refused.status_code == 422 and storage.seats.get(seat["id"]) == before


# ----- characters -----


def test_a_player_claims_and_releases_a_character(app, joined, storage, campaign, garrek):
    ana, seat = joined()
    claimed = ana.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={})
    assert claimed.status_code == 200 and claimed.json()["id"] == garrek.id
    assert storage.characters.get(garrek.id).controller_id == seat["id"]
    assert ana.get(f"/api/campaigns/{campaign.id}/seats").json()[1]["characters"] == [garrek.id]

    released = ana.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/release", json={})
    assert released.status_code == 200 and storage.characters.get(garrek.id).controller_id is None
    assert seats_events(app).count({"campaign_id": campaign.id}) == 3, "the join, the claim and the release"


def test_a_character_another_seat_plays_is_409(joined, campaign, garrek):
    ana, _ = joined()
    bo, _ = joined("Bo", "en", address="10.0.0.8")
    assert ana.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={}).status_code == 200
    refused = bo.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={})
    assert refused.status_code == 409
    assert bo.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/release", json={}).status_code == 403


def test_the_host_gives_a_character_to_a_seat(local, joined, storage, campaign, garrek):
    ana, seat = joined()
    _, bo = joined("Bo", "en", address="10.0.0.8")
    given = local.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={"seat": seat["id"]})
    assert given.status_code == 200 and storage.characters.get(garrek.id).controller_id == seat["id"]
    taken = local.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={"seat": bo["id"]})
    assert taken.status_code == 200 and storage.characters.get(garrek.id).controller_id == bo["id"]
    assert local.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/release", json={}).status_code == 200
    refused = ana.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={"seat": bo["id"]})
    assert refused.status_code == 403, "giving is the host's"


def test_observers_claim_nothing(joined, campaign, garrek):
    bo, _ = joined("Bo", "en", "observer")
    refused = bo.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={})
    assert refused.status_code == 403 and refused.json() == {"error": "Observers don't act."}


def test_claiming_an_unknown_character_or_an_npc(local, storage, campaign):
    assert local.post(f"/api/campaigns/{campaign.id}/characters/chr_000000000000/claim", json={}).status_code == 404
    npc = storage.characters.create(campaign.id, "Tira", kind="npc")
    assert local.post(f"/api/campaigns/{campaign.id}/characters/{npc.id}/claim", json={}).status_code == 422


# ----- leaving, and who I am -----


def test_leaving_frees_characters_and_clears_the_cookie(app, joined, storage, campaign, garrek):
    ana, seat = joined()
    ana.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={})
    response = ana.post(f"/api/campaigns/{campaign.id}/leave", json={})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert cookie.startswith((f'{SEAT_COOKIE}=""', f"{SEAT_COOKIE}=;"))
    assert "max-age=0" in cookie.lower()
    assert storage.seats.get(seat["id"]).left_at is not None
    assert storage.characters.get(garrek.id).controller_id is None
    assert {"campaign_id": campaign.id} in seats_events(app)


def test_a_left_seats_token_opens_nothing(browser, token_seat, campaign):
    _, ana = token_seat("Ana")
    token = ana.cookies.get(SEAT_COOKIE)
    ana.post(f"/api/campaigns/{campaign.id}/leave", json={})
    kept = browser("10.0.0.9")
    kept.cookies.set(SEAT_COOKIE, token)
    assert kept.get(f"/api/campaigns/{campaign.id}/story").status_code == 403


def test_the_host_hands_over_before_leaving(local, campaign):
    refused = local.post(f"/api/campaigns/{campaign.id}/leave", json={})
    assert refused.status_code == 409


def test_me(local, lan, joined, campaign):
    assert local.get("/api/me").json() == {
        "principal": {"id": "owner", "roles": ["organiser"]},
        "account": None,
        "seat": None,
        "keepable_seat": None,
        "owner_account_exists": False,
    }
    ana, seat = joined()
    me = ana.get(f"/api/me?campaign={campaign.id}").json()
    assert me["principal"] == {"id": f"account:{me['account']['id']}", "roles": []}
    assert me["seat"] == {
        "id": seat["id"],
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "name": "Ana",
        "language": "nl",
        "role": "player",
        "organiser": False,
    }
    assert lan.get("/api/me").status_code == 401


def test_me_at_a_table_gives_the_owner_their_owner_seat(local, joined, campaign):
    """The play screen asks `/api/me?campaign=…` to know its own seat: the owner's is their owner seat there."""
    owner = seats.owner_seat(local.app.state.storage, campaign.id)
    me = local.get(f"/api/me?campaign={campaign.id}").json()
    assert me["seat"] == {
        "id": owner.id,
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "name": owner.name,
        "language": owner.language,
        "role": "host",
        "organiser": True,
    }
    assert local.get("/api/me?campaign=cmp_000000000000").json()["seat"] is None, "an unknown campaign: no seat"
    ana, seat = joined()
    assert ana.get(f"/api/me?campaign={campaign.id}").json()["seat"]["id"] == seat["id"]
    assert ana.get("/api/me?campaign=cmp_000000000000").json()["seat"] is None, "an account's seat is per table"
