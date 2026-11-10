"""The fourth wall, per seat (plan 4 Task 3, Review Focus 1; spec §7.5): what is for one seat never reaches another
seat's browser, through two seats' own clients.

A `SECRET-XYZZY` is planted in an Ask the DM answer to Ana, in narration for Ana's character only, in an NPC's notes
and in a DM-only room of the map. Bo, at the same table, and Cy, who observes, never get it: not through
`GET …/story`, the event stream and its replay (`since=0`), `GET …/characters` or the map view.

A tell is for the seats that play its characters when it is told: claiming, releasing or leaving later shows it to
nobody new (audit finding 1).
"""

import asyncio
import json
import time
from dataclasses import replace

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from delve.dm.claude_cli import account
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.domain.backends import Registry
from delve.domain.histories import History
from delve.domain.world import TraitsPortrait
from delve.play import seats
from delve.play.audience import for_characters
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, make_registries, playing
from tests.web.test_campaigns_api import campaign, character, characters_view, crypt_module, move
from tests.web.test_events import free_socket
from tests.web.test_map_state_api import PLANTED

SECRET = "SECRET-XYZZY"


class TellingDM(FakeDM):
    """The fake DM, whose next beat a test scripts once it knows its characters."""

    def then(self, *events) -> None:
        self._script.append(list(events))


@pytest.fixture
def dm():
    """A side pass that answers Ask the DM with the secret, the worst it could do."""
    return TellingDM([], side_handler=lambda prompt: f"{SECRET}: the abbot is the ritualist.")


@pytest.fixture
def registries(dm):
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    return registries


@pytest.fixture
def table(app, local, storage):
    """A campaign on the planted crypt: Ana plays Garrek, Bo plays Tira, Cy observes; Grik is an NPC with a secret
    story. Each seat has its own browser on the LAN."""
    module = crypt_module(local, PLANTED)
    started = campaign(local, module["id"])
    cid = started["id"]
    playing(storage, cid)
    garrek, tira = (character(local, cid, name)["id"] for name in ("Garrek", "Tira"))
    grik = storage.characters.create(cid, "Grik", kind="npc")
    storage.characters.save(replace(grik, sheet=replace(grik.sheet, notes_md=f"{SECRET}: he serves the cult.")))
    assert move(local, cid, [garrek, tira], "room.entry_hall").status_code == 200

    clients, people = [], {}
    for name, role in (("Ana", "player"), ("Bo", "player"), ("Cy", "observer")):
        token = new_seat_token()
        seat = storage.seats.create(cid, name, "en", role, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        people[name] = (seat, client, token)
    seats.claim(storage, garrek, people["Ana"][0])
    seats.claim(storage, tira, people["Bo"][0])
    yield {"campaign": cid, "garrek": garrek, "tira": tira, "grik": grik.id, **people}
    for client in clients:
        client.__exit__(None, None, None)


def plant(app, storage, table):
    """Ana asks the DM, and the DM tells Garrek something alone; answers the newest event's seq."""
    cid = table["campaign"]
    _, ana, _ = table["Ana"]
    asked = ana.post(f"/api/campaigns/{cid}/ask", json={"question": "Who is the ritualist?"})
    assert asked.status_code == 200, asked.json()
    assert SECRET in asked.json()["answer"]
    whisper = {"text": f"{SECRET} whispers to you."}
    told = storage.story.append(cid, None, "dm_text", whisper, for_characters([table["garrek"]]))
    app.state.events.publish(
        "story", {"campaign_id": cid, "entry": {"id": told.id}}, scope="table", campaign_id=cid, audience=told.audience
    )
    return app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)


def test_the_story_is_each_seats_own(app, storage, table):
    plant(app, storage, table)
    path = f"/api/campaigns/{table['campaign']}/story"
    _, ana, _ = table["Ana"]
    ana_story = ana.get(path).json()
    assert [e["kind"] for e in ana_story["entries"]] == ["ask", "answer", "dm_text"]
    assert SECRET in json.dumps(ana_story)

    for name in ("Bo", "Cy"):
        _, client, _ = table[name]
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"entries": [], "has_more": False}, name

    # A page counts only what the seat sees.
    first = ana.get(path, params={"limit": 2}).json()
    assert [e["kind"] for e in first["entries"]] == ["answer", "dm_text"] and first["has_more"] is True
    earlier = ana.get(path, params={"limit": 2, "before": first["entries"][0]["seq"]}).json()
    assert [e["kind"] for e in earlier["entries"]] == ["ask"] and earlier["has_more"] is False


def test_asks_session_block_is_each_seats_own(app, dm, storage, table):
    """Plan faithful modules Task 23 (Review Focus 4): Ask reads the whole session, however long, and only what the
    asker may see: Ana's answer and Garrek's tell, planted early in it, never reach Bo's or Cy's prompt."""
    plant(app, storage, table)
    cid = table["campaign"]
    for n in range(30):
        storage.story.append(cid, None, "dm_text", {"text": f"The hall, hour {n}."})
    for name in ("Bo", "Cy"):
        _, client, _ = table[name]
        assert client.post(f"/api/campaigns/{cid}/ask", json={"question": "What now?"}).status_code == 200
        prompt = dm.side_prompts[-1]
        assert "WHAT HAPPENED THIS SESSION" in prompt and "The hall, hour 0." in prompt, name
        assert SECRET not in prompt and "Who is the ritualist?" not in prompt, name


async def read_until(app, path: str, last_seq: int, cookie: str | None) -> list[str]:
    """Serve `app` on a free loopback port and read the frames of `path`, as a browser with the seat cookie (without
    one, the owner on this machine), up to the one numbered `last_seq`."""
    sock = free_socket()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    serving = asyncio.ensure_future(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)
            frames: list[str] = []
            headers = {"Cookie": f"{SEAT_COOKIE}={cookie}"} if cookie is not None else {}
            url = f"http://127.0.0.1:{port}{path}"
            async with httpx.AsyncClient() as client, client.stream("GET", url, headers=headers) as response:
                assert response.status_code == 200
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        frames.append(frame)
                        if frame.startswith(f"id: {last_seq}\n"):
                            return frames
            return frames
    finally:
        server.should_exit = True
        await serving
        sock.close()


def test_the_event_stream_and_its_replay_are_each_seats_own(app, storage, table):
    last = plant(app, storage, table)
    app.state.events.publish("modules", {"id": "mod_000000000000"})  # the organisers'

    ana = asyncio.run(read_until(app, "/api/events?since=0", last, table["Ana"][2]))
    assert SECRET in "\n".join(ana)
    assert sum(frame.count("event: story") for frame in ana) == 3, "Ana's question, its answer and the tell"

    for name in ("Bo", "Cy"):
        frames = asyncio.run(read_until(app, "/api/events?since=0", last, table[name][2]))
        assert frames[-1].startswith(f"id: {last}\n"), name
        assert SECRET not in "\n".join(frames), name
        assert not any("event: story" in frame for frame in frames), name
        assert not any("event: modules" in frame for frame in frames), name


