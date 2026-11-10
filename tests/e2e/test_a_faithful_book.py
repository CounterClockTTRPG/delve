"""A faithful book, end to end (faithful modules Task 29): through the API of `delve serve`, with the fake `claude` on
`PATH` answering every side and vision call by its prompt.

The book is built in code: a house and a ship, each keyed from 1 (so 7 is in both), each with a full-page map plate
(the house's of two levels, its ground floor and its cellar; the ship's of one), a roster of pregenerated characters,
a page of two handouts, and a stat line whose ½ the text layer lost ("HD ;"). Tesseract never runs, so Claude's look
classifies the picture pages.

1. It converts with the book's maps drafted: the steps include classifying and gaps, and one draft follows per map
   page, page by page.
2. The house's draft keeps two maps, with the house's keys on them; the ship's draft keeps one.
3. The export is a valid `.dscn`.
4. A campaign's DM finds the ship's 7 by part, and the primer names no part without a map.
5. The pregens route lists the roster, and the DM's first beat makes the party from `module_pregens`.
6. The party goes into the house's room 4, and the DM finds its secret trapdoor (an exit to the cellar) with
   `door(found=True)`: a second seat's fog view shows it only once found.

`faithful_answer` answers the same calls for the browser check (`tests/e2e/fake_play_server.py`,
`web/e2e/zz-faithful.spec.ts`). The real `claude` never runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import httpx
import pytest

from delve.modules.dscn import Bundle
from delve.modules.dscn.validate import validate
from tests.e2e.test_a_table_of_three import Stream
from tests.e2e.test_play_with_fake_claude import Delve
from tests.fixtures import fake_claude
from tests.fixtures.pdfs import Page, pdf_bytes, picture_page, text_page
from tests.web.conftest import PASSWORD

HOUSE_TITLE = "The Haunted House"
SHIP_TITLE = "The Ghost Ship"
ROSTER_TITLE = "Pregenerated Characters"
HOUSE, SHIP, ROSTER = "the-haunted-house", "the-ghost-ship", "pregenerated-characters"
"""The texts' ids, from their titles."""

HOUSE_KEY = [
    ("1. Porch", "Rotten boards creak underfoot. The front door opens on area 2."),
    ("2. Hall", "Dust lies thick on the stairs. Doors lead to areas 1 and 3."),
    ("3. Kitchen", "A cold hearth and a long table. A door east opens on area 4."),
    ("4. Pantry", "Shelves of spoiled food. A secret trapdoor under the flour sacks leads down to area 5."),
    ("5. Cellar Stair", "A ladder comes down from the trapdoor in area 4."),
    ("6. Spider Den", "Webs fill the room. Two giant spiders wait here."),
    ("7. Wine Cellar", "Ned Shakeshaft hides among the barrels, in area 7."),
]
SHIP_KEY = [
    ("1. Main Deck", "The deck is slick with green weed."),
    ("2. Forecastle", "A torn log book lies on the chart table."),
    ("3. Hold", "Giant rats: AC 7; MV 12; HD ; hp 2"),
    ("4. Galley", "Pots swing on their hooks with the swell."),
    ("5. Crew Quarters", "Empty hammocks sway in the dark."),
    ("6. Sail Locker", "Old canvas, rotten through."),
    ("7. Captain's Cabin", "Four ghouls guard the captain's chest. Ned waits here for the smugglers."),
]
GAP_LINE = "Giant rats: AC 7; MV 12; HD ; hp 2"
FILLED_LINE = "Giant rats: AC 7; MV 12; HD ½; hp 2"
ROSTER_ROWS = [
    ("Name", "Race", "Class", "Level", "AC", "hp"),
    ("Aldon", "Human", "Fighter", "3", "4", "24"),
    ("Caine", "Half-elf", "Fighter/Thief", "3/3", "6", "17"),
]
HOUSE_INTRO = "The old house stands on the cliff above the town."
SHIP_INTRO = "The ghost ship lies at anchor in the bay."


