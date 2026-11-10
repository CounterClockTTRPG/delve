"""Books and quick dungeons, end to end (plan 5 Task 8): through the API of `delve serve`, with the fake `claude` on
`PATH` answering the conversion's side calls.

A PDF built in code, with a two-column chapter holding three keyed rooms and a full-page picture, converts as a
draft. The module has the chapter's text in reading order, its three keyed headings linked to the sketched map, the
picture as an attachment, and the `map-sketched` and `image-to-describe` warnings. The draft can't start a campaign
until it's marked ready; then it can. A request generates a module that starts a campaign at once. The whole module's
print page lists its parts.

The fake answers the side calls in the order they come: a book of one chunk is converted (one call), its one text
gets its entity drafts (one call), its room key is sketched (one call), its metadata is read (one call); then the
request's plan (one call), its sketch (one call) and its metadata (one call). `answer_for` answers the same prompts by their kind instead, for the browser check
(`tests/e2e/fake_play_server.py`).

`scripts/convert_live.py` (`make convert-live`) runs here with the fake too, so the owner's live check works when
they run it with the real one.

The real `claude` never runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from tests.e2e.test_play_with_fake_claude import Delve
from tests.fixtures import fake_claude
from tests.fixtures.pdfs import pdf_bytes, picture_page, two_column_page

ROOT = Path(__file__).resolve().parents[2]

CHAPTER = "The Sunken Shrine of the Drowned God and its Halls"
LEFT = [
    "The shrine lies under the old mill pond.",
    "Pilgrims once came here to pray for rain.",
    "Now the kobolds of Muckfoot hold its halls.",
    "1. Flooded Stair",
    "Worn steps go down into cold black water.",
    "A door at the bottom opens on area 2.",
]
RIGHT = [
    "2. Hall of Echoes",
    "Every footstep rings back three times.",
    "Six kobolds guard the hall with spears.",
    "A passage south leads on to area 3.",
    "3. Drowned Altar",
    "Chief Muckfoot hides behind the altar.",
    "His hoard is forty silver pieces.",
]


def book_pdf() -> bytes:
    """The book: page 1 the chapter in two columns, page 2 a full-page picture (its map plate)."""
    return pdf_bytes([two_column_page(LEFT, RIGHT, heading=CHAPTER), picture_page()])


CONVERTED = f"""\
# {CHAPTER}

The shrine lies under the old mill pond. Pilgrims once came here to pray for rain. Now the kobolds of Muckfoot hold
its halls.

## 1. Flooded Stair

Worn steps go down into cold black water. A door at the bottom opens on area 2.

## 2. Hall of Echoes

Every footstep rings back three times. Six kobolds guard the hall with spears. A passage south leads on to area 3.

## 3. Drowned Altar

