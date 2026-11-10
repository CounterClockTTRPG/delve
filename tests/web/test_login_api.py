"""Logging in and out (players and tavern Task C4): the session cookie, the throttle, the browsers an account is
logged in on, changing a password, the one-time links, the first owner account, and an account's tables. No answer
and no log line holds a password or a token."""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from delve.domain.accounts import PASSWORD_MAX
from delve.play import logins, passwords
from delve.play.accounts import make_link
from delve.play.clock import FakeClock
from delve.web.app import create_app
from delve.web.routes import accounts as accounts_routes
from delve.web.routes.accounts import DEVICE_COOKIE, LoginThrottle
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, PASSWORD, SESSION_COOKIE, log_in, make_account, session_for
from tests.web.test_seats_identity import make_campaign

WRONG = {"error": "Wrong username or password."}
TOO_MANY = {"error": "Too many tries: wait 15 minutes."}
NOT_AN_ACCOUNT = {"error": "Log in to an account first."}
NO_LINK = {"error": "This link doesn't work: ask for a new one."}
NEW_PASSWORD = "a brand new password"
START = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)

# Every answer of this file, to check that none holds a password.
ANSWERS: list[str] = []


@pytest.fixture(autouse=True)
def _keep_answers(app):
    ANSWERS.clear()
    yield


def _kept(response):
    ANSWERS.append(response.text + repr(response.headers.get("set-cookie", "")))
    return response


def login(client, username="ana", password=PASSWORD, **headers):
    return _kept(client.post("/api/login", json={"username": username, "password": password}, headers=headers))


@pytest.fixture
def ana(storage):
    return make_account(storage)


@pytest.fixture
def clock():
    return FakeClock(START)


@pytest.fixture
def timed(config, storage, registries, static_dir, clock):
    """An app whose login sessions keep time by `clock`."""
    return create_app(config, storage, registries, static_dir=static_dir, clock=clock)


@pytest.fixture
def ticks(app):
    """The throttle's clock, moved by hand: `ticks.now += 60`."""

    class Ticks:
        now = 1000.0

    app.state.login_throttle.clock = lambda: Ticks.now
    return Ticks


def _cookie_flags(response, name=SESSION_COOKIE) -> set[str]:
    """The flags of the cookie `name` the response sets (a login sets the device cookie too)."""
    (header,) = [h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}=")]
    return {part.strip().lower() for part in header.split(";")[1:]}


def test_login_sets_the_session_cookie(lan, ana):
    response = login(lan)
    assert response.status_code == 200
    assert response.json() == {
        "account": {
            "id": ana.id,
            "username": "ana",
            "display_name": "ana",
            "language": "en",
            "organiser": False,
            "owner": False,
        }
    }
    flags = _cookie_flags(response)
    assert flags == {"httponly", "samesite=lax", "path=/", "max-age=31536000"}, "no Secure over http"
    assert lan.get("/api/me").json()["principal"]["id"] == f"account:{ana.id}"


def test_secure_only_from_a_https_proxy_here(app, ana):
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        proxied = login(tunnel, **{"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"})
        assert "secure" in _cookie_flags(proxied)
        plain = login(tunnel, **{"X-Forwarded-For": "203.0.113.9"})
        assert "secure" not in _cookie_flags(plain)
    with TestClient(app, base_url=BASE_URL) as lan:
        assert "secure" not in _cookie_flags(login(lan, **{"X-Forwarded-Proto": "https"})), "a LAN client's say"


def test_login_any_case(lan, ana):
    assert login(lan, " ANA ").status_code == 200


def test_wrong_and_unknown_say_the_same(lan, ana):
    wrong = login(lan, "ana", "not the password")
    unknown = login(lan, "nobody", PASSWORD)
    invalid = login(lan, "x", PASSWORD)
    assert wrong.status_code == unknown.status_code == invalid.status_code == 401
    assert wrong.json() == unknown.json() == invalid.json() == WRONG
    assert "set-cookie" not in wrong.headers


