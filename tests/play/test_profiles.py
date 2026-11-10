"""Profiles (players and tavern Task D1): the fields and their limits, and who may read them. A card is for the
account itself, organisers and those who share a table with it; the note for the host and the time zone are for the
hosts of its tables only."""

from dataclasses import replace

import pytest

from delve.domain.accounts import EMBLEMS, Account, Profile
from delve.play import profiles, seats
from delve.play.accounts import create_account
from delve.play.context import PlayError
from delve.play.profiles import card, summary, updated, viewer_of_account, viewer_of_owner, viewer_of_seat
from tests.play.conftest import crypt_campaign

PASSWORD = "correct horse battery"
PROFILE = Profile("Ana", avatar_emblem="lion")


def test_profile_validation():
    assert updated(PROFILE, {"display_name": "  " + "a" * 40 + " "}).display_name == "a" * 40
    for refused in ("", "   ", "a" * 41):
        with pytest.raises(PlayError, match="A display name has 1 to 40 characters."):
            updated(PROFILE, {"display_name": refused})
    assert updated(PROFILE, {"pronouns": "p" * 40}).pronouns == "p" * 40
    with pytest.raises(PlayError, match="at most 40"):
        updated(PROFILE, {"pronouns": "p" * 41})
    for key in ("about", "host_note"):
        assert getattr(updated(PROFILE, {key: "x" * 500}), key) == "x" * 500
        with pytest.raises(PlayError, match="at most 500"):
            updated(PROFILE, {key: "x" * 501})
    assert updated(PROFILE, {"about": " one\ntwo\x00\x07\tthree "}).about == "one\ntwothree"
    assert updated(PROFILE, {"colour": "ember"}).colour == "ember"
    with pytest.raises(PlayError, match="colour"):
        updated(PROFILE, {"colour": "pink"})
    assert updated(PROFILE, {"language": "nl"}).language == "nl"
    for refused in ("n", "dutch", "NL", "n1"):
        with pytest.raises(PlayError, match="language"):
            updated(PROFILE, {"language": refused})
    with pytest.raises(PlayError, match="emblem"):
        updated(PROFILE, {"avatar_emblem": "unicorn"})
    for key in ("display_name", "about", "colour", "time_zone"):
        with pytest.raises(PlayError):
            updated(PROFILE, {key: 7})


def test_emblem_clears_picture():
    pictured = replace(PROFILE, avatar_sha="ab" * 32)
    chosen = updated(pictured, {"avatar_emblem": "oak"})
    assert chosen.avatar_emblem == "oak" and chosen.avatar_sha is None
    assert updated(pictured, {"about": "hi"}).avatar_sha == "ab" * 32


def test_unknown_key_refused():
    for key in ("avatar_sha", "username", "organiser", "owner", "nickname"):
        with pytest.raises(PlayError, match=key):
            updated(PROFILE, {key: "x"})


def test_time_zone_known_or_null():
    zoned = updated(PROFILE, {"time_zone": "Europe/Brussels"})
    assert zoned.time_zone == "Europe/Brussels"
    assert updated(zoned, {"time_zone": None}).time_zone is None
    for refused in ("Mars/Olympus", "", "/etc/passwd", "../../etc/passwd"):
        with pytest.raises(PlayError, match="time zone"):
            updated(PROFILE, {"time_zone": refused})


@pytest.fixture
def tables(storage):
    """Ana and Cy at table A, Bo at table B, the owner hosting both."""
    a, b = crypt_campaign(storage), crypt_campaign(storage)
    for campaign in (a, b):
        seats.owner_seat(storage, campaign.id)
    ana, bo, cy = (create_account(storage, name, PASSWORD) for name in ("ana", "bo.b", "cyd"))
    ana = storage.accounts.save_profile(
        ana.id, replace(ana.profile, about="likes maps", host_note="leaves at ten", time_zone="Europe/Brussels")
    )
    seat_of = {
        "ana": storage.seats.create(a.id, "Ana", "en", "player", account_id=ana.id),
        "bo": storage.seats.create(b.id, "Bo", "en", "player", account_id=bo.id),
        "cy": storage.seats.create(a.id, "Cy", "en", "player", account_id=cy.id),
    }
    return {"a": a, "b": b, "ana": ana, "bo": bo, "cy": cy, "seats": seat_of}