def test_the_characters_hide_the_dms_knowledge(storage, table):
    _, bo, _ = table["Bo"]
    listed = bo.get(f"/api/campaigns/{table['campaign']}/characters")
    assert listed.status_code == 200
    assert SECRET not in listed.text
    grik = next(c for c in listed.json() if c["id"] == table["grik"])
    assert grik == {"id": table["grik"], "name": "Grik", "kind": "npc"}
    assert {c["name"] for c in listed.json()} == {"Garrek", "Tira", "Grik"}


def test_the_map_view_is_of_a_seats_own_characters(local, table):
    cid = table["campaign"]
    _, bo, _ = table["Bo"]
    theirs = characters_view(bo, cid, [table["garrek"]])
    assert theirs.status_code == 403
    assert theirs.json() == {"error": "You can only see what your own characters know."}
    assert characters_view(bo, cid, [table["tira"], table["garrek"]]).status_code == 403
    _, cy, _ = table["Cy"]
    assert characters_view(cy, cid, [table["tira"]]).status_code == 403

    own = characters_view(bo, cid, [table["tira"]])
    assert own.status_code == 200
    assert "Entry Hall" in own.json()["svg"] and SECRET not in own.json()["svg"]
    # The host may view any group (spec §7.4), but still through the fog.
    hosts = characters_view(local, cid, [table["garrek"]])
    assert hosts.status_code == 200 and SECRET not in hosts.json()["svg"]


# ----- a tell is for the seats of its time (audit finding 1) -----


def act_and_wait(app, local, cid) -> int:
    """The host acts (and says go while the beat waits for the players); answers the newest event's seq once the
    beat is done."""
    assert local.post(f"/api/campaigns/{cid}/act", json={"text": "We listen."}).status_code == 202
    beat = app.state.storage.beats.current(cid)
    if beat is not None and beat.status == "open":
        # The beat may close between the read and the go: then go finds it running.
        assert local.post(f"/api/campaigns/{cid}/go", json={}).status_code in (202, 409)
    deadline = time.monotonic() + 5
    while app.state.storage.beats.current(cid) is not None:
        assert time.monotonic() < deadline, "the beat is still open or running"
        time.sleep(0.02)
    return app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)


def tell(app, local, dm, cid, character_id) -> int:
    """The host acts, and the DM tells `character_id` a secret through the real `tell` result; answers the newest
    event's seq once the beat is done."""
    told = {"told": {"characters": [character_id], "text": f"{SECRET} for you alone."}}
    dm.then(
        ToolCall("t1", "tell", {"characters": [character_id], "text": "…"}), ToolResult("t1", True, json.dumps(told))
    )
    return act_and_wait(app, local, cid)


def sees_the_tell(app, cid, client, cookie, last) -> tuple[bool, bool]:
    """Whether the seat of `client` (and `cookie`, None for the owner) reads the secret: in its story, and in the
    replay of the event stream."""
    story_text = client.get(f"/api/campaigns/{cid}/story").text
    frames = asyncio.run(read_until(app, "/api/events?since=0", last, cookie))
    return SECRET in story_text, SECRET in "\n".join(frames)


def test_a_pc_claimed_after_its_player_left_brings_no_past_tells(app, local, dm, storage, table):
    """Ana is told something for Garrek, then leaves. Bo claims Garrek: the tell stays Ana's."""
    cid = table["campaign"]
    last = tell(app, local, dm, cid, table["garrek"])
    [whisper] = [e for e in storage.story.list(cid) if e.kind == "dm_text"]
    assert whisper.audience == {"seats": [table["Ana"][0].id]}
    assert whisper.payload["told_to"] == [table["garrek"]]
    _, ana, ana_token = table["Ana"]
    _, bo, bo_token = table["Bo"]
    assert sees_the_tell(app, cid, ana, ana_token, last) == (True, True)
    assert sees_the_tell(app, cid, bo, bo_token, last) == (False, False)

    assert ana.post(f"/api/campaigns/{cid}/leave", json={}).status_code == 204
    claimed = bo.post(f"/api/campaigns/{cid}/characters/{table['garrek']}/claim", json={})
    assert claimed.status_code == 200, claimed.text
    assert sees_the_tell(app, cid, bo, bo_token, last) == (False, False)


def test_a_released_pc_brings_no_past_tells_to_the_host(app, local, dm, storage, table):
    """Ana is told something for Garrek, then releases him: he is free, so the host plays him now, but the tell stays
    Ana's."""
    cid = table["campaign"]
    last = tell(app, local, dm, cid, table["garrek"])
    _, ana, ana_token = table["Ana"]
    assert sees_the_tell(app, cid, local, None, last) == (False, False)
    assert ana.post(f"/api/campaigns/{cid}/characters/{table['garrek']}/release", json={}).status_code == 200
    assert sees_the_tell(app, cid, local, None, last) == (False, False)
    assert sees_the_tell(app, cid, ana, ana_token, last) == (True, True)


def test_a_free_pcs_tells_stay_the_hosts_when_a_player_claims_it(app, local, dm, storage, table):
    """A tell to a free PC is the host's, who plays it. Bo claims it and releases it: the tell stays the host's."""
    cid = table["campaign"]
    hob = storage.characters.create(cid, "Hob")  # a PC nobody claimed: the host plays it
    last = tell(app, local, dm, cid, hob.id)
    [whisper] = [e for e in storage.story.list(cid) if e.kind == "dm_text"]
    assert whisper.audience == {"seats": [storage.seats.owner_seat(cid).id]}
    _, bo, bo_token = table["Bo"]
    assert sees_the_tell(app, cid, local, None, last) == (True, True)
    assert sees_the_tell(app, cid, bo, bo_token, last) == (False, False)

    assert bo.post(f"/api/campaigns/{cid}/characters/{hob.id}/claim", json={}).status_code == 200
    assert sees_the_tell(app, cid, bo, bo_token, last) == (False, False)
    assert bo.post(f"/api/campaigns/{cid}/characters/{hob.id}/release", json={}).status_code == 200
    assert sees_the_tell(app, cid, bo, bo_token, last) == (False, False)
    assert sees_the_tell(app, cid, local, None, last) == (True, True)


# ----- tool rows are the host's (walkthrough fixes Task 5, Review Focus 4) -----