def test_disabled_and_passwordless_say_the_same(storage, lan, ana):
    from delve.play.accounts import create_account

    create_account(storage, "nopass", None)
    storage.accounts.set_disabled(ana.id, START.isoformat())
    assert login(lan).json() == login(lan, "nopass", PASSWORD).json() == WRONG


def test_login_body_must_be_text(lan):
    response = _kept(lan.post("/api/login", json={"username": "ana", "password": ["secret words here"]}))
    assert response.status_code == 422 and "secret words here" not in response.text
    response = _kept(lan.post("/api/login", json={"password": "secret words here"}))
    assert response.status_code == 422 and "secret words here" not in response.text


def test_throttle_per_username(lan, ana, ticks):
    for _ in range(5):
        assert login(lan, "ana", "not the password").status_code == 401
    refused = login(lan)
    assert refused.status_code == 429 and refused.json() == TOO_MANY, "checked before the password is"
    assert login(lan, "ANA").status_code == 429, "the folded username"
    ticks.now += 15 * 60
    assert login(lan).status_code == 200


def test_parallel_logins_cant_get_past_the_throttle(lan, ana, ticks, monkeypatch):
    """Audit finding 4: 60 wrong passwords sent at once got 44 checks past a limit of 5, as each counted only once its
    slow password check was done. An attempt now counts before the check, so at most 5 are checked."""

    def slow(storage, username, password):
        """A wrong password (None), checked long enough for every other attempt to arrive meanwhile."""
        time.sleep(0.3)

    monkeypatch.setattr(accounts_routes.accounts, "authenticate", slow)
    with ThreadPoolExecutor(30) as pool:
        answers = list(pool.map(lambda _: login(lan, "ana", "not the password").status_code, range(30)))
    assert answers.count(401) == 5 and answers.count(429) == 25


def test_a_reserved_attempt_is_taken_back_when_it_succeeds(ticks):
    limits = LoginThrottle()
    limits.clock = lambda: ticks.now
    for _ in range(4):
        limits.reserve("ana", "203.0.113.9")
    at = limits.reserve("ana", "203.0.113.9")
    with pytest.raises(HTTPException) as refused:
        limits.reserve("ana", "203.0.113.9")
    assert refused.value.status_code == 429, "the fifth attempt, still being checked, already counts"
    limits.succeeded("ana", "203.0.113.9", at)
    limits.reserve("ana", "203.0.113.9")


def test_one_outsider_cant_lock_the_owner_out(app, storage, ticks):
    """Audit finding 7: five wrong passwords from anywhere locked a username out for everyone. Now a username waits
    after 5 failures from one address, for that address, and after 50 from all of them, for everyone."""
    make_account(storage, "olga", owner=True)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        outsider = {"X-Forwarded-For": "203.0.113.9"}
        for _ in range(5):
            assert login(tunnel, "olga", "not the password", **outsider).status_code == 401
        assert login(tunnel, "olga", PASSWORD, **outsider).status_code == 429
        assert login(tunnel, "olga", PASSWORD, **{"X-Forwarded-For": "198.51.100.4"}).status_code == 200
        tunnel.cookies.clear()  # the rest are other browsers, with no device cookie of olga's
        for n in range(45):  # at most 4 from each address: 50 failures in all, with the outsider's 5
            assert login(tunnel, "olga", "nope", **{"X-Forwarded-For": f"10.1.{n // 4}.1"}).status_code == 401
        assert login(tunnel, "olga", "nope", **{"X-Forwarded-For": "10.2.0.1"}).status_code == 429
        assert login(tunnel, "olga", PASSWORD, **{"X-Forwarded-For": "198.51.100.4"}).status_code == 429
        assert login(tunnel, "olga", PASSWORD).status_code == 429, "every address waits now"
        ticks.now += 15 * 60
        assert login(tunnel, "olga", PASSWORD, **{"X-Forwarded-For": "198.51.100.4"}).status_code == 200