SHARED = {"account_id", "display_name", "pronouns", "avatar", "colour", "about"}
HOSTS = {"host_note", "time_zone"}


def test_card_needs_a_shared_table(storage, tables):
    ana = tables["ana"]
    assert card(storage, ana.id, viewer_of_account(storage, tables["bo"])) is None
    seen = card(storage, ana.id, viewer_of_account(storage, tables["cy"]))
    assert set(seen) == SHARED and seen["about"] == "likes maps"
    assert card(storage, "acc_nobody", viewer_of_account(storage, tables["cy"])) is None
    # Once Cy leaves the table, they share none.
    storage.seats.save(replace(tables["seats"]["cy"], left_at="2026-10-24T20:00:00+00:00"))
    assert card(storage, ana.id, viewer_of_account(storage, tables["cy"])) is None
    # A token seat at A reads Ana's card; one at B doesn't.
    token_a = storage.seats.create(tables["a"].id, "Dee", "en", "player", token_hash="d" * 64)
    token_b = storage.seats.create(tables["b"].id, "Eve", "en", "observer", token_hash="e" * 64)
    assert set(card(storage, ana.id, viewer_of_seat(storage, token_a, organiser=False))) == SHARED
    assert card(storage, ana.id, viewer_of_seat(storage, token_b, organiser=False)) is None
    # An organiser reads every card, but no host's field unless hosting.
    assert set(card(storage, ana.id, viewer_of_seat(storage, token_b, organiser=True))) == SHARED


def test_a_public_tables_players_are_seen_by_any_account(storage, tables):
    """Find a table shows who sits at a public table (DEL-218): any logged-in account reads their card's shared
    fields, never the host's; not a seat token, not an observer's, and not once the table is private or complete."""
    ana, a = tables["ana"], tables["a"]
    bo = viewer_of_account(storage, tables["bo"])
    assert card(storage, ana.id, bo) is None, "table A is private"
    storage.campaigns.set_listing(a.id, "public", "", None)
    assert set(card(storage, ana.id, bo)) == SHARED
    token_b = storage.seats.create(tables["b"].id, "Eve", "en", "player", token_hash="e" * 64)
    assert card(storage, ana.id, viewer_of_seat(storage, token_b, organiser=False)) is None, "no account, no listing"
    storage.seats.save(replace(tables["seats"]["ana"], role="observer"))
    assert card(storage, ana.id, bo) is None, "an observer isn't shown at the table"
    storage.seats.save(replace(tables["seats"]["ana"], role="player"))
    storage.campaigns.set_status(a.id, "complete")
    assert card(storage, ana.id, bo) is None, "a complete table isn't listed"


def test_the_owners_card_is_read_at_the_owners_tables(storage, tables):
    """The owner's seats have no account but show the owner's: those at them, and at a public one anyone, read it."""
    boss = create_account(storage, "boss", PASSWORD, owner=True)
    assert set(card(storage, boss.id, viewer_of_account(storage, tables["cy"]))) == SHARED
    stranger = create_account(storage, "dee", PASSWORD)
    assert card(storage, boss.id, viewer_of_account(storage, stranger)) is None
    storage.campaigns.set_listing(tables["b"].id, "public", "", None)
    assert set(card(storage, boss.id, viewer_of_account(storage, stranger))) == SHARED


def test_people_at_the_table(storage, tables):
    """A table's card shows its host first, then its co-hosts and players, each with their profile; no observer."""
    a = tables["a"]
    storage.seats.create(a.id, "Watcher", "en", "observer")
    boss = create_account(storage, "boss", PASSWORD, owner=True)
    people = profiles.people(storage, a.id)
    assert [(p["name"], p["role"]) for p in people] == [("Host", "host"), ("Ana", "player"), ("Cy", "player")]
    assert people[0]["profile"]["account_id"] == boss.id, "the owner's seat shows the owner's account"
    assert people[1]["profile"]["display_name"] == "ana"


