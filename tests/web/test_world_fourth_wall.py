"""The fourth wall for the world, per seat (plan 6 Task 12, Review Focus 1; Decision 7): what only the DM knows of
the world never reaches a seat's browser.

`SECRET-XYZZY` is planted in a hidden world-map place (its name, description and `doc`), a faction's `notes_md` and
an unknown faction's name, a clock's `on_complete`, an unknown quest and a known quest's notes and DM-only note, a
possession's `notes_md`, an NPC's possession (its location, description and inventory), and a merchant's shelf. The
DM reads them in a beat through `factions`, `clocks`, `world_map`, `possession` and `magic_merchant`, and the
organisers edit them through their routes. Ana and Bo, who play, and Cy, who observes, never get it: not through
`GET …/world`, the world-map list and view, the story, or the event stream with `since=0`; and the organisers' routes
refuse them.

Plan 7 Task 11 (Review Focus 1): a map the party knows nothing of, its name `secret-xyzzy-…` and its title
`SECRET-XYZZY`, is saved and deleted by the organiser while Bo and Cy listen live; neither their live stream nor
their `since=0` replay names it (a table's `world` event carries only the campaign's id), and no seat lists it. A
picture's unknown half, planted magenta, is never in a seat's tile.
"""

import asyncio
import io
import json

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from PIL import Image

from delve.dm.fake import FAKE_DM_CAPABILITIES
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.domain.backends import Registry
from delve.domain.world import Faction, Merchant, Quest, QuestNote
from delve.maps.geo import pictures
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.model import Frame, GeoMap, Grid, PictureRef
from delve.play import factions, possessions, seats, world_maps
from delve.play.context import context_for
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.maps.geo.test_tiles import MAGENTA, halves
from tests.web.conftest import BASE_URL, make_registries, playing
from tests.web.test_events import free_socket
from tests.web.test_fourth_wall_per_seat import TellingDM, act_and_wait, read_until
from tests.web.test_world_api import isles_doc, made, vale_module

SECRET = "SECRET-XYZZY"
SHELF = [{"name": f"{SECRET} wand of wonder", "value_gp": 5000, "price_gp": 10000}]


@pytest.fixture
def dm():
    return TellingDM([])


@pytest.fixture
def registries(dm):
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    return registries


