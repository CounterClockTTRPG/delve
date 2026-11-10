"""Write a module and play it, end to end (plan 3 Task 10): through the API of `delve serve`, with the fake `claude`
and the real bridge and tool host.

A module is made from nothing: a map with two rooms, a keyed text whose headings link to them by themselves, an NPC
and an encounter as form records, and a player image and a DM-only image with their descriptions. It exports as a
`.dscn` that imports into a fresh data dir with the same source. A campaign plays it in AD&D 2e with no setting, and
the DM shows both images: the player one reaches the story and is served, the DM-only one is refused and 404.

The real `claude` never runs.
"""

from __future__ import annotations

import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from delve.config import Config
from delve.storage import open_storage
from delve.web.app import create_app
from tests.e2e.test_play_with_fake_claude import Delve
from tests.fixtures import SAMPLES
from tests.web.conftest import BASE_URL, make_registries

ROOMS = (
    'map "Gatehouse" {\n  grid { bounds 30 x 10 }\n}\n\n'
    'room "gate" {\n  rect 1,1 4 x 4\n  label "The Gate"\n}\n\n'
    'room "hall" {\n  rect 10,1 4 x 4\n  label "The Hall"\n}\n'
)
KEY = (
    "# The Gatehouse\n\n"
    "## 1. The Gate\n\n"
    "> A rusted portcullis bars the way.\n\n"
    "Brother Odo watches from the murder holes ([[npc:odo]]).\n\n"
    "## 2. The Hall\n\n"
    "> A long hall, cold as a tomb.\n\n"
    "The [[encounter:hall-rats]] nest under the benches.\n"
)
ODO = {
    "id": "odo",
    "name": "Brother Odo",
    "audience": "gm",
    "summary": "The gatehouse's last warden.",
    "disposition": -20,
    "description": "Half mad; he thinks the party are grave robbers.",
    "stats": {"adnd2e": {"race": "Human", "class": "Cleric", "level": 3, "ac": 5, "hp": 14}},
}
RATS = {
    "id": "hall-rats",
    "name": "Hall rats",
    "audience": "gm",
    "key": "key:2",
    "kind": "dungeon",
    "fixed": [{"count": "2d4", "creature": "monster:giant-rat"}],
    "description": "Only when the party lingers.",
}
GATE_PNG = (SAMPLES / "scenarios" / "crypt-of-saint-vellis" / "assets" / "img" / "ritualist-token.png").read_bytes()
SECRET = "SECRET-XYZZY"


def png(rgb: tuple[int, int, int]) -> bytes:
    """A 1×1 PNG of one colour."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes([0, *rgb]))) + chunk(
        b"IEND", b""
    )


VAULT_PNG = png((90, 10, 10))
TURNS = [
    [
        {"text": "The portcullis looms before you. "},
        {"tool": "session_primer", "args": {}},
        {"tool": "show_image", "args": {"asset": "gate", "caption": "The gatehouse at dusk"}},
        {"tool": "show_image", "args": {"asset": "vault", "caption": "Behold"}},
        {"text": "Rust flakes from the bars as the wind picks up."},
    ],
]


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path, turns=TURNS)
    yield server
    server.stop()


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def write_the_module(http) -> str:
    """The module, made from nothing through the editor's routes; its id."""
    module = ok(http.post("/api/modules", json={"title": "The Gatehouse"}), 201)["id"]
    # A new module has one empty map, `map`: the map is written there.
    ok(http.put(f"/api/modules/{module}/maps/map", json={"source": ROOMS}))

    ok(http.post(f"/api/modules/{module}/texts", json={"id": "key", "title": "Key", "map": "map"}), 201)
    saved = ok(http.put(f"/api/modules/{module}/texts/key", json={"markdown": KEY}))
    assert [(link["key"], link["node"], link["explicit"]) for link in saved["links"]] == [
        ("1", "room.gate", False),
        ("2", "room.hall", False),
    ], "both keyed headings link to their rooms by themselves"

    assert ok(http.put(f"/api/modules/{module}/entities/npcs/odo", json=ODO))["record"] == ODO
    assert ok(http.put(f"/api/modules/{module}/entities/encounters/hall-rats", json=RATS))["record"] == RATS

    for name, data, description, audience in (
        ("gate.png", GATE_PNG, "The gatehouse from the road: show it when they arrive.", "player"),
        ("vault.png", VAULT_PNG, f"{SECRET}: the vault behind the hall, for the DM only.", "gm"),
    ):
        upload = http.post(
            f"/api/modules/{module}/assets", params={"name": name}, content=data, headers={"Content-Type": "image/png"}
        )
        attachment = ok(upload, 201)
        assert (attachment["description"], attachment["audience"]) == ("", "gm")
        described = http.patch(
            f"/api/modules/{module}/assets/{attachment['id']}", json={"description": description, "audience": audience}
        )
        assert ok(described)["audience"] == audience

    source = ok(http.get(f"/api/modules/{module}/source"))
    assert [a["id"] for a in source["attachments"]] == ["gate", "vault"]
    assert source["warnings"] == [], "every room has text, every key a room, every ref its record"
    return module


