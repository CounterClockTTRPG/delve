"""Seats (plan 4 Task 1; spec §7.2, §11): the people at a table, their roles, and the characters they play."""

import pytest

from delve.play import seats
from delve.play.context import NotFound, PlayError
from delve.play.seats import NotAllowed, SeatConflict


@pytest.fixture
def host(storage, campaign):
    return seats.create_owner_seat(storage, campaign.id)


@pytest.fixture
def ana(storage, campaign):
    return storage.seats.create(campaign.id, "Ana", "nl", "player")


@pytest.fixture
def bo(storage, campaign):
    return storage.seats.create(campaign.id, "Bo", "en", "player")


def test_the_owner_seat(storage, campaign):
    mira = storage.characters.create(campaign.id, "Mira")
    owner = seats.create_owner_seat(storage, campaign.id)
    assert (owner.name, owner.language, owner.role, owner.owner, owner.organiser) == ("Host", "en", "host", True, True)
    assert seats.owner_seat(storage, campaign.id) == owner
    assert seats.controls(storage, owner.id) == set(), "a new seat plays nothing until it claims"
    seats.claim(storage, mira.id, owner)
    assert seats.controls(storage, owner.id) == {mira.id}


def test_the_owner_seat_is_the_owner_accounts(storage, campaign):
    """With an owner account, the owner's seat is named after it and shows its profile; a player's seat shows its
    own account, and a seat without one none."""
    from delve.domain.accounts import Profile

    saldek = storage.accounts.create("saldek", Profile("Saldek"), owner=True)
    owner = seats.create_owner_seat(storage, campaign.id)
    assert owner.name == "Saldek" and owner.account_id is None
    assert seats.shown_account(storage, owner).id == saldek.id
    ana = storage.accounts.create("ana", Profile("Ana"))
    joined = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    assert seats.shown_account(storage, joined).id == ana.id
    assert seats.shown_account(storage, storage.seats.create(campaign.id, "Bo", "en", "player")) is None


def test_the_owner_seat_is_made_when_missing(storage, campaign):
    """A campaign made outside the API (a test, a script) gets the owner's seat on first use."""
    owner = seats.owner_seat(storage, campaign.id)
    assert owner.owner and owner.role == "host"
    assert seats.owner_seat(storage, campaign.id) == owner
    assert [s.id for s in storage.seats.list(campaign.id)] == [owner.id]


def test_one_host_at_a_time(storage, campaign, host, ana, bo):
    with pytest.raises(NotAllowed) as refused:
        seats.set_role(storage, campaign.id, bo.id, "cohost", by=ana)
    assert refused.value.message == "Only the host can do that."

    cohost = seats.set_role(storage, campaign.id, ana.id, "cohost", by=host)
    assert cohost.role == "cohost"
    assert seats.set_role(storage, campaign.id, bo.id, "observer", by=cohost).role == "observer"

    with pytest.raises(SeatConflict):
        seats.set_role(storage, campaign.id, host.id, "player", by=host)  # the table would have no host
    assert storage.seats.get(host.id).role == "host"

    handed = seats.set_role(storage, campaign.id, ana.id, "host", by=host)
    assert handed.role == "host"
    assert storage.seats.get(host.id).role == "cohost", "the old host becomes a co-host"
    assert [s.role for s in storage.seats.list(campaign.id)].count("host") == 1

    with pytest.raises(PlayError):
        seats.set_role(storage, campaign.id, bo.id, "dm", by=handed)
    with pytest.raises(NotFound):
        seats.set_role(storage, campaign.id, "seat_000000000000", "player", by=handed)


def test_an_observer_plays_nothing(storage, campaign, host, ana):
    mira = storage.characters.create(campaign.id, "Mira")
    seats.claim(storage, mira.id, ana)
    seats.set_role(storage, campaign.id, ana.id, "observer", by=host)
    assert seats.controls(storage, ana.id) == set()
    with pytest.raises(NotAllowed) as refused:
        seats.claim(storage, mira.id, storage.seats.get(ana.id))
    assert refused.value.message == "Observers don't act."
    with pytest.raises(PlayError):
        seats.claim(storage, mira.id, host, for_seat=ana.id)