def _page_lines(title: str, intro: str, key: list[tuple[str, str]]) -> list[str]:
    return [title, intro, *(line for heading, body in key for line in (heading, body))]


# ----- the book's pictures -----

CELL = 30
"""Pixels a printed square takes on a plate."""


def _plate(title: str, levels: list[list[tuple[str, int, int, int, int]]]) -> tuple[int, int, bytes]:
    """A map plate: its title, then each level's rooms `(key, x, y, w, h)` in squares, outlined and numbered, black on
    white, as grey pixels for the PDF."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (612, 792), 255)
    draw = ImageDraw.Draw(image)
    draw.text((40, 24), title.upper(), fill=0, font=ImageFont.load_default(size=28))
    font = ImageFont.load_default(size=22)
    for n, rooms in enumerate(levels):
        top = 90 + n * 340
        for x in range(18):
            for y in range(10):
                draw.point((40 + x * CELL, top + y * CELL), fill=160)
        for key, x, y, w, h in rooms:
            box = (40 + x * CELL, top + y * CELL, 40 + (x + w) * CELL, top + (y + h) * CELL)
            draw.rectangle(box, outline=0, width=4)
            draw.text((box[0] + 12, box[1] + 10), key, fill=0, font=font)
    return image.width, image.height, image.tobytes()


HOUSE_ROOMS = [
    [("1", 1, 1, 4, 4), ("2", 5, 1, 6, 4), ("3", 5, 5, 6, 4), ("4", 11, 5, 4, 4)],
    [("5", 1, 1, 5, 4), ("6", 6, 1, 5, 4), ("7", 6, 5, 5, 4)],
]
SHIP_ROOMS = [
    [("1", 1, 1, 8, 3), ("2", 9, 1, 4, 3), ("3", 1, 4, 4, 4), ("4", 5, 4, 4, 4), ("5", 9, 4, 4, 4), ("6", 13, 1, 3, 3),
     ("7", 13, 4, 3, 4)],
]  # fmt: skip


def _handouts() -> tuple[int, int, bytes]:
    """A page of two handouts: a note and a log page, each in its box."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (612, 792), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)
    for (x0, y0, x1, y1), words in (((0.1, 0.08, 0.9, 0.45), "Meet me below the pantry."),
                                    ((0.1, 0.55, 0.9, 0.92), "Day 12: the crew is gone.")):  # fmt: skip
        box = (x0 * 612, y0 * 792, x1 * 612, y1 * 792)
        draw.rectangle(box, outline=0, fill=230, width=3)
        draw.text((box[0] + 24, box[1] + 40), words, fill=0, font=font)
    return image.width, image.height, image.tobytes()


def book_pages() -> list[Page]:
    """The book: the house's key, the ship's key, their plates, the roster, and the handouts. The pictures are on
    pages 3 and later, which the browser check's other book (`test_books_and_quick_dungeons.book_pdf`, two pages)
    doesn't have, since a classifying prompt names only its page."""
    return [
        text_page(_page_lines(HOUSE_TITLE, HOUSE_INTRO, HOUSE_KEY)),
        text_page(_page_lines(SHIP_TITLE, SHIP_INTRO, SHIP_KEY)),
        picture_page(_plate("Haunted House", HOUSE_ROOMS)),
        picture_page(_plate("The Ghost Ship", SHIP_ROOMS)),
        text_page([ROSTER_TITLE, *(" ".join(row) for row in ROSTER_ROWS)]),
        picture_page(_handouts()),
    ]


def book_pdf() -> bytes:
    return pdf_bytes(book_pages())


MAP_PAGES = 2
"""The book's map pages: one draft each."""


# ----- Claude's answers -----


def _section(title: str, intro: str, key: list[tuple[str, str]]) -> str:
    rooms = "\n\n".join(f"## {heading}\n\n{body}" for heading, body in key)
    return f"# {title}\n\n{intro}\n\n{rooms}\n"


def _table(rows: list[tuple[str, ...]]) -> str:
    lines = [f"| {' | '.join(rows[0])} |", f"|{'---|' * len(rows[0])}"]
    return "\n".join([*lines, *(f"| {' | '.join(row)} |" for row in rows[1:])])


