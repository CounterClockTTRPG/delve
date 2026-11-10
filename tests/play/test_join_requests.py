"""Join requests (DEL-204 part B): an account asks to join a public table with a short note, talks with the hosts on
the request, and withdraws it; the host or a co-host accepts it, which seats the account as a player, or declines it,
with a reason in the thread."""

from datetime import UTC, datetime, timedelta

import pytest

from delve.domain.accounts import Profile
from delve.play import join_requests, seats
from delve.play.context import PlayError
from delve.play.join_requests import RequestConflict
from delve.play.seats import TableFull

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


@pytest.fixture
def public(storage, campaign):
    seats.owner_seat(storage, campaign.id)
    return storage.campaigns.set_listing(campaign.id, "public", "Newcomers welcome.", None)


@pytest.fixture
def ana(storage):
    return storage.accounts.create("ana", Profile("Ana", language="nl"))


def _ask(storage, campaign, account, note="Hi! I'd love to play.", at=NOW):
    return join_requests.ask(storage, campaign, account, note, at)


# ----- asking -----


def test_asking_starts_the_thread_with_the_note(storage, public, ana):
    asked = _ask(storage, public, ana, "  Hi! I'd love to play.  ")
    assert (asked.campaign_id, asked.account_id, asked.status) == (public.id, ana.id, "pending")
    assert asked.messages == (
        {"from": "player", "name": "Ana", "text": "Hi! I'd love to play.", "at": NOW.isoformat()},
    )
    assert asked.created_at == NOW.isoformat() and asked.decided_at is None and asked.seat_id is None
    assert storage.join_requests.get(asked.id) == asked


def test_an_empty_note_starts_an_empty_thread(storage, public, ana):
    assert _ask(storage, public, ana, "   ").messages == ()


def test_a_note_past_1000_characters_is_refused(storage, public, ana):
    with pytest.raises(PlayError) as refused:
        _ask(storage, public, ana, "x" * 1001)
    assert not isinstance(refused.value, RequestConflict)
    assert _ask(storage, public, ana, " " + "x" * 1000 + " ").messages[0]["text"] == "x" * 1000, "1000 after strip"


def test_one_pending_request_per_table(storage, public, ana):
    _ask(storage, public, ana)
    with pytest.raises(RequestConflict) as refused:
        _ask(storage, public, ana)
    assert refused.value.message == "You asked already: wait for the host."


def test_a_seated_account_does_not_ask(storage, public, ana):
    storage.seats.create(public.id, "Ana", "nl", "observer", account_id=ana.id)
    with pytest.raises(RequestConflict) as refused:
        _ask(storage, public, ana)
    assert refused.value.message == "You're at this table already."


def test_the_owner_account_is_seated_everywhere(storage, public):
    owner = storage.accounts.create("olga", Profile("Olga"), owner=True)
    with pytest.raises(RequestConflict):
        _ask(storage, public, owner)


def test_a_full_table_takes_no_request(storage, public, ana):
    storage.campaigns.set_listing(public.id, "public", "", 1)
    storage.seats.create(public.id, "Bo", "en", "player")
    with pytest.raises(TableFull):
        _ask(storage, storage.campaigns.get(public.id), ana)


# ----- talking -----


def test_the_player_and_the_hosts_talk_on_the_request(storage, public, ana):
    asked = _ask(storage, public, ana)
    later = NOW + timedelta(minutes=5)
    replied = join_requests.say(storage, asked.id, "host", "Host", "  Welcome! Tuesdays at eight.  ", later)
    answered = join_requests.say(storage, asked.id, "player", "Ana", "Great.", later)
    assert [m["from"] for m in answered.messages] == ["player", "host", "player"]
    assert replied.messages[1] == {
        "from": "host",
        "name": "Host",
        "text": "Welcome! Tuesdays at eight.",
        "at": later.isoformat(),
    }
    assert storage.join_requests.get(asked.id) == answered


def test_a_message_has_1_to_1000_characters(storage, public, ana):
    asked = _ask(storage, public, ana)
    for wrong in ("", "   ", "x" * 1001):
        with pytest.raises(PlayError) as refused:
            join_requests.say(storage, asked.id, "player", "Ana", wrong, NOW)
        assert not isinstance(refused.value, RequestConflict)
    assert storage.join_requests.get(asked.id).messages == asked.messages


def test_a_thread_holds_50_messages(storage, public, ana):
    asked = _ask(storage, public, ana)
    for n in range(49):
        join_requests.say(storage, asked.id, "player", "Ana", f"message {n}", NOW)
    assert len(storage.join_requests.get(asked.id).messages) == 50
    with pytest.raises(RequestConflict) as refused:
        join_requests.say(storage, asked.id, "host", "Host", "One more?", NOW)
    assert refused.value.message == "Talk at the table once you're seated."


