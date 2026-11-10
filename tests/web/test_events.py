import asyncio
import json
import socket
from dataclasses import replace

import httpx
import pytest
import uvicorn

from delve.domain.campaigns import Seat
from delve.web.auth import OWNER, seat_principal
from delve.web.events import BUFFER_SIZE, MAX_BEHIND, Event, EventBus, Viewer, sse_frame


async def take(iterator, n):
    return [await asyncio.wait_for(anext(iterator), 1) for _ in range(n)]


def test_publish_assigns_increasing_seq():
    bus = EventBus()
    assert [bus.publish("a", {}), bus.publish("b", {"x": 1}), bus.publish("a", {})] == [1, 2, 3]


def test_subscribe_replays_since():
    async def run():
        bus = EventBus()
        for i in range(5):
            bus.publish("tick", {"i": i})
        events = bus.subscribe(since=3)
        replayed = await take(events, 2)
        bus.publish("tick", {"i": 5})
        live = await take(events, 1)
        await events.aclose()
        return replayed + live

    events = asyncio.run(run())
    assert events == [Event(4, "tick", {"i": 3}), Event(5, "tick", {"i": 4}), Event(6, "tick", {"i": 5})]


def test_subscribe_without_since_is_live_only():
    async def run():
        bus = EventBus()
        bus.publish("old", {})
        events = bus.subscribe(since=None)
        first = asyncio.ensure_future(anext(events))
        await asyncio.sleep(0)
        bus.publish("new", {})
        event = await asyncio.wait_for(first, 1)
        await events.aclose()
        return event

    assert asyncio.run(run()) == Event(2, "new", {})


def test_buffer_keeps_last_500():
    async def run():
        bus = EventBus()
        for i in range(BUFFER_SIZE + 10):
            bus.publish("tick", {"i": i})
        events = bus.subscribe(since=0)
        first = await take(events, 1)
        await events.aclose()
        return first[0]

    assert BUFFER_SIZE == 500
    assert asyncio.run(run()).seq == 11


def test_since_from_an_earlier_process_replays_the_buffer():
    async def run():
        bus = EventBus()
        bus.publish("tick", {})
        events = bus.subscribe(since=900)
        first = await take(events, 1)
        await events.aclose()
        return first[0]

    assert asyncio.run(run()).seq == 1


def test_slow_subscriber_dropped():
    async def run():
        bus = EventBus()
        slow = bus.subscribe(since=None)
        first = asyncio.ensure_future(anext(slow))
        await asyncio.sleep(0)
        bus.publish("tick", {"i": 0})
        await first
        assert bus.subscriber_count == 1
        for i in range(MAX_BEHIND + 1):
            bus.publish("tick", {"i": i + 1})
        assert bus.subscriber_count == 0
        return [event async for event in slow]

    assert MAX_BEHIND == 1000
    assert asyncio.run(run()) == []


def test_closed_subscriber_unregisters():
    async def run():
        bus = EventBus()
        events = bus.subscribe(since=None)
        pending = asyncio.ensure_future(anext(events))
        await asyncio.sleep(0)
        assert bus.subscriber_count == 1
        pending.cancel()
        await asyncio.sleep(0)
        await events.aclose()
        return bus.subscriber_count

    assert asyncio.run(run()) == 0


def test_sse_frame():
    assert sse_frame(Event(7, "preferences", {"language": "nl"})) == (
        'id: 7\nevent: preferences\ndata: {"language": "nl"}\n\n'
    )


def test_sse_requires_principal(lan):
    response = lan.get("/api/events")
    assert response.status_code == 401
    assert response.json() == {"error": "Log in to go on."}


def test_sse_bad_since_422(local):
    assert local.get("/api/events?since=x").status_code == 422


def free_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    return sock