def test_tool_rows_reach_the_host_and_no_other_seat(app, local, dm, storage, table):
    """The DM rolls and has a call refused: the host sees both rows, in the story and the stream; the players and the
    observer see neither, only what the characters perceive."""
    cid = table["campaign"]
    dm.then(
        ToolCall("r1", "roll", {"notation": "1d20", "purpose": "listen"}),
        ToolResult("r1", True, json.dumps({"total": 12})),
        ToolCall("r2", "combat_round", {}),
        ToolResult("r2", False, json.dumps({"error": "no fight"})),
    )
    last = act_and_wait(app, local, cid)
    assert [e.payload["name"] for e in storage.story.list(cid) if e.kind == "tool"] == ["roll", "combat_round"]

    hosts = [(e["kind"], e["payload"]) for e in local.get(f"/api/campaigns/{cid}/story").json()["entries"]]
    assert ("tool", {"name": "roll"}) in hosts and ("tool", {"name": "combat_round", "failed": True}) in hosts
    host_frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, None)))
    assert '"kind": "tool"' in host_frames

    for name in ("Ana", "Bo", "Cy"):
        _, client, cookie = table[name]
        kinds = [e["kind"] for e in client.get(f"/api/campaigns/{cid}/story").json()["entries"]]
        assert "tool" not in kinds, name
        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert '"kind": "tool"' not in frames and "combat_round" not in frames, name


# ----- the host's out-of-character note is the host's (review of the walkthrough fixes) -----


def test_the_hosts_ooc_note_reaches_the_host_alone(app, local, dm, storage, table):
    """The host plays no character, so the DM ends its reply with a note for the host (dm.md). The note, split over
    deltas, never reaches another seat, not even in part: not in the story, the stream, its replay or an Ask prompt.
    The narration before it reaches everyone."""
    cid = table["campaign"]
    dm.then(
        TextDelta("The hall is quiet."),
        TextDelta("\n\n(oo"),
        TextDelta("c, for the host: "),
        TextDelta(f"{SECRET}: confirm the spell list.)"),
    )
    last = act_and_wait(app, local, cid)
    host = storage.seats.owner_seat(cid)
    texts = [(e.payload["text"], e.audience) for e in storage.story.list(cid) if e.kind == "dm_text"]
    assert texts == [
        ("The hall is quiet.", None),
        (f"(ooc, for the host: {SECRET}: confirm the spell list.)", {"seats": [host.id]}),
    ]

    hosts = local.get(f"/api/campaigns/{cid}/story").text
    assert SECRET in hosts and "The hall is quiet." in hosts
    assert SECRET in "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, None)))

    for name in ("Ana", "Bo", "Cy"):
        _, client, cookie = table[name]
        story_text = client.get(f"/api/campaigns/{cid}/story").text
        assert "The hall is quiet." in story_text, name
        assert SECRET not in story_text and "(oo" not in story_text, name
        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert "The hall is quiet." in frames, name
        assert SECRET not in frames and "(oo" not in frames, name

    for name in ("Ana", "Bo"):
        _, client, _ = table[name]
        assert client.post(f"/api/campaigns/{cid}/ask", json={"question": "What now?"}).status_code == 200
        assert "The hall is quiet." in dm.side_prompts[-1], name
        assert SECRET not in dm.side_prompts[-1] and "(oo" not in dm.side_prompts[-1], name
    assert local.post(f"/api/campaigns/{cid}/ask", json={"question": "What now?"}).status_code == 200
    assert SECRET in dm.side_prompts[-1]


# ----- claim and release answer a seat's sheet (review of the walkthrough fixes) -----


def test_claim_and_release_answer_the_sheet_a_seat_may_read(storage, table):
    """A player claims and releases a free PC: the answers hold what `GET …/characters` holds, never its DM notes."""
    cid = table["campaign"]
    hob = storage.characters.create(cid, "Hob")
    storage.characters.save(replace(hob, sheet=replace(hob.sheet, notes_md=f"{SECRET}: a doppelganger.")))
    _, bo, _ = table["Bo"]
    listed = next(c for c in bo.get(f"/api/campaigns/{cid}/characters").json() if c["id"] == hob.id)

    claimed = bo.post(f"/api/campaigns/{cid}/characters/{hob.id}/claim", json={})
    assert claimed.status_code == 200 and SECRET not in claimed.text
    assert claimed.json() == listed
    released = bo.post(f"/api/campaigns/{cid}/characters/{hob.id}/release", json={})
    assert released.status_code == 200 and SECRET not in released.text
    assert released.json() == listed


# ----- a private act is its seat's and the DM's (plan 7 Task 17) -----


def test_a_private_act_reaches_no_other_seat(app, local, dm, storage, table):
    """Ana acts privately with a secret while Bo's act is open: Bo and Cy never get it, not through the pending acts,
    the story, the stream or its replay. Ana does, and the DM does."""
    from delve.web.routes.play import table_of

    cid = table["campaign"]
    ana_seat, ana, ana_token = table["Ana"]
    bo_seat, bo, _ = table["Bo"]
    table_of(app).present = lambda campaign_id: {ana_seat.id, bo_seat.id}
    dm.then(TextDelta("The hall is quiet."))
    acted = ana.post(f"/api/campaigns/{cid}/act", json={"text": f"{SECRET}: I pocket the gem.", "private": True})
    assert acted.status_code == 202 and acted.json()["beat"]["status"] == "open"
    assert SECRET not in acted.text, "the beat never carries the texts"
    assert SECRET in ana.get(f"/api/campaigns/{cid}/beat/pending").text
    for name in ("Bo", "Cy"):
        _, client, _ = table[name]
        pending = client.get(f"/api/campaigns/{cid}/beat/pending")
        assert pending.status_code == 200 and SECRET not in pending.text, name
    _, cy, _ = table["Cy"]
    assert cy.get(f"/api/campaigns/{cid}/beat/pending").json() == {"pending": []}

    assert bo.post(f"/api/campaigns/{cid}/act", json={"text": "I keep watch."}).status_code == 202
    beat = storage.beats.current(cid)
    if beat is not None and beat.status == "open":
        assert local.post(f"/api/campaigns/{cid}/go", json={}).status_code in (202, 409)
    deadline = time.monotonic() + 5
    while storage.beats.current(cid) is not None:
        assert time.monotonic() < deadline, "the beat is still open or running"
        time.sleep(0.02)
    assert SECRET in dm.sent[-1], "the DM gets it"
    last = app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)

    assert sees_the_tell(app, cid, ana, ana_token, last) == (True, True)
    assert sees_the_tell(app, cid, local, None, last) == (False, False), "not even the host"
    for name in ("Bo", "Cy"):
        _, client, cookie = table[name]
        assert sees_the_tell(app, cid, client, cookie, last) == (False, False), name
        assert "I keep watch." in client.get(f"/api/campaigns/{cid}/story").text, name


