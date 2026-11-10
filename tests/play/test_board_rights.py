"""Board rights (DEL-297): who may read, write, moderate and manage a zone, and who wears which badge."""

from dataclasses import replace

import pytest

from delve.domain.accounts import Profile
from delve.domain.board import Zone
from delve.play.board_rights import VISITOR, Caller, Rights, badges, caller_of, rights, valid_levels

NOTHING = Rights(read=False, write=False, moderate=False, manage=False, manage_wide=False)


def _account(storage, name, **flags):
    return storage.accounts.create(name, Profile(name.title()), **flags)


@pytest.fixture
def ana(storage):
    return _account(storage, "ana")


@pytest.fixture
def bo(storage):
    return _account(storage, "bo")


@pytest.fixture
def organiser(storage):
    return _account(storage, "olga", organiser=True)


@pytest.fixture
def table(storage, campaign):
    """The campaign's table: accounts seated as host, cohost, player and observer, and `gone`, a player who left."""
    seated = {}
    for role in ("host", "cohost", "player", "observer", "gone"):
        account = _account(storage, f"the{role}")
        seat = storage.seats.create(campaign.id, role, "en", "player" if role == "gone" else role, account_id=account.id)
        if role == "gone":
            storage.seats.save(replace(seat, left_at="2026-10-24T20:00:00+00:00"))
        seated[role] = account
    return seated


def _zone(campaign_id=None, **fields):
    fields.setdefault("read", "everybody")
    fields.setdefault("write", "accounts")
    return Zone("bzn_1", "Engine", campaign_id=campaign_id, **fields)


def _can(r):
    return (r.read, r.write, r.moderate, r.manage, r.manage_wide)


def test_a_visitor_reads_an_everybody_zone_and_writes_nowhere(storage):
    zone = _zone()
    assert rights(storage, VISITOR, zone) == Rights(read=True, write=False, moderate=False, manage=False, manage_wide=False)
    assert rights(storage, VISITOR, _zone(read="accounts")) == NOTHING


def test_an_account_writes_an_accounts_zone_but_moderates_nothing(storage, ana):
    r = rights(storage, Caller(ana), _zone(read="accounts"))
    assert _can(r) == (True, True, False, False, False)


def test_a_members_zone_is_its_members_and_moderators_only(storage, ana, bo):
    zone = _zone(read="members", write="members", members=(ana.id,))
    assert _can(rights(storage, Caller(ana), zone)) == (True, True, False, False, False)
    assert rights(storage, Caller(bo), zone) == NOTHING
    keeper = _zone(read="members", write="members", moderators=(bo.id,))
    assert _can(rights(storage, Caller(bo), keeper)) == (True, True, True, False, False)


def test_a_table_zone_reads_for_observers_and_writes_for_players_and_hosts(storage, campaign, table):
    zone = _zone(campaign.id, read="table", write="table")
    assert _can(rights(storage, Caller(table["observer"]), zone)) == (True, False, False, False, False)
    assert _can(rights(storage, Caller(table["player"]), zone)) == (True, True, False, False, False)


def test_a_player_who_left_the_table_reads_nothing_there(storage, campaign, table):
    assert rights(storage, Caller(table["gone"]), _zone(campaign.id, read="table", write="table")) == NOTHING


def test_an_outsider_does_not_get_into_a_table_zone(storage, campaign, table, ana):
    assert rights(storage, Caller(ana), _zone(campaign.id, read="table", write="table")) == NOTHING


def test_a_disabled_account_is_a_visitor(storage, ana):
    disabled = storage.accounts.set_disabled(ana.id, "2026-10-24T20:00:00+00:00")
    assert caller_of(disabled, False, False) == VISITOR
    assert caller_of(ana, True, False) == Caller(ana, True, False)
    assert rights(storage, Caller(disabled), _zone(read="accounts")) == NOTHING
    assert _can(rights(storage, Caller(disabled), _zone())) == (True, False, False, False, False)


def test_an_organiser_does_everything_everywhere(storage, campaign, organiser):
    for zone in (_zone(read="members", write="members"), _zone(campaign.id, read="table", write="table")):
        assert _can(rights(storage, Caller(organiser, organiser=True), zone)) == (True, True, True, True, True)


def test_the_owner_by_token_alone_does_everything(storage):
    zone = _zone(read="members", write="members")
    assert _can(rights(storage, Caller(owner=True), zone)) == (True, True, True, True, True)


def test_the_host_manages_their_campaigns_zone_but_not_wide(storage, campaign, table):
    zone = _zone(campaign.id, read="table", write="table")
    assert _can(rights(storage, Caller(table["host"]), zone)) == (True, True, True, True, False)
    assert _can(rights(storage, Caller(table["host"]), _zone())) == (True, True, False, False, False)


def test_a_cohost_moderates_but_does_not_manage(storage, campaign, table):
    zone = _zone(campaign.id, read="table", write="table")
    assert _can(rights(storage, Caller(table["cohost"]), zone)) == (True, True, True, False, False)


@pytest.mark.parametrize(
    ("read", "write", "campaign", "ok"),
    [
        ("everybody", "accounts", None, True),
        ("everybody", "everybody", None, False),
        ("accounts", "members", None, True),
        ("members", "accounts", None, False),
        ("members", "table", "cmp_1", False),
        ("table", "table", None, False),
        ("table", "table", "cmp_1", True),
        ("accounts", "table", "cmp_1", True),
    ],
)
def test_valid_levels(read, write, campaign, ok):
    assert (valid_levels(read, write, campaign) is None) == ok


def test_badges_name_what_an_author_is_in_the_zone(storage, campaign, table, organiser, ana):
    zone = _zone(campaign.id, moderators=(table["host"].id, ana.id))
    assert badges(storage, zone, organiser.id) == ["organiser"]
    assert badges(storage, zone, table["host"].id) == ["moderator", "host"]
    assert badges(storage, zone, table["cohost"].id) == ["cohost"]
    assert badges(storage, zone, ana.id) == ["moderator"]
    assert badges(storage, zone, table["gone"].id) == []
    assert badges(storage, zone, None) == []