def test_claim_give_and_release(storage, campaign, host, ana, bo):
    mira = storage.characters.create(campaign.id, "Mira")
    anselm = storage.characters.create(campaign.id, "Anselm")
    grik = storage.characters.create(campaign.id, "Grik", kind="npc")

    assert seats.claim(storage, mira.id, ana).controller_id == ana.id
    with pytest.raises(SeatConflict) as taken:
        seats.claim(storage, mira.id, bo)
    assert taken.value.message == "Another player plays Mira."
    assert seats.claim(storage, mira.id, ana).controller_id == ana.id, "claiming your own is fine"
    with pytest.raises(PlayError):
        seats.claim(storage, grik.id, bo)  # an NPC is the DM's
    with pytest.raises(NotFound):
        seats.claim(storage, "chr_000000000000", bo)

    with pytest.raises(NotAllowed):
        seats.claim(storage, anselm.id, ana, for_seat=bo.id)  # only the host gives
    assert seats.claim(storage, mira.id, host, for_seat=bo.id).controller_id == bo.id, "the host gives any character"
    assert seats.claim(storage, anselm.id, host, for_seat=host.id).controller_id == host.id, "itself included"
    assert seats.controls(storage, bo.id) == {mira.id} and seats.controls(storage, ana.id) == set()

    with pytest.raises(NotAllowed):
        seats.release(storage, mira.id, ana)  # neither its player nor the host
    assert seats.release(storage, mira.id, bo).controller_id is None
    seats.claim(storage, mira.id, ana)
    assert seats.release(storage, mira.id, host).controller_id is None, "the host releases any character"


def test_a_fallen_pc_is_not_claimed(storage, campaign, host, ana):
    """DEL-190: a dead PC, by its hit points' `dead` condition or because it left the party as `died`, isn't claimed;
    the host may still give it."""
    from dataclasses import replace

    griff = storage.characters.create(campaign.id, "Griff")
    griff = storage.characters.save(replace(griff, state=replace(griff.state, hp=-10, conditions=["downed", "dead"])))
    elmorth = storage.characters.create(campaign.id, "Elmorth")
    storage.characters.set_departure(elmorth.id, "died")
    for dead in (griff, elmorth):
        with pytest.raises(PlayError) as refused:
            seats.claim(storage, dead.id, ana)
        assert refused.value.message == f"{dead.name} has fallen."
    assert seats.fallen(storage.characters.get(elmorth.id))
    assert seats.claim(storage, griff.id, host, for_seat=ana.id).controller_id == ana.id, "the host still gives it"
    assert seats.claim(storage, griff.id, ana).controller_id == ana.id, "claiming your own is fine"


def test_a_seat_of_another_table(storage, campaign, host):
    module = storage.modules.get(campaign.module_id)
    elsewhere = storage.campaigns.create("Friday", module.id, campaign.revision, ruleset="osric", setting="greyhawk")
    stranger = storage.seats.create(elsewhere.id, "Stranger", "en", "player")
    mira = storage.characters.create(campaign.id, "Mira")
    with pytest.raises(NotFound):
        seats.claim(storage, mira.id, stranger)
    with pytest.raises(NotFound):
        seats.claim(storage, mira.id, host, for_seat=stranger.id)
    with pytest.raises(NotFound):
        seats.set_role(storage, campaign.id, stranger.id, "player", by=host)


def test_leaving_frees_characters(storage, campaign, host, ana):
    mira = storage.characters.create(campaign.id, "Mira")
    seats.claim(storage, mira.id, ana)
    left = seats.leave(storage, ana)
    assert left.left_at and seats.controls(storage, ana.id) == set()
    assert storage.characters.get(mira.id).controller_id is None
    with pytest.raises(PlayError):
        seats.claim(storage, mira.id, left)  # a seat that left plays nothing
    with pytest.raises(PlayError):
        seats.claim(storage, mira.id, host, for_seat=left.id)
    with pytest.raises(PlayError):
        seats.set_role(storage, campaign.id, left.id, "host", by=host)


def test_the_host_hands_over_before_leaving(storage, campaign, host, ana):
    with pytest.raises(SeatConflict) as refused:
        seats.leave(storage, host)
    assert refused.value.message == "Hand the host role to another seat before you leave."
    seats.set_role(storage, campaign.id, ana.id, "host", by=host)
    assert seats.leave(storage, storage.seats.get(host.id)).left_at


