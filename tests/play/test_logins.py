"""Login sessions (players and tavern Task C1): a token that stands for an account, alive until 30 days after its
last use, ended by logging out, a password change (but this one), a reset link (all), or disabling the account."""

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from delve.play import logins
from delve.play.accounts import create_account, make_link
from delve.play.seats import NotAllowed

PASSWORD = "correct horse battery"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _day(n: float) -> datetime:
    return NOW + timedelta(days=n)


def test_session_round_trip(storage):
    ana = create_account(storage, "ana", PASSWORD)
    token = logins.start(storage, ana.id, "Firefox on a phone", "192.0.2.7", NOW)
    account, login = logins.resolve(storage, token, NOW)
    assert account == ana
    assert (login.account_id, login.device, login.address) == (ana.id, "Firefox on a phone", "192.0.2.7")
    assert login.created_at == login.last_used_at == NOW.isoformat()
    assert logins.resolve(storage, "not a token", NOW) is None
    logins.end(storage, token)
    assert logins.resolve(storage, token, NOW) is None


def test_device_cut_to_200(storage):
    ana = create_account(storage, "ana", PASSWORD)
    token = logins.start(storage, ana.id, "x" * 500, "", NOW)
    assert logins.resolve(storage, token, NOW)[1].device == "x" * 200


def test_session_ends_30_days_after_last_use(storage):
    ana = create_account(storage, "ana", PASSWORD)
    used = logins.start(storage, ana.id, "", "", NOW)
    unused = logins.start(storage, ana.id, "", "", NOW)
    assert logins.resolve(storage, used, _day(29)) is not None
    assert logins.resolve(storage, used, _day(58)) is not None, "30 days from its last use, not from its start"
    assert logins.resolve(storage, unused, _day(30)) is None
    assert storage.login_sessions.by_token_hash(hashlib.sha256(unused.encode()).hexdigest()) is None, "and its row gone"
    assert logins.resolve(storage, used, _day(58 + 30)) is None


def test_touch_at_most_once_a_minute(storage):
    ana = create_account(storage, "ana", PASSWORD)
    token = logins.start(storage, ana.id, "", "", NOW)
    assert logins.resolve(storage, token, NOW + timedelta(seconds=59))[1].last_used_at == NOW.isoformat()
    later = NOW + timedelta(seconds=61)
    assert logins.resolve(storage, token, later)[1].last_used_at == later.isoformat()
    assert storage.login_sessions.list(ana.id)[0].last_used_at == later.isoformat()


def test_disabled_account_has_no_session(storage):
    ana = create_account(storage, "ana", PASSWORD)
    bo = create_account(storage, "bram", PASSWORD)
    token = logins.start(storage, ana.id, "", "", NOW)
    kept = logins.start(storage, bo.id, "", "", NOW)
    storage.accounts.set_disabled(ana.id, NOW.isoformat())
    assert logins.resolve(storage, token, NOW) is None, "disabled by hand: the session no longer counts"
    storage.accounts.set_disabled(ana.id, None)
    logins.disable(storage, ana.id, True, NOW, by_owner=False)
    assert storage.login_sessions.list(ana.id) == [], "disabling ends every login"
    assert logins.resolve(storage, token, NOW) is None
    assert logins.resolve(storage, kept, NOW) is not None
    logins.disable(storage, ana.id, False, NOW, by_owner=False)
    assert logins.resolve(storage, token, NOW) is None, "enabling again doesn't bring a session back"


def test_disable_refused_ends_nothing(storage):
    owner = create_account(storage, "olga", PASSWORD, owner=True)
    token = logins.start(storage, owner.id, "", "", NOW)
    with pytest.raises(NotAllowed):
        logins.disable(storage, owner.id, True, NOW, by_owner=False)
    assert logins.resolve(storage, token, NOW) is not None


def test_password_change_ends_other_sessions(storage):
    ana = create_account(storage, "ana", PASSWORD)
    tokens = [logins.start(storage, ana.id, "", "", NOW) for _ in range(3)]
    keep = logins.resolve(storage, tokens[0], NOW)[1].id
    logins.change_password(storage, ana.id, PASSWORD, "a new password here", keep=keep)
    assert logins.resolve(storage, tokens[0], NOW) is not None
    assert logins.resolve(storage, tokens[1], NOW) is None and logins.resolve(storage, tokens[2], NOW) is None


def test_wrong_old_password_ends_nothing(storage):
    ana = create_account(storage, "ana", PASSWORD)
    tokens = [logins.start(storage, ana.id, "", "", NOW) for _ in range(2)]
    keep = logins.resolve(storage, tokens[0], NOW)[1].id
    with pytest.raises(NotAllowed):
        logins.change_password(storage, ana.id, "not the password", "a new password here", keep=keep)
    assert all(logins.resolve(storage, token, NOW) is not None for token in tokens)


def test_reset_link_ends_every_session(storage):
    ana = create_account(storage, "ana", PASSWORD)
    tokens = [logins.start(storage, ana.id, "", "", NOW) for _ in range(2)]
    link = make_link(storage, ana.id, "reset-password", NOW, by_owner=False)
    assert logins.use_link(storage, link, "a new password here", NOW) == storage.accounts.get(ana.id)
    assert all(logins.resolve(storage, token, NOW) is None for token in tokens)


def test_token_stored_only_as_hash(storage, tmp_path):
    ana = create_account(storage, "ana", PASSWORD)
    token = logins.start(storage, ana.id, "Firefox", "192.0.2.7", NOW)
    with sqlite3.connect(tmp_path / "data" / "delve.db") as db:
        rows = db.execute("SELECT * FROM login_sessions").fetchall()
    assert len(rows) == 1
    assert token not in repr(rows) and hashlib.sha256(token.encode()).hexdigest() in rows[0]
