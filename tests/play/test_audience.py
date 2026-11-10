"""Who sees what (plan 4 Task 3, spec §7.5): `can_see` for every role and audience, the characters a seat plays, and
an audience of characters resolved to seats as it is stored (audit finding 1)."""

import pytest

from delve.domain.campaigns import Seat
from delve.play import seats
from delve.play.audience import can_see, resolve, roles_for, seat_controls
from delve.play.table import add_entry, story

ROLES = ("host", "cohost", "player", "observer")


def seat(role, seat_id="seat_a", left_at=None):
    return Seat(seat_id, "cmp_1", "Ana", "en", role, left_at=left_at)


@pytest.mark.parametrize("role", ROLES)
def test_everyone_sees_what_is_for_everyone(role):
    assert can_see(seat(role), None, set())


@pytest.mark.parametrize("role", ("host", "cohost", "player"))
def test_characters_are_seen_by_the_seats_that_play_them(role):
    audience = {"characters": ["chr_1", "chr_2"]}
    assert can_see(seat(role), audience, {"chr_2", "chr_9"})
    assert not can_see(seat(role), audience, {"chr_9"})
    assert not can_see(seat(role), audience, set())


@pytest.mark.parametrize("role", ("host", "cohost", "player"))
def test_seats_are_seen_by_those_seats(role):
    assert can_see(seat(role), {"seats": ["seat_a", "seat_b"]}, set())
    assert not can_see(seat(role), {"seats": ["seat_b"]}, {"chr_1"})


def test_observers_see_only_what_is_for_everyone():
    observer = seat("observer")
    assert not can_see(observer, {"seats": ["seat_a"]}, set())
    assert not can_see(observer, {"characters": ["chr_1"]}, {"chr_1"})


@pytest.mark.parametrize(
    "audience",
    [{}, {"party": ["chr_1"]}, {"characters": "chr_1"}, {"characters": ["chr_1"], "seats": ["seat_a"]}, ["seat_a"]],
)
def test_an_audience_delve_doesnt_know_is_seen_by_nobody(audience):
    assert not can_see(seat("host"), audience, {"chr_1"})


def test_a_seat_that_left_sees_nothing():
    gone = seat("player", left_at="2026-10-18T10:00:00+00:00")
    assert not can_see(gone, None, set())
    assert not can_see(gone, {"seats": ["seat_a"]}, set())


def make_campaign(storage):
    module = storage.modules.create("The Crypt")
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")


def test_the_host_plays_their_own_and_every_free_pc(storage):
    campaign = make_campaign(storage)
    host = seats.owner_seat(storage, campaign.id)
    player = storage.seats.create(campaign.id, "Bo", "en", "player")
    garrek = storage.characters.create(campaign.id, "Garrek")
    tira = storage.characters.create(campaign.id, "Tira")
    storage.characters.create(campaign.id, "Grik", kind="npc")
    seats.claim(storage, tira.id, player)

    assert seat_controls(storage, host) == {garrek.id}
    assert seat_controls(storage, player) == {tira.id}
    cohost = storage.seats.create(campaign.id, "Cy", "en", "cohost")
    assert seat_controls(storage, cohost) == set()


def test_the_story_pages_by_what_the_seat_sees(storage):
    campaign = make_campaign(storage)
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    storage.story.append(campaign.id, None, "dm_text", {"text": "for everyone"})
    for n in range(120):  # more than a page of the store, all for Bo
        storage.story.append(campaign.id, None, "answer", {"text": f"for Bo {n}"}, {"seats": [bo.id]})
    storage.story.append(campaign.id, None, "ask", {"text": "Ana's"}, {"seats": [ana.id]})

    page = story(storage, campaign.id, ana, limit=1)
    assert [e.payload["text"] for e in page["entries"]] == ["Ana's"] and page["has_more"] is True
    earlier = story(storage, campaign.id, ana, before_seq=page["entries"][0].seq, limit=1)
    assert [e.payload["text"] for e in earlier["entries"]] == ["for everyone"] and earlier["has_more"] is False
    assert len(story(storage, campaign.id, bo, limit=200)["entries"]) == 121
    observer = storage.seats.create(campaign.id, "Cy", "en", "observer")
    assert [e.payload["text"] for e in story(storage, campaign.id, observer)["entries"]] == ["for everyone"]


