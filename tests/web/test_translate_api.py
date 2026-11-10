"""Translation through the API (plan 4 Task 7; spec §7.7): a Dutch act reaches the DM in English, and `GET …/story
?language=nl` reads back each entry's translation, for the entries the seat may see only: a planted `SECRET-XYZZY` in
a tell to Ana's character never reaches Bo, who reads Dutch too (Review Focus 1)."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.domain.backends import Registry
from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.web.auth import seat_principal
from delve.web.events import Viewer
from delve.web.routes.play import table_of
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.play.test_translate import translator
from tests.web.conftest import BASE_URL, make_registries, playing

SECRET = "SECRET-XYZZY"


@pytest.fixture
def dm():
    return FakeDM([], side_handler=translator)


@pytest.fixture
def registries(dm):
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    return registries


@pytest.fixture
def table(app, storage, dm):
    """The owner hosts in English; Ana (Dutch) plays Garrek, Bo (Dutch) plays Tira; all three are at the table. The
    DM tells Garrek a secret, then says the hall is dark."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")
    playing(storage, campaign.id)
    host = seats.owner_seat(storage, campaign.id)
    garrek = storage.characters.create(campaign.id, "Garrek")
    tira = storage.characters.create(campaign.id, "Tira")
    clients, people = [], {}
    for name in ("Ana", "Bo"):
        token = new_seat_token()
        seat = storage.seats.create(campaign.id, name, "nl", "player", token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        people[name] = (seat, client)
    seats.claim(storage, garrek.id, people["Ana"][0])
    seats.claim(storage, tira.id, people["Bo"][0])
    told = {"told": {"characters": [garrek.id], "text": f"{SECRET}: a voice says your name."}}
    dm._script = [
        [
            ToolCall("t1", "tell", {"characters": ["Garrek"], "text": "…"}),
            ToolResult("t1", True, json.dumps(told)),
            TextDelta("The hall is dark."),
        ]
    ]
    here = {host.id, people["Ana"][0].id, people["Bo"][0].id}
    table_of(app).present = lambda campaign_id: set(here)
    yield {"campaign": campaign.id, **people}
    for client in clients:
        client.__exit__(None, None, None)


def path(table, rest: str) -> str:
    return f"/api/campaigns/{table['campaign']}/{rest}"


def settled(client, table) -> list[dict]:
    """The story in Dutch once the beat is answered and every translation has ended."""
    deadline = time.monotonic() + 5
    while True:
        # The beat's state first: the story read after it holds every entry the beat told, each with its translation
        # under way. The story route runs in the threadpool, so read first it could catch an entry told an instant
        # before its translation was queued, and the beat closing just after.
        idle = client.get(path(table, "play/state")).json()["beat"] is None
        entries = client.get(path(table, "story?language=nl")).json()["entries"]
        busy = [e for e in entries if e.get("translation", {}).get("status") == "translating"]
        if idle and not busy and any(e["kind"] == "dm_text" for e in entries):
            return entries
        assert time.monotonic() < deadline, entries
        time.sleep(0.02)


def test_a_dutch_table_reads_the_story_in_dutch(local, dm, table):
    _, ana = table["Ana"]
    _, bo = table["Bo"]
    assert ana.post(path(table, "act"), json={"text": "Ik open de deur."}).status_code == 202
    assert bo.post(path(table, "pass"), json={}).status_code == 202

    entries = settled(ana, table)
    [sent] = dm.sent
    assert "Ana (playing Garrek):\n> I open the door." in sent and "Bo passes." in sent

    act = next(e for e in entries if e["kind"] == "player_act")
    assert act["payload"]["text"] == "I open the door." and act["payload"]["original"] == "Ik open de deur."
    assert act["translation"] == {"language": "nl", "text": "Ik open de deur.", "status": "done"}
    shown = {e["payload"]["text"]: e["translation"] for e in entries if e["kind"] == "dm_text"}
    assert shown["The hall is dark."] == {"language": "nl", "text": "NL: The hall is dark.", "status": "done"}
    assert shown[f"{SECRET}: a voice says your name."]["text"] == f"NL: {SECRET}: a voice says your name."

    # Bo reads Dutch too, but the tell is Ana's: neither it nor its translation reaches Bo, or the host.
    for client in (bo, local):
        page = client.get(path(table, "story?language=nl")).json()
        assert SECRET not in json.dumps(page)
    bo_entries = bo.get(path(table, "story?language=nl")).json()["entries"]
    assert any(e.get("translation", {}).get("text") == "NL: The hall is dark." for e in bo_entries)
    # Without a language, the story is the English alone.
    assert all("translation" not in e for e in ana.get(path(table, "story")).json()["entries"])


def test_a_dutch_seats_question_comes_back_in_dutch(app, storage, table):
    """Walkthrough T3: Ana asks the DM in Dutch through the route. The stored `nl` translation of the answer, and the
    answer's translation event Ana's browser gets, are Dutch; and the question is Ana's own words."""
    seat, ana = table["Ana"]
    answered = ana.post(path(table, "ask"), json={"question": "Wat is THAC0?"})
    assert answered.status_code == 200, answered.text
    assert answered.json() == {"answer": "THAC0 is what you need to hit AC 0."}

    deadline = time.monotonic() + 5
    while True:
        entries = {e["kind"]: e for e in ana.get(path(table, "story?language=nl")).json()["entries"]}
        if entries.get("answer", {}).get("translation", {}).get("status") == "done":
            break
        assert time.monotonic() < deadline, entries
        time.sleep(0.02)
    assert entries["ask"]["payload"]["text"] == "What is THAC0?"
    assert entries["ask"]["translation"] == {"language": "nl", "text": "Wat is THAC0?", "status": "done"}
    answer = entries["answer"]
    assert answer["translation"] == {"language": "nl", "text": "NL: THAC0 is what you need to hit AC 0.", "status": "done"}
    assert storage.translations.for_entries([answer["id"]], "nl")[answer["id"]].text == "NL: THAC0 is what you need to hit AC 0."

    bus = app.state.events
    viewer = Viewer.of(seat_principal(storage.seats.get(seat.id)))
    heard = [e.data for e in bus._buffer if e.type == "translation" and bus.may_see(viewer, e)]
    assert [e["text"] for e in heard if e["entry_id"] == answer["id"]][-1] == "NL: THAC0 is what you need to hit AC 0."
    # Bo reads Dutch too, but the question is Ana's alone.
    bo = Viewer.of(seat_principal(storage.seats.get(table["Bo"][0].id)))
    assert not [e for e in bus._buffer if e.data.get("entry_id") == answer["id"] and bus.may_see(bo, e)]