CONVERTED = (
    _section(HOUSE_TITLE, HOUSE_INTRO, HOUSE_KEY)
    + "\n"
    + _section(SHIP_TITLE, SHIP_INTRO, SHIP_KEY)
    + f"\n# {ROSTER_TITLE}\n\n{_table(ROSTER_ROWS)}\n"
)
HOUSE_ENTITIES = {
    "npcs": [{"id": "ned-shakeshaft", "name": "Ned Shakeshaft", "summary": "A spy of the smugglers, in area 7."}],
    "encounters": [{"id": "spiders", "name": "Giant spiders", "summary": "Two giant spiders in area 6."}],
}
SHIP_ENTITIES = {
    "npcs": [{"id": "ned", "name": "Ned", "summary": "The smugglers' man aboard, in area 7."}],
    "encounters": [{"id": "ghouls", "name": "Ghouls", "summary": "Four ghouls in area 7."}],
}
ALDON = {
    "id": "aldon",
    "name": "Aldon",
    "race": "Human",
    "class": "Fighter",
    "level": 3,
    "alignment": "Lawful Good",
    "gear": ["Chain mail", "Long sword"],
    "background": "A guard of the town watch.",
    "stats": {"adnd2e": {"ability_scores": {"str": "18/76", "int": 10, "wis": 11, "dex": 12, "con": 15, "cha": 9},
                         "hp_max": 24, "ac": 4}},
}  # fmt: skip
CAINE = {
    "id": "caine",
    "name": "Caine",
    "race": "Half-elf",
    "class": "Fighter/Thief",
    "level": "3/3",
    "alignment": "Chaotic Good",
    "gear": ["Leather armour", "Short sword", "Thieves' tools"],
    "background": "A sailor who knows the bay.",
    "stats": {"adnd2e": {"ability_scores": {"str": 14, "int": 13, "wis": 9, "dex": 17, "con": 12, "cha": 11},
                         "hp_max": 17, "ac": 6}},
}  # fmt: skip
ROSTER_ENTITIES = {"pregens": [ALDON, CAINE]}
DEDUPED = [["ned-shakeshaft", "ned"]]
"""Claude's groups of the NPCs: the house's Ned Shakeshaft and the ship's Ned are one."""

HOUSE_PLATE = {"kind": "map", "title": "Haunted House", "handouts": []}
SHIP_PLATE = {"kind": "map", "title": "The Ghost Ship", "handouts": []}
HANDOUT_PAGE = {
    "kind": "handout",
    "title": None,
    "handouts": [
        {"box": [0.1, 0.08, 0.9, 0.45], "title": "A note from the pantry", "key": "4", "part": "the house"},
        {"box": [0.1, 0.55, 0.9, 0.92], "title": "The ship's log", "key": "2", "part": "the ship"},
    ],
}
GAPS = [{"n": 1, "line": FILLED_LINE}]