# ----- an NPC's line is everyone's, and only its line (portraits plan Task 7) -----


def test_an_npcs_line_reaches_every_seat_without_its_notes(app, local, dm, storage, table):
    """Grik, whose story holds the secret, says a line through the real `say` result: every seat, the observer too,
    reads the line with Grik's name and portrait, in the story and the replay, and none reads the secret."""
    from delve.dm.tools.say import said_line

    cid = table["campaign"]
    grik = storage.characters.get(table["grik"])
    portrait = TraitsPortrait("a wiry goblin, one ear torn", "grik-1")
    grik = storage.characters.save(replace(grik, sheet=replace(grik.sheet, portrait=portrait)))
    said = {"said": said_line(grik, "Shiny things, yes?", "sneer")}
    dm.then(
        TextDelta("A goblin grins."),
        ToolCall("s1", "say", {"npc": "Grik", "text": "Shiny things, yes?", "mood": "sneer"}),
        ToolResult("s1", True, json.dumps(said)),
    )
    last = act_and_wait(app, local, cid)
    line = {
        "speaker": {"id": grik.id, "name": "Grik", "portrait": portrait.to_dict()},
        "mood": "sneer",
        "text": "Shiny things, yes?",
    }
    for name, client, cookie in [("Host", local, None)] + [(n, table[n][1], table[n][2]) for n in ("Ana", "Bo", "Cy")]:
        entries = client.get(f"/api/campaigns/{cid}/story").json()["entries"]
        assert [e["payload"] for e in entries if e["kind"] == "say"] == [line], name
        assert SECRET not in json.dumps(entries), name
        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert "Shiny things, yes?" in frames and SECRET not in frames, name


# ----- the tool count is the host's and the co-hosts' (plan 7 Task 18) -----


def test_the_tool_count_reaches_the_host_and_co_hosts_only(app, local, dm, storage, table):
    """The DM calls tools: the host's stream and a co-host's carry `beat_tools` with the count; a player's and the
    observer's carry neither the event nor a `tool_count`, in the `beat` events or `play/state`."""
    cid = table["campaign"]
    token = new_seat_token()
    dee = storage.seats.create(cid, "Dee", "en", "cohost", token_hash=token_hash(token))
    dm.then(
        ToolCall("r1", "roll", {"notation": "1d20", "purpose": "listen"}),
        ToolResult("r1", True, json.dumps({"total": 12})),
        ToolCall("s1", "dm_secrets", {}),
        ToolResult("s1", True, json.dumps({"secrets": [SECRET]})),
        TextDelta("The hall is quiet."),
    )
    last = act_and_wait(app, local, cid)

    for cookie in (None, token):
        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert "event: beat_tools" in frames and '"tool_count": 2' in frames, cookie
        assert SECRET not in frames
    assert dee.role == "cohost"
    for name in ("Ana", "Bo", "Cy"):
        _, client, cookie = table[name]
        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert "event: beat" in frames, name
        assert "beat_tools" not in frames and "tool_count" not in frames, name
        assert "tool_count" not in client.get(f"/api/campaigns/{cid}/play/state").text, name


# ----- pregens reach no seat before they are characters (faithful modules Task 19) -----


def test_pregens_reach_only_the_host_before_they_are_characters(app, local, dm, storage, table):
    """The module offers a pregen to the players and keeps one back, planted. The host's picker lists the first and
    never the second; a player and the observer read neither, through the route, the story, the stream or its replay,
    even when the DM reads them with `module_pregens`."""
    cid = table["campaign"]
    mid = storage.campaigns.get(cid).module_id
    ned = {"id": "ned", "name": "Ned Shakeshaft", "race": "Human", "class": "Thief", "level": 3}
    spy = {"id": "spy", "name": "The Spy", "audience": "gm", "background": f"{SECRET}: paid by the lizard men."}
    for record in (ned, spy):
        assert local.put(f"/api/modules/{mid}/entities/pregens/{record['id']}", json=record).status_code == 200
    later = storage.revisions.snapshot(mid)
    storage.campaigns.set_revision(cid, later.number)  # the host upgrades to the revision with the pregens

    hosts = local.get(f"/api/campaigns/{cid}/pregens")
    assert hosts.status_code == 200 and SECRET not in hosts.text
    assert [p["name"] for p in hosts.json()["pregens"]] == ["Ned Shakeshaft"]

    pregens = {"pregens": [{"id": "spy", "name": "The Spy", "audience": "gm", "sheet": {"background": SECRET}}]}
    dm.then(ToolCall("p1", "module_pregens", {}), ToolResult("p1", True, json.dumps(pregens)))
    last = act_and_wait(app, local, cid)
    assert SECRET in local.get(f"/api/campaigns/{cid}/dm/log").text, "the DM read it"
    assert not [e for e in storage.story.list(cid) if e.kind == "tool"], "a DM-only tool makes no row"

    for name in ("Ana", "Bo", "Cy"):
        _, client, cookie = table[name]
        refused = client.get(f"/api/campaigns/{cid}/pregens")
        assert refused.status_code == 403 and "Ned" not in refused.text and SECRET not in refused.text, name
        story_text = client.get(f"/api/campaigns/{cid}/story").text
        assert SECRET not in story_text and "The Spy" not in story_text, name
        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert SECRET not in frames and "The Spy" not in frames and "module_pregens" not in frames, name


# ----- the play screen's Setting tab (settings plan Task 8) -----