Chief Muckfoot hides behind the altar. His hoard is forty silver pieces.
"""
ENTITIES = json.dumps(
    {
        "npcs": [{"id": "muckfoot", "name": "Chief Muckfoot", "summary": "The kobold chief, behind the altar."}],
        "encounters": [{"id": "hall-guards", "name": "Hall guards", "summary": "Six kobolds with spears."}],
        "factions": [],
        "quests": [],
    }
)
SHRINE_MAP = """\
```dmap
include "core.dmap"

map "The Sunken Shrine" {
  grid { cell 32 px  units feet 10  bounds 30 x 20 }
  room_numbers off
}

room "r1" { rect 1,1 6 x 5  label "1. Flooded Stair" }
room "r2" { rect 7,1 8 x 5  label "2. Hall of Echoes" }
room "r3" { rect 7,6 8 x 6  label "3. Drowned Altar" }

door between room.r1 and room.r2 { }
door between room.r2 and room.r3 { }
```
"""
REQUEST = "A dungeon with kobolds, no plot"
PLAN = json.dumps(
    {
        "title": "The Kobold Warren",
        "summary": "A warren of kobolds under a hill, with no story to follow.",
        "rooms": [
            {
                "key": "1",
                "name": "Burrow Mouth",
                "read_aloud": "A low tunnel slopes into the hill. It smells of wet dog.",
                "dm_text": "Two kobold sentries doze here. A tunnel east leads to area 2.",
                "monsters": "2 kobolds (AC 7, HD 1/2, hp 3 each)",
                "treasure": "",
            },
            {
                "key": "2",
                "name": "Den",
                "read_aloud": "Bedding of rushes covers the floor.",
                "dm_text": "Eight kobolds sleep here. West to area 1, south to area 3.",
                "monsters": "8 kobolds",
                "treasure": "",
            },
            {
                "key": "3",
                "name": "Chief's Hole",
                "read_aloud": "A crude throne of bones faces the door.",
                "dm_text": "The chief, Grik, and his hoard. The only way out is north, to area 2.",
                "monsters": "Grik, kobold chief (AC 6, HD 1, hp 7)",
                "treasure": "A pouch of 40 sp and a silver ring (25 gp).",
            },
        ],
        "npcs": [{"id": "grik", "name": "Grik", "summary": "Cowardly and greedy; he bargains for his life."}],
        "encounters": [{"id": "den-kobolds", "name": "Den kobolds", "summary": "The eight sleepers of the den."}],
    }
)
WARREN_MAP = """\
```dmap
include "core.dmap"

map "The Kobold Warren" {
  grid { cell 32 px  units feet 10  bounds 30 x 20 }
  room_numbers off
}

room "r1" { rect 1,1 6 x 5  label "1. Burrow Mouth" }
room "r2" { rect 7,1 8 x 5  label "2. Den" }
room "r3" { rect 7,6 8 x 6  label "3. Chief's Hole" }

door between room.r1 and room.r2 { }
door between room.r2 and room.r3 { }
```
"""
METADATA = json.dumps({"summary": "Kobolds in a drowned shrine.", "tags": ["dungeon", "kobolds"]})
SIDE = (CONVERTED, ENTITIES, SHRINE_MAP, METADATA, PLAN, WARREN_MAP, METADATA)
"""The side calls' answers, in the order this test makes them."""

PROMPT_STARTS = {
    "You are converting part of": "convert",
    "Below, between `<text>`": "entities",
    "You draw a schematic map": "sketch",
    "You write a small adventure module": "generate",
    "You describe a role-playing adventure module": "metadata",
}


def answer_for(prompt: str) -> str | None:
    """The answer to a conversion's side call by the kind of its prompt; None for any other prompt. A sketch of the
    shrine's room key gets the shrine's map, any other the warren's."""
    kind = next((kind for start, kind in PROMPT_STARTS.items() if prompt.startswith(start)), None)
    if kind == "sketch":
        return SHRINE_MAP if "Flooded Stair" in prompt else WARREN_MAP
    return {"convert": CONVERTED, "entities": ENTITIES, "generate": PLAN, "metadata": METADATA}.get(kind or "")


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path, turns=[], side=SIDE)
    yield server
    server.stop()


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def ended(http, conversion: dict, timeout: float = 60) -> dict:
    """The conversion once it has ended."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        now = ok(http.get(f"/api/conversions/{conversion['id']}"))
        if now["status"] != "running":
            return now
        time.sleep(0.1)
    raise AssertionError(f"conversion {conversion['id']} still running")


def side_prompts(delve: Delve) -> list[str]:
    """The prompts of the side calls the fake `claude` answered, in order: each read from its stdin, in the input log,
    by the pid of a side call's argv record."""
    side_pids = {
        record["pid"]
        for record in delve.lines(delve.argv_log)
        if "-p" in record["argv"] and "--input-format" not in record["argv"]
    }
    return [record["text"] for record in delve.lines(delve.input_log) if record["pid"] in side_pids]


def printed_parts(http, module_id: str) -> list[str]:
    """The parts the print page (`web/src/routes/ModulePrint.tsx`) lists, from the answers it is built from: the title
    page, each text, each played map (each drawn and parsed), the NPCs, the encounters, the images (each served)."""
    module = ok(http.get(f"/api/modules/{module_id}"))
    source = ok(http.get(f"/api/modules/{module_id}/source"))
    parts = ["title"] + ["text"] * len(source["texts"])
    for module_map in (m for m in module["maps"] if m["role"] == "map"):
        body = {"source": module_map["source"], "module_id": module_id}
        assert "<svg" in ok(http.post("/api/dsl/render", json=body))["svg"]
        assert ok(http.post("/api/dsl/parse", json=body))["map"]["rooms"]
        parts.append("map")
    parts += [kind for kind in ("npcs", "encounters") if source["entities"].get(kind)]
    images = [a for a in source["attachments"] if a["type"].startswith("image/")]
    for image in images:
        served = http.get(f"/api/modules/{module_id}/assets/{image['id']}")
        assert served.status_code == 200 and served.headers["content-type"] == image["type"]
    return parts + (["images"] if images else [])