def test_the_owner_comes_back_to_their_seat(storage, campaign, host, ana):
    """The owner can never be locked out of a table on their own install: their seat is theirs again."""
    seats.set_role(storage, campaign.id, ana.id, "host", by=host)
    seats.leave(storage, storage.seats.get(host.id))
    back = seats.owner_seat(storage, campaign.id)
    assert back.id == host.id and back.left_at is None and back.role == "cohost"


def test_two_first_requests_at_once_share_one_owner_seat(storage, campaign, monkeypatch):
    """A campaign made outside the API has no owner seat; two requests that both look before either makes it (the
    play screen asks several routes at once) get the same seat, never an error."""
    made = seats.create_owner_seat(storage, campaign.id)
    looked = []
    real = storage.seats.owner_seat

    def not_yet_the_first_time(campaign_id):
        looked.append(campaign_id)
        return None if len(looked) == 1 else real(campaign_id)

    monkeypatch.setattr(storage.seats, "owner_seat", not_yet_the_first_time)
    assert seats.owner_seat(storage, campaign.id).id == made.id


def test_nobody_but_the_owner_takes_the_owners_seat_down(storage, campaign, host, ana):
    """The host the owner handed over to can't make the owner a player or an observer (403); the owner can."""
    seats.set_role(storage, campaign.id, ana.id, "host", by=host)
    for role in ("player", "observer"):
        with pytest.raises(NotAllowed) as refused:
            seats.set_role(storage, campaign.id, host.id, role, by=storage.seats.get(ana.id))
        assert refused.value.message == "Only the owner can change the owner's seat to that role."
    assert storage.seats.get(host.id).role == "cohost"
    assert seats.set_role(storage, campaign.id, host.id, "observer", by=host).role == "observer"


def test_the_owner_always_takes_the_host_role_back(storage, campaign, host, ana):
    """Even as an observer, without table rights: the host they handed over to becomes a co-host."""
    seats.set_role(storage, campaign.id, ana.id, "host", by=host)
    seats.set_role(storage, campaign.id, host.id, "observer", by=storage.seats.get(host.id))
    with pytest.raises(NotAllowed):
        seats.set_role(storage, campaign.id, ana.id, "player", by=storage.seats.get(host.id))
    back = seats.set_role(storage, campaign.id, host.id, "host", by=storage.seats.get(host.id))
    assert back.role == "host"
    assert storage.seats.get(ana.id).role == "cohost"


def test_only_the_host_or_the_owner_hands_the_host_role_over(storage, campaign, host, ana, bo):
    """A co-host has table rights but can't make itself (or anyone) the host, which would demote the owner's seat
    quietly and give it what only the host sees (DEL-149, audit finding 1)."""
    cohost = seats.set_role(storage, campaign.id, ana.id, "cohost", by=host)
    for seat_id in (ana.id, bo.id):
        with pytest.raises(NotAllowed) as refused:
            seats.set_role(storage, campaign.id, seat_id, "host", by=cohost)
        assert refused.value.message == "Only the host can hand the host role over."
    assert storage.seats.get(host.id).role == "host"
    assert storage.seats.get(ana.id).role == "cohost"

    # The host does; the owner, now a co-host, still may, to anyone.
    seats.set_role(storage, campaign.id, bo.id, "host", by=host)
    assert seats.set_role(storage, campaign.id, ana.id, "host", by=storage.seats.get(host.id)).role == "host"
    assert storage.seats.get(bo.id).role == "cohost"


def test_a_full_table_makes_no_observer_a_player(storage, campaign, host, ana):
    """DEL-204: an observer made a player or a co-host would take a place; at a full table that is refused. A player
    made a co-host keeps the place it has, and an observer stays one."""
    storage.campaigns.set_listing(campaign.id, "public", "", 1)
    watcher = storage.seats.create(campaign.id, "Cy", "en", "observer")
    for role in ("player", "cohost"):
        with pytest.raises(seats.TableFull):
            seats.set_role(storage, campaign.id, watcher.id, role, by=host)
    assert storage.seats.get(watcher.id).role == "observer"
    assert seats.set_role(storage, campaign.id, ana.id, "cohost", by=host).role == "cohost"
    storage.campaigns.set_listing(campaign.id, "public", "", 2)
    assert seats.set_role(storage, campaign.id, watcher.id, "player", by=host).role == "player", "room again"
