"""Table talk and private questions through the API (plan 4 Task 6; spec §7.3): `POST …/talk` for any seat, observers
included; `POST …/ask/{answer_id}/share` for the asker only; and talk never reaches the DM."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.provider import TextDelta
from delve.domain.backends import Registry
from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, make_registries, playing

TALK_ONLY = "TALK-ONLY-PLUGH"


@pytest.fixture
def dm():
    return FakeDM([[TextDelta("The door creaks open.")]], side_handler=lambda prompt: "Yes, with a rope.")


@pytest.fixture
def registries(dm):
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    return registries


@pytest.fixture
def table(app, storage):
    """Ana plays Garrek, Bo plays Tira, Cy observes; each has their own browser on the LAN."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")
    playing(storage, campaign.id)
    seats.owner_seat(storage, campaign.id)
    garrek = storage.characters.create(campaign.id, "Garrek")
    tira = storage.characters.create(campaign.id, "Tira")
    clients, people = [], {}
    for name, role in (("Ana", "player"), ("Bo", "player"), ("Cy", "observer")):
        token = new_seat_token()
        seat = storage.seats.create(campaign.id, name, "en", role, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        people[name] = (seat, client)
    seats.claim(storage, garrek.id, people["Ana"][0])
    seats.claim(storage, tira.id, people["Bo"][0])
    yield {"campaign": campaign.id, **people}
    for client in clients:
        client.__exit__(None, None, None)


def path(table, rest: str) -> str:
    return f"/api/campaigns/{table['campaign']}/{rest}"


def story_kinds(client, table) -> list[str]:
    return [e["kind"] for e in client.get(path(table, "story")).json()["entries"]]


def test_an_observer_talks_to_the_whole_table(local, table):
    cy_seat, cy = table["Cy"]
    response = cy.post(path(table, "talk"), json={"text": "Shall we rest first?"})
    assert response.status_code == 201, response.json()
    entry = response.json()["entry"]
    assert entry["kind"] == "talk" and entry["audience"] is None and entry["beat_id"] is None
    assert entry["payload"] == {
        "seat_id": cy_seat.id,
        "name": "Cy",
        "text": "Shall we rest first?",
        "original": "Shall we rest first?",
        "language": "en",
    }
    for client in (local, table["Ana"][1], table["Bo"][1], cy):
        assert story_kinds(client, table) == ["talk"]


def test_talk_refusals(local, lan, table, storage):
    _, ana = table["Ana"]
    empty = ana.post(path(table, "talk"), json={"text": "  "})
    assert empty.status_code == 422 and empty.json() == {"error": "Say something."}
    assert lan.post(path(table, "talk"), json={"text": "Hi"}).status_code == 401
    other = storage.campaigns.create(
        "Thursday", storage.campaigns.get(table["campaign"]).module_id, 1, ruleset="osric", setting="greyhawk"
    )
    assert ana.post(f"/api/campaigns/{other.id}/talk", json={"text": "Hi"}).status_code == 403
    assert ana.post(path(table, "talk"), content="Hi", headers={"Content-Type": "text/plain"}).status_code == 415


def test_the_asker_shares_an_answer(local, table):
    _, ana = table["Ana"]
    _, bo = table["Bo"]
    assert ana.post(path(table, "ask"), json={"question": "Can Garrek climb the wall?"}).status_code == 200
    assert story_kinds(bo, table) == [] and story_kinds(local, table) == []
    asked, answer = ana.get(path(table, "story")).json()["entries"]

    for client in (bo, local, table["Cy"][1]):
        refused = client.post(path(table, f"ask/{answer['id']}/share"), json={})
        assert refused.status_code == 403 and refused.json() == {"error": "Only who asked can share the answer."}
    for missing in (asked["id"], "sty_nothing"):
        assert ana.post(path(table, f"ask/{missing}/share"), json={}).status_code == 404

    shared = ana.post(path(table, f"ask/{answer['id']}/share"), json={})
    assert shared.status_code == 201, shared.json()
    payload = shared.json()["entry"]["payload"]
    assert (payload["text"], payload["answer"], payload["shared"]) == (
        "Can Garrek climb the wall?",
        "Yes, with a rope.",
        answer["id"],
    )
    assert bo.get(path(table, "story")).json()["entries"][0]["payload"] == payload


def test_talk_never_reaches_the_dm(local, dm, table):
    _, bo = table["Bo"]
    assert bo.post(path(table, "talk"), json={"text": f"{TALK_ONLY}: the abbot did it."}).status_code == 201
    assert local.post(path(table, "act"), json={"text": "We open the door."}).status_code == 202
    deadline = time.monotonic() + 5
    while local.get(path(table, "play/state")).json()["beat"] is not None:
        assert time.monotonic() < deadline, "the beat is still running"
        time.sleep(0.02)

    assert len(dm.sent) == 1 and "We open the door." in dm.sent[0]
    assert TALK_ONLY not in json.dumps(dm.sent)
    assert "dm_text" in story_kinds(bo, table)