def test_success_clears_the_usernames_count(lan, ana, ticks):
    for _ in range(4):
        login(lan, "ana", "not the password")
    assert login(lan).status_code == 200
    for _ in range(4):
        assert login(lan, "ana", "not the password").status_code == 401
    assert login(lan).status_code == 200


def test_failures_older_than_the_window_dont_count(lan, ana, ticks):
    for _ in range(4):
        login(lan, "ana", "not the password")
    ticks.now += 15 * 60 + 1
    for _ in range(4):
        login(lan, "ana", "not the password")
    assert login(lan).status_code == 200


def test_throttle_per_address(app, storage, ticks):
    make_account(storage, "zed")
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        visitor = {"X-Forwarded-For": "203.0.113.9"}
        for n in range(20):
            assert login(tunnel, f"user{n:02}", "not the password", **visitor).status_code == 401
        refused = login(tunnel, "zed", PASSWORD, **visitor)
        assert refused.status_code == 429 and refused.json() == TOO_MANY
        assert login(tunnel, "zed", PASSWORD, **{"X-Forwarded-For": "198.51.100.4"}).status_code == 200
    with TestClient(app, base_url=BASE_URL) as lan:
        assert login(lan, "zed").status_code == 200, "another address is unaffected"


def test_a_forged_cf_connecting_ip_is_no_fresh_address(app, storage, ticks):
    """Audit finding 5: behind any proxy here but Cloudflare, a visitor chose their own CF-Connecting-IP each try."""
    make_account(storage, "zed")
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        for n in range(20):
            forged = {"X-Forwarded-For": "9.9.9.9", "CF-Connecting-IP": f"10.0.0.{n}"}
            assert login(tunnel, f"user{n:02}", "not the password", **forged).status_code == 401
        assert (
            login(tunnel, "zed", **{"X-Forwarded-For": "9.9.9.9", "CF-Connecting-IP": "10.0.0.99"}).status_code == 429
        )


def test_one_visitor_rotating_forged_entries_stays_one_address(app, storage, ticks):
    make_account(storage, "zed")
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        for n in range(20):
            login(tunnel, f"user{n:02}", "not the password", **{"X-Forwarded-For": f"10.0.0.{n}, 203.0.113.9"})
        assert login(tunnel, "zed", **{"X-Forwarded-For": "10.0.0.99, 203.0.113.9"}).status_code == 429
        assert login(tunnel, "zed", **{"X-Forwarded-For": "198.51.100.4"}).status_code == 200, "another visitor"


def test_lan_clients_cant_choose_their_address(app, storage, ticks):
    make_account(storage, "zed")
    with TestClient(app, base_url=BASE_URL) as lan:
        for n in range(20):
            login(lan, f"user{n:02}", "not the password", **{"X-Forwarded-For": f"10.0.0.{n}"})
        assert login(lan, "zed", **{"X-Forwarded-For": "10.0.0.99"}).status_code == 429


def test_throttle_unknown_usernames_too(lan, ana, ticks):
    for _ in range(5):
        login(lan, "nobody", PASSWORD)
    known = login(lan, "ana", "not the password")
    unknown = login(lan, "nobody", PASSWORD)
    assert unknown.status_code == 429 and unknown.json() == TOO_MANY, "an unknown username waits as a known one"
    assert known.status_code == 401
    for _ in range(4):
        login(lan, "ana", "not the password")
    assert login(lan, "ana", PASSWORD).json() == unknown.json(), "the answer never says a username exists"


def test_logout_ends_the_session(storage, lan, ana):
    login(lan)
    assert lan.get("/api/me").status_code == 200
    response = _kept(lan.post("/api/logout", json={}))
    assert response.status_code == 204
    assert (
        f"{SESSION_COOKIE}=" in response.headers["set-cookie"] and "max-age=0" in response.headers["set-cookie"].lower()
    )
    assert storage.login_sessions.list(ana.id) == []
    assert lan.get("/api/me").status_code == 401
    assert _kept(lan.post("/api/logout", json={})).status_code == 204, "without a session too"