TRAPDOOR = "room.r4/exit@13,7"
"""The secret trapdoor in the house's room 4, an exit to the cellar: its secret's key."""
HOUSE_DRAFT = """\
```dmap
# level: Ground floor
# part: the-haunted-house
include "core.dmap"

map "Ground floor" {
  grid { cell 32 px  units feet 10  bounds 20 x 14 }
  room_numbers off
}

room "r1" { rect 1,1 4 x 4  label "1. Porch" }
room "r2" { rect 5,1 6 x 4  label "2. Hall" }
room "r3" { rect 5,5 6 x 4  label "3. Kitchen" }
room "r4" {
  rect 11,5 4 x 4  label "4. Pantry"
  exit at 13,7 { to "haunted-house-2" at 2,2  label "Trapdoor"  secret }
}

door between room.r1 and room.r2 { }
door between room.r2 and room.r3 { }
door between room.r3 and room.r4 { }
```

```dmap
# level: Cellar
# part: the-haunted-house
include "core.dmap"

map "Cellar" {
  grid { cell 32 px  units feet 10  bounds 20 x 14 }
  room_numbers off
}

room "r5" {
  rect 1,1 5 x 4  label "5. Cellar Stair"
  exit at 2,2 { to "haunted-house-1" at 13,7  label "Ladder up" }
}
room "r6" { rect 6,1 5 x 4  label "6. Spider Den" }
room "r7" { rect 6,5 5 x 4  label "7. Wine Cellar" }

door between room.r5 and room.r6 { }
door between room.r6 and room.r7 { }
```
"""
SHIP_DRAFT = """\
```dmap
# level: Main deck
# part: the-ghost-ship
include "core.dmap"

map "Main deck" {
  grid { cell 32 px  units feet 5  bounds 18 x 10 }
  room_numbers off
}

room "r1" { rect 1,1 8 x 3  label "1. Main Deck" }
room "r2" { rect 9,1 4 x 3  label "2. Forecastle" }
room "r3" { rect 1,4 4 x 4  label "3. Hold" }
room "r4" { rect 5,4 4 x 4  label "4. Galley" }
room "r5" { rect 9,4 4 x 4  label "5. Crew Quarters" }
room "r6" { rect 13,1 3 x 3  label "6. Sail Locker" }
room "r7" { rect 13,4 3 x 4  label "7. Captain's Cabin" }

door between room.r1 and room.r2 { }
door between room.r1 and room.r4 { }
door between room.r3 and room.r4 { }
door between room.r4 and room.r5 { }
door between room.r2 and room.r6 { }
door between room.r5 and room.r7 { }
```
"""
HOUSE_MAPS = ("haunted-house-ground-floor", "haunted-house-cellar")
SHIP_MAP = "the-ghost-ship"

PROMPTS = [
    {"has": ["You are converting part of", SHIP_TITLE], "answer": CONVERTED},
    {"has": ["Below, between `<text>`", f"text:{HOUSE}#"], "answer": json.dumps(HOUSE_ENTITIES)},
    {"has": ["Below, between `<text>`", f"text:{SHIP}#"], "answer": json.dumps(SHIP_ENTITIES)},
    {"has": ["Below, between `<text>`", f"text:{ROSTER}#"], "answer": json.dumps(ROSTER_ENTITIES)},
    {"has": ["Below, between `<records>`", "ned-shakeshaft"], "answer": json.dumps(DEDUPED)},
    {"has": ["You look at page 3 of"], "answer": json.dumps(HOUSE_PLATE)},
    {"has": ["You look at page 4 of"], "answer": json.dumps(SHIP_PLATE)},
    {"has": ["You look at page 6 of"], "answer": json.dumps(HANDOUT_PAGE)},
    {"has": ["The picture is page 2 of", GAP_LINE], "answer": json.dumps(GAPS)},
    {"has": ["You redraw the map in the picture", f"### part: {HOUSE} "], "answer": HOUSE_DRAFT},
    {"has": ["You redraw the map in the picture", f"### part: {SHIP} "], "answer": SHIP_DRAFT},
]
"""The fake's answers by prompt (`fake_claude`'s `prompts`): the conversion's calls run at once, in no fixed order."""


def faithful_answer(prompt: str) -> str | None:
    """The answer to one of the faithful book's side or vision calls, by its prompt; None for any other."""
    return fake_claude._by_prompt(prompt, PROMPTS)


# ----- the DM's beats -----


def _sheet(pregen: dict) -> dict:
    """The sheet `module_pregens` gives for `pregen`: its sheet fields, with the book's race, class, level, alignment
    and background (a two-class "3/3" as `levels`)."""
    sheet = {**pregen["stats"]["adnd2e"], "race": pregen["race"], "cls": pregen["class"]}
    if isinstance(pregen["level"], int):
        sheet["level"] = pregen["level"]
    else:
        classes = [c.strip().lower() for c in pregen["class"].split("/")]
        sheet["levels"] = dict(zip(classes, (int(n) for n in pregen["level"].split("/")), strict=True))
    return {**sheet, "alignment": pregen["alignment"], "background": pregen["background"]}