def test_the_setting_tab_never_gives_a_seat_dm_only_content(local, storage, table):
    """A DM-only page, a DM-only section of an ordinary page, a DM-only fact of the install and a DM-only proposal of
    the table's campaign, each holding the secret: no seat reads it through `…/setting/*`, a search for the secret's
    own word or for a word only in the DM-only section included. Not the owner's own seat either (decision 11)."""
    from delve.domain.setting_content import Proposal, SettingAddition, SettingFact

    cid = table["campaign"]
    pages = storage.setting_pages
    pages.put(SettingAddition("greyhawk", "Hideout", kind="place", text=f"{SECRET}: the cult's lair.", dm_only=True))
    pages.put(SettingAddition("greyhawk", "Saltmarsh", kind="place", text=f"A town.\n\n::: dm\n{SECRET} plover\n:::"))
    storage.setting_facts.add(SettingFact(0, "greyhawk", f"{SECRET}: Iuz is dead.", dm_only=True))
    storage.proposals.add(Proposal(0, "greyhawk", cid, "fact", text=f"{SECRET}: Vecna wakes.", dm_only=True))
    storage.proposals.add(Proposal(0, "greyhawk", cid, "page", title="Lair", text=SECRET, dm_only=True))
    storage.proposals.add(Proposal(0, "greyhawk", cid, "edit", title="Saltmarsh", text=f"{SECRET} gull", dm_only=True))

    base = f"/api/campaigns/{cid}/setting"
    paths = [
        base,
        f"{base}/facts",
        f"{base}/pages/Saltmarsh",
        f"{base}/pages/Hideout",
        f"{base}/pages/Lair",
        *(f"{base}/search?q={q}" for q in (SECRET, "XYZZY", "plover", "gull", "cult", "Saltmarsh", "town")),
        *(f"{base}/kinds/{kind}" for kind in ("place", "character")),
        *(f"{base}/kinds/place?q={q}" for q in ("Hideout", "Salt")),
    ]
    clients = [("Ana", table["Ana"][1]), ("Bo", table["Bo"][1]), ("Cy", table["Cy"][1]), ("owner", local)]
    for name, client in clients:
        for path in paths:
            response = client.get(path)
            assert response.status_code in (200, 404), (name, path, response.text)
            body = response.json()
            body.pop("query", None)  # a search answers its query back
            assert SECRET not in json.dumps(body) and "plover" not in json.dumps(body), (name, path)
        assert client.get(f"{base}/pages/Hideout").status_code == 404, name
        assert client.get(f"{base}/pages/Lair").status_code == 404, name
        assert client.get(f"{base}/pages/Saltmarsh").json()["text"] == "A town.", name
        assert client.get(f"{base}/search?q={SECRET}").json()["results"] == [], name
    assert SECRET in local.get("/api/settings/greyhawk/pages/Hideout").text, "the organisers' area has it"


@pytest.mark.parametrize("mode", ["append", "replace"])
def test_an_open_edit_of_a_dm_only_page_makes_a_seat_no_page(local, storage, table, mode):
    """A DM-only page of the install, a DM-only override and a DM-only proposed page, each holding the secret, and an
    open edit of each (stored as one that isn't DM-only): no seat reads the page, or more than the shipped one."""
    from delve.domain.setting_content import Proposal, SettingAddition

    cid = table["campaign"]
    pages = storage.setting_pages
    pages.put(SettingAddition("greyhawk", "Hideout", kind="place", text=f"{SECRET}: the cult's lair.", dm_only=True))
    pages.put(SettingAddition("greyhawk", "Hardby", text=f"{SECRET}: the Despotrix.", dm_only=True))
    storage.proposals.add(Proposal(0, "greyhawk", cid, "page", title="Lair", text=SECRET, dm_only=True))
    for title in ("Hideout", "Hardby", "Lair"):
        storage.proposals.add(Proposal(0, "greyhawk", cid, "edit", title=title, text="gull", mode=mode))

    base = f"/api/campaigns/{cid}/setting"
    clients = [("Ana", table["Ana"][1]), ("Bo", table["Bo"][1]), ("Cy", table["Cy"][1]), ("owner", local)]
    for name, client in clients:
        for title in ("Hideout", "Lair"):
            assert client.get(f"{base}/pages/{title}").status_code == 404, (name, title)
        hardby = client.get(f"{base}/pages/Hardby")  # the shipped page as shipped, where the reference has one
        assert hardby.status_code in (200, 404) and SECRET not in hardby.text and "gull" not in hardby.text, name
        for path in (*(f"{base}/search?q={q}" for q in ("gull", "Hideout", "Lair")), f"{base}/kinds/place"):
            assert SECRET not in client.get(path).text, (name, path)
    assert SECRET in local.get("/api/settings/greyhawk/pages/Hideout").text, "the organisers' area has it"


# ----- the setting's world maps on the Setting tab (settings plan Task 9) -----


def test_a_setting_maps_hidden_features_reach_no_seat(local, storage, table):
    """A ready setting map with a hidden feature named `SECRET-XYZZY`, and an ordinary one whose DM notes and `hidden`
    tag hold it: no seat's list or view of the setting's maps holds it, the owner's own seat neither."""
    from delve.domain.world import WorldMapSource
    from delve.maps.geo.geojson import to_geojson
    from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid

    def place(id_, name, **kw):
        return GeoFeature(id_, "places", "town", name, {"type": "Point", "coordinates": [15.0, 15.0]}, **kw)

    marked = GeoMap(
        Frame(100.0, 100.0),
        Grid("square", 10.0, 10, 10),
        "p" * 100,
        (
            place("lair", SECRET, hidden=True, dm_notes=SECRET, description=SECRET),
            place("ashford", "Ashford", dm_notes=f"{SECRET}: the reeve is a doppelganger."),
        ),
    )
    storage.setting_maps.put("greyhawk", WorldMapSource("march", "The March", "", geo=to_geojson(marked)))
    cid = table["campaign"]
    assert storage.campaigns.get(cid).setting == "greyhawk"
    base = f"/api/campaigns/{cid}/setting/maps"
    clients = [("Ana", table["Ana"][1]), ("Bo", table["Bo"][1]), ("Cy", table["Cy"][1]), ("owner", local)]
    for name, client in clients:
        assert client.get(base).json() == [{"name": "march", "title": "The March"}], name
        view = client.get(f"{base}/march/view")
        assert view.status_code == 200, (name, view.text)
        assert SECRET not in view.text, name
        assert [f["name"] for f in view.json()["features"]] == ["Ashford"], name
    assert SECRET in local.get("/api/settings/greyhawk/world-maps/march").text, "the organisers' map has it"


# ----- a novel reaches no seat, an organiser seat included (novelization Task 5) -----