def test_sessions_list_and_end_one(app, storage, lan, ana):
    login(lan)
    with TestClient(app, base_url=BASE_URL) as phone:
        login(phone)
        listed = _kept(lan.get("/api/account/sessions")).json()
        assert len(listed) == 2 and sorted(s["current"] for s in listed) == [False, True]
        assert set(listed[0]) == {"id", "device", "last_used_at", "current"}
        other = next(s for s in listed if not s["current"])
        assert _kept(lan.request("DELETE", f"/api/account/sessions/{other['id']}", json={})).status_code == 204
        assert phone.get("/api/me").status_code == 401
    bo = make_account(storage, "bram")
    theirs = session_for(storage, bo)
    their_id = logins.resolve(storage, theirs, datetime.now(UTC))[1].id
    assert lan.request("DELETE", f"/api/account/sessions/{their_id}", json={}).status_code == 404
    assert logins.resolve(storage, theirs, datetime.now(UTC)) is not None


def test_end_all_logs_out_everywhere(app, storage, lan, ana):
    login(lan)
    with TestClient(app, base_url=BASE_URL) as phone:
        login(phone)
        response = _kept(lan.post("/api/account/sessions/end-all", json={}))
        assert response.status_code == 204 and "max-age=0" in response.headers["set-cookie"].lower()
        assert phone.get("/api/me").status_code == 401
    assert lan.get("/api/me").status_code == 401, "this one included"
    assert storage.login_sessions.list(ana.id) == []


def test_account_routes_are_for_accounts(app, lan, local, token, storage):
    for client, headers in ((local, {}), (lan, {"Authorization": f"Bearer {token}"})):
        for method, path in (("GET", "/api/account/sessions"), ("GET", "/api/account/tables")):
            response = client.request(method, path, headers=headers)
            assert response.status_code == 403 and response.json() == NOT_AN_ACCOUNT, (method, path)
        response = client.put("/api/account/password", json={"old": "x", "new": NEW_PASSWORD}, headers=headers)
        assert response.status_code == 403 and response.json() == NOT_AN_ACCOUNT
    seat_token = new_seat_token()
    storage.seats.create(make_campaign(storage).id, "Bo", "en", "player", token_hash=token_hash(seat_token))
    with TestClient(app, base_url=BASE_URL) as seated:
        seated.cookies.set(SEAT_COOKIE, seat_token)
        assert seated.get("/api/account/sessions").json() == NOT_AN_ACCOUNT
    assert lan.get("/api/account/sessions").status_code == 401


def test_password_change_ends_other_sessions(app, storage, lan, ana):
    login(lan)
    with TestClient(app, base_url=BASE_URL) as phone:
        login(phone)
        response = _kept(lan.put("/api/account/password", json={"old": PASSWORD, "new": NEW_PASSWORD}))
        assert response.status_code == 204
        assert phone.get("/api/me").status_code == 401
    assert lan.get("/api/me").status_code == 200, "this one stays"
    _kept(lan.post("/api/logout", json={}))
    assert login(lan, "ana", PASSWORD).status_code == 401
    assert login(lan, "ana", NEW_PASSWORD).status_code == 200


def test_password_change_refusals(lan, ana, ticks):
    login(lan)
    wrong = _kept(lan.put("/api/account/password", json={"old": "not the password", "new": NEW_PASSWORD}))
    assert wrong.status_code == 403 and wrong.json() == {"error": "Your current password is wrong."}
    short = _kept(lan.put("/api/account/password", json={"old": PASSWORD, "new": "short"}))
    assert short.status_code == 422 and short.json() == {"error": "A password has at least 10 characters."}
    for _ in range(4):
        _kept(lan.put("/api/account/password", json={"old": "not the password", "new": NEW_PASSWORD}))
    throttled = _kept(lan.put("/api/account/password", json={"old": PASSWORD, "new": NEW_PASSWORD}))
    assert throttled.status_code == 429, "a wrong old password counts as a failed login"