@pytest.fixture
def world(app, local, storage):
    """The vale with every DM-only thing of the world planted, the party at Oakton; Ana plays Garrek, Bo plays Tira,
    Cy observes, each in their own browser on the LAN."""
    cid = made(local, vale_module(storage).id, setting=None)
    playing(storage, cid)
    ctx = context_for(storage, cid, "beat-0", catalogs=over(PlayReference()))
    world_maps.place_party(ctx, "oakton")
    storage.quests.put(
        Quest(
            cid,
            "relic",
            "Find the relic",
            status="active",
            known=True,
            log=(QuestNote(1, "The abbot sent us.", True), QuestNote(1, f"{SECRET}: the abbot lied.", False)),
            notes_md=f"{SECRET}: the relic is fake.",
        )
    )
    storage.quests.put(Quest(cid, "plot", f"{SECRET}: the coup", known=False))
    storage.factions.put(Faction(cid, "watch", "The Watch", known=True, reputation=30, notes_md=SECRET, strength=77))
    storage.factions.put(Faction(cid, "cult", f"{SECRET} cult", known=False))
    factions.add_clock(ctx, "The eye wakes", days=3, faction="watch", on_complete=SECRET)
    possessions.add(ctx, "The Gull", "ship", notes=f"{SECRET}: smuggles for the cult.", stats={"mv": 12})
    storage.merchants.put(Merchant(cid, "ostler", "Ostler's", items=tuple(SHELF)))
    storage.characters.create(cid, "Vesk", kind="npc")
    possessions.add(
        ctx,
        "The Black Barge",
        "ship",
        owner="Vesk",
        location=f"{SECRET}: moored under the tower",
        description=f"{SECRET}: a smuggler's barge",
        inventory=[f"{SECRET} crate"],
    )

    garrek = storage.characters.create(cid, "Garrek")
    tira = storage.characters.create(cid, "Tira")
    people, clients = {}, []
    for name, role in (("Ana", "player"), ("Bo", "player"), ("Cy", "observer")):
        token = new_seat_token()
        seat = storage.seats.create(cid, name, "en", role, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        people[name] = (seat, client, token)
    seats.claim(storage, garrek.id, people["Ana"][0])
    seats.claim(storage, tira.id, people["Bo"][0])
    yield {"campaign": cid, **people}
    for client in clients:
        client.__exit__(None, None, None)


def path(cid: str, rest: str) -> str:
    return f"/api/campaigns/{cid}/{rest}"


def dm_reads_the_world(app, local, dm, cid) -> int:
    """A beat in which the DM reads every DM-only thing of the world, the answers carrying the secret, and narrates;
    answers the newest event's seq once the beat is done."""
    calls = [
        ("factions", {}, {"factions": [{"id": "cult", "name": f"{SECRET} cult", "notes_md": SECRET}]}),
        ("clocks", {}, {"clocks": [{"id": 1, "label": "The eye wakes", "on_complete": SECRET}]}),
        ("world_map", {"feature": "old-tower"}, {"feature": {"name": "old-tower", "dm_notes": SECRET}}),
        ("possession", {"id": "The Gull"}, {"notes_md": SECRET}),
        ("magic_merchant", {"merchant": "ostler"}, {"merchant": "Ostler's", "items": SHELF}),
        ("quests", {}, {"quests": [{"id": "plot", "title": f"{SECRET}: the coup"}]}),
    ]
    events = []
    for n, (name, args, result) in enumerate(calls):
        events += [ToolCall(f"w{n}", name, args), ToolResult(f"w{n}", True, json.dumps(result))]
    dm.then(*events, TextDelta("The road east is quiet."))
    return act_and_wait(app, local, cid)


def organisers_edit_the_world(local, cid) -> None:
    """The organisers change each record through their routes, putting the secret in its DM-only fields."""
    assert (
        local.put(
            path(cid, "factions/watch"), json={"name": "The Watch", "known": True, "notes_md": SECRET}
        ).status_code
        == 200
    )
    [clock] = local.get(path(cid, "clocks")).json()
    assert local.put(path(cid, f"clocks/{clock['id']}"), json={**clock, "on_complete": SECRET}).status_code == 200
    assert local.put(path(cid, "quests/plot"), json={"title": f"{SECRET} plot", "known": False}).status_code == 200
    [gull] = [p for p in local.get(path(cid, "possessions")).json() if p["name"] == "The Gull"]
    assert local.put(path(cid, f"possessions/{gull['id']}"), json={"notes_md": SECRET}).status_code == 200


SEATS = ("Ana", "Bo", "Cy")


def test_the_world_reaches_no_seat_with_a_dm_only_word(app, local, dm, storage, world):
    cid = world["campaign"]
    dm_reads_the_world(app, local, dm, cid)
    organisers_edit_the_world(local, cid)
    last = app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)

    # The DM and the organisers have it: the plant is real.
    assert SECRET in local.get(path(cid, "factions")).text
    assert SECRET in local.get(path(cid, "world-maps/vale")).text
    host_frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, None)))
    assert '"magic_merchant"' in host_frames and SECRET not in host_frames  # the host sees the row, not the shelf

    for name in SEATS:
        _, client, cookie = world[name]
        seen = client.get(path(cid, "world"))
        assert seen.status_code == 200, name
        assert SECRET not in seen.text and "strength" not in seen.text and "reputation" not in seen.text, name
        assert "Oakton" in seen.text and "Find the relic" in seen.text and "Friendly" in seen.text, name
        assert [q["id"] for q in seen.json()["quests"]] == ["relic"], name
        assert [f["id"] for f in seen.json()["factions"]] == ["watch"], name
        assert [p["name"] for p in seen.json()["possessions"]] == ["The Gull"], name  # never an NPC's

        assert SECRET not in client.get(path(cid, "world-maps")).text, name
        view = client.get(path(cid, "world-maps/vale/view"))
        assert view.status_code == 200 and SECRET not in view.text and "Drowned Tower" not in view.text, name

        story = client.get(path(cid, "story"))
        assert "The road east is quiet." in story.text, name
        assert SECRET not in story.text and "magic_merchant" not in story.text, name

        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert "event: world" in frames and "The road east is quiet." in frames, name
        assert SECRET not in frames and "Ostler" not in frames, name


