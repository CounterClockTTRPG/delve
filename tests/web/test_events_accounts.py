"""An account's event stream (players and tavern Task C3, Review Focus 1): it listens at one table, the one its
`?campaign=` names and it has a seat at, and hears nothing more once its login ends or its account is disabled."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from delve.domain.board import Zone
from delve.play import logins
from delve.web import events
from delve.web.auth import OWNER, account_principal, seat_principal
from delve.web.events import Event, EventBus, StoredTables, Viewer, viewer_of
from tests.web.conftest import SESSION_COOKIE, make_account, session_for
from tests.web.test_events import read_frames
from tests.web.test_seats_identity import make_campaign


@pytest.fixture
def campaign(storage):
    return make_campaign(storage)


@pytest.fixture
def other(storage):
    return make_campaign(storage, "Friday")


def _viewer(storage, token, campaign_id):
    account, login = logins.resolve(storage, token, datetime.now(UTC))
    return viewer_of(storage, account_principal(account, login, logins.token_hash(token)), campaign_id)


def test_account_stream_sees_only_its_own_table(app, storage, campaign, other, monkeypatch):
    ana = make_account(storage)
    seat = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    token = session_for(storage, ana)
    bus = app.state.events
    of_b = bus.publish("beat", {"at": "B"}, scope="table", campaign_id=other.id)
    of_a = bus.publish("beat", {"at": "A"}, scope="table", campaign_id=campaign.id)
    bus.publish("modules", {})

    at_a = _viewer(storage, token, campaign.id)
    assert at_a.seat == seat
    assert bus.may_see(at_a, Event(of_a, "beat", {}, "table", campaign.id))
    assert not bus.may_see(at_a, Event(of_b, "beat", {}, "table", other.id))
    assert not bus.may_see(at_a, Event(9, "modules", {})), "a player account isn't an organiser"
    nowhere = _viewer(storage, token, None)
    assert not bus.may_see(nowhere, Event(of_a, "beat", {}, "table", campaign.id))
    assert not bus.may_see(_viewer(storage, token, other.id), Event(of_b, "beat", {}, "table", other.id))

    # Through the stream itself: replayed from the start, only A's event arrives.
    cookie = {"Cookie": f"{SESSION_COOKIE}={token}"}
    frames = asyncio.run(read_frames(app, f"/api/events?since=0&campaign={campaign.id}", 1, headers=cookie))
    assert frames[0].startswith(f"id: {of_a}\nevent: beat\n")
    monkeypatch.setattr(events, "PING_SECONDS", 0.05)
    assert asyncio.run(read_frames(app, "/api/events?since=0", 1, headers=cookie)) == [": ping\n\n"]
    assert asyncio.run(read_frames(app, f"/api/events?since=0&campaign={other.id}", 1, headers=cookie)) == [
        ": ping\n\n"
    ]


def test_an_organiser_account_hears_organisers_but_no_other_table(storage, app, campaign, other):
    otto = make_account(storage, "otto", organiser=True)
    storage.seats.create(campaign.id, "Otto", "en", "player", account_id=otto.id)
    token = session_for(storage, otto)
    bus = app.state.events
    assert bus.may_see(_viewer(storage, token, campaign.id), Event(1, "modules", {}))
    assert bus.may_see(_viewer(storage, token, None), Event(1, "modules", {}))
    assert not bus.may_see(_viewer(storage, token, None), Event(2, "beat", {}, "table", other.id))
    assert not bus.may_see(_viewer(storage, token, campaign.id), Event(2, "beat", {}, "table", other.id))
    storage.accounts.set_organiser(otto.id, False)
    assert not bus.may_see(_viewer(storage, token, None), Event(3, "modules", {})), "the account's right as it is now"


def test_an_owner_account_is_seated_at_every_table(storage, app, campaign, other):
    olga = make_account(storage, "olga", owner=True)
    token = session_for(storage, olga)
    bus = app.state.events
    viewer = _viewer(storage, token, None)
    assert viewer.seat is None
    assert bus.may_see(viewer, Event(1, "beat", {}, "table", other.id))
    assert bus.may_see(viewer, Event(2, "modules", {}))
    logins.end(storage, token)
    assert not bus.may_see(viewer, Event(3, "modules", {})), "nothing once its login ended"


def test_ended_login_stream_gets_no_more_events(storage, app, campaign):
    ana = make_account(storage)
    storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    token = session_for(storage, ana)
    viewer = _viewer(storage, token, campaign.id)
    bus = app.state.events

    async def run():
        stream = bus.subscribe(None, viewer)
        first = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        while first.done():  # the seat's own arrival at the table
            first = asyncio.ensure_future(anext(stream))
            await asyncio.sleep(0)
        bus.publish("beat", {"n": 1}, scope="table", campaign_id=campaign.id)
        assert (await asyncio.wait_for(first, 1)).data == {"n": 1}
        storage.login_sessions.end_all(ana.id)
        second = asyncio.ensure_future(anext(stream))
        bus.publish("beat", {"n": 2}, scope="table", campaign_id=campaign.id)
        await asyncio.sleep(0.05)
        assert not second.done(), "the next event of A doesn't arrive"
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        await stream.aclose()

    asyncio.run(run())


def test_a_disabled_account_hears_nothing(storage, app, campaign):
    ana = make_account(storage)
    storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    token = session_for(storage, ana)
    viewer = _viewer(storage, token, campaign.id)
    storage.accounts.set_disabled(ana.id, "2026-10-24T12:00:00+00:00")
    assert not app.state.events.may_see(viewer, Event(1, "beat", {}, "table", campaign.id))


def test_account_presence_is_its_seat(storage, app, campaign):
    ana = make_account(storage)
    seat = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    viewer = _viewer(storage, session_for(storage, ana), campaign.id)
    nowhere = _viewer(storage, session_for(storage, ana), None)
    bus = app.state.events

    async def run():
        stream = bus.subscribe(None, viewer)
        waiting = asyncio.ensure_future(anext(stream))
        idle = bus.subscribe(None, nowhere)
        idle_waiting = asyncio.ensure_future(anext(idle))
        await asyncio.sleep(0)
        assert seat.id in bus.present(campaign.id)
        assert bus.present(campaign.id) == {seat.id}, "listening at no table is no presence, and not the owner's"
        for task in (waiting, idle_waiting):
            task.cancel()
        await asyncio.gather(waiting, idle_waiting, return_exceptions=True)
        await stream.aclose()
        await idle.aclose()

    asyncio.run(run())


# ----- the board's events (DEL-297): only to who may read the zone -----


@pytest.fixture
def bus(storage):
    return EventBus(StoredTables(storage))


def test_a_board_event_goes_only_to_who_may_read_the_zone(bus, storage, campaign):
    ana = make_account(storage)
    bo = make_account(storage, "bob")
    otto = make_account(storage, "otto", organiser=True)
    olga = make_account(storage, "olga", owner=True)
    cy = make_account(storage, "cyd")
    seat = storage.seats.create(campaign.id, "Cy", "en", "player", account_id=cy.id)
    members = storage.board.create_zone(Zone("", "Members", read="members", write="members", members=(ana.id,)))
    table = storage.board.create_zone(Zone("", "Tuesday", read="table", write="table", campaign_id=campaign.id))
    open_zone = storage.board.create_zone(Zone("", "Lobby", read="everybody", write="accounts"))
    viewers = {
        name: _viewer(storage, session_for(storage, account), None)
        for name, account in (("ana", ana), ("bo", bo), ("otto", otto), ("olga", olga), ("cy", cy))
    }
    viewers["owner"] = Viewer.of(OWNER)
    viewers["seat"] = Viewer.of(seat_principal(seat))  # a seat token without its account is a visitor

    def hears(zone_id):
        event = Event(1, "board", {"zone_id": zone_id}, "board", zone_id=zone_id)
        return {name for name, viewer in viewers.items() if bus.may_see(viewer, event)}

    assert hears(members.id) == {"ana", "otto", "olga", "owner"}
    assert hears(table.id) == {"cy", "otto", "olga", "owner"}
    assert hears(open_zone.id) == set(viewers)
    storage.board.delete_zone(members.id)
    assert hears(members.id) == {"otto", "olga", "owner"}, "a deleted zone's event goes to organisers only"

    storage.accounts.set_disabled(ana.id, "2026-10-29T12:00:00+00:00")
    storage.login_sessions.end_all(bo.id)
    assert hears(open_zone.id) == {"cy", "otto", "olga", "owner", "seat"}, "no disabled account, no dead login"
    assert not EventBus().may_see(viewers["owner"], Event(2, "board", {}, "board", zone_id=open_zone.id)), (
        "without tables, nobody hears the board"
    )


def test_a_board_event_is_replayed_only_to_who_may_read_the_zone(bus, storage):
    ana = make_account(storage)
    bo = make_account(storage, "bob")
    zone = storage.board.create_zone(Zone("", "Members", read="members", write="members", members=(ana.id,)))
    bus.publish("board", {"n": 1}, scope="board", zone_id=zone.id)
    bus.publish("board", {"n": 2}, scope="board", zone_id="zone_gone")

    async def replay(account):
        stream = bus.subscribe(0, _viewer(storage, session_for(storage, account), None))
        first = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        got = [first.result().data] if first.done() else []
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        await stream.aclose()
        return got

    assert asyncio.run(replay(ana)) == [{"n": 1}]
    assert asyncio.run(replay(bo)) == []


def test_a_member_taken_out_hears_nothing_more(bus, storage):
    ana = make_account(storage)
    zone = storage.board.create_zone(Zone("", "Members", read="members", write="members", members=(ana.id,)))
    viewer = _viewer(storage, session_for(storage, ana), None)

    async def run():
        stream = bus.subscribe(None, viewer)
        first = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        bus.publish("board", {"n": 1}, scope="board", zone_id=zone.id)
        assert (await asyncio.wait_for(first, 1)).data == {"n": 1}
        storage.board.save_zone(replace(storage.board.get_zone(zone.id), members=()))
        second = asyncio.ensure_future(anext(stream))
        bus.publish("board", {"n": 2}, scope="board", zone_id=zone.id)
        await asyncio.sleep(0.05)
        assert not second.done(), "the next event of the zone doesn't arrive"
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        await stream.aclose()

    asyncio.run(run())


def test_a_replay_asks_once_per_zone(storage):
    class Counting(StoredTables):
        asked = 0

        def may_read_zone(self, principal, zone_id):
            Counting.asked += 1
            return super().may_read_zone(principal, zone_id)

    ana = make_account(storage)
    zone = storage.board.create_zone(Zone("", "Lobby", read="accounts", write="accounts"))
    bus = EventBus(Counting(storage))
    for n in range(10):
        bus.publish("board", {"n": n}, scope="board", zone_id=zone.id)
    Counting.asked = 0

    async def run():
        stream = bus.subscribe(0, _viewer(storage, session_for(storage, ana), None))
        got = [await anext(stream) for _ in range(10)]
        await stream.aclose()
        return got

    assert len(asyncio.run(run())) == 10
    assert Counting.asked == 1
