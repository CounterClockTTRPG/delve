"""The board's rules (DEL-297): zones, topics, posts, moderators and members, each decided by the zone's rights."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from delve.domain.accounts import Profile
from delve.domain.board import Zone
from delve.play.board import (
    BoardConflict,
    BoardRefused,
    NeedsAccount,
    add_member,
    attach_picture,
    author_of,
    create_zone,
    delete_post,
    delete_topic,
    delete_zone,
    edit_post,
    is_new,
    may_attach,
    readable_post,
    readable_topic,
    readable_zone,
    remove_member,
    reorder_zones,
    reply,
    set_moderators,
    set_topic,
    start_topic,
    take_down_picture,
    untie_campaign,
    update_zone,
    visit,
)
from delve.play.board_rights import VISITOR, Caller
from delve.play.context import NotFound, PlayError
from delve.play.talk_pictures import TalkPicture

NOW = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
ORGANISER = Caller(organiser=True, owner=True)


def make_account(storage, name, **flags):
    return storage.accounts.create(name, Profile(name.title()), **flags)


@pytest.fixture
def ana(storage):
    return make_account(storage, "ana")


@pytest.fixture
def bo(storage):
    return make_account(storage, "bob")


@pytest.fixture
def moderator(storage):
    return make_account(storage, "mia")


@pytest.fixture
def host(storage, campaign):
    account = make_account(storage, "hal")
    storage.seats.create(campaign.id, "host", "en", "host", account_id=account.id)
    return account


@pytest.fixture
def engine_zone(storage, moderator):
    return storage.board.create_zone(
        Zone("", "Engine", read="everybody", write="accounts", moderators=(moderator.id,), created_at=NOW.isoformat())
    )


@pytest.fixture
def members_zone(storage, moderator, ana):
    zone = Zone(
        "",
        "Back room",
        read="members",
        write="members",
        moderators=(moderator.id,),
        members=(ana.id,),
        created_at=NOW.isoformat(),
    )
    return storage.board.create_zone(zone)


@pytest.fixture
def table_zone(storage, campaign):
    zone = Zone("", "Tuesday", read="table", write="table", campaign_id=campaign.id, created_at=NOW.isoformat())
    return storage.board.create_zone(zone)


@pytest.fixture
def topic(storage, ana, engine_zone):
    return start_topic(storage, Caller(ana), engine_zone.id, "Saving throws", "How do they work?", NOW)[0]


@pytest.fixture
def anas_post(storage, ana, topic):
    return reply(storage, Caller(ana), topic.id, "And one more thing.", NOW)


@pytest.fixture
def picture():
    return TalkPicture(b"RIFF....WEBP", 40, 30)


def test_anyone_who_may_write_starts_a_topic(storage, ana, engine_zone):
    topic, first = start_topic(storage, Caller(ana), engine_zone.id, "  Saving throws ", " How? \n", NOW)
    assert (topic.title, topic.author_id, topic.zone_id, topic.posts) == ("Saving throws", ana.id, engine_zone.id, 1)
    assert (first.text, first.author_id, first.topic_id) == ("How?", ana.id, topic.id)
    assert storage.board.topics(engine_zone.id) == [topic]


def test_a_visitor_may_not_start_one(storage, engine_zone):
    with pytest.raises(NeedsAccount):
        start_topic(storage, VISITOR, engine_zone.id, "Hi", "Hello", NOW)


def test_a_visitor_reads_an_open_zone(storage, topic, anas_post):
    _, found = readable_topic(storage, VISITOR, topic.id)
    assert found.id == topic.id
    assert readable_post(storage, VISITOR, anas_post.id)[2] == anas_post


def test_a_zone_one_may_not_read_is_not_found(storage, bo, members_zone):
    with pytest.raises(NotFound):
        start_topic(storage, Caller(bo), members_zone.id, "Hi", "Hello", NOW)
    with pytest.raises(NotFound):
        readable_zone(storage, Caller(bo), members_zone.id)
    with pytest.raises(NotFound):
        readable_zone(storage, Caller(bo), "bzn_nothing")


def test_a_topic_and_a_post_in_a_zone_one_may_not_read_are_not_found(storage, ana, bo, members_zone):
    topic, first = start_topic(storage, Caller(ana), members_zone.id, "Secret", "Shh", NOW)
    with pytest.raises(NotFound):
        readable_topic(storage, Caller(bo), topic.id)
    with pytest.raises(NotFound):
        readable_post(storage, Caller(bo), first.id)
    with pytest.raises(NotFound):
        reply(storage, Caller(bo), topic.id, "Let me in", NOW)


def test_a_reader_who_may_not_write_is_refused(storage, ana, bo, members_zone):
    zone = storage.board.save_zone(replace(members_zone, read="accounts"))
    assert readable_zone(storage, Caller(bo), zone.id) == zone
    with pytest.raises(BoardRefused):
        start_topic(storage, Caller(bo), zone.id, "Hi", "Hello", NOW)


def test_titles_and_posts_are_stripped_and_bounded(storage, ana, engine_zone):
    for title, text in (("   ", "x"), ("x", " \n "), ("x" * 121, "y"), ("x", "y" * 20_001)):
        with pytest.raises(PlayError):
            start_topic(storage, Caller(ana), engine_zone.id, title, text, NOW)
    topic, first = start_topic(storage, Caller(ana), engine_zone.id, "x" * 120, "y" * 20_000, NOW)
    assert (len(topic.title), len(first.text)) == (120, 20_000)


def test_a_reply_follows_on_the_topic(storage, ana, bo, topic):
    post = reply(storage, Caller(bo), topic.id, "  Roll a d20. ", LATER)
    assert (post.text, post.author_id, post.created_at) == ("Roll a d20.", bo.id, LATER.isoformat())
    stored = storage.board.get_topic(topic.id)
    assert (stored.posts, stored.last_author_id, stored.last_post_at) == (2, bo.id, LATER.isoformat())


def test_a_locked_topic_takes_no_reply_but_a_moderators(storage, ana, moderator, topic):
    set_topic(storage, Caller(moderator), topic.id, locked=True)
    with pytest.raises(BoardConflict):
        reply(storage, Caller(ana), topic.id, "late", NOW)
    assert reply(storage, Caller(moderator), topic.id, "closing note", NOW).text == "closing note"


def test_only_who_moderates_pins_locks_and_deletes_topics(storage, ana, moderator, topic):
    with pytest.raises(BoardRefused):
        set_topic(storage, Caller(ana), topic.id, pinned=True)
    with pytest.raises(BoardRefused):
        delete_topic(storage, Caller(ana), topic.id)
    pinned = set_topic(storage, Caller(moderator), topic.id, pinned=True)
    assert (pinned.pinned, pinned.locked) == (True, False)
    delete_topic(storage, Caller(moderator), topic.id)
    assert storage.board.get_topic(topic.id) is None


def test_a_removed_post_cannot_be_edited(storage, ana, moderator, topic, anas_post):
    delete_post(storage, Caller(moderator), anas_post.id, NOW)
    with pytest.raises(BoardConflict):
        edit_post(storage, Caller(ana), anas_post.id, "again", NOW)


def test_deleting_keeps_the_place_and_says_by_whom(storage, ana, moderator, bo, topic, anas_post, picture):
    storage.board.save_zone(replace(storage.board.get_zone(topic.zone_id), pictures=True))
    attach_picture(storage, Caller(ana), anas_post.id, picture)
    own = delete_post(storage, Caller(ana), anas_post.id, NOW)
    assert (own.text, own.picture, own.removed) == ("", None, "author")
    assert storage.board.get_post(anas_post.id) == own
    other = reply(storage, Caller(ana), topic.id, "Another", NOW)
    with pytest.raises(BoardRefused):
        delete_post(storage, Caller(bo), other.id, NOW)
    taken = delete_post(storage, Caller(moderator), other.id, NOW)
    assert (taken.text, taken.removed) == ("", "moderator")


def test_editing_is_the_authors_and_marks_the_time(storage, ana, bo, anas_post):
    with pytest.raises(BoardRefused):
        edit_post(storage, Caller(bo), anas_post.id, "mine now", LATER)
    edited = edit_post(storage, Caller(ana), anas_post.id, "  Better words. ", LATER)
    assert (edited.text, edited.edited_at) == ("Better words.", LATER.isoformat())
    assert storage.board.get_post(anas_post.id) == edited
    with pytest.raises(PlayError):
        edit_post(storage, Caller(ana), anas_post.id, "  ", LATER)


def test_pictures_need_the_zones_option(storage, ana, bo, moderator, anas_post, picture):
    with pytest.raises(BoardRefused):
        attach_picture(storage, Caller(ana), anas_post.id, picture)
    zone, _, _ = readable_post(storage, Caller(ana), anas_post.id)
    update_zone(storage, ORGANISER, zone.id, {"pictures": True}, NOW)
    with pytest.raises(BoardRefused):
        attach_picture(storage, Caller(bo), anas_post.id, picture)
    post = attach_picture(storage, Caller(ana), anas_post.id, picture)
    assert {key: post.picture[key] for key in ("mime", "width", "height")} == {
        "mime": "image/webp",
        "width": 40,
        "height": 30,
    }
    assert storage.blobs.get(post.picture["blob"]) is not None
    with pytest.raises(BoardRefused):
        take_down_picture(storage, Caller(bo), anas_post.id)
    assert take_down_picture(storage, Caller(moderator), anas_post.id).picture is None
    assert storage.board.get_post(anas_post.id).picture is None


def test_the_owner_by_token_posts_as_the_owner_account_or_none(storage, engine_zone):
    owner = Caller(organiser=True, owner=True)
    assert start_topic(storage, owner, engine_zone.id, "Hi", "x", NOW)[1].author_id is None
    account = make_account(storage, "raf", owner=True)
    assert start_topic(storage, owner, engine_zone.id, "Hi", "x", NOW)[1].author_id == account.id
    assert author_of(storage, owner) == account.id


def test_the_owner_by_token_edits_their_own_posts(storage, engine_zone):
    owner = Caller(organiser=True, owner=True)
    _, first = start_topic(storage, owner, engine_zone.id, "Hi", "x", NOW)
    assert edit_post(storage, owner, first.id, "y", LATER).text == "y"


def test_organisers_create_any_zone(storage, campaign):
    zone = create_zone(storage, ORGANISER, {"name": " Rules ", "description": " Ask here ", "read": "everybody"}, NOW)
    assert (zone.name, zone.description, zone.read, zone.write, zone.pictures) == (
        "Rules",
        "Ask here",
        "everybody",
        "accounts",
        False,
    )
    assert storage.board.zones() == [zone]
    tied = create_zone(
        storage, ORGANISER, {"name": "Tuesday", "read": "table", "write": "table", "campaign_id": campaign.id}, NOW
    )
    assert tied.campaign_id == campaign.id


def test_a_zones_fields_are_checked(storage, campaign, table_zone):
    for fields in (
        {"name": " "},
        {"name": "x" * 81},
        {"name": "x", "description": "y" * 501},
        {"name": "x", "read": "anyone"},
        {"name": "x", "write": "nobody"},
        {"name": "x", "write": "everybody"},
        {"name": "x", "read": "members", "write": "accounts"},
        {"name": "x", "read": "table", "write": "table"},
        {"name": "x", "campaign_id": "cmp_nothing"},
        {"name": "x", "pictures": "yes"},
    ):
        with pytest.raises(PlayError) as refused:
            create_zone(storage, ORGANISER, fields, NOW)
        assert not isinstance(refused.value, (BoardRefused, BoardConflict))
    with pytest.raises(BoardConflict):
        create_zone(storage, ORGANISER, {"name": "Again", "campaign_id": campaign.id}, NOW)


def test_an_account_creates_and_changes_no_zone(storage, ana, engine_zone):
    with pytest.raises(BoardRefused):
        create_zone(storage, Caller(ana), {"name": "Mine"}, NOW)
    with pytest.raises(BoardRefused):
        update_zone(storage, Caller(ana), engine_zone.id, {"name": "Mine"}, NOW)
    with pytest.raises(NeedsAccount):
        create_zone(storage, VISITOR, {"name": "Mine"}, NOW)


def test_a_host_makes_their_tables_zone_but_cannot_open_it(storage, host, campaign, ana):
    zone = create_zone(
        storage, Caller(host), {"name": "Tuesday", "read": "table", "write": "table", "campaign_id": campaign.id}, NOW
    )
    assert (zone.campaign_id, zone.read) == (campaign.id, "table")
    with pytest.raises(BoardConflict):
        create_zone(
            storage,
            Caller(host),
            {"name": "Again", "read": "members", "write": "members", "campaign_id": campaign.id},
            NOW,
        )
    for fields in ({"read": "accounts", "write": "accounts"}, {"read": "everybody"}, {"campaign_id": None}):
        with pytest.raises(BoardRefused):
            update_zone(storage, Caller(host), zone.id, fields, NOW)
    opened = update_zone(storage, Caller(host), zone.id, {"read": "members", "write": "members", "pictures": True}, NOW)
    assert (opened.read, opened.write, opened.pictures) == ("members", "members", True)
    with pytest.raises(NotFound):
        update_zone(storage, Caller(ana), zone.id, {"name": "Taken"}, NOW)


def test_a_host_keeps_managing_a_zone_an_organiser_opened_wider(storage, host, campaign, table_zone):
    update_zone(storage, ORGANISER, table_zone.id, {"read": "accounts", "write": "accounts"}, NOW)
    saved = update_zone(
        storage,
        Caller(host),
        table_zone.id,
        {"name": "Tuesdays", "read": "accounts", "write": "accounts", "pictures": True},
        NOW,
    )
    assert (saved.name, saved.read, saved.write, saved.pictures) == ("Tuesdays", "accounts", "accounts", True)
    narrowed = update_zone(storage, Caller(host), table_zone.id, {"read": "accounts", "write": "members"}, NOW)
    assert (narrowed.read, narrowed.write) == ("accounts", "members")
    for fields in ({"read": "everybody"}, {"read": "accounts", "write": "accounts"}):
        with pytest.raises(BoardRefused):
            update_zone(storage, Caller(host), table_zone.id, fields, NOW)
    assert (storage.board.get_zone(table_zone.id).read, storage.board.get_zone(table_zone.id).write) == (
        "accounts",
        "members",
    )


def test_a_host_makes_no_zone_open_to_accounts(storage, host, campaign):
    with pytest.raises(BoardRefused):
        fields = {"name": "Open", "read": "accounts", "write": "accounts", "campaign_id": campaign.id}
        create_zone(storage, Caller(host), fields, NOW)


def test_may_attach_refuses_as_attach_does(storage, ana, bo, anas_post, picture):
    with pytest.raises(BoardRefused):
        may_attach(storage, Caller(ana), anas_post.id)
    zone, _, _ = readable_post(storage, Caller(ana), anas_post.id)
    update_zone(storage, ORGANISER, zone.id, {"pictures": True}, NOW)
    assert may_attach(storage, Caller(ana), anas_post.id).id == anas_post.id
    with pytest.raises(BoardRefused):
        may_attach(storage, Caller(bo), anas_post.id)
    with pytest.raises(NeedsAccount):
        may_attach(storage, VISITOR, anas_post.id)
    with pytest.raises(NotFound):
        may_attach(storage, Caller(ana), "bps_nothing")
    delete_post(storage, Caller(ana), anas_post.id, NOW)
    with pytest.raises(BoardConflict):
        may_attach(storage, Caller(ana), anas_post.id)


def test_a_hosts_zone_is_the_tables_unless_they_say(storage, host, campaign):
    zone = create_zone(storage, Caller(host), {"name": "Tuesday", "campaign_id": campaign.id}, NOW)
    assert (zone.read, zone.write) == ("table", "table")


def test_a_host_makes_no_zone_wider_than_the_table(storage, host, campaign):
    for fields in ({"name": "Open", "read": "everybody", "campaign_id": campaign.id}, {"name": "Untied"}):
        with pytest.raises(BoardRefused):
            create_zone(storage, Caller(host), fields, NOW)


def test_a_cohost_does_not_make_the_tables_zone(storage, campaign):
    cohost = make_account(storage, "cora")
    storage.seats.create(campaign.id, "cohost", "en", "cohost", account_id=cohost.id)
    with pytest.raises(BoardRefused):
        create_zone(
            storage, Caller(cohost), {"name": "T", "read": "table", "write": "table", "campaign_id": campaign.id}, NOW
        )


def test_organisers_update_move_and_untie_zones(storage, campaign, table_zone):
    moved = update_zone(
        storage,
        ORGANISER,
        table_zone.id,
        {"campaign_id": None, "read": "accounts", "write": "accounts", "name": " Open "},
        NOW,
    )
    assert (moved.campaign_id, moved.read, moved.name) == (None, "accounts", "Open")
    with pytest.raises(PlayError):
        update_zone(storage, ORGANISER, table_zone.id, {"read": "table", "write": "table"}, NOW)
    with pytest.raises(NotFound):
        update_zone(storage, ORGANISER, "bzn_nothing", {"name": "x"}, NOW)


def test_only_organisers_reorder_and_delete_zones(storage, host, campaign, engine_zone, table_zone):
    with pytest.raises(BoardRefused):
        reorder_zones(storage, Caller(host), [table_zone.id, engine_zone.id])
    with pytest.raises(BoardRefused):
        delete_zone(storage, Caller(host), table_zone.id)
    with pytest.raises(PlayError):
        reorder_zones(storage, ORGANISER, [table_zone.id])
    with pytest.raises(PlayError):
        reorder_zones(storage, ORGANISER, [table_zone.id, table_zone.id])
    assert [zone.id for zone in reorder_zones(storage, ORGANISER, [table_zone.id, engine_zone.id])] == [
        table_zone.id,
        engine_zone.id,
    ]
    delete_zone(storage, ORGANISER, table_zone.id)
    assert [zone.id for zone in storage.board.zones()] == [engine_zone.id]


def test_a_host_names_their_zones_moderators(storage, host, campaign, table_zone, ana, bo):
    zone = set_moderators(storage, Caller(host), table_zone.id, ["ana", "bob", "ana"])
    assert zone.moderators == (ana.id, bo.id)
    with pytest.raises(PlayError, match="No account has that username."):
        set_moderators(storage, Caller(host), table_zone.id, ["nobody"])


def test_a_moderator_names_no_moderators(storage, moderator, engine_zone, ana):
    with pytest.raises(BoardRefused):
        set_moderators(storage, Caller(moderator), engine_zone.id, ["ana"])


def test_moderators_add_members_by_username(storage, moderator, members_zone, ana, bo):
    with pytest.raises(PlayError, match="No account has that username."):
        add_member(storage, Caller(moderator), members_zone.id, "nobody")
    zone = add_member(storage, Caller(moderator), members_zone.id, "BOB")
    assert zone.members == (ana.id, bo.id)
    assert readable_zone(storage, Caller(bo), zone.id) == zone
    assert add_member(storage, Caller(moderator), members_zone.id, "bob").members == (ana.id, bo.id)
    with pytest.raises(BoardRefused):
        add_member(storage, Caller(bo), members_zone.id, "mia")
    zone = remove_member(storage, Caller(moderator), members_zone.id, bo.id)
    assert zone.members == (ana.id,)
    with pytest.raises(NotFound):
        readable_zone(storage, Caller(bo), zone.id)


def test_new_marks_start_at_the_first_visit(storage, ana, topic):
    assert not is_new(topic, {}, None)
    first = visit(storage, Caller(ana), LATER)
    assert first == LATER.isoformat()
    assert visit(storage, Caller(ana), LATER + timedelta(days=1)) == first
    assert not is_new(topic, {}, first)
    newer = reply(storage, Caller(ana), topic.id, "news", LATER + timedelta(minutes=1))
    topic = storage.board.get_topic(topic.id)
    assert is_new(topic, {}, first)
    assert not is_new(topic, {topic.id: newer.created_at}, first)
    assert is_new(topic, {topic.id: NOW.isoformat()}, first)
    assert visit(storage, VISITOR, NOW) is None


def test_untying_a_deleted_campaigns_zone_makes_it_members(storage, campaign, table_zone):
    untie_campaign(storage, campaign.id)
    zone = storage.board.get_zone(table_zone.id)
    assert (zone.campaign_id, zone.read, zone.write) == (None, "members", "members")
    untie_campaign(storage, campaign.id)
