"""A scanned book's shape, converted (walkthrough fixes Task 9): what UK7 and the Tomb of Horrors had in them.

The book is three scanned pages, each an image made with Pillow and no text layer, as a scan is:
1. a page of text holding a room key of three rooms;
2. the map, with its title, a legend and room numbers;
3. a handout, which OCR reads as junk.

The OCR is a fake `ocr` that tells the pages apart by the grey of a block in their top left corner, and answers what
tesseract would read on each. Claude is the fake `claude` on `PATH`, behind the real `ClaudeCliProvider`, answering
the side calls in the order the conversion makes them: the text page's chunk, then its entities.

The module keeps the map page as a `map-page-2` attachment with a `book-map` warning, keeps the handout as a picture,
and puts none of what OCR read on those two pages in any text. Its room key isn't sketched as an invented layout,
since the map page is titled like its text: that page is drafted after the conversion (faithful modules B5). Neither
the real `claude` nor tesseract runs.
"""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from delve.config import Config
from delve.conversions import ConversionServices, start_pdf, wait
from delve.dm.claude_cli.provider import ClaudeCliProvider, MemorySessions
from delve.domain.settings import BackendChoice
from delve.modules.source import load_source
from delve.storage import open_storage
from tests.fixtures import fake_claude
from tests.fixtures.pdfs import picture_page, write_pdf

TEXT_GREY, MAP_GREY, HANDOUT_GREY = 40, 120, 200
"""The grey of the block in each page's top left corner, by which the fake OCR knows the page."""

ROOMS = [
    (
        "1. Flooded Stair",
        (
            "Worn steps go down into cold black water that fills the lower half of the stair. The water is four feet "
            "deep at the bottom and very cold. A door at the bottom opens on the hall, area 2, and it is stuck shut "
            "with silt; it takes a bend bars roll or two rounds of digging to open it."
        ),
    ),
    (
        "2. Hall of Echoes",
        (
            "Every footstep rings back three times from the vaulted ceiling of this long hall. Six kobolds guard the "
            "hall with spears and short bows, and they hear anyone who comes down the stair unless the party is "
            "silent. A passage to the south leads on to the altar, area 3, and the kobolds fall back there when half "
            "of them are down."
        ),
    ),
    (
        "3. Drowned Altar",
        (
            "Chief Muckfoot hides behind the altar with his two wives and his hoard. The altar is of green stone, "
            "carved with fishes and waves, and the water around it is ten feet deep. His hoard is forty silver pieces "
            "and a pearl worth one hundred gold pieces, sewn into a pouch at his belt."
        ),
    ),
]
INTRODUCTION = (
    "The shrine lies under the old mill pond, below the village of Wetherby. Pilgrims once came here to pray for "
    "rain, and the priests kept the halls dry with pumps of bronze. The pumps failed long ago, and now the kobolds "
    "of Muckfoot hold the halls, raiding the farms around the pond for sheep and grain. The villagers will pay the "
    "party well to drive them out."
)
TEXT_OCR = "THE SUNKEN SHRINE\n\n" + INTRODUCTION + "\n\n" + "\n\n".join(f"{key}\n{body}" for key, body in ROOMS)
"""What OCR reads on the text page: a page of real words, and the room key."""
MAP_OCR = "MAP 1 – THE SUNKEN SHRINE\nFALSE DOOR SECRET DOOR STAIRS UP COVERED PIT\n1 2 3 4 5 6 7 8 9 10 11 12"
"""… on the map: its title, its legend and its room numbers."""
HANDOUT_OCR = "\n".join(["Ue A A NE OM TON NIL ON b i 10 wePr. Wena Sylar"] * 20)
"""… on the handout: junk."""
OCR = {TEXT_GREY: TEXT_OCR, MAP_GREY: MAP_OCR, HANDOUT_GREY: HANDOUT_OCR}

CONVERTED = "# The Sunken Shrine\n\n" + INTRODUCTION + "\n\n" + "\n\n".join(f"## {k}\n\n{b}" for k, b in ROOMS) + "\n"
ENTITIES = json.dumps(
    {
        "npcs": [
            {"id": "muckfoot", "name": "Chief Muckfoot", "summary": "The kobold chief, behind the altar."},
            {"id": "muckfoot-2", "name": "chief muckfoot ", "summary": "He has two wives."},
        ],
        "encounters": [{"id": "hall-guards", "name": "Hall guards", "summary": "Six kobolds with spears, in area 2."}],
        "factions": [],
        "quests": [],
    }
)
METADATA = json.dumps({"summary": "Kobolds hold a drowned shrine.", "tags": ["dungeon", "kobolds"]})
SIDE = [CONVERTED, ENTITIES, METADATA]


def scan(grey: int, draw) -> tuple[int, int, bytes]:
    """A scanned page as Pillow makes it: white paper, the page's grey block in the top left corner, and `draw`'s
    marks."""
    from PIL import Image, ImageDraw

    image = Image.new("L", (612, 792), 255)
    pen = ImageDraw.Draw(image)
    pen.rectangle((0, 0, 60, 60), fill=grey)
    draw(pen)
    return image.width, image.height, image.tobytes()


