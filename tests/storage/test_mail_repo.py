"""Email storage (DEL-314): an account's address and switches, the outbox, confirmations and board follows."""

import pytest

from delve.config import Config
from delve.domain.accounts import Profile
from delve.domain.board import Post, Topic, Zone
from delve.domain.mail import Confirmation, Outgoing
from delve.storage import open_storage

NOW = "2026-10-30T10:00:00+00:00"
LATER = "2026-10-30T11:00:00+00:00"


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path))
    yield opened
    opened.close()


def make_account(storage, name):
    return storage.accounts.create(name, Profile(name.title()))


def outgoing(id, account_id, next_at=NOW, **fields):
    values = {
        "id": id,
        "kind": "host",
        "account_id": account_id,
        "language": "en",
        "subject": "s",
        "text": "t",
        "html": "<p>t</p>",
        "reply_to": None,
        "unsubscribe": None,
        "created_at": NOW,
        "next_at": next_at,
    }
    return Outgoing(**{**values, **fields})


def confirmation(token, account_id, address="ana@example.org"):
    return Confirmation(token, account_id, address, NOW, LATER)


def test_an_accounts_address_and_switches_round_trip(storage):
    account = make_account(storage, "ana")
    assert (account.email, account.email_pending, account.mail_host, account.mail_board) == (None, None, True, True)
    storage.accounts.set_email(account.id, email="ana@example.org", email_pending=None)
    storage.accounts.set_mail_switches(account.id, mail_host=False, mail_board=True)
    got = storage.accounts.get(account.id)
    assert (got.email, got.email_pending, got.mail_host, got.mail_board) == ("ana@example.org", None, False, True)
    assert [a.id for a in storage.accounts.with_email("ANA@example.org")] == [account.id]


def test_with_email_skips_pending_addresses_and_disabled_or_unapproved_accounts(storage):
    typed = make_account(storage, "typed")
    storage.accounts.set_email(typed.id, email=None, email_pending="x@example.org")
    off = make_account(storage, "off")
    storage.accounts.set_email(off.id, email="x@example.org", email_pending=None)
    storage.accounts.set_disabled(off.id, NOW)
    waiting = storage.accounts.create("waiting", Profile("W"), pending=True)
    storage.accounts.set_email(waiting.id, email="x@example.org", email_pending=None)
    assert storage.accounts.with_email("x@example.org") == []


def test_the_outbox_hands_out_due_messages_and_records_their_end(storage):
    account = make_account(storage, "ana")
    storage.mail.add(outgoing("m1", account.id, next_at=NOW))
    storage.mail.add(outgoing("m2", account.id, next_at=LATER))
    assert [m.id for m in storage.mail.due(NOW, 10)] == ["m1"]
    storage.mail.sent("m1", NOW)
    assert [m.id for m in storage.mail.due(LATER, 10)] == ["m2"] and storage.mail.sent_since(NOW) == 1
    storage.mail.retry("m2", 1, "2026-10-30T12:00:00+00:00")
    assert storage.mail.due(LATER, 10) == []
    assert storage.mail.due("2026-10-30T12:00:00+00:00", 10)[0].attempts == 1


def test_failed_and_dropped_messages_leave_the_queue_and_are_listed_newest_first(storage):
    account = make_account(storage, "ana")
    for id in ("a", "b", "c"):
        storage.mail.add(outgoing(id, account.id, reply_to="host@example.org"))
    storage.mail.failed("a", NOW, "bad address")
    storage.mail.dropped("b", LATER)
    assert [m.id for m in storage.mail.due(LATER, 10)] == ["c"]
    failures = storage.mail.recent_failures(10)
    assert [(m.id, m.failure, m.reply_to) for m in failures] == [("b", "dropped", None), ("a", "bad address", None)]
    assert [m.id for m in storage.mail.recent_failures(10, dropped=False)] == ["a"], "real failures alone"


def test_waiting_counts_the_messages_neither_sent_nor_failed(storage):
    account = make_account(storage, "ana")
    for id, next_at in (("a", NOW), ("b", LATER), ("c", NOW), ("d", NOW)):
        storage.mail.add(outgoing(id, account.id, next_at=next_at))
    storage.mail.sent("c", NOW)
    storage.mail.failed("d", NOW, "bad address")
    assert storage.mail.waiting() == 2, "due now or later alike"


def test_sending_clears_the_hosts_reply_address_and_prune_forgets_old_sent_mail(storage):
    account = make_account(storage, "ana")
    storage.mail.add(outgoing("m1", account.id, reply_to="host@example.org"))
    storage.mail.add(outgoing("m2", account.id))
    storage.mail.sent("m1", NOW)
    storage.mail.prune_sent(LATER)
    assert storage.mail.sent_since("2000-01-01") == 0
    assert [m.id for m in storage.mail.due(LATER, 10)] == ["m2"]


def test_a_new_confirmation_drops_the_unused_one(storage):
    ana, bo = make_account(storage, "ana"), make_account(storage, "bo")
    storage.mail.put_confirmation(confirmation("h1", ana.id))
    storage.mail.put_confirmation(confirmation("hb", bo.id))
    storage.mail.put_confirmation(confirmation("h2", ana.id, "new@example.org"))
    assert storage.mail.confirmation("h1") is None
    assert storage.mail.confirmation("h2").address == "new@example.org"
    assert storage.mail.confirmation("hb") is not None
    assert storage.mail.use_confirmation("h2", NOW) is True
    assert storage.mail.use_confirmation("h2", NOW) is False
    assert storage.mail.confirmation("h2").used_at == NOW
    storage.mail.put_confirmation(confirmation("h3", ana.id))  # a used one stays
    assert storage.mail.confirmation("h2") is not None


def test_deleting_an_account_drops_its_mail_and_confirmations(storage):
    account = storage.accounts.create("gone", Profile("Gone"), pending=True)
    storage.mail.add(outgoing("m1", account.id))
    storage.mail.put_confirmation(confirmation("h1", account.id))
    assert storage.accounts.delete_pending(account.id)
    assert storage.mail.due(LATER, 10) == [] and storage.mail.confirmation("h1") is None


def test_a_topics_followers_and_their_last_notice(storage):
    ana, bo = make_account(storage, "ana"), make_account(storage, "bo")
    zone = storage.board.create_zone(Zone("", "Z"))
    topic, _ = storage.board.add_topic(
        Topic("", zone.id, "T", ana.id, NOW, NOW, ana.id), Post("", "", ana.id, "hi", NOW)
    )
    assert not storage.board.following(ana.id, topic.id)
    storage.board.follow(ana.id, topic.id)
    storage.board.follow(ana.id, topic.id)
    storage.board.follow(bo.id, topic.id)
    storage.board.set_notified(ana.id, topic.id, NOW)
    assert storage.board.following(ana.id, topic.id)
    assert storage.board.followers(topic.id) == sorted([(ana.id, NOW), (bo.id, None)])
    storage.board.unfollow(ana.id, topic.id)
    assert storage.board.followers(topic.id) == [(bo.id, None)]
    storage.board.delete_topic(topic.id)
    assert storage.board.followers(topic.id) == []