def test_a_novel_reaches_no_seat(app, local, dm, storage, table):
    """The owner novelizes the campaign, and the writer plants the secret in the title, the outline and every chapter;
    a second novel is planted in storage. No seat reads either: not Ana, Bo or Cy, and not Dee, a co-host with the
    install's organiser rights, through any novel route, the story, the conversions or the event stream and its
    replay. Dee does get the job's `conversion` events: they name the job and its step, never the novel's text."""
    from delve.domain.novels import Chapter, Novel

    cid = table["campaign"]
    token = new_seat_token()
    storage.seats.create(cid, "Dee", "en", "cohost", organiser=True, token_hash=token_hash(token))
    dee = TestClient(app, base_url=BASE_URL)
    dee.__enter__()
    dee.cookies.set(SEAT_COOKIE, token)

    def writer(prompt: str) -> str:
        if prompt.startswith("You are a novelist. You turn"):
            chapters = [{"title": f"{SECRET} {n}", "summary": f"{SECRET} summary {n}"} for n in (1, 2, 3)]
            return json.dumps({"title": f"{SECRET} title", "chapters": chapters})
        return f"{SECRET}: the abbot is the ritualist."

    dm._side_handler = writer
    started = local.post("/api/novels", json={"source": "campaign", "id": cid, "length": "short-story"})
    assert started.status_code == 202, started.text
    deadline = time.monotonic() + 10
    while (novel := local.get(f"/api/novels/{started.json()['id']}").json())["status"] == "writing":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert novel["status"] == "done" and SECRET in novel["chapters"][2]["text"], "the owner reads it"
    planted = storage.novels.create(
        Novel("", f"{SECRET} planted", campaign_id=cid, chapters=[Chapter("One", SECRET, SECRET)], status="done")
    )
    last = app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)

    seated = [(name, table[name][1], table[name][2]) for name in ("Ana", "Bo", "Cy")] + [("Dee", dee, token)]
    try:
        for name, client, cookie in seated:
            for novel_id in (novel["id"], planted.id):
                for method, path, body in [
                    ("GET", f"/api/novels?campaign_id={cid}", None),
                    ("GET", f"/api/novels/{novel_id}", None),
                    ("PATCH", f"/api/novels/{novel_id}", {"title": "Mine"}),
                    ("DELETE", f"/api/novels/{novel_id}", {}),
                    ("POST", f"/api/novels/{novel_id}/continue", {}),
                    ("POST", f"/api/novels/{novel_id}/cancel", {}),
                    ("POST", "/api/novels", {"source": "campaign", "id": cid}),
                ]:
                    response = client.request(method, path, json=body)
                    assert response.status_code == 403, (name, method, path)
                    assert SECRET not in response.text, (name, path)
            assert SECRET not in client.get(f"/api/campaigns/{cid}/story").text, name
            jobs = client.get("/api/conversions")
            assert jobs.status_code == (200 if name == "Dee" else 403), name
            assert SECRET not in jobs.text, name
            frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
            assert SECRET not in frames, name
            assert ("event: conversion" in frames) == (name == "Dee"), name
    finally:
        dee.__exit__(None, None, None)
    assert storage.novels.get(planted.id) == planted, "no seat changed it"


# ----- a banner's prompt and error reach no seat (looks and banners plan Task 3) -----


def test_a_waiting_or_failed_banners_prompt_and_error_reach_no_seat(app, local, storage, registries, table):
    """The owner paints the banner again with the secret as its hint, and the painter fails with the secret; a
    waiting banner's prompt holds it too. No seat reads either, through the banner's routes, the pictures route,
    `play/state`, the story or the event stream and its replay, not the owner's own seat either; the campaign's page
    and the module's banners are the organisers', and the campaign's page shows the error, never the prompt."""
    from delve.domain import new_id
    from delve.domain.backends import ModelInfo, ProviderCapabilities
    from delve.domain.settings import Job
    from delve.domain.world import CampaignImage
    from tests.web.test_campaigns_api import settled

    class Broken:
        async def generate(self, req):
            raise RuntimeError(f"{SECRET}: the model is down")

    cid = table["campaign"]
    [shown] = storage.campaign_images.list(cid, kind="banner")
    assert settled(storage, shown.id).status == "done"
    broken = ProviderCapabilities(
        "broken",
        "A free painter that always fails",
        frozenset({Job.IMAGE_SCENE}),
        models=("local",),
        model_info={"local": ModelInfo("Local", "local", None, paid=False)},
    )
    registries.images.register(broken, Broken)
    storage.settings.save({"choices": {"image.scene": {"provider": "broken", "model": "local", "effort": None}}})
    asked = local.post(f"/api/campaigns/{cid}/banner", json={"hint": SECRET})
    assert asked.status_code == 202 and SECRET not in asked.text
    failed = settled(storage, asked.json()["image_id"])
    assert failed.status == "failed" and SECRET in failed.error and SECRET in failed.prompt
    waiting = storage.campaign_images.put(
        CampaignImage(new_id("img"), cid, "banner", status="waiting", prompt=f"{SECRET}: the cult's lair.")
    )
    last = app.state.events.publish("beat", {"campaign_id": cid}, scope="table", campaign_id=cid)

    mid = storage.campaigns.get(cid).module_id
    seated = [(n, table[n][1], table[n][2]) for n in ("Ana", "Bo", "Cy")] + [("owner", local, None)]
    for name, client, cookie in seated:
        state = client.get(f"/api/campaigns/{cid}/play/state")
        assert state.status_code == 200 and state.json()["banner"] == shown.id, name
        assert SECRET not in state.text, name
        banner = client.get(f"/api/campaigns/{cid}/banner")
        assert banner.status_code == 200 and SECRET.encode() not in banner.content, name
        for row in (failed, waiting):
            picture = client.get(f"/api/campaigns/{cid}/pictures/{row.id}")
            assert picture.status_code == 404 and SECRET not in picture.text, (name, row.status)
        assert SECRET not in client.get(f"/api/campaigns/{cid}/story").text, name
        frames = "\n".join(asyncio.run(read_until(app, "/api/events?since=0", last, cookie)))
        assert SECRET not in frames, name
        if cookie is not None:
            for path in (f"/api/campaigns/{cid}", f"/api/modules/{mid}/banners", f"/api/modules/{mid}/banners/{cid}"):
                refused = client.get(path)
                assert refused.status_code == 403 and SECRET not in refused.text, (name, path)
                assert client.post(f"/api/campaigns/{cid}/banner", json={}).status_code == 403, name

    page = local.get(f"/api/campaigns/{cid}").json()
    assert page["banner"]["pending"] == {"status": "waiting", "error": None}
    assert SECRET not in json.dumps(page), "the organisers' page never shows a prompt"
    storage.campaign_images.delete(waiting.id)
    page = local.get(f"/api/campaigns/{cid}").json()
    assert page["banner"]["pending"]["status"] == "failed", "the failure, for the organisers alone"
    assert SECRET in page["banner"]["pending"]["error"] and failed.prompt not in json.dumps(page)
    assert SECRET not in local.get(f"/api/modules/{mid}/banners").text


# ----- a tool row's call and reply are the host's (backlog Features 19, owner 2026-10-22: host only) -----