@pytest.mark.parametrize("collection", ["factions", "clocks", "quests", "possessions"])
def test_the_organisers_routes_refuse_a_seat(world, collection):
    cid = world["campaign"]
    for name in SEATS:
        _, client, _ = world[name]
        assert client.get(path(cid, collection)).status_code == 403, name
        assert client.get(path(cid, f"{collection}/x")).status_code == 403, name
        assert client.put(path(cid, f"{collection}/x"), json={}).status_code == 403, name
        assert client.request("DELETE", path(cid, f"{collection}/x"), json={}).status_code == 403, name


PLANTED_MAP = "secret-xyzzy-lair"
"""Its name, in lowercase: the checks look for `xyzzy` in any case."""


def leaks(text: str) -> bool:
    return "xyzzy" in text.casefold()


async def live_and_replayed(app, cid: str, cookies: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Serve `app`; with each seat's browser listening live, the organiser (the owner on this machine) saves the
    planted map, says what the party knows of it, imports it again over GeoJSON and deletes it; the frames each
    browser got live, up to an end marker, and the host's own."""
    sock = free_socket()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    serving = asyncio.ensure_future(server.serve(sockets=[sock]))
    base = f"http://127.0.0.1:{port}"
    end = "END-OF-THE-ORGANISERS-CHANGES"

    async def listen(cookie: str | None) -> list[str]:
        headers = {"Cookie": f"{SEAT_COOKIE}={cookie}"} if cookie is not None else {}
        frames: list[str] = []
        async with httpx.AsyncClient() as client, client.stream("GET", f"{base}/api/events", headers=headers) as r:
            assert r.status_code == 200
            buffer = ""
            async for chunk in r.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    frame, buffer = buffer.split("\n\n", 1)
                    frames.append(frame)
                    if end in frame:
                        return frames
        return frames

    try:
        async with asyncio.timeout(15):
            while not server.started:
                await asyncio.sleep(0.01)
            before = app.state.events.subscriber_count
            listeners = [asyncio.ensure_future(listen(c)) for c in [*cookies, None]]
            while app.state.events.subscriber_count < before + len(listeners):
                await asyncio.sleep(0.01)
            maps = f"{base}/api/campaigns/{cid}/world-maps"
            async with httpx.AsyncClient() as organiser:
                body = {"title": SECRET, "geo": isles_doc()}
                assert (await organiser.put(f"{maps}/{PLANTED_MAP}", json=body)).status_code == 200
                known = {"how": "nothing"}
                assert (await organiser.put(f"{maps}/{PLANTED_MAP}/knowledge", json=known)).status_code == 200
                assert (await organiser.request("DELETE", f"{maps}/{PLANTED_MAP}", json={})).status_code == 204
                again = {"name": PLANTED_MAP, "title": SECRET, "document": isles_doc()}
                assert (await organiser.post(f"{maps}/geojson", json=again)).status_code == 201
            app.state.events.publish("beat", {"campaign_id": cid, "end": end}, scope="table", campaign_id=cid)
            *seen, host = await asyncio.gather(*listeners)
            return dict(zip(cookies, seen, strict=True)), host
    finally:
        server.should_exit = True
        await serving
        sock.close()


def test_a_map_the_party_knows_nothing_of_is_never_named_to_a_seat(app, local, storage, world):
    cid = world["campaign"]
    cookies = [world[name][2] for name in SEATS]
    live, host = asyncio.run(live_and_replayed(app, cid, cookies))
    assert sum("event: world" in frame for frame in host) == 4, "the plant is real: four changes"
    assert SECRET in local.get(path(cid, f"world-maps/{PLANTED_MAP}")).text

    last = app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)
    for name, cookie in zip(SEATS, cookies, strict=True):
        _, client, _ = world[name]
        replayed = asyncio.run(read_until(app, "/api/events?since=0", last, cookie))
        for frames in (live[cookie], replayed):
            world_frames = [f for f in frames if "event: world" in f]
            assert len(world_frames) >= 4, name
            assert not leaks("\n".join(frames)), name
            for frame in world_frames:
                data = json.loads(frame.split("data: ", 1)[1])
                assert data == {"campaign_id": cid}, name  # no map key, live or replayed
        assert [m["name"] for m in client.get(path(cid, "world-maps")).json()] == ["vale"], name
        assert not leaks(client.get(path(cid, "world-maps")).text), name
        assert client.get(path(cid, f"world-maps/{PLANTED_MAP}/view")).status_code == 404, name
        assert client.get(path(cid, f"world-maps/{PLANTED_MAP}/tiles/0/0/0")).status_code == 404, name
        organisers = client.get(path(cid, "organiser/world-maps"))
        assert organisers.status_code == 403 and not leaks(organisers.text), name
    assert PLANTED_MAP in {m["name"] for m in local.get(path(cid, "organiser/world-maps")).json()}