def imported_elsewhere(root, dscn: bytes) -> dict:
    """The `.dscn` imported into a fresh data dir: that module's source."""
    config = Config(data_dir=root / "fresh")
    storage = open_storage(config)
    try:
        app = create_app(config, storage, make_registries())
        with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as fresh:
            module = ok(fresh.post("/api/modules/import", content=dscn, headers={"Content-Type": "application/zip"}), 201)
            assert module["title"] == "The Gatehouse"
            return ok(fresh.get(f"/api/modules/{module['id']}/source"))
    finally:
        storage.close()


def test_write_export_import_and_play_a_module(delve, tmp_path):
    http = delve.http
    module = write_the_module(http)
    source = ok(http.get(f"/api/modules/{module}/source"))

    # Export, then import into a fresh data dir: the same source. The headings that linked themselves come back as
    # explicit keys, since in a `.dscn` `keys[]` is the only source of truth (format §5.3); they link the same rooms.
    exported = http.get(f"/api/modules/{module}/export.dscn")
    assert exported.status_code == 200, exported.text
    again = imported_elsewhere(tmp_path, exported.content)
    for part in ("texts", "entities", "attachments", "warnings"):
        assert again[part] == source[part], part
    assert source["keys"] == [] and again["keys"] == [
        {"key": "1", "title": "The Gate", "node": "map:map#room.gate", "text": "text:key#1"},
        {"key": "2", "title": "The Hall", "node": "map:map#room.hall", "text": "text:key#2"},
    ]
    assert again["links"] == [{**link, "explicit": True} for link in source["links"]]

    # A campaign in OSRIC with no setting.
    campaign = ok(
        http.post("/api/campaigns", json={"name": "Gate night", "module_id": module, "ruleset": "osric", "setting": None}),
        201,
    )
    assert (campaign["ruleset"], campaign["setting"]) == ("osric", "")
    play = f"/api/campaigns/{campaign['id']}"

    # The DM shows the player image, then tries the DM-only one.
    assert http.post(f"{play}/act", json={"text": "We walk up to the gatehouse."}).status_code == 202
    delve.settle(campaign["id"])
    entries = ok(http.get(f"{play}/story", params={"limit": 200}))["entries"]
    assert not [e for e in entries if e["kind"] == "dm_error"]
    tools = [e["payload"] for e in entries if e["kind"] == "tool"]
    assert tools == [{"name": "show_image"}, {"name": "show_image", "failed": True}]
    images = [e["payload"] for e in entries if e["kind"] == "image"]
    assert images == [{"asset": "gate", "caption": "The gatehouse at dusk"}]
    assert SECRET not in str(entries) and "vault" not in str(entries)

    served = http.get(f"{play}/images/gate")
    assert served.status_code == 200 and served.content == GATE_PNG
    assert served.headers["content-type"] == "image/png" and served.headers["x-content-type-options"] == "nosniff"
    refused = http.get(f"{play}/images/vault")
    assert refused.status_code == 404 and set(refused.json()) == {"error"}

    # The DM was told why: the refusal is in its own log only.
    assert "That image is for the DM only." in str(ok(http.get(f"{play}/dm/log")))