def test_set_password_link(storage, lan):
    from delve.play.accounts import create_account

    cy = create_account(storage, "cy.r", None, display_name="Cy")
    link = make_link(storage, cy.id, "set-password", datetime.now(UTC), by_owner=False)
    assert _kept(lan.get(f"/api/account-links/{link}")).json() == {"username": "cy.r", "kind": "set-password"}
    assert lan.get("/api/account-links/nope").status_code == 404
    assert lan.get("/api/account-links/nope").json() == NO_LINK
    short = _kept(lan.post(f"/api/account-links/{link}", json={"password": "short"}))
    assert short.status_code == 422
    used = _kept(lan.post(f"/api/account-links/{link}", json={"password": NEW_PASSWORD}))
    assert used.status_code == 200 and used.json()["account"]["username"] == "cy.r"
    assert lan.get("/api/me").json()["principal"]["id"] == f"account:{cy.id}", "logged in"
    again = _kept(lan.post(f"/api/account-links/{link}", json={"password": "another password!"}))
    assert again.status_code == 404 and again.json() == NO_LINK
    assert lan.get(f"/api/account-links/{link}").status_code == 404


def test_reset_link_ends_older_logins(app, storage, lan, ana):
    login(lan)
    link = make_link(storage, ana.id, "reset-password", datetime.now(UTC), by_owner=False)
    with TestClient(app, base_url=BASE_URL) as phone:
        assert _kept(phone.post(f"/api/account-links/{link}", json={"password": NEW_PASSWORD})).status_code == 200
        assert phone.get("/api/me").status_code == 200
    assert lan.get("/api/me").status_code == 401, "every older login ended"


def test_link_expires_after_24_hours(storage, lan, ana):
    old = make_link(storage, ana.id, "reset-password", datetime.now(UTC) - timedelta(hours=24), by_owner=False)
    assert lan.get(f"/api/account-links/{old}").json() == NO_LINK
    assert lan.post(f"/api/account-links/{old}", json={"password": NEW_PASSWORD}).status_code == 404
    fresh = make_link(
        storage, ana.id, "reset-password", datetime.now(UTC) - timedelta(hours=23, minutes=59), by_owner=False
    )
    assert lan.get(f"/api/account-links/{fresh}").status_code == 200


def test_session_slides_30_days_by_the_apps_clock(timed, storage, ana, clock):
    import asyncio

    with TestClient(timed, base_url=BASE_URL) as lan:
        assert login(lan).status_code == 200
        asyncio.run(clock.advance(29 * 24 * 3600))
        assert lan.get("/api/me").status_code == 200
        asyncio.run(clock.advance(29 * 24 * 3600))
        assert lan.get("/api/me").status_code == 200, "used at day 29: alive at day 58"
        asyncio.run(clock.advance(30 * 24 * 3600))
        assert lan.get("/api/me").status_code == 401
    assert storage.login_sessions.list(ana.id) == []