def test_a_pictures_unknown_half_never_reaches_a_seats_tile(app, local, storage, world):
    """The isles over a picture whose right half is magenta: the party knows only the left half."""
    cid = world["campaign"]
    stored = pictures.store(storage, halves(), "image/png")
    geo = GeoMap(Frame(512.0, 256.0), Grid("square", 32.0, 16, 8), "p" * 128, (), PictureRef(stored.id, 512, 256, 1.0))
    assert local.put(path(cid, "world-maps/isles"), json={"title": "Isles", "geo": to_geojson(geo)}).status_code == 200
    ring = [[0, 0], [256, 0], [256, 256], [0, 256]]
    assert local.put(path(cid, "world-maps/isles/knowledge"), json={"how": "area", "ring": ring}).status_code == 200

    for name in SEATS:
        _, client, _ = world[name]
        assert stored.id not in client.get(path(cid, "world-maps/isles/view")).text, name
        for z, x, y in ((0, 0, 0), (1, 0, 0), (1, 1, 0)):
            tile = client.get(path(cid, f"world-maps/isles/tiles/{z}/{x}/{y}"))
            if tile.status_code == 404:
                continue
            colours = Image.open(io.BytesIO(tile.content)).convert("RGB").getcolors(256 * 256)
            assert not any(r > 200 and b > 200 and g < 120 for _, (r, g, b) in colours), (name, z, x, y, MAGENTA)
        assert client.get(path(cid, "world-maps/isles/tiles/1/1/0")).status_code == 404, name
        assert client.get(path(cid, "world-maps/isles/picture")).status_code == 403, name
        assert client.get(f"/api/world-pictures/{stored.id}/tiles/0/0/0").status_code == 403, name


@pytest.mark.parametrize(
    ("method", "rest"),
    [
        ("GET", "organiser/world-maps"),
        ("GET", "world-maps/vale"),
        ("GET", "world-maps/vale/dm-view"),
        ("PUT", "world-maps/vale"),
        ("DELETE", "world-maps/vale"),
        ("PUT", "world-maps/vale/knowledge"),
        ("POST", "world-maps/geojson"),
        ("GET", "world-maps/vale/export.geojson"),
        ("GET", "world-maps/vale/picture"),
    ],
)
def test_the_organisers_world_map_routes_refuse_a_seat(world, method, rest):
    cid = world["campaign"]
    for name in SEATS:
        _, client, _ = world[name]
        answer = client.request(method, path(cid, rest), **({"json": {}} if method != "GET" else {}))
        assert answer.status_code == 403 and SECRET not in answer.text, name
