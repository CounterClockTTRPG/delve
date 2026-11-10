"""Conversions in the background (plateau 5 Task 4): a job per PDF or request, its progress as `conversion` events,
and a module made only at the end, in one transaction.

Claude is `FakeDM` with a side handler that answers by the prompt it gets: the convert prompt with the chunk's own
text (already Markdown in these books), the entities prompt with no records, the sketch prompt with a map of the
three rooms, and the generate prompt with a plan.
"""

import asyncio
import json
import re
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from delve.config import Config
from delve.conversions import (
    CONVERSION_TIMEOUT,
    ConversionRunning,
    ConversionServices,
    answer_questions,
    cancel,
    close_orphans,
    module_questions,
    runner,
    start_generate,
    start_job,
    start_pdf,
    wait,
)
from delve.conversions.dungeon_maps import drafts, draw_book_maps
from delve.conversions.runner import MAKING_NOTES
from delve.conversions.thorough import start_thorough
from delve.conversions.thorough.workspace import Workspace
from delve.dm.fake import FakeDM
from delve.dm.provider import Usage
from delve.domain.modules import ModuleMap
from delve.domain.settings import BackendChoice
from delve.modules.books.convert import CHUNK_BUDGET
from delve.modules.books.pdf import PdfBook, PdfPage, ReadStopped
from delve.modules.source import derive, load_source
from delve.storage import open_storage
from tests.fixtures.pdfs import picture_page, text_page, write_pdf, zero_page_pdf
from tests.modules.books.test_generate import PLAN
from tests.modules.books.test_sketch import GOOD

CAVES = [
    "# The Caves",
    "## 1. Entrance",
    "Worn steps lead down into the dark. A door to the east opens on the hall (area 2).",
    "## 2. Hall",
    "A long hall. The entrance is to the west; a passage south leads to the shrine (area C3).",
    "## C3. Shrine",
    "A kobold shrine to a dragon. The only way out is north, back to the hall.",
]


NO_BOOK_MAP = "# Sketched from the room key: an invented layout. No map page was found in the book.\n"
LEGEND = "MAP 3 – THE KOBOLD CAVES\nSECRET DOOR\nSTAIRS 1 2 3 4 5 6 7 8 9"
"""What OCR reads on the book's map page: its title, its legend and its room numbers."""


def _source_of(prompt: str) -> str:
    return re.search(r"<source>\n(.*)\n</source>", prompt, re.DOTALL).group(1)


class Claude:
    """The side handler: answers by the kind of prompt, and can be told to fail or to wait on a kind."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.seen: list[str] = []
        self.scope: dict = {"scale": "module", "questions": []}
        """What the scope call before Generate answers (DEL-134)."""
        self.pictures: list[dict] = []
        """What the choice of a generated module's pictures answers (DEL-347)."""

    @staticmethod
    def kind(prompt: str) -> str:
        if "<source>" in prompt:
            return "convert"
        if prompt.startswith(("You draw a schematic map", "You draw the map of a place")):
            return "sketch"
        if prompt.startswith("You write a small adventure module"):
            return "generate"
        if prompt.startswith("You help an organiser who asked for an adventure module"):
            return "scope"
        if prompt.startswith("You choose the pictures"):
            return "pictures"
        return "entities"

    def __call__(self, prompt: str) -> str:
        kind = self.kind(prompt)
        self.seen.append(kind)
        if kind == self.fail_on:
            raise RuntimeError("claude stopped (exit code 1): overloaded")
        if kind == "convert":
            return _source_of(prompt).replace("\n", "\n\n")
        if kind == "sketch":
            return GOOD
        if kind == "generate":
            return json.dumps(PLAN)
        if kind == "scope":
            return json.dumps(self.scope)
        if kind == "pictures":
            return json.dumps({"pictures": self.pictures})
        return "{}"


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _services(storage, claude: Claude) -> tuple[ConversionServices, FakeDM, list[tuple[str, dict]]]:
    dm = FakeDM([], side_handler=claude)
    events: list[tuple[str, dict]] = []
    services = ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        publish=lambda kind, data: events.append((kind, data)),
        ocr=None,
    )
    return services, dm, events


def _caves_pdf(tmp_path: Path) -> Path:
    return write_pdf(tmp_path / "upload.pdf", [text_page(CAVES), picture_page()])