def test_host_sees_note_and_time_zone(storage, tables):
    ana, a = tables["ana"], tables["a"]
    owner_view = card(storage, ana.id, viewer_of_owner(storage))
    assert set(owner_view) == SHARED | HOSTS
    assert owner_view["host_note"] == "leaves at ten" and owner_view["time_zone"] == "Europe/Brussels"
    assert set(card(storage, ana.id, viewer_of_account(storage, tables["cy"]))) == SHARED
    # Cy becomes A's co-host: now they read the host's fields.
    cohost = storage.seats.save(replace(tables["seats"]["cy"], role="cohost"))
    assert set(card(storage, ana.id, viewer_of_account(storage, tables["cy"]))) == SHARED | HOSTS
    assert set(card(storage, ana.id, viewer_of_seat(storage, cohost, organiser=False))) == SHARED | HOSTS
    # An organiser account hosting only B reads Ana's card, not its host's fields.
    org = create_account(storage, "orga", PASSWORD, organiser=True)
    storage.seats.create(tables["b"].id, "Org", "en", "cohost", account_id=org.id)
    assert set(card(storage, ana.id, viewer_of_account(storage, org))) == SHARED
    # The owner, when another seat hosts A, isn't A's host any more.
    storage.seats.save(replace(seats.owner_seat(storage, a.id), role="player"))
    storage.seats.save(replace(cohost, role="host"))
    assert set(card(storage, ana.id, viewer_of_owner(storage))) == SHARED


def test_owner_account_is_the_owner(storage, tables):
    boss = create_account(storage, "boss", PASSWORD, owner=True)
    assert set(card(storage, tables["ana"].id, viewer_of_account(storage, boss))) == SHARED | HOSTS
    assert "language" in card(storage, boss.id, viewer_of_account(storage, boss))


def test_owner_account_sits_at_the_owners_seats(storage, tables):
    """The owner's seat, which has no account, shows the owner account's profile: whoever shares its table reads that
    card (and so its picture)."""
    boss = create_account(storage, "boss", PASSWORD, owner=True)
    assert set(card(storage, boss.id, viewer_of_account(storage, tables["cy"]))) == SHARED
    token_b = storage.seats.create(tables["b"].id, "Eve", "en", "observer", token_hash="e" * 64)
    assert set(card(storage, boss.id, viewer_of_seat(storage, token_b, organiser=False))) == SHARED
    # Once the owner's seat at B is left, B's seats share no table with the owner.
    storage.seats.save(replace(seats.owner_seat(storage, tables["b"].id), left_at="2026-10-24T20:00:00+00:00"))
    assert card(storage, boss.id, viewer_of_seat(storage, token_b, organiser=False)) is None
    # Another owner account, after the first, isn't the one the owner's seats show.
    other = create_account(storage, "boss2", PASSWORD, owner=True)
    assert card(storage, other.id, viewer_of_account(storage, tables["cy"])) is None


def test_own_card_has_everything(storage, tables):
    ana = tables["ana"]
    own = card(storage, ana.id, viewer_of_account(storage, ana))
    assert set(own) == SHARED | HOSTS | {"language", "avatar_emblem"}
    assert own["language"] == "en" and own["host_note"] == "leaves at ten"
    # Bo, with no table shared, still reads their own.
    assert card(storage, tables["bo"].id, viewer_of_account(storage, tables["bo"]))["display_name"] == "bo.b"


def test_summary_avatar():
    assert summary_of(PROFILE)["avatar"] == {"emblem": "lion"}
    sha = "0123456789abcdef" * 4
    assert summary_of(replace(PROFILE, avatar_sha=sha))["avatar"] == {"picture": sha[:12]}
    assert set(summary_of(PROFILE)) == {"account_id", "display_name", "pronouns", "avatar", "colour"}


def summary_of(profile: Profile) -> dict:
    return summary(Account("acc_1", "ana", profile))


def test_emblems_are_the_domains():
    assert profiles.EMBLEMS == EMBLEMS