def test_a_tool_rows_call_and_reply_reach_the_host_alone(app, local, dm, storage, table):
    """The DM rolls, then runs a batch: the host opens each row and reads its call and reply, from the DM log; a
    co-host, who sees the rows, the players and the observer get 403, so a reply's secrets reach no other seat."""
    cid = table["campaign"]
    steps = [{"tool": "roll", "args": {"notation": "1d6"}}]
    reply = {
        "ran": 1,
        "requested": 1,
        "stopped_early": False,
        "results": [{"step": 0, "tool": "roll", "result": {"total": 4}}],
    }
    dm.then(
        ToolCall("r1", "roll", {"notation": "1d20", "purpose": "listen"}),
        ToolResult("r1", True, json.dumps({"total": 12})),
        ToolCall("b1", "batch", {"steps": steps}),
        ToolResult("b1", True, json.dumps(reply)),
    )
    act_and_wait(app, local, cid)
    roll, batch = [e for e in storage.story.list(cid) if e.kind == "tool"]

    answered = local.get(f"/api/campaigns/{cid}/story/{roll.id}/tool")
    assert answered.status_code == 200, answered.json()
    assert answered.json() == {
        "name": "roll",
        "args": {"notation": "1d20", "purpose": "listen"},
        "ok": True,
        "result": {"total": 12},
    }
    assert local.get(f"/api/campaigns/{cid}/story/{batch.id}/tool").json() == {
        "name": "batch",
        "args": {"steps": steps},
        "ok": True,
        "result": reply,
    }

    cohost = storage.seats.create(cid, "Di", "en", "cohost", token_hash=token_hash(token := new_seat_token()))
    with TestClient(app, base_url=BASE_URL) as di:
        di.cookies.set(SEAT_COOKIE, token)
        assert di.get(f"/api/campaigns/{cid}/story/{roll.id}/tool").status_code == 403
    assert cohost.role == "cohost"
    for name in ("Ana", "Bo", "Cy"):
        _, client, _ = table[name]
        assert client.get(f"/api/campaigns/{cid}/story/{roll.id}/tool").status_code == 403, name


def test_a_tool_row_that_isnt_one_answers_404(local, storage, table):
    cid = table["campaign"]
    told = storage.story.append(cid, None, "dm_text", {"text": "Hello."}, None)
    assert local.get(f"/api/campaigns/{cid}/story/{told.id}/tool").status_code == 404
    assert local.get(f"/api/campaigns/{cid}/story/sty_nope/tool").status_code == 404


# ----- the DM's history is the host's (review of carrying the party on) -----


def test_the_dms_history_reaches_the_host_alone(app, local, storage, table):
    """A carried party's history holds the DM's text with the secret: the host reads it; a co-host, the players and
    the observer read the status and the table's text alone, and can neither replace nor rewrite it."""
    cid = table["campaign"]
    storage.histories.put(
        History(cid, dm_md=f"## The party\n\n{SECRET}", table_md="## The party\n\nTold.", status="done")
    )
    path = f"/api/campaigns/{cid}/history"
    assert SECRET in local.get(path).json()["dm_md"]

    storage.seats.create(cid, "Di", "en", "cohost", token_hash=token_hash(token := new_seat_token()))
    with TestClient(app, base_url=BASE_URL) as di:
        di.cookies.set(SEAT_COOKIE, token)
        clients = {"Di": di, **{name: table[name][1] for name in ("Ana", "Bo", "Cy")}}
        for name, client in clients.items():
            read = client.get(path)
            assert read.status_code == 200, name
            assert read.json() == {"status": "done", "table_md": "## The party\n\nTold."}, name
            assert SECRET not in read.text, name
            assert client.put(path, json={"dm_md": "", "table_md": ""}).status_code == 403, name
            assert client.post(f"{path}/write", json={"overwrite": True}).status_code == 403, name
    assert SECRET in storage.histories.get(cid).dm_md


# ----- the Rulesets area (rulesets plan Task 5, Review Focus 1 and 4) -----


def test_the_rulesets_area_gives_a_seat_no_monster_and_no_dm_notes(app, local, storage, table):
    """The table's campaign chose an item, a class and a race rule whose DM notes hold the secret; another campaign's
    rule holds it whole. No seat reads the secret or meets a monster through `/api/rulesets/*`, whatever
    `?campaign=` it passes; the owner, picking the campaign, reads the notes."""
    from tests.web.test_rulesets_api import monster_id, with_the_book

    with_the_book(app.state.registries)
    cid = table["campaign"]
    body = f"## Rules\n\nPlain words.\n\n## DM Notes\n\n{SECRET}: a minotaur's.\n"
    chosen = [
        storage.house_rules.create(title=f"Homebrew {kind}", body_md=body, kind=kind, phases=["always"])
        for kind in ("item", "class", "race")
    ]
    storage.campaign_house_rules.put(cid, [], [rule.id for rule in chosen])
    elsewhere = storage.house_rules.create(title="Elsewhere", body_md=SECRET, kind="item", phases=["items"])
    other = storage.campaigns.create(
        "Other", storage.campaigns.get(cid).module_id, 1, ruleset="osric", setting="greyhawk"
    )
    storage.campaign_house_rules.put(other.id, [], [elsewhere.id])
    base = "/api/rulesets/osric"
    minotaur = {"id": monster_id(local)}
    paths = [
        "/api/rulesets",
        base,
        *(f"{base}/{section}" for section in ("spells", "items", "classes", "races", "abilities", "turning")),
        *(f"{base}/{s}/hr-{rule.id}" for s, rule in zip(("items", "classes", "races"), chosen, strict=True)),
        f"{base}/items/hr-{elsewhere.id}",
        *(f"{base}/search?q={q}" for q in ("Homebrew", "minotaur", "Elsewhere", SECRET)),
    ]
    unknown = table["Ana"][1].get(f"{base}/spells/999999").content
    for name in ("Ana", "Bo", "Cy"):
        _, client, _ = table[name]
        for path in paths:
            for asked in (path, f"{path}{'&' if '?' in path else '?'}campaign={other.id}"):
                response = client.get(asked)
                assert response.status_code in (200, 404), (name, asked, response.text)
                assert SECRET not in response.text and "monsters" not in response.text, (name, asked)
        for path in (f"{base}/monsters", f"{base}/monsters/{minotaur['id']}", f"{base}/items/hr-{elsewhere.id}"):
            assert client.get(path).content == unknown, (name, path)
        assert client.get(f"{base}/items/hr-{chosen[0].id}").json()["text"] == "## Rules\n\nPlain words.\n", name
    assert SECRET in local.get(f"{base}/items/hr-{chosen[0].id}?campaign={cid}").json()["text"]


# DM notes that a line-by-line cut would miss: in a blockquote, in a list item, underlined straight after a heading,
# after a backtick line that opens no fence, and as a link's text.
HIDDEN_NOTES = (
    "## About\n\nok\n\n> ## DM Notes\n>\n> SECRET-XYZZY\n",
    "## About\n\nok\n\n- ## DM Notes\n\n  SECRET-XYZZY\n",
    "## About\nDM Notes\n--------\n\nSECRET-XYZZY\n",
    "## About\n\n```a`b\n\n## DM Notes\n\nSECRET-XYZZY\n",
    "## [DM Notes](#x)\n\nSECRET-XYZZY\n",
)