def test_a_conversion_reports_progress_and_makes_a_module(storage, tmp_path):
    services, dm, events = _services(storage, Claude())
    path = _caves_pdf(tmp_path)
    pdf = path.read_bytes()

    async def scenario():
        started = await start_pdf(services, path, "The Kobold Caves", "ready")
        assert (started.kind, started.title, started.mode, started.status) == (
            "pdf",
            "The Kobold Caves",
            "ready",
            "running",
        )
        assert storage.conversions.get(started.id).status == "running", "a reload sees the running job"
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done" and done.error is None and done.module_id
    assert not path.exists(), "the uploaded file is the job's, removed when it ends"
    module = storage.modules.get(done.module_id)
    assert "homebrew" not in module.metadata.get("tags", []), "a converted book isn't homebrew (DEL-226)"
    assert module.title == "The Kobold Caves" and module.draft is False
    assert module.maps == (ModuleMap("the-caves", "map", NO_BOOK_MAP + GOOD, True),)

    source = load_source(storage, module.id)
    [text] = source.texts
    assert (text.id, text.title, text.audience, text.map) == ("the-caves", "The Caves", "gm", "the-caves")
    derived = derive(source, module.maps)
    assert sorted((link.key, link.map, link.node) for link in derived.links) == [
        ("1", "the-caves", "room.r1"),
        ("2", "the-caves", "room.r2"),
        ("C3", "the-caves", "room.rC3"),
    ]

    picture, original = source.attachments
    assert (picture.id, picture.type, picture.audience, picture.role) == ("page-2", "image/png", "gm", "attachment")
    assert storage.blobs.get(picture.sha256)[:8] == b"\x89PNG\r\n\x1a\n"
    assert (original.id, original.type, original.audience, original.role) == (
        "source-pdf",
        "application/pdf",
        "gm",
        "source",
    )
    assert original.description == "The original PDF" and original.size == len(pdf)
    assert storage.blobs.get(original.sha256) == pdf

    codes = [w["code"] for w in done.warnings]
    assert "image-to-describe" in codes
    [sketched] = [w for w in done.warnings if w["code"] == "map-sketched"]
    assert sketched == {
        "code": "map-sketched",
        "message": "Sketched from the room key: an invented layout; compare it with page 2.",
        "ref": "map:the-caves",
    }

    conversion = [data for kind, data in events if kind == "conversion"]
    assert all(set(data) == {"id", "status", "step", "done", "total", "steps", "cost_usd"} for data in conversion)
    steps = [data["step"] for data in conversion]
    for step in ("reading", "converting", "entities", "pictures", "maps"):
        assert step in steps
    assert steps.index("reading") < steps.index("converting") < steps.index("maps")
    converting = [(d["done"], d["total"]) for d in conversion if d["step"] == "converting"]
    assert converting[0] == (0, 2) and converting[-1] == (2, 2), "pages done out of pages"
    assert conversion[-1]["status"] == "done"
    assert all(d["status"] == "running" for d in conversion[:-1])
    assert set(dm.side_timeouts) == {CONVERSION_TIMEOUT}
    assert len(dm.side_prompts) == len(dm.side_timeouts)


