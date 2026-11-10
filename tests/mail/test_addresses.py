"""A player's own address (DEL-314): typed in, it waits for its confirmation link and gets nothing else; the link
confirms it; Google's address fills an account that has none."""

import re
from datetime import timedelta

import pytest

from delve.domain.accounts import Profile
from delve.mail import addresses, outbox
from delve.mail.settings import MailSettings, save, save_key
from delve.play.context import PlayError
from tests.mail.conftest import NOW


@pytest.fixture
def mail_on(tmp_path):
    save(tmp_path, MailSettings(provider="emailit", sender="delve@example.org", public_url="https://delve.example"))
    save_key(tmp_path, "k-1")
    return tmp_path


def account(storage, name="ana"):
    return storage.accounts.create(name, Profile(name.title()))


def queued(storage):
    return storage.mail.due(outbox.iso(NOW + timedelta(days=1)), 50)


def token_in(message) -> str:
    [token] = re.findall(r"https://delve\.example/account/email/([\w-]+)", message.text)
    return token


@pytest.mark.parametrize(
    "raw, expected",
    [("  ana@example.org \n", "ana@example.org"), ("Ana.Lind@Mail.Example.org", "Ana.Lind@Mail.Example.org")],
)
def test_normalise_strips_an_address(raw, expected):
    assert addresses.normalise(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ana",
        "ana@",
        "@example.org",
        "ana@example",
        "ana@@example.org",
        "a@b@example.org",
        "ana lind@example.org",
        "a" * 250 + "@example.org",
    ],
)
def test_normalise_refuses_what_isnt_an_address(raw):
    with pytest.raises(PlayError):
        addresses.normalise(raw)


def test_no_address_is_asked_for_while_mail_isnt_set_up(storage, tmp_path):
    ana = account(storage)
    with pytest.raises(PlayError, match="Email isn't set up on this Delve."):
        addresses.ask_to_confirm(storage, tmp_path, ana, "ana@example.org", NOW)
    assert storage.accounts.get(ana.id).email_pending is None
    assert queued(storage) == []


def test_a_typed_address_waits_and_only_its_confirmation_is_queued(storage, mail_on):
    ana = account(storage)
    addresses.ask_to_confirm(storage, mail_on, ana, "ana@example.org", NOW)
    ana = storage.accounts.get(ana.id)
    assert (ana.email, ana.email_pending) == (None, "ana@example.org")
    [message] = queued(storage)
    assert message.kind == "confirm" and message.account_id == ana.id and message.unsubscribe is None
    assert token_in(message)
    assert "ana@example.org" not in message.text, "the outbox keeps no address"


def test_the_link_confirms_the_address_once(storage, mail_on):
    ana = account(storage)
    addresses.ask_to_confirm(storage, mail_on, ana, "ana@example.org", NOW)
    token = token_in(queued(storage)[0])
    confirmed = addresses.confirm(storage, token, NOW + timedelta(hours=1))
    assert (confirmed.email, confirmed.email_pending) == ("ana@example.org", None)
    assert storage.accounts.get(ana.id).email == "ana@example.org"
    with pytest.raises(PlayError, match="This link has expired or was used."):
        addresses.confirm(storage, token, NOW + timedelta(hours=2))


def test_a_new_address_leaves_the_old_one_in_use_until_it_is_confirmed(storage, mail_on):
    ana = account(storage)
    storage.accounts.set_email(ana.id, email="old@example.org", email_pending=None)
    addresses.ask_to_confirm(storage, mail_on, storage.accounts.get(ana.id), "new@example.org", NOW)
    ana = storage.accounts.get(ana.id)
    assert (ana.email, ana.email_pending) == ("old@example.org", "new@example.org")
    assert outbox.address_for(ana, "reset") == "old@example.org"
    addresses.confirm(storage, token_in(queued(storage)[0]), NOW)
    ana = storage.accounts.get(ana.id)
    assert (ana.email, ana.email_pending) == ("new@example.org", None)


def test_an_expired_link_refuses(storage, mail_on):
    ana = account(storage)
    addresses.ask_to_confirm(storage, mail_on, ana, "ana@example.org", NOW)
    token = token_in(queued(storage)[0])
    with pytest.raises(PlayError, match="expired or was used"):
        addresses.confirm(storage, token, NOW + timedelta(hours=24))
    assert storage.accounts.get(ana.id).email is None


def test_a_superseded_link_refuses(storage, mail_on):
    ana = account(storage)
    addresses.ask_to_confirm(storage, mail_on, ana, "first@example.org", NOW)
    first = token_in(queued(storage)[0])
    addresses.ask_to_confirm(storage, mail_on, storage.accounts.get(ana.id), "second@example.org", NOW)
    with pytest.raises(PlayError, match="expired or was used"):
        addresses.confirm(storage, first, NOW)
    assert storage.accounts.get(ana.id).email is None


def test_a_link_for_an_address_since_removed_refuses(storage, mail_on):
    ana = account(storage)
    addresses.ask_to_confirm(storage, mail_on, ana, "ana@example.org", NOW)
    token = token_in(queued(storage)[0])
    addresses.remove(storage, ana.id)
    with pytest.raises(PlayError, match="expired or was used"):
        addresses.confirm(storage, token, NOW)
    ana = storage.accounts.get(ana.id)
    assert (ana.email, ana.email_pending) == (None, None)


def test_an_unknown_link_refuses(storage):
    with pytest.raises(PlayError, match="expired or was used"):
        addresses.confirm(storage, "nothing-like-it", NOW)


def test_a_disabled_accounts_link_refuses(storage, mail_on):
    ana = account(storage)
    addresses.ask_to_confirm(storage, mail_on, ana, "ana@example.org", NOW)
    token = token_in(queued(storage)[0])
    storage.accounts.set_disabled(ana.id, outbox.iso(NOW))
    with pytest.raises(PlayError, match="expired or was used"):
        addresses.confirm(storage, token, NOW)


def test_googles_address_fills_only_an_account_without_one(storage):
    empty, typed, waiting = account(storage, "empty"), account(storage, "typed"), account(storage, "waiting")
    storage.accounts.set_email(typed.id, email="mine@example.org", email_pending=None)
    storage.accounts.set_email(waiting.id, email=None, email_pending="soon@example.org")
    for each in (empty, typed, waiting):
        addresses.from_google(storage, storage.accounts.get(each.id), "g@gmail.com")
    assert storage.accounts.get(empty.id).email == "g@gmail.com"
    assert storage.accounts.get(typed.id).email == "mine@example.org"
    assert (storage.accounts.get(waiting.id).email, storage.accounts.get(waiting.id).email_pending) == (
        None,
        "soon@example.org",
    )


def test_an_unverified_google_address_fills_nothing(storage):
    ana = account(storage)
    addresses.from_google(storage, ana, "")
    assert storage.accounts.get(ana.id).email is None