def test_first_owner_from_this_machine(app, storage, local, lan):
    assert local.get("/api/me").json()["owner_account_exists"] is False
    refused = _kept(lan.post("/api/accounts/first-owner", json={"username": "olga", "password": PASSWORD}))
    assert refused.status_code == 403
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        proxied = tunnel.post(
            "/api/accounts/first-owner",
            json={"username": "olga", "password": PASSWORD},
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
        assert proxied.status_code == 403, "not through a proxy here"
    body = {"username": "Olga", "password": PASSWORD, "display_name": "Olga the Owner"}
    made = _kept(local.post("/api/accounts/first-owner", json=body))
    assert made.status_code == 201
    assert made.json()["account"]["owner"] is True and made.json()["account"]["display_name"] == "Olga the Owner"
    assert "secure" not in _cookie_flags(made)
    me = local.get("/api/me").json()
    assert me["principal"]["id"] == f"account:{made.json()['account']['id']}", "logged in"
    assert me["owner_account_exists"] is True
    again = _kept(local.post("/api/accounts/first-owner", json={"username": "otto", "password": PASSWORD}))
    assert again.status_code == 403 and storage.accounts.by_username("otto") is None


def test_owner_account_exists_only_from_this_machine(storage, lan, ana):
    login(lan)
    assert "owner_account_exists" not in lan.get("/api/me").json()


def test_my_tables_of_the_owner_hold_every_table(storage, lan):
    """The owner's seat has no account, but an owner account is seated at every table by it: a table it made is in its
    tables, as its host, once."""
    from delve.play import seats

    make_account(storage, "olga", owner=True)
    tuesday, friday = make_campaign(storage), make_campaign(storage, "Friday")
    host = seats.create_owner_seat(storage, tuesday.id)
    seats.create_owner_seat(storage, friday.id)
    login(lan, "olga")
    tables = _kept(lan.get("/api/account/tables")).json()
    assert sorted(t["name"] for t in tables) == ["Friday", "Tuesday"]
    assert next(t for t in tables if t["name"] == "Tuesday")["seat_id"] == host.id
    assert {t["role"] for t in tables} == {"host"}


def test_my_tables_put_complete_campaigns_last(storage, lan, ana):
    done, tuesday = make_campaign(storage, "Done"), make_campaign(storage)
    storage.campaigns.set_status(done.id, "complete")
    for campaign in (done, tuesday):
        storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    storage.story.append(done.id, None, "dm_text", {"text": "The end."})
    login(lan)
    tables = _kept(lan.get("/api/account/tables")).json()
    assert [(t["name"], t["status"]) for t in tables] == [("Tuesday", "in_progress"), ("Done", "complete")]


def test_my_tables(storage, lan, ana):
    tuesday, friday, sunday = make_campaign(storage), make_campaign(storage, "Friday"), make_campaign(storage, "Sun")
    played = storage.seats.create(tuesday.id, "Ana", "en", "player", account_id=ana.id)
    storage.seats.create(friday.id, "Ana", "en", "observer", account_id=ana.id)
    left = storage.seats.create(sunday.id, "Ana", "en", "player", account_id=ana.id)
    from delve.play import seats

    seats.leave(storage, left)
    entry = storage.story.append(tuesday.id, None, "dm_text", {"text": "The hall."})
    login(lan)
    tables = _kept(lan.get("/api/account/tables")).json()
    assert [t["campaign_id"] for t in tables] == [tuesday.id, friday.id], "newest play first; the one left isn't"
    assert tables[0] == {
        "campaign_id": tuesday.id,
        "name": "Tuesday",
        "module_title": "The Crypt",
        "status": "in_progress",
        "role": "player",
        "slots": None,
        "taken": 1,
        "people": [{"seat_id": played.id, "name": "Ana", "role": "player", "profile": tables[0]["people"][0]["profile"]}],
        "seat_id": played.id,
        "last_played_at": entry.at,
        "session_number": 1,
        "banner": False,
        "next_sessions": [],
    }
    assert tables[1]["role"] == "observer" and tables[1]["last_played_at"] is None


def test_no_password_in_answers_or_logs(caplog, storage, lan, ana, ticks):
    caplog.set_level(logging.DEBUG)
    login(lan)
    login(lan, "ana", "not the password")
    _kept(lan.put("/api/account/password", json={"old": PASSWORD, "new": NEW_PASSWORD}))
    link = make_link(storage, ana.id, "reset-password", datetime.now(UTC), by_owner=False)
    _kept(lan.post(f"/api/account-links/{link}", json={"password": "the third password"}))
    # Delve's own log lines: the test client's (httpx) names the URLs it asks for.
    logged = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore")))
    for password in (PASSWORD, "not the password", NEW_PASSWORD, "the third password"):
        assert password not in logged
        assert not any(password in answer for answer in ANSWERS), password
    assert link not in logged


def test_access_log_hides_link_tokens():
    from delve.web.app import AccessLogRedactor

    args = ("1.2.3.4", "GET", "/api/account-links/SECRETTOKEN?x=1", "1.1", 200)
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', args, None)
    assert AccessLogRedactor().filter(record) is True
    assert "SECRETTOKEN" not in record.getMessage() and "/api/account-links/…" in record.getMessage()
    page = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s", ("GET", "/account/link/SECRETTOKEN"), None)
    AccessLogRedactor().filter(page)
    assert "SECRETTOKEN" not in page.getMessage()
    other = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "%s %s", ("GET", "/api/modules"), None)
    AccessLogRedactor().filter(other)
    assert other.getMessage() == "GET /api/modules"