async def read_frames(app, path, n, headers=None):
    """Serve `app` with uvicorn on a free loopback port and read the first `n` frames of `path`."""
    sock = free_socket()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    serving = asyncio.ensure_future(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
            frames = []
            url = f"http://127.0.0.1:{port}{path}"
            async with httpx.AsyncClient() as client, client.stream("GET", url, headers=headers) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer and len(frames) < n:
                        frame, buffer = buffer.split("\n\n", 1)
                        frames.append(frame + "\n\n")
                    if len(frames) == n:
                        break
            return frames
    finally:
        server.should_exit = True
        await serving
        sock.close()


def test_sse_frame_format(app):
    seq = app.state.events.publish("preferences", {"language": "nl"})
    frames = asyncio.run(read_frames(app, "/api/events?since=0", 1))
    assert frames == [f"id: {seq}\nevent: preferences\ndata: {json.dumps({'language': 'nl'})}\n\n"]
    assert app.state.events.subscriber_count == 0


def test_sse_honours_last_event_id(app):
    for i in range(3):
        app.state.events.publish("tick", {"i": i})
    frames = asyncio.run(read_frames(app, "/api/events", 2, headers={"Last-Event-ID": "1"}))
    assert [frame.splitlines()[0] for frame in frames] == ["id: 2", "id: 3"]


def test_sse_pings_when_quiet(app, monkeypatch):
    from delve.web import events

    monkeypatch.setattr(events, "PING_SECONDS", 0.05)
    assert asyncio.run(read_frames(app, "/api/events", 1)) == [": ping\n\n"]


# ----- who gets an event (plan 4 Task 3) -----


class Tables:
    """Two tables: the owner's seat `seat_own` at A, and the seats in `seats`, which play `controls`."""

    def __init__(self, *seats: Seat, controls=None):
        self.seats = {seat.id: seat for seat in seats}
        self.owner = Seat("seat_own", "cmp_a", "Host", "en", "host", organiser=True, owner=True)
        self.played = controls or {}

    def current(self, seat):
        return self.seats.get(seat.id, replace(seat, left_at="gone"))

    def owner_seat(self, campaign_id):
        return self.owner if campaign_id == "cmp_a" else None

    def controls(self, seat):
        return set(self.played.get(seat.id, ()))


ANA = Seat("seat_ana", "cmp_a", "Ana", "en", "player")
BO = Seat("seat_bo", "cmp_a", "Bo", "en", "player")
CY = Seat("seat_cy", "cmp_a", "Cy", "en", "observer")
DEE = Seat("seat_dee", "cmp_b", "Dee", "en", "player", organiser=True)
EVE = Seat("seat_eve", "cmp_b", "Eve", "en", "player")


def viewer(seat):
    return Viewer.of(seat_principal(seat))


@pytest.fixture
def bus():
    return EventBus(Tables(ANA, BO, CY, DEE, EVE, controls={"seat_ana": {"chr_g"}, "seat_own": {"chr_free"}}))


def test_publish_keeps_scope_campaign_and_audience():
    bus = EventBus()
    with pytest.raises(ValueError):
        bus.publish("beat", {}, scope="table")
    with pytest.raises(ValueError):
        bus.publish("beat", {}, scope="everyone", campaign_id="cmp_a")
    seq = bus.publish("story", {}, scope="table", campaign_id="cmp_a", audience={"seats": ["seat_ana"]})
    assert list(bus._buffer) == [Event(seq, "story", {}, "table", "cmp_a", {"seats": ["seat_ana"]})]


def test_a_board_event_must_name_its_zone(bus):
    with pytest.raises(ValueError):
        bus.publish("board", {}, scope="board")
    seq = bus.publish("board", {"zone_id": "zone_a"}, scope="board", zone_id="zone_a")
    assert list(bus._buffer)[-1] == Event(seq, "board", {"zone_id": "zone_a"}, "board", zone_id="zone_a")


def test_organiser_events_go_to_organisers_only(bus):
    event = Event(1, "modules", {})
    assert bus.may_see(Viewer.of(OWNER), event)
    assert bus.may_see(viewer(DEE), event), "a seat granted the organiser role"
    assert not any(bus.may_see(viewer(seat), event) for seat in (ANA, CY, EVE))


def test_table_events_go_to_the_seats_that_may_see_them(bus):
    everyone = Event(1, "beat", {}, "table", "cmp_a")
    assert all(bus.may_see(viewer(seat), everyone) for seat in (ANA, BO, CY))
    assert bus.may_see(Viewer.of(OWNER), everyone)
    assert bus.may_see(viewer(DEE), everyone), "an organiser seated at another table"
    assert not bus.may_see(viewer(EVE), everyone), "a player of another table"

    to_ana = Event(2, "story", {}, "table", "cmp_a", {"seats": ["seat_ana"]})
    assert [bus.may_see(viewer(s), to_ana) for s in (ANA, BO, CY, EVE)] == [True, False, False, False]
    assert not bus.may_see(Viewer.of(OWNER), to_ana), "the owner sees as their own seat at that table"
    assert bus.may_see(viewer(DEE), to_ana)

    to_garrek = Event(3, "story", {}, "table", "cmp_a", {"characters": ["chr_g"]})
    assert [bus.may_see(viewer(s), to_garrek) for s in (ANA, BO, CY)] == [True, False, False]
    assert not bus.may_see(Viewer.of(OWNER), to_garrek)
    assert bus.may_see(Viewer.of(OWNER), Event(4, "story", {}, "table", "cmp_a", {"characters": ["chr_free"]}))

    assert not bus.may_see(viewer(ANA), Event(5, "story", {}, "table", "cmp_a", {"party": ["chr_g"]}))
    assert not bus.may_see(Viewer.of(OWNER), Event(6, "story", {}, "table", None))


def test_a_seat_that_left_or_lost_the_organiser_role_gets_nothing_more():
    tables = Tables(replace(ANA, left_at="2026-10-18T10:00:00+00:00"), replace(DEE, organiser=False))
    bus = EventBus(tables)
    assert not bus.may_see(viewer(ANA), Event(1, "beat", {}, "table", "cmp_a"))
    assert not bus.may_see(viewer(DEE), Event(2, "modules", {}))
    assert not bus.may_see(viewer(BO), Event(3, "beat", {}, "table", "cmp_a")), "a seat that is gone"


def test_live_and_replayed_events_are_filtered_the_same(bus):
    async def run():
        bus.publish("story", {"n": 1}, scope="table", campaign_id="cmp_a", audience={"seats": ["seat_ana"]})
        bus.publish("modules", {"n": 2})
        bus.publish("beat", {"n": 3}, scope="table", campaign_id="cmp_a")
        replayed = bus.subscribe(since=0, viewer=viewer(BO))
        first = await take(replayed, 1)
        live = asyncio.ensure_future(anext(replayed))
        await asyncio.sleep(0)
        bus.publish("story", {"n": 4}, scope="table", campaign_id="cmp_a", audience={"characters": ["chr_g"]})
        bus.publish("characters", {"n": 5}, scope="table", campaign_id="cmp_a")
        second = await asyncio.wait_for(live, 1)
        while second.type == "seats":  # BO's coming to the table, published to it
            second = await asyncio.wait_for(anext(replayed), 1)
        await replayed.aclose()
        return [e.data["n"] for e in first + [second]]

    assert asyncio.run(run()) == [3, 5]


def test_presence_lasts_while_listening_and_for_the_grace_after(bus):
    """Plan 4 Task 4: a seat is present while it listens, and for 30 s after; then the table hears `seats`, and the
    beats are told."""
    from delve.play.clock import FakeClock

    async def run():
        clock = FakeClock()
        bus._clock = clock
        told: list = []
        bus.on_presence = told.append
        assert bus.present("cmp_a") == set()

        ana = bus.subscribe(None, viewer(ANA))
        watching = asyncio.ensure_future(anext(ana))
        await asyncio.sleep(0)
        assert bus.present("cmp_a") == {"seat_ana"} and bus.present("cmp_b") == set()
        assert told == ["cmp_a"]
        owner = bus.subscribe(None, Viewer.of(OWNER))
        owner_watching = asyncio.ensure_future(anext(owner))
        await asyncio.sleep(0)
        assert bus.present("cmp_a") == {"seat_ana", "seat_own"}, "the owner, as their owner seat"
        assert told == ["cmp_a", None]

        watching.cancel()
        await asyncio.gather(watching, return_exceptions=True)
        await ana.aclose()
        await clock.advance(29)
        assert "seat_ana" in bus.present("cmp_a"), "a reload or a short loss of signal isn't going away"
        await clock.advance(2)
        assert bus.present("cmp_a") == {"seat_own"}
        assert told == ["cmp_a", None, "cmp_a"]
        seats = [e for e in bus._buffer if e.type == "seats"]
        assert [(e.data, e.scope, e.campaign_id) for e in seats] == [({"campaign_id": "cmp_a"}, "table", "cmp_a")] * 2

        owner_watching.cancel()
        await asyncio.gather(owner_watching, return_exceptions=True)
        await owner.aclose()

    asyncio.run(run())


def test_coming_back_within_the_grace_changes_nothing(bus):
    from delve.play.clock import FakeClock

    async def run():
        clock = FakeClock()
        bus._clock = clock
        told: list = []
        bus.on_presence = told.append
        for _ in range(2):
            stream = bus.subscribe(None, viewer(BO))
            waiting = asyncio.ensure_future(anext(stream))
            await asyncio.sleep(0)
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            await stream.aclose()
            await clock.advance(10)
        await clock.advance(15)
        assert bus.present("cmp_a") == {"seat_bo"} and told == ["cmp_a"]
        await clock.advance(10)
        assert bus.present("cmp_a") == set() and told == ["cmp_a", "cmp_a"]

    asyncio.run(run())


# ----- a restart isn't held up by the streams (DEL-205) -----


def test_close_ends_every_stream():
    async def run():
        bus = EventBus()
        events = bus.subscribe(since=None)
        waiting = asyncio.ensure_future(anext(events))
        await asyncio.sleep(0)
        assert bus.subscriber_count == 1
        bus.close()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(waiting, 1)
        return bus.subscriber_count

    assert asyncio.run(run()) == 0


def test_a_server_with_a_stream_open_stops_at_once(app):
    """uvicorn waits for every open connection as it shuts down; DelveServer ends the streams first, so it stops in
    well under its grace (an open stream used to hold a restart up until systemd killed it, and the proxy said 502)."""
    from delve.web.app import DelveServer

    async def run():
        sock = free_socket()
        port = sock.getsockname()[1]
        config = uvicorn.Config(app, log_level="warning", lifespan="off", timeout_graceful_shutdown=30)
        server = DelveServer(config, app)
        serving = asyncio.ensure_future(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    await asyncio.sleep(0.01)
                url = f"http://127.0.0.1:{port}/api/events"
                async with httpx.AsyncClient() as client, client.stream("GET", url) as response:
                    assert response.status_code == 200
                    while app.state.events.subscriber_count == 0:
                        await asyncio.sleep(0.01)
                    started = asyncio.get_running_loop().time()
                    server.should_exit = True
                    await asyncio.wait_for(serving, 5)
                    return asyncio.get_running_loop().time() - started
        finally:
            server.should_exit = True
            await serving
            sock.close()

    assert asyncio.run(run()) < 3


# ----- from any thread (DEL-166), asking the tables once per batch (DEL-172) -----


def test_publish_from_many_threads_numbers_every_event_once():
    """Sync routes publish from the threadpool: the numbering raced. Now every event gets its own number, in order."""
    import threading

    bus = EventBus()
    seqs: list[int] = []

    def publish_many():
        for _ in range(200):
            seqs.append(bus.publish("tick", {}))

    threads = [threading.Thread(target=publish_many) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(seqs) == list(range(1, 1601))
    assert [e.seq for e in bus._buffer] == list(range(1101, 1601))


def test_an_event_published_off_the_loop_is_handed_on_on_the_loop_in_order():
    import threading

    async def run():
        bus = EventBus()
        bus.bind(asyncio.get_running_loop())
        handed_on: list[str] = []
        may_see = bus.may_see

        def recording(viewer, event, tables=None):
            handed_on.append(threading.current_thread().name)
            return may_see(viewer, event, tables)

        bus.may_see = recording
        events = bus.subscribe(since=None)
        first = asyncio.ensure_future(anext(events))
        await asyncio.sleep(0)
        off = await asyncio.to_thread(bus.publish, "off", {})
        on = bus.publish("on", {})
        got = [await asyncio.wait_for(first, 1), *await take(events, 1)]
        await events.aclose()
        return off, on, got, handed_on

    off, on, got, handed_on = asyncio.run(run())
    assert (off, on) == (1, 2)
    assert [(e.seq, e.type) for e in got] == [(1, "off"), (2, "on")]
    assert set(handed_on) == {threading.current_thread().name}, "the subscribers are told on the loop's thread"


class CountingTables(Tables):
    def __init__(self, *seats, controls=None):
        super().__init__(*seats, controls=controls)
        self.asked = 0

    def current(self, seat):
        self.asked += 1
        return super().current(seat)

    def owner_seat(self, campaign_id):
        self.asked += 1
        return super().owner_seat(campaign_id)

    def controls(self, seat):
        self.asked += 1
        return super().controls(seat)


def test_a_replay_asks_the_tables_once_per_question():
    """A reconnecting phone replayed 500 events with 3–4 queries each (1,504 for one account): now each question is
    asked once for the whole replay."""

    async def run():
        tables = CountingTables(ANA, BO, controls={"seat_ana": {"chr_g"}})
        bus = EventBus(tables)
        for _ in range(BUFFER_SIZE):
            bus.publish("story", {}, scope="table", campaign_id="cmp_a", audience={"characters": ["chr_g"]})
        tables.asked = 0
        events = bus.subscribe(since=0, viewer=viewer(ANA))
        replayed = await take(events, BUFFER_SIZE)
        await events.aclose()
        return tables.asked, replayed

    asked, replayed = asyncio.run(run())
    assert len(replayed) == BUFFER_SIZE
    assert asked == 3  # the seat as it is now and the characters it plays, then the seat for its own `seats` event


def test_one_batch_asks_once_for_every_listener():
    async def run():
        tables = CountingTables(ANA, BO, controls={"seat_ana": {"chr_g"}})
        bus = EventBus(tables)
        streams = [bus.subscribe(None, viewer(seat)) for seat in (ANA, ANA, BO)]
        waiting = [asyncio.ensure_future(anext(s)) for s in streams]
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        tables.asked = 0
        bus.publish("story", {}, scope="table", campaign_id="cmp_a", audience={"characters": ["chr_g"]})
        asked = tables.asked
        got = []
        for stream, first in zip(streams[:2], waiting[:2], strict=True):
            event = await asyncio.wait_for(first, 1)
            while event.type == "seats":  # the seats coming to the table
                event = await asyncio.wait_for(anext(stream), 1)
            got.append(event)
        waiting[2].cancel()
        await asyncio.gather(waiting[2], return_exceptions=True)
        for stream in streams:
            await stream.aclose()
        return asked, got

    asked, got = asyncio.run(run())
    assert [e.type for e in got] == ["story", "story"]
    assert asked == 4  # Ana's seat and characters once for both her streams, Bo's seat and characters