def test_a_pdf_a_draft_and_a_request_become_modules(delve):
    http = delve.http

    # The PDF converts as a draft.
    upload = http.post(
        "/api/conversions/pdf",
        params={"title": "The Sunken Shrine", "mode": "draft", "thorough": "false"},
        content=book_pdf(),
        headers={"Content-Type": "application/pdf"},
    )
    started = ok(upload, 202)
    assert (started["kind"], started["mode"], started["status"]) == ("pdf", "draft", "running")
    done = ended(http, started)
    assert done["status"] == "done", done["error"]
    assert (done["step"], done["done"], done["total"]) == ("maps", 1, 1)

    # Claude was asked for the chapter in reading order: the left column, then the right.
    convert, entities, sketch, metadata = side_prompts(delve)
    assert convert.startswith("You are converting part of")
    order = [convert.index(line) for line in (CHAPTER, *LEFT, *RIGHT)]
    assert order == sorted(order), "the heading, then the left column, then the right"
    assert entities.startswith("Below, between `<text>`") and "## 2. Hall of Echoes" in entities
    assert sketch.startswith("You draw a schematic map") and 'label "3. Drowned Altar"' in sketch
    assert metadata.startswith("You describe a role-playing adventure module") and "## 2. Hall of Echoes" in metadata

    module_id = done["module_id"]
    module = ok(http.get(f"/api/modules/{module_id}"))
    assert (module["title"], module["draft"]) == ("The Sunken Shrine", True)
    source = ok(http.get(f"/api/modules/{module_id}/source"))
    [text] = source["texts"]
    assert (text["title"], text["audience"], text["map"]) == (CHAPTER, "gm", text["id"])
    for line in (*LEFT[:3], *RIGHT[1:4], *RIGHT[5:]):
        assert line in " ".join(text["markdown"].split()), line

    # The three keyed headings link to the rooms of the sketched map, which is the module's played map.
    assert [(m["name"], m["role"], m["is_default"]) for m in module["maps"]] == [(text["id"], "map", True)]
    assert [(link["key"], link["node"], link["explicit"]) for link in source["links"]] == [
        ("1", "room.r1", False),
        ("2", "room.r2", False),
        ("3", "room.r3", False),
    ]
    assert source["entities"]["npcs"][0]["name"] == "Chief Muckfoot"
    assert source["entities"]["encounters"][0]["name"] == "Hall guards"

    # The picture page is an attachment, beside the original PDF.
    assert [(a["id"], a["type"], a["audience"], a["role"], a["description"]) for a in source["attachments"]] == [
        ("page-2", "image/png", "gm", "attachment", "Page 2: a map or full-page picture"),
        ("source-pdf", "application/pdf", "gm", "source", "The original PDF"),
    ]
    pdf = http.get(f"/api/modules/{module_id}/assets/source-pdf")
    assert pdf.status_code == 200 and pdf.content == book_pdf()

    warnings = {(w["code"], w["ref"]): w["message"] for w in done["warnings"]}
    assert warnings[("map-sketched", f"map:{text['id']}")] == "Sketched from the room key: an invented layout; compare it with page 2."
    assert ("image-to-describe", "asset:page-2") in warnings
    assert {code for code, _ in warnings} <= {"map-sketched", "image-to-describe", "page-not-read", "page-not-classified"}, (
        "page-not-read only where tesseract isn't installed; the fake claude's look at the picture page names no kind"
    )

    # The draft can't start a campaign until it's marked ready; then it can.
    campaign = {"name": "Shrine night", "module_id": module_id}
    refused = http.post("/api/campaigns", json=campaign)
    assert refused.status_code == 409 and refused.json()["error"] == "This module is a draft: mark it ready first."
    assert ok(http.patch(f"/api/modules/{module_id}", json={"draft": False}))["draft"] is False
    assert ok(http.post("/api/campaigns", json=campaign), 201)["module_id"] == module_id

    # A request generates a module that starts a campaign at once.
    generated = ended(http, ok(http.post("/api/conversions/generate", json={"request": REQUEST, "scale": "module"}), 202))
    assert generated["status"] == "done", generated["error"]
    assert (generated["kind"], generated["mode"], generated["title"]) == ("generate", "ready", "The Kobold Warren")
    plan, warren_sketch, _ = side_prompts(delve)[4:]
    assert plan.startswith("You write a small adventure module") and REQUEST in plan
    assert 'label "2. Den"' in warren_sketch
    warren = ok(http.get(f"/api/modules/{generated['module_id']}"))
    assert (warren["title"], warren["draft"]) == ("The Kobold Warren", False)
    warren_source = ok(http.get(f"/api/modules/{warren['id']}/source"))
    assert [link["node"] for link in warren_source["links"]] == ["room.r1", "room.r2", "room.r3"]
    assert [w["code"] for w in generated["warnings"]] == ["map-sketched"]
    started_at_once = ok(http.post("/api/campaigns", json={"name": "Warren", "module_id": warren["id"]}), 201)
    assert started_at_once["module_id"] == warren["id"]

    # The whole module's print page lists its parts, in order.
    assert printed_parts(http, module_id) == ["title", "text", "map", "npcs", "encounters", "images"]
    assert printed_parts(http, warren["id"]) == ["title", "text", "map", "npcs", "encounters"]

    assert [c["id"] for c in ok(http.get("/api/conversions"))] == [generated["id"], started["id"]]
    assert len(side_prompts(delve)) == len(SIDE), "no other side call"