def test_log_in_helper(storage, lan, ana):
    log_in(lan)
    assert lan.get("/api/me").json()["account"]["username"] == "ana"


def test_login_busy_is_503_and_not_counted(lan, ana, monkeypatch, ticks):
    """Clara's final audit, finding 3: when no scrypt place frees up in time the login is 503, and the attempt is taken
    back from the throttle, so a busy Delve locks nobody out."""
    monkeypatch.setattr(passwords, "SCRYPT_WAIT_S", 0.01)
    monkeypatch.setattr(passwords, "_running", threading.BoundedSemaphore(1))
    passwords._running.acquire()
    for _ in range(LoginThrottle.PER_USERNAME_AND_ADDRESS + 1):
        busy = login(lan)
        assert (busy.status_code, busy.json()) == (503, {"error": "Busy: try again in a moment."})
    passwords._running.release()
    assert login(lan).status_code == 200


def test_oversized_fields_are_401_before_the_throttle_and_scrypt(app, lan, ana, monkeypatch):
    """Clara's final audit, finding 4: a username past `USERNAME_FIELD_MAX` or a password past `PASSWORD_MAX` is the
    same 401, with no scrypt run, and no throttle key is made of it."""
    ran = []
    monkeypatch.setattr(passwords, "_scrypt", lambda *args: ran.append(args))
    for username, password in (
        ("a" * (accounts_routes.USERNAME_FIELD_MAX + 1), PASSWORD),
        ("ana", "x" * (PASSWORD_MAX + 1)),
        ("x" * 100_000, "x" * 100_000),
    ):
        refused = login(lan, username, password)
        assert (refused.status_code, refused.json()) == (401, WRONG)
    assert ran == [] and app.state.login_throttle._failures == {}
    assert accounts_routes.USERNAME_FIELD_MAX == 64


# ----- the device cookie (DEL-154, audit finding 8) -----


def lock_everywhere(tunnel, username):
    """Ten strangers' addresses, five wrong passwords each: the username waits everywhere (`PER_USERNAME`)."""
    for n in range(10):
        for _ in range(5):
            assert login(tunnel, username, "nope", **{"X-Forwarded-For": f"10.9.{n}.1"}).status_code == 401
    assert login(tunnel, username, PASSWORD, **{"X-Forwarded-For": "10.8.0.1"}).status_code == 429


def test_a_login_sets_the_device_cookie(app, ana):
    with TestClient(app, base_url=BASE_URL) as lan:
        flags = _cookie_flags(login(lan), DEVICE_COOKIE)
        assert flags == {"httponly", "samesite=lax", "path=/", "max-age=31536000"}, "no Secure over http"
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as tunnel:
        proxied = login(tunnel, **{"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"})
        assert "secure" in _cookie_flags(proxied, DEVICE_COOKIE)
    with TestClient(app, base_url=BASE_URL) as lan:
        assert DEVICE_COOKIE not in repr(login(lan, "ana", "not the password").headers), "only a login that succeeds"


def test_strangers_cant_lock_the_owner_out_of_a_known_device(app, storage, ticks):
    """Audit finding 8: ten addresses with five wrong passwords each locked any username out everywhere for 15
    minutes, the owner's included. A browser the account logged in on before keeps its device cookie, and that
    username's lock from everywhere doesn't hold it."""
    make_account(storage, "olga", owner=True)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as owners:
        assert login(owners, "olga", **{"X-Forwarded-For": "198.51.100.4"}).status_code == 200
        login(owners, "olga", "a typo", **{"X-Forwarded-For": "198.51.100.4"})
        with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as strangers:
            lock_everywhere(strangers, "olga")
        assert login(owners, "olga", **{"X-Forwarded-For": "198.51.100.4"}).status_code == 200
        assert login(owners, "olga", **{"X-Forwarded-For": "192.0.2.77"}).status_code == 200, "from a new address too"
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as unknown:
        assert login(unknown, "olga", **{"X-Forwarded-For": "198.51.100.4"}).status_code == 429, "a new browser waits"