def text_marks(pen) -> None:
    for line in range(40):
        pen.text((72, 90 + line * 16), "the shrine lies under the old mill pond " * 2, fill=0)


def map_marks(pen) -> None:
    for i in range(7):
        pen.line((72 + i * 78, 144, 72 + i * 78, 612), fill=0, width=2)
        pen.line((72, 144 + i * 78, 540, 144 + i * 78), fill=0, width=2)
    for n in range(1, 13):
        pen.text((90 + (n - 1) % 6 * 78, 160 + (n - 1) // 6 * 78), str(n), fill=0)
    pen.text((72, 650), "FALSE DOOR  SECRET DOOR  STAIRS UP  COVERED PIT", fill=0)


def handout_marks(pen) -> None:
    pen.ellipse((150, 200, 460, 600), outline=0, width=6)
    pen.polygon([(306, 250), (420, 560), (190, 560)], outline=0)


def fake_ocr(png: bytes) -> str:
    """What tesseract would read on the page, known by the grey of its corner block."""
    from PIL import Image

    with Image.open(io.BytesIO(png)) as image:
        grey = image.convert("L").getpixel((5, 5))
    return OCR[min(OCR, key=lambda g: abs(g - grey))]


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


@pytest.fixture
def claude(tmp_path, monkeypatch):
    """The fake `claude` first on `PATH`, with the side answers scripted."""
    bin_dir = tmp_path / "bin"
    fake_claude.install(bin_dir)
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"turns": [], "side": SIDE}), encoding="utf-8")
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_ARGV_LOG", str(tmp_path / "argv.jsonl"))
    monkeypatch.setenv("FAKE_CLAUDE_INPUT_LOG", str(tmp_path / "input.jsonl"))
    return tmp_path


def test_a_scanned_book_keeps_its_map_page_and_handout_and_sketches_nothing(storage, claude, tmp_path):
    provider = ClaudeCliProvider(tmp_path / "data", MemorySessions())
    services = ConversionServices(
        storage=storage,
        conversion=lambda: (provider, BackendChoice("claude-cli", "fake")),
        ocr=fake_ocr,
    )
    book = [
        picture_page(scan(TEXT_GREY, text_marks)),
        picture_page(scan(MAP_GREY, map_marks)),
        picture_page(scan(HANDOUT_GREY, handout_marks)),
    ]
    path = write_pdf(tmp_path / "The Sunken Shrine.pdf", book)

    async def scenario():
        started = await start_pdf(services, path, "The Sunken Shrine", "draft")
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert done.status == "done", done.error
    inputs = [json.loads(line)["text"] for line in (tmp_path / "input.jsonl").read_text().splitlines()]
    assert len(inputs) == len(SIDE), "one chunk, its entities and the metadata: every side call went to the fake"
    assert inputs[0].startswith("You are converting part of") and "1. Flooded Stair" in inputs[0]

    module = storage.modules.get(done.module_id)
    assert module.metadata == {"summary": "Kobolds hold a drowned shrine.", "tags": ["dungeon", "kobolds"]}, "read from its text"
    source = load_source(storage, done.module_id)

    # The text page is text; the map page and the handout are kept as pictures.
    [text] = source.texts
    assert text.title == "The Sunken Shrine"
    for heading in ("## 1. Flooded Stair", "## 2. Hall of Echoes", "## 3. Drowned Altar"):
        assert heading in text.markdown, heading
    attachments = {a.id: a for a in source.attachments}
    assert list(attachments) == ["map-page-2", "page-3", "source-pdf"]
    assert attachments["map-page-2"].description == "Page 2: a map from the book (MAP 1 – THE SUNKEN SHRINE)"
    assert attachments["map-page-2"].type == attachments["page-3"].type == "image/png"
    assert attachments["page-3"].description == "Page 3: a map or full-page picture"

    # No OCR junk, and nothing OCR read on the map or the handout, is in any text.
    for markdown in [t.markdown for t in source.texts]:
        for read in ("wePr", "Sylar", "TON NIL", "COVERED PIT", "FALSE DOOR", "MAP 1"):
            assert read not in markdown, read

    # The map page is titled like the text, so the room key isn't sketched: the page is drafted instead.
    assert module.maps == () and text.map is None

    # Same-name NPCs are one, every keyed heading has an entry, and the encounter in area 2 is keyed to it.
    assert [npc["name"] for npc in source.entities["npcs"]] == ["Chief Muckfoot"]
    assert [(k["key"], k.get("encounter")) for k in source.keys] == [
        ("1", None),
        ("2", "encounter:hall-guards"),
        ("3", None),
    ]

    warnings = {(w["code"], w["ref"]) for w in done.warnings}
    assert ("book-map", "asset:map-page-2") in warnings
    assert ("image-to-describe", "asset:page-3") in warnings
    assert "map-sketched" not in {code for code, _ in warnings}
    assert not {code for code, _ in warnings} & {"numbers-changed", "page-not-read"}