def test_the_browser_checks_claude_reads_the_side_prompt_from_stdin(tmp_path):
    """`claude` of `tests/e2e/fake_play_server.py`: a conversion's side prompt, on stdin, is answered by its kind; any
    other goes to the fake on stdin, so the script's side answer is used by it and not before."""
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"turns": [], "side": ["The scripted answer."]}), encoding="utf-8")
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("DELVE_", "FAKE_CLAUDE_"))},
        "PYTHONPATH": str(ROOT),
        "FAKE_CLAUDE_SCRIPT": str(script),
        "FAKE_CLAUDE_INPUT_LOG": str(tmp_path / "input.jsonl"),
    }

    def claude(prompt: str) -> str:
        argv = [sys.executable, "-m", "tests.e2e.fake_play_server", "--claude", "-p", "--model", "fake"]
        run = subprocess.run(
            argv, input=prompt, env=env, cwd=ROOT, check=False, capture_output=True, text=True, timeout=60
        )
        assert run.returncode == 0, run.stderr
        return run.stdout

    entities_prompt = "Below, between `<text>`, is a module's text."
    assert claude(entities_prompt) == ENTITIES + "\n"
    assert claude("Can a surprised character act?") == "The scripted answer.\n"
    assert claude("And again?") == "(fake answer)\n"
    logged = [json.loads(line)["text"] for line in (tmp_path / "input.jsonl").read_text().splitlines()]
    assert logged == ["Can a surprised character act?", "And again?"]


def test_convert_live_reports_and_leaves_a_dscn(tmp_path):
    """The owner's live check, with the fake `claude` first on `PATH`: its timings, warnings, coverage and `.dscn`."""
    bin_dir = tmp_path / "bin"
    fake_claude.install(bin_dir)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"turns": [], "side": list(SIDE[:4])}), encoding="utf-8")
    pdf = tmp_path / "The Sunken Shrine.pdf"
    pdf.write_bytes(book_pdf())
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("DELVE_", "FAKE_CLAUDE_"))},
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "FAKE_CLAUDE_SCRIPT": str(script),
        "FAKE_CLAUDE_ARGV_LOG": str(tmp_path / "argv.jsonl"),
    }
    out = tmp_path / "out"
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "convert_live.py"), str(pdf), "--out", str(out)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    report = run.stdout
    assert "as “The Sunken Shrine” (draft)" in report
    assert "Claude calls (4):" in report
    for kind in ("chunk     page", "entities  the-sunken-shrine", "sketch", "metadata"):
        assert kind in report, report
    assert "map-sketched" in report and "image-to-describe" in report
    assert "Word coverage:" in report
    assert len((tmp_path / "argv.jsonl").read_text().splitlines()) == 4, "every call went to the fake"
    [dscn] = out.iterdir()
    assert dscn.suffix == ".dscn" and "scenario.json" in zipfile.ZipFile(dscn).namelist()