def test_a_device_cookie_is_for_its_own_account(app, storage, ana, ticks):
    """Logging in to an account of one's own gives a device cookie for that account alone."""
    make_account(storage, "olga", owner=True)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as stranger:
        assert login(stranger, "ana", **{"X-Forwarded-For": "203.0.113.9"}).status_code == 200
        lock_everywhere(stranger, "olga")
        assert login(stranger, "olga", PASSWORD, **{"X-Forwarded-For": "203.0.113.9"}).status_code == 429


def test_a_forged_device_cookie_is_no_device(app, storage, ticks):
    make_account(storage, "olga", owner=True)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as owners:
        login(owners, "olga", **{"X-Forwarded-For": "198.51.100.4"})
        kept = owners.cookies[DEVICE_COOKIE]
        owners.cookies.delete(DEVICE_COOKIE)
        lock_everywhere(owners, "olga")
        account_id, issued, nonce, mac = kept.split(".")
        for forged in (
            f"{account_id}.{issued}.{nonce}.{mac[:-2]}xx",
            f"{account_id}.{int(issued) + 1}.{nonce}.{mac}",
            f"{account_id}.{issued}.other{nonce}.{mac}",
            "nonsense",
            "",
        ):
            owners.cookies.set(DEVICE_COOKIE, forged)
            assert login(owners, "olga", **{"X-Forwarded-For": "198.51.100.4"}).status_code == 429, forged


def test_a_device_cookie_has_its_own_limit(app, storage, ticks):
    """With a device cookie the username's lock from everywhere doesn't hold, so the device has a lock of its own:
    after `PER_DEVICE` failures it waits, whichever address it comes from."""
    make_account(storage, "olga", owner=True)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as device:
        login(device, "olga", **{"X-Forwarded-For": "198.51.100.4"})
        for n in range(LoginThrottle.PER_DEVICE):
            assert login(device, "olga", "nope", **{"X-Forwarded-For": f"10.7.{n}.1"}).status_code == 401
        assert login(device, "olga", **{"X-Forwarded-For": "10.7.99.1"}).status_code == 429
        ticks.now += 15 * 60
        assert login(device, "olga", **{"X-Forwarded-For": "10.7.99.1"}).status_code == 200


def test_a_device_keeps_the_pair_and_address_limits(app, storage, ticks):
    make_account(storage, "olga", owner=True)
    with TestClient(app, base_url=BASE_URL) as device:
        login(device, "olga")
        for n in range(LoginThrottle.PER_ADDRESS):
            login(device, f"user{n:02}", "not the password")
        assert login(device, "olga").status_code == 429, "its address waits, device or not"


def test_a_device_cookie_ends_after_a_year(timed, storage, clock, ticks):
    make_account(storage, "olga", owner=True)
    with TestClient(timed, base_url=BASE_URL, client=("127.0.0.1", 50000)) as owners:
        timed.state.login_throttle.clock = lambda: ticks.now
        login(owners, "olga", **{"X-Forwarded-For": "198.51.100.4"})
        clock._now += timedelta(days=366)
        lock_everywhere(owners, "olga")
        assert login(owners, "olga", **{"X-Forwarded-For": "198.51.100.4"}).status_code == 429


def test_logout_keeps_the_device_cookie(lan, ana):
    login(lan)
    response = _kept(lan.post("/api/logout", json={}))
    assert DEVICE_COOKIE not in response.headers.get("set-cookie", "")
    assert lan.cookies.get(DEVICE_COOKIE)


def test_the_device_secret_is_kept_0600(app, config):
    import stat

    path = config.data_dir / "device-secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(path.read_text().strip()) == 64