def test_the_rulesets_area_cuts_every_dm_notes_heading(app, local, storage, table):
    """Each body's DM notes hold the secret where CommonMark still renders a heading. No seat's entry, list or search
    holds it; the owner reads every one whole."""
    from tests.web.test_rulesets_api import with_the_book

    with_the_book(app.state.registries)
    cid = table["campaign"]
    assert all(SECRET in body for body in HIDDEN_NOTES)
    rules = [
        storage.house_rules.create(title=f"Hidden {n}", body_md=body, kind="item", phases=["items"])
        for n, body in enumerate(HIDDEN_NOTES)
    ]
    storage.campaign_house_rules.put(cid, [], [rule.id for rule in rules])
    base = "/api/rulesets/osric"
    for name in ("Ana", "Bo", "Cy"):
        _, client, _ = table[name]
        for rule in rules:
            response = client.get(f"{base}/items/hr-{rule.id}")
            assert response.status_code == 200, (name, rule.title)
            assert SECRET not in response.text, (name, rule.title)
        for path in (f"{base}/items?q=Hidden", f"{base}/search?q=Hidden", f"{base}/search?q={SECRET}"):
            assert SECRET not in client.get(path).text, (name, path)
    for rule in rules:
        assert local.get(f"{base}/items/hr-{rule.id}?campaign={cid}").json()["text"] == rule.body_md


# ----- the Claude account's usage is the host's -----


def test_the_accounts_usage_reaches_the_host_alone(app, local, storage, table):
    """The subscription is the host's: the host reads its windows; a co-host, the players and the observer get 403."""
    cid = table["campaign"]
    path = f"/api/campaigns/{cid}/play/usage"
    assert local.get(path).json() == {"usage": None}
    account.note(
        {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed",
                "unifiedWindows": {"five_hour": {"utilization": 0.82, "resetsAt": 1792834200}},
            },
        }
    )
    windows = local.get(path).json()["usage"]["windows"]
    assert windows == [{"name": "five_hour", "utilization": 0.82, "resets_at": "2026-10-24T09:30:00Z"}]

    storage.seats.create(cid, "Di", "en", "cohost", token_hash=token_hash(token := new_seat_token()))
    with TestClient(app, base_url=BASE_URL) as di:
        di.cookies.set(SEAT_COOKIE, token)
        assert di.get(path).status_code == 403
    for name in ("Ana", "Bo", "Cy"):
        _, client, _ = table[name]
        assert client.get(path).status_code == 403, name


def test_the_talks_own_pages_are_each_seats_own(app, storage, table):
    """DEL-219: `?kind=talk` pages the talk alone, past a story page of acts and narration, as the seat may see it:
    a talk line meant for other seats never comes."""
    cid = table["campaign"]
    seats = {s.name: s for s in storage.seats.list(cid)}
    storage.story.append(cid, None, "talk", {"seat_id": seats["Bo"].id, "name": "Bo", "text": "Mind the stairs."})
    storage.story.append(cid, None, "talk", {"seat_id": seats["Cy"].id, "name": "Cy", "text": "Only Bo hears."},
                         {"seats": [seats["Bo"].id]})
    for n in range(60):
        storage.story.append(cid, None, "dm_text", {"text": f"The hall, hour {n}."})
    storage.story.append(cid, None, "talk", {"seat_id": seats["Bo"].id, "name": "Bo", "text": "Torches out."})
    path = f"/api/campaigns/{cid}/story"
    _, ana, _ = table["Ana"]

    newest = ana.get(path).json()["entries"]
    assert [e["payload"]["text"] for e in newest if e["kind"] == "talk"] == ["Torches out."], "the story page has one"
    talk = ana.get(path, params={"kind": "talk"}).json()
    assert [e["payload"]["text"] for e in talk["entries"]] == ["Mind the stairs.", "Torches out."]
    assert talk["has_more"] is False and {e["kind"] for e in talk["entries"]} == {"talk"}

    first = ana.get(path, params={"kind": "talk", "limit": 1}).json()
    assert [e["payload"]["text"] for e in first["entries"]] == ["Torches out."] and first["has_more"] is True
    earlier = ana.get(path, params={"kind": "talk", "limit": 1, "before": first["entries"][0]["seq"]}).json()
    assert [e["payload"]["text"] for e in earlier["entries"]] == ["Mind the stairs."] and earlier["has_more"] is False

    _, bo, _ = table["Bo"]
    assert "Only Bo hears." in [e["payload"]["text"] for e in bo.get(path, params={"kind": "talk"}).json()["entries"]]
    assert ana.get(path, params={"kind": "sneaky"}).status_code == 422


def test_an_items_dm_notes_reach_no_seat(app, local, storage, dm, table):
    """DEL-181: a player read "Glass phial … (DM: potion of neutralise poison)" on another's sheet. An item's DM note,
    and "(DM: …)" the DM wrote into its notes, are on the organiser's campaign page only: never a seat's sheet, the
    play state, an event, or the prompt of Ask the DM."""
    from delve.domain.characters import Item

    cid, garrek = table["campaign"], table["garrek"]
    character = storage.characters.get(garrek)
    phial = Item("Glass phial", notes=f"stoppered, cloudy (DM: {SECRET} neutralise poison, 2 doses)")
    storage.characters.save(replace(character, state=replace(character.state, inventory=(phial,))))

    for name in ("Ana", "Bo", "Cy"):
        _, client, _ = table[name]
        for route in ("characters", "play/state"):
            answer = client.get(f"/api/campaigns/{cid}/{route}")
            assert answer.status_code == 200 and SECRET not in answer.text, (name, route)
        sheets = client.get(f"/api/campaigns/{cid}/characters").json()
        (mine,) = [c for c in sheets if c["id"] == garrek]
        (item,) = mine["state"]["inventory"]
        assert item["notes"] == "stoppered, cloudy" and "dm_notes" not in item

    _, ana, _ = table["Ana"]
    assert ana.post(f"/api/campaigns/{cid}/ask", json={"question": "What is the glass phial?"}).status_code == 200
    assert SECRET not in dm.side_prompts[-1]

    organiser = local.get(f"/api/campaigns/{cid}/dm/characters").json()
    (whole,) = [c for c in organiser if c["id"] == garrek]
    assert whole["state"]["inventory"][0]["dm_notes"] == f"{SECRET} neutralise poison, 2 doses"