def test_a_decided_request_takes_no_message(storage, public, ana):
    asked = _ask(storage, public, ana)
    join_requests.withdraw(storage, asked.id, NOW)
    with pytest.raises(RequestConflict):
        join_requests.say(storage, asked.id, "player", "Ana", "Wait!", NOW)


# ----- withdrawing -----


def test_withdrawing(storage, public, ana):
    asked = _ask(storage, public, ana)
    later = NOW + timedelta(hours=1)
    withdrawn = join_requests.withdraw(storage, asked.id, later)
    assert (withdrawn.status, withdrawn.decided_at) == ("withdrawn", later.isoformat())
    with pytest.raises(RequestConflict):
        join_requests.withdraw(storage, asked.id, later)
    assert _ask(storage, public, ana).status == "pending", "asking again"


# ----- accepting -----


def test_accepting_seats_the_account_as_a_player(storage, public, ana):
    asked = _ask(storage, public, ana)
    accepted, seat, made = join_requests.accept(storage, asked.id, NOW)
    assert made and (seat.account_id, seat.role, seat.name, seat.language) == (ana.id, "player", "Ana", "nl")
    assert (accepted.status, accepted.seat_id, accepted.decided_at) == ("accepted", seat.id, NOW.isoformat())
    assert storage.seats.for_account(ana.id, public.id) == seat
    with pytest.raises(RequestConflict):
        join_requests.accept(storage, asked.id, NOW)


def test_the_new_seat_s_name_is_made_unique(storage, public, ana):
    storage.seats.create(public.id, "ana", "en", "player")
    _, seat, _ = join_requests.accept(storage, _ask(storage, public, ana).id, NOW)
    assert seat.name == "Ana (2)"


def test_accepting_at_a_full_table_is_refused(storage, public, ana):
    asked = _ask(storage, public, ana)
    storage.campaigns.set_listing(public.id, "public", "", 1)
    storage.seats.create(public.id, "Bo", "en", "player")
    with pytest.raises(TableFull):
        join_requests.accept(storage, asked.id, NOW)
    assert storage.join_requests.get(asked.id).status == "pending"
    assert storage.seats.for_account(ana.id, public.id) is None


def test_accepting_a_seated_account_keeps_its_seat(storage, public, ana):
    asked = _ask(storage, public, ana)
    storage.campaigns.set_listing(public.id, "public", "", 1)
    seat = storage.seats.create(public.id, "Ana", "nl", "player", account_id=ana.id)  # joined by the link meanwhile
    accepted, kept, made = join_requests.accept(storage, asked.id, NOW)
    assert not made and kept == seat and (accepted.status, accepted.seat_id) == ("accepted", seat.id)


# ----- declining -----


def test_declining_adds_the_reason_to_the_thread(storage, public, ana):
    asked = _ask(storage, public, ana)
    declined = join_requests.decline(storage, asked.id, "Host", "  We're full for this arc.  ", NOW)
    assert (declined.status, declined.decided_at) == ("declined", NOW.isoformat())
    assert declined.messages[-1] == {
        "from": "host",
        "name": "Host",
        "text": "We're full for this arc.",
        "at": NOW.isoformat(),
    }
    with pytest.raises(RequestConflict):
        join_requests.decline(storage, asked.id, "Host", "", NOW)


def test_declining_without_a_reason(storage, public, ana):
    asked = _ask(storage, public, ana)
    assert join_requests.decline(storage, asked.id, "Host", "  ", NOW).messages == asked.messages
    other = storage.accounts.create("bo", Profile("Bo"))
    with pytest.raises(PlayError):
        join_requests.decline(storage, _ask(storage, public, other).id, "Host", "x" * 1001, NOW)


# ----- the host's list -----


def test_the_host_reads_the_pending_then_the_recently_decided(storage, public):
    people = [storage.accounts.create(name, Profile(name.title())) for name in ("ana", "bo", "cy", "dee", "eve")]
    asked = [_ask(storage, public, p, at=NOW + timedelta(minutes=n)) for n, p in enumerate(people)]
    join_requests.decline(storage, asked[0].id, "Host", "", NOW - timedelta(days=15))  # long ago: not listed
    join_requests.withdraw(storage, asked[1].id, NOW - timedelta(days=2))
    join_requests.decline(storage, asked[2].id, "Host", "", NOW - timedelta(days=1))
    listed = join_requests.for_host(storage, public.id, NOW)
    assert [r.id for r in listed] == [asked[3].id, asked[4].id, asked[2].id, asked[1].id]