PARTY_ACT = "Create the party from the module's pregenerated characters: Aldon, Caine."
TURNS = [
    [
        {"text": "Let me make your party from the book's characters. "},
        {"tool": "session_primer", "args": {}},
        {"tool": "new_session", "args": {"title": "The house on the cliff"}},
        {"tool": "module_pregens", "args": {}},
        *({"tool": "create_character", "args": {"name": p["name"], "sheet": _sheet(p)}} for p in (ALDON, CAINE)),
        *(
            {"tool": "add_item", "args": {"character": p["name"], "item": item}}
            for p in (ALDON, CAINE)
            for item in p["gear"]
        ),
        {"tool": "module_key", "args": {"room": "7", "part": "ship"}},
        {"text": "Aldon and Caine stand at the gate of the old house."},
    ],
    [
        {"tool": "move_party", "args": {"to": "r4", "map": HOUSE_MAPS[0]}},
        {"text": "The pantry smells of spoiled flour."},
    ],
    [
        {"tool": "door", "args": {"door": TRAPDOOR, "found": True}},
        {"text": "Under the flour sacks, Caine finds a trapdoor."},
    ],
]
"""The DM's beats: the party made from the pregens, into the pantry, and the trapdoor found."""


# ----- the test -----


@pytest.fixture
def delve(tmp_path):
    server = Delve(tmp_path, turns=TURNS)
    script = json.loads(server.script.read_text(encoding="utf-8"))
    server.script.write_text(json.dumps({**script, "prompts": PROMPTS}), encoding="utf-8")
    yield server
    server.stop()


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def wait_for(probe, what: str, timeout: float = 90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = probe()
        if found:
            return found
        time.sleep(0.2)
    raise AssertionError(f"no {what} in {timeout} s")


def tool_results(http, campaign: str, name: str) -> list[dict]:
    """The results of the DM's calls of the tool `name`, from the DM log (its `tool_call` and `tool_result` events)."""
    events = [e["raw"] for e in ok(http.get(f"/api/campaigns/{campaign}/dm/log"))["entries"]]
    calls = {e["id"] for e in events if e.get("type") == "tool_call" and e["name"] == name}
    return [e["content"] for e in events if e.get("type") == "tool_result" and e["id"] in calls]


def test_a_faithful_book_converts_drafts_exports_and_plays(delve):
    http = delve.http
    listening = httpx.Client(base_url=str(http.base_url), timeout=30)
    stream = Stream(listening)

    # 1. The book converts, its map pages classified by Claude's look, the lost ½ read from its page.
    started = ok(
        http.post(
            "/api/conversions/pdf",
            params={"title": "The Sinister House", "mode": "draft", "thorough": "false"},
            content=book_pdf(),
            headers={"Content-Type": "application/pdf"},
        ),
        202,
    )

    def ended():
        now = ok(http.get(f"/api/conversions/{started['id']}"))
        return now if now["status"] != "running" else None

    done = wait_for(ended, "end of the conversion")
    assert done["status"] == "done", done["error"]
    steps = list(dict.fromkeys(e["step"] for e in stream.of("conversion") if e["id"] == started["id"]))
    assert steps == ["reading", "classifying", "converting", "entities", "pictures", "gaps", "maps"], steps
    module_id = done["module_id"]
    codes = {w["code"] for w in done["warnings"]}
    assert "text-filled" in codes and "text-gap" not in codes and "page-not-classified" not in codes
    assert "map-sketched" not in codes, "every part has its map page: no room-key sketch"

    source = ok(http.get(f"/api/modules/{module_id}/source"))
    assert [t["id"] for t in source["texts"]] == [HOUSE, SHIP, ROSTER]
    assert FILLED_LINE in source["texts"][1]["markdown"]
    pages = {a["id"]: a for a in source["attachments"]}
    assert pages["map-page-3"]["description"] == "Page 3: a map from the book (Haunted House)"
    assert pages["map-page-4"]["description"] == "Page 4: a map from the book (The Ghost Ship)"
    assert (pages["handout-6-1"]["audience"], pages["handout-6-2"]["audience"]) == ("player", "player")
    keys = {k["key"]: k for k in source["keys"]}
    assert "asset:handout-6-1" in keys["haunted-house-4"]["assets"]
    assert "asset:handout-6-2" in keys["ghost-ship-2"]["assets"]
    assert [p["name"] for p in source["entities"]["pregens"]] == ["Aldon", "Caine"]
    assert [n["name"] for n in source["entities"]["npcs"]] == ["Ned Shakeshaft"], "the two Neds are one"
    assert ok(http.get(f"/api/modules/{module_id}"))["maps"] == [], "nothing is drawn until a draft is kept"

    # The drafts follow, page by page: one per map page, the house's of two levels.
    drafts = wait_for(
        lambda: (found := ok(http.get(f"/api/modules/{module_id}/map-drafts"))) and len(found) == MAP_PAGES and found,
        "drafts",
    )
    jobs = {c["id"]: c["title"] for c in ok(http.get("/api/conversions")) if c["kind"] == "book-map"}
    drawn = list(dict.fromkeys(jobs[e["id"]] for e in stream.of("conversion") if e["id"] in jobs))
    assert drawn == ["page 3", "page 4"], "page by page, one job after another"
    listening.close()
    by_page = {d["page"]: d for d in drafts}
    house, ship = by_page["map-page-3"], by_page["map-page-4"]
    assert (house["part"], ship["part"]) == (HOUSE, SHIP)
    assert [m["name"] for m in house["maps"]] == list(HOUSE_MAPS)
    assert [m["name"] for m in ship["maps"]] == [SHIP_MAP]
    assert '"haunted-house-cellar"' in house["maps"][0]["source"], "the trapdoor's exit names the cellar"

    # 2. Kept: the house's two maps and the ship's one, each room linked to its part's heading.
    ok(http.post(f"/api/modules/{module_id}/map-drafts/{house['id']}/keep", json={}), 201)
    ok(http.post(f"/api/modules/{module_id}/map-drafts/{ship['id']}/keep", json={}), 201)
    module = ok(http.get(f"/api/modules/{module_id}"))
    assert [(m["name"], m["is_default"]) for m in module["maps"]] == [
        (HOUSE_MAPS[0], True),
        (HOUSE_MAPS[1], False),
        (SHIP_MAP, False),
    ]
    keys = {k["key"]: k for k in ok(http.get(f"/api/modules/{module_id}/source"))["keys"]}
    assert keys["haunted-house-4"]["node"] == f"map:{HOUSE_MAPS[0]}#room.r4"
    assert keys["haunted-house-7"]["node"] == f"map:{HOUSE_MAPS[1]}#room.r7"
    assert keys["ghost-ship-7"]["node"] == f"map:{SHIP_MAP}#room.r7"

    # 3. The export is a valid .dscn.
    exported = http.get(f"/api/modules/{module_id}/export.dscn")
    assert exported.status_code == 200, exported.text
    errors = [d for d in validate(Bundle.from_zip(exported.content)) if d.severity == "error"]
    assert errors == [], errors

    # 4. A campaign, its DM making the party from the pregens.
    ok(http.patch(f"/api/modules/{module_id}", json={"draft": False}))
    campaign = ok(http.post("/api/campaigns", json={"name": "Saltmarsh nights", "module_id": module_id}), 201)["id"]
    play = f"/api/campaigns/{campaign}"
    listed = ok(http.get(f"{play}/pregens"))
    assert [(p["name"], p["class"], p["level"]) for p in listed["pregens"]] == [
        ("Aldon", "Fighter", 3),
        ("Caine", "Fighter/Thief", "3/3"),
    ]
    ok(http.post(f"{play}/act", json={"text": PARTY_ACT}), 202)
    state = delve.settle(campaign)
    assert [pc["name"] for pc in state["party"]] == ["Aldon", "Caine"]
    [pregens] = tool_results(http, campaign, "module_pregens")
    assert [p["sheet"] for p in pregens["pregens"]] == [_sheet(ALDON), _sheet(CAINE)]
    [primer] = tool_results(http, campaign, "session_primer")
    assert primer["module"]["unmapped"] == [], "every part is on a map"
    [ship_7] = tool_results(http, campaign, "module_key")
    assert (ship_7["key"], ship_7["part"]) == ("ghost-ship-7", "ghost-ship")
    assert "ghouls" in json.dumps(ship_7).lower()

    # 5. Bo joins and plays Caine; the party goes into the pantry, room 4.
    pcs = {pc["name"]: pc["id"] for pc in state["party"]}
    token = ok(http.get(f"{play}/invite"))["join_token"]
    with httpx.Client(base_url=str(http.base_url), timeout=30) as bo:
        ok(
            bo.post(
                f"/api/join/{token}/account",
                json={"username": "bo.r", "password": PASSWORD, "display_name": "Bo", "language": "en", "role": "player"},
            ),
            201,
        )
        ok(bo.post(f"{play}/characters/{pcs['Caine']}/claim", json={}))
        ok(http.post(f"{play}/act", json={"text": "We go through the kitchen into the pantry."}), 202)
        state = delve.settle(campaign)
        assert {(p["map"], p["label"]) for p in state["positions"]} == {(HOUSE_MAPS[0], "4. Pantry")}
        view = f"{play}/maps/{HOUSE_MAPS[0]}/view"
        before = ok(bo.get(view, params={"characters": pcs["Caine"]}))["svg"]
        assert "Trapdoor" not in before, "the secret trapdoor is hidden until found"
        assert "Pantry" in before

        # 6. The DM finds the trapdoor: Bo's fog view shows it.
        ok(http.post(f"{play}/act", json={"text": "We search the pantry for a way down."}), 202)
        delve.settle(campaign)
        [found] = tool_results(http, campaign, "door")
        assert (found["secret"], found["kind"], found["revealed"]) == (TRAPDOOR, "exit", True)
        after = ok(bo.get(view, params={"characters": pcs["Caine"]}))["svg"]
        assert "Trapdoor" in after
        assert ok(bo.get(f"{play}/pregens"), 403) is not None, "only the host reads the pregens"

    entries = ok(http.get(f"{play}/story", params={"limit": 200}))["entries"]
    assert not [e for e in entries if e["kind"] == "dm_error"]
    assert "module_pregens" not in json.dumps([e for e in entries if e["kind"] == "tool"])


def test_the_fake_answers_side_and_vision_calls_by_their_prompt(tmp_path):
    """`fake_claude`'s `prompts`: a side or vision call whose prompt holds a rule's words gets its answer, and takes
    no `side` or `vision` item; any other gets the next item."""
    script = tmp_path / "script.json"
    rules = [{"has": ["page 2", "map"], "answer": "the map"}, {"has": ["records"], "answer": "[]"}]
    script.write_text(json.dumps({"side": ["next side"], "vision": ["next vision"], "prompts": rules}))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DELVE_", "FAKE_CLAUDE_"))}
    env["FAKE_CLAUDE_SCRIPT"] = str(script)

    def run(argv: list[str], stdin: str) -> str:
        done = subprocess.run(
            [sys.executable, str(fake_claude.FAKE_CLAUDE), *argv],
            input=stdin,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout

    def look(prompt: str) -> str:
        image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0K"}}
        message = {"type": "user", "message": {"role": "user", "content": [image, {"type": "text", "text": prompt}]}}
        lines = run(["-p", "--input-format", "stream-json", "--output-format", "stream-json"], json.dumps(message))
        return [json.loads(line) for line in lines.splitlines()][-1]["result"]

    assert run(["-p"], "Group these records.") == "[]\n"
    assert look("You look at page 2 of a book: a map?") == "the map"
    assert run(["-p"], "Something else.") == "next side\n"
    assert look("Page 3: what is it?") == "next vision"