def test_a_pdf_job_reads_lost_glyphs_from_the_page_in_step_3(storage, tmp_path):
    """D3: a stat line whose ½ the text layer lost is read again from its page's picture, after the conversion."""
    assert runner.STEPS["pdf"][2] == ("converting", "gaps")
    goblins = ["# The Store", "Two goblins guard the barrels.", "Goblins (2): AC 7; HD ; hp 4; #AT 1; D 1-6."]

    def vision(prompt: str, image: bytes, media_type: str) -> str:
        assert media_type == "image/png" and image
        return json.dumps([{"n": 1, "line": "Goblins (2): AC 7; HD ½; hp 4; #AT 1; D 1-6."}])

    dm = FakeDM([], side_handler=Claude(), vision_handler=vision)
    events: list[tuple[str, dict]] = []
    services = ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        publish=lambda kind, data: events.append((kind, data)),
        ocr=None,
    )

    async def scenario():
        path = write_pdf(tmp_path / "upload.pdf", [text_page(goblins), text_page(["Another page of text."])])
        started = await start_pdf(services, path, "The Store", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done", done.error
    [prompt] = dm.vision_prompts
    assert "page 1" in prompt and "HD ;" in prompt
    [text] = load_source(storage, done.module_id).texts
    assert "AC 7; HD ½; hp 4" in text.markdown
    assert [w["code"] for w in done.warnings if w["code"].startswith("text-")] == ["text-filled"]
    gaps = [(d["done"], d["total"], d["steps"]) for k, d in events if k == "conversion" and d["step"] == "gaps"]
    assert gaps == [(0, 1, {"index": 3, "count": 5}), (1, 1, {"index": 3, "count": 5})]


def test_a_conversion_sums_what_its_calls_cost(storage, tmp_path):
    """G2: every side and vision call's cost goes into the job's `cost_usd`, stored as it goes."""
    dm = FakeDM([], side_handler=Claude(), side_usage=Usage(1000, 50, 0.01))
    services = ConversionServices(
        storage=storage, conversion=lambda: (dm, BackendChoice("fake", "fake-large")), ocr=None
    )
    stored: list[float | None] = []
    save = storage.conversions.save
    storage.conversions.save = lambda conversion: stored.append(conversion.cost_usd) or save(conversion)

    async def scenario():
        path = write_pdf(tmp_path / "upload.pdf", [text_page(CAVES)])
        started = await start_pdf(services, path, "The Kobold Caves", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done", done.error
    assert len(dm.side_prompts) + len(dm.vision_prompts) == 4, "convert, entities, the sketch and the metadata"
    assert done.cost_usd == pytest.approx(0.04)
    assert storage.conversions.get(done.id).cost_usd == pytest.approx(0.04)
    assert sorted({round(c, 2) for c in stored if c is not None}) == [0.01, 0.02, 0.03, 0.04], "saved as it goes"
    assert runner.conversion_json(done)["cost_usd"] == pytest.approx(0.04)


def test_a_conversion_with_no_reported_cost_has_none(storage, tmp_path):
    services, _, _ = _services(storage, Claude())

    async def scenario():
        started = await start_pdf(services, write_pdf(tmp_path / "upload.pdf", [text_page(CAVES)]), "Caves", "ready")
        return await wait(services, started.id)

    assert asyncio.run(scenario()).cost_usd is None


def _convert_with_ocr(storage, tmp_path, pages, ocr_text: str = LEGEND, title: str = "The Kobold Caves"):
    services, _, _ = _services(storage, Claude())
    services.ocr = lambda png: ocr_text

    async def scenario():
        started = await start_pdf(services, write_pdf(tmp_path / "upload.pdf", pages), title, "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert done.status == "done", done.error
    return done, storage.modules.get(done.module_id), load_source(storage, done.module_id)


def test_no_sketch_when_a_map_page_matches(storage, tmp_path):
    """B5: the text "The Caves" and the plate "MAP 3 – THE KOBOLD CAVES" share "caves": the plate is drafted after the
    conversion (`draw_book_maps`), and the room key isn't sketched as an invented layout."""
    done, module, source = _convert_with_ocr(storage, tmp_path, [text_page(CAVES), picture_page()])

    assert module.maps == ()
    assert [a.id for a in source.attachments] == ["map-page-2", "source-pdf"]
    [text] = source.texts
    assert text.map is None
    assert not [w for w in done.warnings if w["code"] == "map-sketched"]


def test_a_text_with_no_map_page_is_sketched_as_invented(storage, tmp_path):
    """B5: a map page titled for another place matches no text, so the text gets its room-key sketch, which says no
    map page was found and is named after its text, never after that page."""
    plate = "MAP 4 – THE DRAGON TOWER\nSECRET DOOR\nSTAIRS 1 2 3 4 5 6 7 8 9"
    done, module, source = _convert_with_ocr(storage, tmp_path, [text_page(CAVES), picture_page()], ocr_text=plate)

    [sketch] = module.maps
    assert sketch.name == "the-caves" and sketch.source == NO_BOOK_MAP + GOOD
    assert source.texts[0].map == "the-caves"
    assert sorted(link.node for link in derive(source, module.maps).links) == ["room.r1", "room.r2", "room.rC3"]
    [sketched] = [w for w in done.warnings if w["code"] == "map-sketched"]
    assert sketched["message"] == "Sketched from the room key: an invented layout; compare it with page 2."


@pytest.mark.parametrize(
    ("text", "plate", "shared"),
    [
        ("PART ONE — THE HAUNTED HOUSE", "Haunted House", 2),
        ("The Caves", "MAP 3 – THE KOBOLD CAVES", 1),
        ("Part Two — The Sea Ghost", "The Sea Ghost: main deck and lower deck", 1),
        ("The Haunted House", "The Sea Ghost: decks", 0),
        ("Part One: the map", "Map of part one", 0),
        ("The Caves", "", 0),
    ],
)
def test_plate_matches_counts_the_words_they_share(text, plate, shared):
    assert runner.plate_matches(text, plate) == shared


def test_a_sketched_map_is_never_named_after_the_module(storage, tmp_path):
    # The rooms come before any chapter, so their text is titled by the module; the map page has no title.
    _, module, source = _convert_with_ocr(
        storage, tmp_path, [text_page(CAVES[1:]), picture_page()], ocr_text="SECRET DOOR STAIRS"
    )

    [sketch] = module.maps
    assert source.texts[0].title == "The Kobold Caves"
    assert sketch.name == "sketch" and source.texts[0].map == "sketch"


def test_the_reading_counts_its_pages_and_every_step_says_which_of_how_many(storage, tmp_path):
    services, _, events = _services(storage, Claude())
    path = write_pdf(tmp_path / "upload.pdf", [text_page(CAVES[:3]), text_page(CAVES[3:]), picture_page()])

    async def scenario():
        started = await start_pdf(services, path, "The Kobold Caves", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    conversion = [data for kind, data in events if kind == "conversion"]
    reading = [(d["done"], d["total"]) for d in conversion if d["step"] == "reading"]
    assert reading == [(0, 0), (1, 3), (2, 3), (3, 3)], "a count per page read, so OCR shows 12 of 38 pages"
    index = {"reading": 1, "classifying": 2, "converting": 3, "gaps": 3, "entities": 4, "pictures": 4, "maps": 5}
    assert all(d["steps"] == {"index": index[d["step"]], "count": 5} for d in conversion)
    assert runner.conversion_json(done)["steps"] == {"index": 5, "count": 5}


def test_a_pdf_job_classifies_its_picture_pages_in_step_2_of_5(storage, tmp_path):
    """A2: after the reading, Claude looks at each whole-page picture the reading didn't find a map on; a map answer
    makes it a map page, which is drafted after the conversion rather than its text sketched (B5)."""
    assert runner.STEPS["pdf"] == (
        ("reading",),
        ("classifying",),
        ("converting", "gaps"),
        ("entities", "pictures"),
        ("maps",),
    )
    dm = FakeDM(
        [], side_handler=Claude(), vision_handler=lambda *_: '{"kind": "map", "title": "The Kobold Caves: level 1"}'
    )
    events: list[tuple[str, dict]] = []
    services = ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        publish=lambda kind, data: events.append((kind, data)),
        ocr=None,
    )

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    conversion = [d for k, d in events if k == "conversion"]
    classifying = [(d["done"], d["total"], d["steps"]) for d in conversion if d["step"] == "classifying"]
    assert classifying == [(0, 1, {"index": 2, "count": 5}), (1, 1, {"index": 2, "count": 5})]
    assert len(dm.vision_images) == 1
    module = storage.modules.get(done.module_id)
    assert module.maps == (), "the classified map page matches the text: it is drafted, not sketched"
    page = load_source(storage, done.module_id).attachment("map-page-2")
    assert page is not None and page.description.startswith("Page 2: a map from the book")


def test_a_generated_module_has_two_steps(storage):
    services, dm, events = _services(storage, Claude())

    async def scenario():
        started = await start_generate(services, "a dungeon with kobolds, no plot", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert "homebrew" in storage.modules.get(done.module_id).metadata["tags"], "a generated module is (DEL-226)"
    steps = [(d["step"], d["steps"]) for k, d in events if k == "conversion"]
    assert ("generating", {"index": 1, "count": 2}) in steps
    assert steps[-1] == ("maps", {"index": 2, "count": 2})
    # A request that came without its scale is scoped first, in a conversion's call. A module is one long answer, so
    # its plan and its map wait longer than a conversion's call; the metadata after them keeps a conversion's.
    assert dm.side_timeouts == [
        runner.CONVERSION_TIMEOUT,
        runner.GENERATE_TIMEOUT,
        runner.GENERATE_TIMEOUT,
        runner.CONVERSION_TIMEOUT,
    ]
    assert ("scoping", {"index": 1, "count": 2}) in steps


def test_a_long_request_is_titled_at_a_word(storage):
    services, _, _ = _services(storage, Claude())
    request = ("A sprawling dungeon of kobold warrens beneath the old salt mine " * 4).strip()[:200]

    async def scenario():
        started = await start_generate(services, request + "\nwith a second line", "ready")
        await wait(services, started.id)
        return started

    title = asyncio.run(scenario()).title
    assert len(title) <= 80 and title.endswith("…")
    assert request.startswith(title.removesuffix("…").rstrip()), "cut at a word, never mid-word"
    assert request[len(title.removesuffix("…").rstrip())] == " "


def test_cancel_leaves_no_module(storage, tmp_path):
    claude = Claude()
    services, _, events = _services(storage, claude)
    path = _caves_pdf(tmp_path)

    async def scenario():
        started = await start_pdf(services, path, "The Kobold Caves", "ready")
        while "sketch" not in claude.seen:  # the last Claude step: everything else is made, nothing stored yet
            await asyncio.sleep(0)
        cancelled = await cancel(services, started.id)
        assert cancelled.status == "cancelled"
        assert await cancel(services, started.id) == cancelled, "cancelling again changes nothing"
        return await wait(services, started.id)

    ended = asyncio.run(scenario())

    assert ended.status == "cancelled" and ended.module_id is None
    assert storage.modules.list() == []
    assert not path.exists()
    assert [d["status"] for k, d in events if k == "conversion"][-1] == "cancelled"


def test_a_failed_call_fails_the_job_with_its_reason(storage, tmp_path):
    # A failed entities call is only a warning (plan Review Focus 2); a failed convert call fails the job.
    services, _, events = _services(storage, Claude(fail_on="convert"))

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        return await wait(services, started.id)

    failed = asyncio.run(scenario())

    assert failed.status == "failed" and failed.module_id is None
    assert failed.error == "claude stopped (exit code 1): overloaded"
    assert storage.modules.list() == []
    assert events[-1] == (
        "conversion",
        {
            "id": failed.id,
            "status": "failed",
            "step": "converting",
            "done": failed.done,
            "total": failed.total,
            "steps": {"index": 3, "count": 5},
            "cost_usd": failed.cost_usd,
        },
    )


def test_a_failed_chunk_call_is_tried_again(storage, tmp_path):
    """A transient failure (an overloaded backend) of one chunk's call doesn't lose the whole book: it is asked again
    after each of `RETRY_DELAYS`, and only the last failure fails the job."""
    claude = Claude()
    left = [2]

    def flaky(prompt: str) -> str:
        if claude.kind(prompt) == "convert" and left[0]:
            left[0] -= 1
            claude.seen.append("convert")
            raise RuntimeError("claude stopped (exit code 1): overloaded")
        return claude(prompt)

    services, _, _ = _services(storage, flaky)

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done", done.error
    assert claude.seen.count("convert") == 3, "two failures, then the third attempt"


@pytest.mark.parametrize(
    "error",
    [
        "claude stopped (exit code 1): You've hit your session limit · resets 3pm (UTC)",
        "claude stopped (exit code 1): API Error: Output blocked by content filtering policy",
    ],
)
def test_the_usage_limit_or_the_content_filter_isnt_tried_again(storage, tmp_path, error):
    """Asked again, the limit and the filter answer the same: the chunk's job fails at once, as before."""
    claude = Claude()

    def lasting(prompt: str) -> str:
        if claude.kind(prompt) == "convert":
            claude.seen.append("convert")
            raise RuntimeError(error)
        return claude(prompt)

    services, _, _ = _services(storage, lasting)

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        return await wait(services, started.id)

    failed = asyncio.run(scenario())

    assert failed.status == "failed" and failed.error == error
    assert claude.seen.count("convert") == 1


def test_a_pdf_that_cant_be_read_fails_with_the_readers_message(storage, tmp_path):
    services, dm, _ = _services(storage, Claude())
    path = tmp_path / "empty.pdf"
    path.write_bytes(zero_page_pdf())

    async def scenario():
        started = await start_pdf(services, path, "Nothing", "draft")
        return await wait(services, started.id)

    failed = asyncio.run(scenario())

    assert (failed.status, failed.step, failed.error) == ("failed", "reading", "The PDF has no pages.")
    assert storage.modules.list() == [] and dm.side_prompts == []


def test_orphans_are_closed_at_start(storage):
    finished = storage.conversions.create("generate", "Kobolds", "ready")
    storage.conversions.save(replace(finished, status="done"))
    left = storage.conversions.create("pdf", "The Kobold Caves", "ready")

    closed = close_orphans(storage)

    assert [c.id for c in closed] == [left.id]
    orphan = storage.conversions.get(left.id)
    assert (orphan.status, orphan.error) == ("failed", "Delve stopped during the conversion.")
    assert storage.conversions.get(finished.id).status == "done"
    assert close_orphans(storage) == []


def test_then_runs_once_the_module_is_made_with_no_job_running(storage, tmp_path):
    services, _, _ = _services(storage, Claude())
    seen = []

    async def then(conversion):
        seen.append((conversion.status, conversion.module_id, dict(services.live)))

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready", then=then)
        done = await wait(services, started.id)
        await asyncio.gather(*services.follow_ups)
        return done

    done = asyncio.run(scenario())
    assert seen == [("done", done.module_id, {})]
    assert services.follow_ups == set()


def test_then_doesnt_run_for_a_failed_job(storage, tmp_path):
    services, _, _ = _services(storage, Claude(fail_on="convert"))
    seen = []

    async def then(conversion):
        seen.append(conversion)

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready", then=then)
        await wait(services, started.id)
        await asyncio.gather(*services.follow_ups)

    asyncio.run(scenario())
    assert seen == []


def test_a_failed_then_is_a_warning_of_the_done_job(storage, tmp_path):
    """`then` runs as a task of its own after the job is done: its failure is a warning on the job, not an exception
    no one retrieves."""
    services, _, _ = _services(storage, Claude())

    async def then(conversion):
        raise RuntimeError("the maps broke")

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready", then=then)
        await wait(services, started.id)
        await asyncio.gather(*services.follow_ups)
        return started

    started = asyncio.run(scenario())

    job = storage.conversions.get(started.id)
    assert job.status == "done"
    assert any(w["code"] == runner.FOLLOW_UP_FAILED and "the maps broke" in w["message"] for w in job.warnings)


def test_a_converted_book_gets_a_draft_drawn_from_its_map_page(storage, tmp_path):
    claude = Claude()
    dm = FakeDM([], side_handler=claude, vision_handler=lambda prompt, image, media_type: f"```dmap\n{GOOD}```")
    services = ConversionServices(
        storage=storage, conversion=lambda: (dm, BackendChoice("fake", "fake-large")), ocr=lambda png: LEGEND
    )

    async def scenario():
        pdf = write_pdf(tmp_path / "upload.pdf", [text_page(CAVES), picture_page()])
        started = await start_pdf(
            services, pdf, "The Kobold Caves", "ready", then=lambda c: draw_book_maps(services, c.module_id)
        )
        done = await wait(services, started.id)
        await asyncio.gather(*services.follow_ups)
        return done

    done = asyncio.run(scenario())
    [draft] = drafts(storage, done.module_id)
    assert (draft["kind"], draft["name"]) == ("book-map", "map-3-the-kobold-caves")
    assert draft["source"].startswith("# Drawn from the book's map")
    assert len(dm.vision_images) == 1


def test_one_conversion_at_a_time(storage, tmp_path):
    services, _, _ = _services(storage, Claude())

    async def scenario():
        first = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        with pytest.raises(ConversionRunning) as refused:
            await start_job(services, "dungeon-map", "A crypt", lambda live: asyncio.sleep(0))
        assert str(refused.value) == "A conversion is running."
        assert refused.value.conversion.id == first.id
        second_pdf = write_pdf(tmp_path / "second.pdf", [text_page(CAVES)])
        queued = await start_pdf(services, second_pdf, "Again", "ready")
        assert queued.status == "queued" and second_pdf.exists(), "a book waits in the queue (owner addition)"
        await wait(services, first.id)
        assert storage.conversions.get(queued.id).status == "running", "it starts when the slot frees"
        await wait(services, queued.id)
        second = await start_generate(services, "A dungeon with kobolds, no plot.", "ready")
        return await wait(services, second.id)

    second = asyncio.run(scenario())
    assert second.status == "done"
    assert len(storage.conversions.list()) == 3


def test_a_running_job_left_by_a_stopped_delve_blocks_nothing(storage, tmp_path):
    """A row still `running` that no task of this process runs is an orphan: a start closes it first."""
    left = storage.conversions.create("pdf", "Left", "ready")
    services, _, _ = _services(storage, Claude())

    async def scenario():
        started = await start_generate(services, "A dungeon with kobolds, no plot.", "ready")
        return await wait(services, started.id)

    assert asyncio.run(scenario()).status == "done"
    assert storage.conversions.get(left.id).status == "failed"


def test_a_300_page_book_is_called_in_chunks_with_the_conversion_timeout(storage, tmp_path, monkeypatch):
    """The reader is Task 1's, tested there; here it hands over 300 pages of about 1300 characters each, so the
    test is quick."""
    pages = [PdfPage(n, f"Page {n} " + " ".join(f"word{i}" for i in range(200)), False, []) for n in range(1, 301)]
    monkeypatch.setattr(runner, "read_pdf", lambda path, *, ocr, should_stop, progress: PdfBook(pages, []))
    services, dm, events = _services(storage, Claude())
    path = write_pdf(tmp_path / "big.pdf", [text_page(["The Big Book"])])

    async def scenario():
        started = await start_pdf(services, path, "The Big Book", "draft")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done"
    converts = [p for p in dm.side_prompts if "<source>" in p]
    assert 10 < len(converts) < 300
    assert all(len(_source_of(p)) <= CHUNK_BUDGET + 300 for p in converts)
    for n in (1, 150, 300):
        assert sum(f"Page {n} " in _source_of(p) for p in converts) == 1, "every page is sent once"
    assert set(dm.side_timeouts) == {CONVERSION_TIMEOUT}
    converting = [(d["done"], d["total"]) for k, d in events if k == "conversion" and d["step"] == "converting"]
    assert converting[0] == (0, 300) and converting[-1] == (300, 300)
    assert [d for d, _ in converting] == sorted(d for d, _ in converting)
    assert (done.step, done.done, done.total) == ("maps", 0, 0), "no text has keyed rooms, so nothing is sketched"


def test_a_draft_module_is_marked_draft(storage, tmp_path):
    services, _, _ = _services(storage, Claude())

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "draft")
        return await wait(services, started.id)

    done = asyncio.run(scenario())
    assert storage.modules.get(done.module_id).draft is True


def test_a_request_generates_a_module(storage):
    services, _, events = _services(storage, Claude())

    async def scenario():
        started = await start_generate(services, "A small dungeon with kobolds, no plot.", "ready")
        assert (started.kind, started.mode) == ("generate", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done" and done.title == "The Kobold Caves"
    module = storage.modules.get(done.module_id)
    assert module.title == "The Kobold Caves" and module.draft is False
    assert [m.name for m in module.maps] == ["map"]
    source = load_source(storage, module.id)
    assert len(derive(source, module.maps).links) == 3
    assert source.attachments == []
    assert [d["step"] for k, d in events if k == "conversion"][-1] == "maps"


def test_a_mode_is_ready_or_draft(storage, tmp_path):
    services, _, _ = _services(storage, Claude())
    with pytest.raises(ValueError, match="ready or draft"):
        asyncio.run(start_generate(services, "Kobolds.", "later"))
    assert storage.conversions.list() == []


def test_an_ended_job_stays_ended(storage, tmp_path):
    """A progress call after the end changes nothing: no `running` again, no event, and no clash with the next job's
    row on the one-running index."""
    services, _, events = _services(storage, Claude(fail_on="convert"))

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        live = services.live[started.id]
        return live, await wait(services, started.id)

    live, failed = asyncio.run(scenario())
    assert failed.status == "failed"
    assert live.conversion == failed, "the job's row is the ended one"
    next_job = storage.conversions.create("generate", "Kobolds", "ready")
    published = len(events)

    runner.progress_for(services, live)("converting", 2, 2)

    assert storage.conversions.get(failed.id) == failed
    assert storage.conversions.running() == next_job
    assert len(events) == published


def _slow_reader(pages: int):
    """A reader that takes a while per page and asks `should_stop` before each, as `read_pdf` does."""
    state = {"read": 0, "reading": threading.Event(), "stopped": threading.Event(), "returned": threading.Event()}

    def read(path, *, ocr, should_stop, progress=None):
        try:
            for n in range(1, pages + 1):
                if should_stop():
                    state["stopped"].set()
                    raise ReadStopped(f"The reading was stopped before page {n}.")
                state["reading"].set()
                time.sleep(0.005)
                state["read"] = n
            return PdfBook([PdfPage(n, CAVES[0], False, []) for n in range(1, pages + 1)], [])
        finally:
            state["returned"].set()

    return read, state


def test_a_cancel_while_reading_stops_the_reading(storage, tmp_path, monkeypatch):
    read, state = _slow_reader(1000)
    monkeypatch.setattr(runner, "read_pdf", read)
    services, dm, events = _services(storage, Claude())

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        assert await asyncio.to_thread(state["reading"].wait, 5)
        cancelled = await cancel(services, started.id)
        assert await asyncio.to_thread(state["returned"].wait, 5), "the reading thread ends"
        return cancelled

    cancelled = asyncio.run(scenario())

    assert (cancelled.status, cancelled.step) == ("cancelled", "reading")
    assert state["stopped"].is_set() and state["read"] < 1000, "the reading stops at the next page"
    assert storage.modules.list() == [] and dm.side_prompts == []
    assert [d["status"] for k, d in events if k == "conversion"][-1] == "cancelled"


def test_a_reading_that_stops_ends_as_cancelled(storage, tmp_path, monkeypatch):
    def stopped(path, *, ocr, should_stop, progress=None):
        raise ReadStopped("The reading was stopped before page 3.")

    monkeypatch.setattr(runner, "read_pdf", stopped)
    services, _, _ = _services(storage, Claude())

    async def scenario():
        started = await start_pdf(services, _caves_pdf(tmp_path), "The Kobold Caves", "ready")
        return await wait(services, started.id)

    ended = asyncio.run(scenario())
    assert (ended.status, ended.error, ended.module_id) == ("cancelled", None, None)


def test_a_text_whose_keys_repeat_is_not_sketched(storage, tmp_path):
    """Two levels each keyed 1..3: a sketch would have two rooms of each name."""
    levels = ["# The Two Levels", "## Upper Level"]
    for level in ("Upper", "Lower"):
        if level == "Lower":
            levels.append("## Lower Level")
        for n, name in ((1, "Stairs"), (2, "Hall"), (3, "Store")):
            levels += [f"### {n}. {level} {name}", f"The {level.lower()} {name.lower()}, dusty and dark."]
    claude = Claude()
    services, _, _ = _services(storage, claude)
    path = write_pdf(tmp_path / "levels.pdf", [text_page(levels)])

    async def scenario():
        started = await start_pdf(services, path, "The Two Levels", "ready")
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done"
    assert "sketch" not in claude.seen
    assert storage.modules.get(done.module_id).maps == ()
    [text] = load_source(storage, done.module_id).texts
    assert text.map is None
    assert {
        "code": "map-not-drawn",
        "message": "The keys repeat in this text, so its map wasn't sketched; draw it by hand.",
        "ref": f"text:{text.id}",
    } in done.warnings
    assert (done.step, done.done, done.total) == ("maps", 0, 0)


# --- questions while making a module (plateau 7 Task 20) -------------------------------------------------------------

ASKED = [
    {"text": "Should Grik bargain?", "default": "He bargains for his life."},
    {"text": "Is the shrine's dragon real?", "default": "No, a carving."},
]


class AskingClaude(Claude):
    """`Claude`, whose plan ends with two questions."""

    def __call__(self, prompt: str) -> str:
        answer = super().__call__(prompt)
        if self.kind(prompt) == "generate":
            return f"{answer}\n\n```questions\n{json.dumps(ASKED)}\n```"
        return answer


def _generated(storage, claude: Claude):
    services, _, _ = _services(storage, claude)

    async def scenario():
        started = await start_generate(services, "A small dungeon with kobolds.", "ready")
        return await wait(services, started.id)

    return asyncio.run(scenario())


def test_a_module_made_with_questions_keeps_them_on_its_job(storage):
    done = _generated(storage, AskingClaude())
    assert done.questions == {
        "questions": [
            {"id": "q1", "text": "Should Grik bargain?", "default": "He bargains for his life.", "answer": None},
            {"id": "q2", "text": "Is the shrine's dragon real?", "default": "No, a carving.", "answer": None},
        ],
        "remarks": [],
    }
    assert _generated(storage, Claude()).questions is None


def test_answers_and_remarks_are_written_into_the_making_notes(storage):
    done = _generated(storage, AskingClaude())
    texts_before = [t.id for t in load_source(storage, done.module_id).texts]

    entry = answer_questions(storage, done.id, {"q1": "No, he fights to the end.", "q2": "  "}, ["More kobolds.", ""])

    assert entry["questions"][0]["answer"] == "No, he fights to the end."
    assert entry["questions"][1]["answer"] is None and entry["remarks"] == ["More kobolds."]
    source = load_source(storage, done.module_id)
    notes = next(t for t in source.texts if t.id == MAKING_NOTES)
    assert (notes.title, notes.audience) == ("Notes from making this module", "gm")
    assert [t.id for t in source.texts] == [*texts_before, MAKING_NOTES]
    assert "Should Grik bargain?" in notes.markdown and "No, he fights to the end." in notes.markdown
    assert "Assumed: No, a carving." in notes.markdown
    assert "More kobolds." in notes.markdown

    again = answer_questions(storage, done.id, {}, [])
    notes = next(t for t in load_source(storage, done.module_id).texts if t.id == MAKING_NOTES)
    assert "Assumed: He bargains for his life." in notes.markdown and "More kobolds." not in notes.markdown
    assert again["remarks"] == []
    assert storage.conversions.get(done.id).status == "done", "the job isn't run again"


def test_answering_an_unknown_question_or_job_is_refused(storage):
    done = _generated(storage, AskingClaude())
    with pytest.raises(ValueError):
        answer_questions(storage, done.id, {"q9": "?"}, [])
    with pytest.raises(KeyError):
        answer_questions(storage, "cnv_missing", {}, [])
    with pytest.raises(KeyError):
        answer_questions(storage, _generated(storage, Claude()).id, {}, [])


def test_the_modules_questions_are_found_after_twenty_later_conversions(storage):
    done = _generated(storage, AskingClaude())
    for n in range(21):
        later = storage.conversions.create("generate", f"Module {n}", "ready")
        storage.conversions.save(replace(later, status="done"))

    [entry] = module_questions(storage, done.module_id)
    assert entry["conversion_id"] == done.id and len(entry["questions"]) == 2
    assert module_questions(storage, storage.modules.create("Elsewhere").id) == []


def test_complete_with_uses_its_own_choice_and_adds_each_calls_cost_to_the_job(storage):
    """Novelization Task 2: a job of another Preferences job (`novel`) calls through `complete_with`, with its own
    choice and timeout; each call's usage still goes into the job's `cost_usd`."""
    novel_dm = FakeDM([], side_handler=lambda prompt: f"written: {prompt}", side_usage=Usage(1000, 50, 0.01))
    novel_choice = BackendChoice("fake", "fake-small")

    def no_conversion_choice():
        raise AssertionError("the conversion job's choice isn't asked")

    services = ConversionServices(storage=storage, conversion=no_conversion_choice, ocr=None)
    answers: list[str] = []

    async def work(live):
        complete = runner.complete_with(services, live, lambda: (novel_dm, novel_choice), 123.0)
        answers.append(await complete("the outline"))
        answers.append(await complete("chapter 1"))
        runner.finish(services, live)

    async def scenario():
        started = await runner.start_job(services, "novel", "Novel: The Crypt", work)
        return await wait(services, started.id)

    done = asyncio.run(scenario())

    assert done.status == "done", done.error
    assert answers == ["written: the outline", "written: chapter 1"]
    assert novel_dm.side_timeouts == [123.0, 123.0]
    assert done.cost_usd == pytest.approx(0.02)
    assert storage.conversions.get(done.id).cost_usd == pytest.approx(0.02)


# ----- thorough jobs (thorough conversion Task 4) -----


def _thorough(storage, tmp_path, status: str = "running", *, state: bool = True):
    """A thorough job's row, as a Delve that stopped left it, and its folder with its state, or without."""
    job = storage.conversions.create("pdf", "The Kobold Caves", "ready")
    if state:
        ws = Workspace.create(job.id, tmp_path / "data", _caves_pdf(tmp_path))
    else:
        ws = Workspace(tmp_path / "data" / "conversions" / job.id)
        ws.root.mkdir(parents=True)
    job = storage.conversions.save(replace(job, status=status, target={"thorough": True, "folder": str(ws.root)}))
    return job, ws


def test_orphans_that_are_thorough_are_paused_with_their_folder_kept(storage, tmp_path):
    job, ws = _thorough(storage, tmp_path)

    [closed] = close_orphans(storage)

    assert (closed.id, closed.status, closed.error) == (job.id, "paused", None)
    assert ws.exists() and ws.state().paused.reason == "Delve stopped"
    assert close_orphans(storage) == [], "a paused job is no orphan"


def test_a_thorough_orphan_stopped_while_copying_the_book_fails(storage, tmp_path):
    _, ws = _thorough(storage, tmp_path, state=False)

    [closed] = close_orphans(storage)

    assert (closed.status, closed.error) == ("failed", "Delve stopped during the conversion.")
    assert not ws.root.exists()


def test_cancel_removes_folder(storage, tmp_path):
    services, _, events = _services(storage, Claude())
    paused, paused_ws = _thorough(storage, tmp_path, "paused")

    async def scenario():
        services.resumes[paused.id] = asyncio.get_running_loop().call_later(3600, lambda: None)
        handle = services.resumes[paused.id]
        cancelled = await cancel(services, paused.id)
        assert handle.cancelled() and services.resumes == {}, "its scheduled resume is dropped"
        return cancelled

    cancelled = asyncio.run(scenario())
    assert cancelled.status == "cancelled" and not paused_ws.root.exists()
    assert events[-1] == ("conversion", {**events[-1][1], "id": paused.id, "status": "cancelled"})

    async def running():
        hang = asyncio.Event()

        async def pipeline(services, live, ws):
            hang.set()
            await asyncio.Event().wait()

        started = await start_thorough(
            services, _caves_pdf(tmp_path), "Caves", "ready", data_dir=tmp_path / "data", pipeline=pipeline
        )
        await hang.wait()
        return await cancel(services, started.id)

    cancelled = asyncio.run(running())
    assert cancelled.status == "cancelled"
    assert not (tmp_path / "data" / "conversions" / cancelled.id).exists()
    assert storage.modules.list() == []


def test_paused_job_does_not_block_a_new_job(storage, tmp_path):
    paused, ws = _thorough(storage, tmp_path, "paused")
    services, _, _ = _services(storage, Claude())

    async def scenario():
        started = await start_generate(services, "A dungeon with kobolds, no plot.", "ready")
        return await wait(services, started.id)

    assert asyncio.run(scenario()).status == "done"
    assert storage.conversions.get(paused.id).status == "paused" and ws.exists()


def test_the_call_timeout_comes_from_the_environment():
    """DEL-139: `DELVE_CALL_TIMEOUT` sets a conversion's, a novel's and a history's per-call timeout; anything but a
    positive number keeps the default."""
    from delve.conversions.runner import DEFAULT_CONVERSION_TIMEOUT, conversion_timeout

    assert conversion_timeout({}) == DEFAULT_CONVERSION_TIMEOUT == 600.0
    assert conversion_timeout({"DELVE_CALL_TIMEOUT": "1800"}) == 1800.0
    for bad in ("", "soon", "0", "-5"):
        assert conversion_timeout({"DELVE_CALL_TIMEOUT": bad}) == DEFAULT_CONVERSION_TIMEOUT, bad


def test_keyed_rooms_are_cut_from_the_body_after_the_front_matter():
    """Each room gets its own text even when the text has front matter, whose lines `Section.line` counts (DEL-162)."""
    from delve.conversions.runner import _keyed_rooms
    from delve.modules.source import TextDoc

    markdown = "---\ntitle: The crypt\naudience: dm\n---\n# The crypt\n\n## 1. Hall\n\nA long hall.\n\n## 2. Vault\n\nA locked vault.\n"
    rooms = _keyed_rooms(TextDoc("crypt", "The crypt", "dm", None, markdown))
    assert rooms == [("1", "## 1. Hall\n\nA long hall."), ("2", "## 2. Vault\n\nA locked vault.")]
