"""Board replies by email (DEL-314): a follower of a topic gets one email for a new reply, then none until they come
back to the topic; never for their own post, never once they may no longer read the zone, and nothing while mail is
off."""

from dataclasses import replace
from datetime import timedelta

import pytest

from delve.mail.board_mail import excerpt, notify
from delve.mail.settings import MailSettings, save, save_key
from delve.play import board
from delve.play.board_rights import Caller
from tests.mail.conftest import NOW, with_address

FAR = "2100-01-01T00:00:00+00:00"


@pytest.fixture
def data_dir(tmp_path):
    save(tmp_path, MailSettings(provider="emailit", sender="delve@example.org", public_url="https://delve.example"))
    save_key(tmp_path, "k-1")
    return tmp_path


def as_caller(account):
    return Caller(account, account.organiser, account.owner)


@pytest.fixture
def thread(storage):
    """A zone open to accounts with a topic bob started; ana follows it."""
    ana, bob = with_address(storage, "ana"), with_address(storage, "bob")
    zone = board.create_zone(storage, Caller(owner=True), {"name": "Engine"}, NOW)
    topic, _ = board.start_topic(storage, as_caller(bob), zone.id, "Morale", "Roll it in the open?", NOW)
    storage.board.follow(ana.id, topic.id)
    return ana, bob, zone, topic


def reply_by(storage, account, topic, n):
    return board.reply(storage, as_caller(account), topic.id, f"Reply **{n}**.", NOW + timedelta(minutes=n))


def queued(storage, kind, account):
    return [m for m in storage.mail.due(FAR, 100) if m.kind == kind and m.account_id == account.id]


def test_a_lively_thread_sends_one_mail_until_the_follower_comes_back(storage, data_dir, thread):
    ana, bob, _, topic = thread
    for n in range(5):
        notify(storage, data_dir, topic, reply_by(storage, bob, topic, n), bob.id, NOW + timedelta(minutes=n))
    assert len(queued(storage, "board", ana)) == 1
    storage.board.mark_read(ana.id, topic.id, (NOW + timedelta(minutes=10)).isoformat())
    later = NOW + timedelta(minutes=11)
    assert notify(storage, data_dir, topic, reply_by(storage, bob, topic, 11), bob.id, later) == 1
    assert len(queued(storage, "board", ana)) == 2


def test_reading_up_to_the_reply_mailed_counts_as_coming_back(storage, data_dir, thread):
    ana, bob, _, topic = thread
    first = reply_by(storage, bob, topic, 1)
    notify(storage, data_dir, topic, first, bob.id, NOW + timedelta(minutes=1))
    storage.board.mark_read(ana.id, topic.id, first.created_at)
    notify(storage, data_dir, topic, reply_by(storage, bob, topic, 2), bob.id, NOW + timedelta(minutes=2))
    assert len(queued(storage, "board", ana)) == 2


def test_the_mail_names_the_poster_the_topic_and_the_zone_and_links_to_the_topic(storage, data_dir, thread):
    ana, bob, zone, topic = thread
    notify(storage, data_dir, topic, reply_by(storage, bob, topic, 1), bob.id, NOW)
    [mail] = queued(storage, "board", ana)
    assert mail.subject == "Bob replied in Morale"
    assert "Reply 1." in mail.text and "**" not in mail.text
    assert f"https://delve.example/board/{zone.id}/{topic.id}" in mail.text
    assert mail.unsubscribe and mail.unsubscribe.startswith(f"{ana.id}.board.")
    assert "/mail/off/" in mail.text


def test_no_mail_for_ones_own_post(storage, data_dir, thread):
    ana, bob, _, topic = thread
    storage.board.follow(bob.id, topic.id)
    assert notify(storage, data_dir, topic, reply_by(storage, ana, topic, 1), ana.id, NOW) == 1
    assert queued(storage, "board", ana) == []
    assert len(queued(storage, "board", bob)) == 1


def test_no_mail_once_the_zone_is_closed_to_the_follower(storage, data_dir, thread):
    ana, bob, zone, topic = thread
    storage.board.save_zone(replace(zone, read="members", write="members", members=(bob.id,)))
    assert notify(storage, data_dir, topic, reply_by(storage, bob, topic, 1), bob.id, NOW) == 0
    assert queued(storage, "board", ana) == []


def test_no_mail_with_the_board_switch_off_or_mail_off(storage, tmp_path, data_dir, thread):
    ana, bob, _, topic = thread
    storage.accounts.set_mail_switches(ana.id, mail_host=True, mail_board=False)
    assert notify(storage, data_dir, topic, reply_by(storage, bob, topic, 1), bob.id, NOW) == 0
    storage.accounts.set_mail_switches(ana.id, mail_host=True, mail_board=True)
    save(tmp_path, MailSettings(provider="log", sender="", public_url="https://delve.example"))
    assert notify(storage, data_dir, topic, reply_by(storage, bob, topic, 2), bob.id, NOW) == 0
    assert queued(storage, "board", ana) == []
    # Nothing was sent, so the first mail is still to come.
    assert storage.board.followers(topic.id) == [(ana.id, None)]


def test_the_excerpt_drops_the_marks_and_stops_on_a_word():
    assert excerpt("## Hi\n\n> **bold** and _it_ [a link](https://x.example)\n- one\n1. two") == (
        "Hi bold and it a link one two"
    )
    long = "word " * 100
    cut = excerpt(long)
    assert len(cut) <= 301 and cut.endswith("word…")
    assert excerpt("snake_case stays") == "snake_case stays"