def test_an_audience_of_characters_is_stored_as_the_seats_that_play_them_then(storage):
    campaign = make_campaign(storage)
    host = seats.owner_seat(storage, campaign.id)
    ana = storage.seats.create(campaign.id, "Ana", "en", "player")
    bo = storage.seats.create(campaign.id, "Bo", "en", "player")
    cy = storage.seats.create(campaign.id, "Cy", "en", "observer")
    garrek, tira, hob = (storage.characters.create(campaign.id, name).id for name in ("Garrek", "Tira", "Hob"))
    seats.claim(storage, garrek, ana)
    seats.claim(storage, tira, bo)

    assert resolve(storage, campaign.id, {"characters": [garrek]}) == {"seats": [ana.id]}
    assert resolve(storage, campaign.id, {"characters": [garrek, tira]}) == {"seats": [ana.id, bo.id]}
    assert resolve(storage, campaign.id, {"characters": [hob]}) == {"seats": [host.id]}, "a free PC is the host's"
    assert resolve(storage, campaign.id, {"characters": ["chr_000000000000"]}) == {"seats": []}
    for other in (None, {"seats": [cy.id]}, {"party": [garrek]}, {"characters": garrek}):
        assert resolve(storage, campaign.id, other) == other

    entry = add_entry(storage, campaign.id, None, "dm_text", {"text": "Psst.", "told_to": [garrek]}, {"characters": [garrek]})
    assert storage.story.get(entry.id).audience == {"seats": [ana.id]}
    seats.leave(storage, ana)
    seats.claim(storage, garrek, bo)
    assert [e.id for e in story(storage, campaign.id, storage.seats.get(bo.id))["entries"]] == []
    assert resolve(storage, campaign.id, {"characters": [garrek]}) == {"seats": [bo.id]}, "a seat that left is out"


def test_tool_rows_are_for_the_seats_that_run_the_table():
    """Review Focus 4 of the walkthrough fixes: a tool row is the host's and the co-hosts', a refused one the host's
    alone; the players and observers see only what the characters perceive."""
    shown, refused = roles_for("tool", {"name": "roll"}), roles_for("tool", {"name": "roll", "failed": True})
    assert can_see(seat("host"), None, set(), shown) and can_see(seat("cohost"), None, set(), shown)
    assert can_see(seat("host"), None, set(), refused) and not can_see(seat("cohost"), None, set(), refused)
    for role in ("player", "observer"):
        assert not can_see(seat(role), None, set(), shown) and not can_see(seat(role), None, set(), refused)
    assert roles_for("tool", {"name": "roll", "error": "old row"}) == refused
    for kind in ("dm_text", "player_act", "image", "recap", "dm_error"):
        assert roles_for(kind, {"name": "roll", "failed": True}) is None


def test_the_story_keeps_tool_rows_for_the_host(storage):
    campaign = make_campaign(storage)
    host = seats.owner_seat(storage, campaign.id)
    cohost = storage.seats.create(campaign.id, "Bo", "en", "cohost")
    player = storage.seats.create(campaign.id, "Ana", "en", "player")
    storage.story.append(campaign.id, None, "dm_text", {"text": "The door creaks."})
    storage.story.append(campaign.id, None, "tool", {"name": "roll"})
    storage.story.append(campaign.id, None, "tool", {"name": "combat_round", "failed": True})

    def kinds(viewer):
        return [(e.kind, e.payload.get("name")) for e in story(storage, campaign.id, viewer)["entries"]]

    assert kinds(host) == [("dm_text", None), ("tool", "roll"), ("tool", "combat_round")]
    assert kinds(cohost) == [("dm_text", None), ("tool", "roll")]
    assert kinds(player) == [("dm_text", None)]
    page = story(storage, campaign.id, player, limit=1)
    assert [e.kind for e in page["entries"]] == ["dm_text"] and page["has_more"] is False
