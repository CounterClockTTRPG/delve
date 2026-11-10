"""Portraits and Connections end to end (portraits plan Task 10): through the API of `delve serve`, with the fake
`claude` and the real bridge and tool host.

An NPC of the campaign, with the planted secret in his DM notes, is drawn and speaks a line through `say` between two
narrations: the story holds the line as its own `say` entry, with his portrait and mood, and no seat's story holds the
secret. Then a fake Replicate token is saved in Connections: `/api/backends` lists Replicate at once, without a
restart, and the token is in no answer and no log. Nothing is painted, so Replicate is never called.

The real `claude` never runs.
"""

from __future__ import annotations

import json

import pytest

from delve.config import Config
from delve.domain.characters import Sheet
from delve.modules.dscn import Bundle
from delve.storage import open_storage
from tests.e2e.test_play_with_fake_claude import SECRET, Delve
from tests.fixtures import SAMPLES

TOKEN = "tok-SECRET-XYZZY"
ANSELM = "Prior Anselm"
LINE = "Thank the saint you have come. Something stirs below the chapel."
TURNS = [
    [
        {"text": "Prior Anselm meets you at the chapel door."},
        {"tool": "portrait", "args": {"of": ANSELM, "description": "an elderly human prior, bald, worried"}},
        {"tool": "say", "args": {"npc": ANSELM, "text": LINE, "mood": "afraid"}},
        {"text": "He turns and leads you inside."},
    ],
]


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path, turns=TURNS)
    yield server
    server.stop()


def test_an_npc_speaks_and_a_token_saved_without_a_restart(delve):
    http = delve.http
    crypt = Bundle.load(SAMPLES / "scenarios" / "crypt-of-saint-vellis").to_zip()
    module = http.post("/api/modules/import", content=crypt, headers={"Content-Type": "application/zip"})
    assert module.status_code == 201, module.text
    created = http.post("/api/campaigns", json={"name": "Vellis", "module_id": module.json()["id"]})
    assert created.status_code == 201, created.text
    campaign = created.json()["id"]
    play = f"/api/campaigns/{campaign}"
    # The NPC, made as the module's import would make him, with the secret in the DM's notes.
    storage = open_storage(Config(data_dir=delve.data_dir))
    try:
        storage.characters.create(
            campaign, ANSELM, kind="npc", sheet=Sheet(kind="npc", race="human", notes_md=f"{SECRET}: he hid the key.")
        )
    finally:
        storage.close()
    bodies: list[str] = []

    # A beat: narration, the NPC's line, narration.
    assert http.post(f"{play}/act", json={"text": "We knock at the chapel door."}).status_code == 202
    delve.settle(campaign)
    story = http.get(f"{play}/story", params={"limit": 200})
    bodies.append(story.text)
    entries = story.json()["entries"]
    spoken = [e["kind"] for e in entries if e["kind"] in ("dm_text", "say")]
    assert spoken == ["dm_text", "say", "dm_text"]
    [said] = [e for e in entries if e["kind"] == "say"]
    assert said["audience"] is None
    assert set(said["payload"]) == {"speaker", "mood", "text"}
    assert said["payload"]["text"] == LINE and said["payload"]["mood"] == "afraid"
    speaker = said["payload"]["speaker"]
    assert set(speaker) == {"id", "name", "portrait"} and speaker["name"] == ANSELM
    assert speaker["portrait"]["kind"] == "traits" and speaker["portrait"]["describe"].startswith("an elderly")
    assert SECRET not in story.text
    assert not [e for e in entries if e["kind"] == "dm_error"]

    # Connections: Replicate isn't there, a fake token is saved, and it is there at once.
    def providers() -> list[str]:
        answer = http.get("/api/backends")
        bodies.append(answer.text)
        return [p["id"] for p in answer.json()["providers"]]

    assert "replicate" not in providers()
    saved = http.put("/api/connections/replicate", json={"token": TOKEN})
    assert saved.status_code == 200 and saved.json() == {"state": "set"}
    assert "replicate" in providers()
    for path in ("/api/connections", "/api/preferences", f"{play}/play/state", f"{play}/characters"):
        answer = http.get(path)
        assert answer.status_code == 200, path
        bodies.append(answer.text)
    assert http.get("/api/connections").json()["replicate"] == {"state": "set"}
    removed = http.delete("/api/connections/replicate", headers={"Content-Type": "application/json"})
    assert removed.json() == {"state": "unset"}
    assert "replicate" not in providers()
    bodies += [saved.text, removed.text]

    # The token is in no answer and no log: not the server's, not the fake's, not the DM log's.
    bodies.append(http.get(f"{play}/dm/log").text)
    delve.stop()
    logs = [
        (delve.data_dir.parent / "serve.log").read_text(encoding="utf-8"),
        *(json.dumps(delve.lines(path)) for path in (delve.argv_log, delve.input_log)),
    ]
    for text in bodies + logs:
        assert TOKEN not in text
    assert (delve.data_dir / "replicate-token").exists() is False
