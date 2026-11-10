"""Dungeon-map drafts (plan 7 Task 13): Claude draws a map from a description, or from the book's map page, as a
conversion job that makes no module. The draft is the job's `result`; nothing is saved in the module until the
organiser keeps it, and a discarded draft is no longer listed."""

import asyncio
import io
import itertools
from dataclasses import replace

import pytest
from PIL import Image

from delve.config import Config
from delve.conversions import ConversionServices, cancel, wait
from delve.conversions.dungeon_maps import (
    DraftMismatch,
    discard_draft,
    drafts,
    draw_book_maps,
    keep_draft,
    mismatch,
    start_book_map,
    start_dungeon_map,
)
from delve.conversions.runner import SKETCHED
from delve.dm.fake import FakeDM
from delve.dm.provider import Usage
from delve.domain.modules import ModuleMap
from delve.domain.settings import BackendChoice
from delve.modules.books.sketch import DESCRIBED, FROM_BOOK
from delve.modules.dscn import Bundle, check
from delve.modules.exporter import export_module
from delve.modules.source import ATTACHMENT, Attachment, ModuleSource, TextDoc, derive, load_source, save_source
from delve.storage import open_storage
from tests.modules.books.test_sketch import BROKEN, GOOD

CAVES_TEXT = """\
# The Kobold Caves

## 1. Entrance

Worn steps lead down into the dark. A door to the east opens on the hall (area 2).

## 2. Hall

A long hall. A passage south leads to the shrine (area C3).

## C3. Shrine

A kobold shrine to a dragon.
"""
SKETCH = f"{SKETCHED} The book's map is asset:map-page-3.\n{GOOD}"
DESCRIPTION = "A kobold warren: an entrance, a long hall and a shrine at the back."


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 200), (240, 236, 220)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def _module(storage, *, sketched: bool = True) -> str:
    """A module with a keyed text, its book's map page, and (when `sketched`) the map sketched from its key."""
    module = storage.modules.create("The Kobold Caves")
    page = _png()
    sha = storage.blobs.put(page, "image/png")
    storage.blobs.link(module.id, ATTACHMENT, sha)
    notes = storage.blobs.put(b"notes", "application/pdf")
    storage.blobs.link(module.id, ATTACHMENT, notes)
    text = TextDoc("caves", "The Kobold Caves", "gm", "caves" if sketched else None, CAVES_TEXT)
    attachments = [
        Attachment("map-page-3", "image/png", sha, len(page), "Page 3: a map from the book (The Kobold Caves)", "gm"),
        Attachment("notes-1", "application/pdf", notes, 5, "Notes", "gm"),
    ]
    if sketched:
        storage.modules.put_map(module.id, ModuleMap("caves", "map", SKETCH, True))
    save_source(storage, module.id, ModuleSource(texts=[text], attachments=attachments))
    return module.id


class Claude:
    """FakeDM, its side calls and vision calls answered from scripts, recording what it was asked."""

    def __init__(self, *, side=(), vision=()):
        self.side, self.vision = list(side), list(vision)
        self.dm = FakeDM(
            [],
            side_handler=lambda prompt: self.side.pop(0) if self.side else GOOD,
            vision_handler=lambda prompt, image, media_type: self.vision.pop(0) if self.vision else GOOD,
        )

    def services(self, storage) -> ConversionServices:
        return ConversionServices(
            storage=storage, conversion=lambda: (self.dm, BackendChoice("fake", "fake-large")), ocr=None
        )


def _done(services, start):
    """The job `start` starts, once it has ended."""

    async def scenario():
        started = await start
        return await wait(services, started.id)

    return asyncio.run(scenario())


# ----- a description -----


def test_a_description_draft_is_the_jobs_result_and_saves_nothing(storage):
    module_id = _module(storage)
    before = storage.modules.get(module_id)
    claude = Claude()
    services = claude.services(storage)

    done = _done(services, start_dungeon_map(services, module_id, "warren", DESCRIPTION))

    assert (done.kind, done.status, done.module_id) == ("dungeon-map", "done", None)
    assert done.target == {"module_id": module_id, "name": "warren"}
    result = done.result
    assert result["module_id"] == module_id and result["name"] == "warren"
    assert result["source"] == f"{DESCRIBED}\n{GOOD}"
    assert [w["code"] for w in result["warnings"]] == ["map-described"]
    assert (result["kept"], result["discarded"]) == (False, False)
    assert storage.modules.get(module_id).maps == before.maps, "nothing is saved until it is kept"
    [prompt] = claude.dm.side_prompts
    assert DESCRIPTION in prompt
    assert "has no room key" in prompt, "the text's rooms are on the sketch already"


def test_an_unlinked_room_key_goes_in_the_prompt_and_is_linked_once_kept(storage):
    module_id = _module(storage, sketched=False)
    claude = Claude()
    services = claude.services(storage)

    done = _done(services, start_dungeon_map(services, module_id, "warren", DESCRIPTION))
    [prompt] = claude.dm.side_prompts
    assert 'room "r1", label "1. Entrance"' in prompt and 'room "rC3", label "C3. Shrine"' in prompt

    kept = keep_draft(storage, module_id, done.id)

    assert kept.name == "warren" and kept.is_default, "the module's first map is its default"
    source = load_source(storage, module_id)
    assert source.texts[0].map == "warren"
    links = derive(source, storage.modules.get(module_id).maps).links
    assert sorted(link.node for link in links) == ["room.r1", "room.r2", "room.rC3"]


def test_a_kept_description_draft_is_a_new_map_and_a_taken_name_gets_2(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    done = _done(services, start_dungeon_map(services, module_id, "caves", DESCRIPTION))

    kept = keep_draft(storage, module_id, done.id)

    assert kept.name == "caves-2" and not kept.is_default
    maps = {m.name: m for m in storage.modules.get(module_id).maps}
    assert maps["caves"].source == SKETCH, "the sketch stays"
    assert maps["caves-2"].source == f"{DESCRIBED}\n{GOOD}"
    assert storage.conversions.get(done.id).result["kept"] is True
    assert drafts(storage, module_id) == []


def test_keep_takes_a_name(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    done = _done(services, start_dungeon_map(services, module_id, "warren", DESCRIPTION))
    assert keep_draft(storage, module_id, done.id, "lower-warren").name == "lower-warren"


def test_a_description_that_never_parses_is_a_draft_with_no_map(storage):
    module_id = _module(storage)
    services = Claude(side=[BROKEN, BROKEN]).services(storage)
    done = _done(services, start_dungeon_map(services, module_id, "warren", DESCRIPTION))

    assert done.status == "done" and done.result["source"] is None
    assert [w["code"] for w in done.result["warnings"]] == ["map-not-drawn"]
    with pytest.raises(ValueError, match="no map"):
        keep_draft(storage, module_id, done.id)


def test_a_description_draft_needs_a_description_and_a_module(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    with pytest.raises(ValueError):
        asyncio.run(start_dungeon_map(services, module_id, "warren", "  "))
    with pytest.raises(KeyError):
        asyncio.run(start_dungeon_map(services, "mod_nope", "warren", DESCRIPTION))


# ----- the book's map -----


def test_a_book_draft_counts_what_its_vision_call_cost(storage):
    """G2: a book-map job's vision call goes into the job's `cost_usd`, as a PDF conversion's calls do."""
    module_id = _module(storage)
    claude = Claude(vision=[f"```dmap\n{GOOD}```"])
    claude.dm.side_usage = Usage(1000, 50, 0.02)
    services = claude.services(storage)

    done = _done(services, start_book_map(services, module_id, "caves", "map-page-3"))

    assert done.status == "done", done.error
    assert done.cost_usd == pytest.approx(0.02)


def test_a_book_draft_sends_the_page_and_replaces_the_sketch_once_kept(storage):
    module_id = _module(storage)
    claude = Claude(vision=[f"```dmap\n{GOOD}```"])
    services = claude.services(storage)

    done = _done(services, start_book_map(services, module_id, "caves", "map-page-3"))

    assert (done.kind, done.status) == ("book-map", "done")
    assert done.target == {"module_id": module_id, "name": "caves", "page": "map-page-3", "part": None}
    [(media_type, size)] = claude.dm.vision_images
    assert media_type == "image/png" and size > 0
    assert 'room "r2", label "2. Hall"' in claude.dm.vision_prompts[0]
    assert done.result["source"] == f"{FROM_BOOK} asset:map-page-3.\n{GOOD}"
    assert storage.modules.get(module_id).maps[0].source == SKETCH, "nothing is saved until it is kept"

    kept = keep_draft(storage, module_id, done.id, "ignored")

    assert kept.name == "caves" and kept.is_default
    [caves] = storage.modules.get(module_id).maps
    assert caves.source == f"{FROM_BOOK} asset:map-page-3.\n{GOOD}"
    assert SKETCHED not in caves.source


def test_a_book_draft_needs_a_map_page_and_the_map(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    with pytest.raises(ValueError, match="map page"):
        asyncio.run(start_book_map(services, module_id, "caves", "notes-1"))
    with pytest.raises(ValueError, match="map page"):
        asyncio.run(start_book_map(services, module_id, "caves", "map-page-9"))
    with pytest.raises(KeyError):
        asyncio.run(start_book_map(services, module_id, "nope", "map-page-3"))


def test_a_sketch_is_replaced_by_its_page(storage):
    module_id = _module(storage)
    unpaged = f"{SKETCHED} No map page was found in the book.\n{GOOD}"
    storage.modules.put_map(module_id, ModuleMap("annex", "map", unpaged, False))
    services = Claude(vision=[f"```dmap\n{GOOD}```"]).services(storage)

    drawn = asyncio.run(draw_book_maps(services, module_id))

    assert [(c.kind, c.status, c.target["name"]) for c in drawn] == [("book-map", "done", "caves")]
    assert drawn[0].target["part"] == "caves", "the page's title matches the text"
    assert drawn[0].target["batch"] == {"index": 1, "count": 1} and drawn[0].title == "page 3"
    [draft] = drafts(storage, module_id)
    assert (draft["kind"], draft["name"], draft["replaces"]) == ("book-map", "caves", "caves")
    assert {m.name: m.source for m in storage.modules.get(module_id).maps}["caves"] == SKETCH, "kept only on Keep"


def test_a_sketch_of_another_part_isnt_replaced_by_the_page(storage):
    """The C-c bug: the page's title names another part than the sketch's text, so its draft is a new map."""
    module_id = _module(storage)
    source = load_source(storage, module_id)
    attachments = [replace(a, description="Page 3: a map from the book (The Sea Ghost)") for a in source.attachments]
    ship = TextDoc("the-sea-ghost", "The Sea Ghost", "gm", None, SHIP_TEXT)
    save_source(storage, module_id, replace(source, texts=[*source.texts, ship], attachments=attachments))
    services = Claude().services(storage)

    [drawn] = asyncio.run(draw_book_maps(services, module_id))

    assert drawn.target["part"] == "the-sea-ghost" and drawn.result["replaces"] is None
    assert drawn.target["name"] == "the-sea-ghost"


def test_every_map_page_is_drafted(storage):
    module_id = _book(storage)
    source = load_source(storage, module_id)
    pages = [
        replace(source.attachments[0], id=f"map-page-{n}", description=f"Page {n}: a map from the book{title}")
        for n, title in ((37, " (The Sea Ghost: decks)"), (2, " (The Haunted House)"), (35, ""))
    ]
    save_source(storage, module_id, replace(source, attachments=[*pages, *source.attachments[1:]]))
    claude = Claude()
    services = claude.services(storage)

    drawn = asyncio.run(draw_book_maps(services, module_id))

    assert [c.title for c in drawn] == ["page 2", "page 35", "page 37"], "in page order"
    assert [c.target["batch"] for c in drawn] == [{"index": n, "count": 3} for n in (1, 2, 3)]
    assert [c.target["part"] for c in drawn] == ["the-haunted-house", None, "the-sea-ghost"]
    assert [c.result["replaces"] for c in drawn] == [None, None, None], "no sketch names these pages"
    assert len(claude.dm.vision_images) == 3
    assert len(drafts(storage, module_id)) == 3


def test_a_cancelled_page_stops_the_pages_after_it(storage):
    """The organiser cancels the first page's job: the drawing stops there, the other pages aren't started."""
    module_id = _book(storage)
    source = load_source(storage, module_id)
    pages = [replace(source.attachments[0], id=f"map-page-{n}", description=f"Page {n}: a map") for n in (2, 3, 4)]
    save_source(storage, module_id, replace(source, attachments=[*pages, *source.attachments[1:]]))
    claude = Claude()
    services = claude.services(storage)

    def cancelling(prompt, image, media_type):
        [running] = services.live
        asyncio.get_running_loop().create_task(cancel(services, running))
        return GOOD

    claude.dm._vision_handler = cancelling

    drawn = asyncio.run(draw_book_maps(services, module_id))

    assert [(c.title, c.status) for c in drawn] == [("page 2", "cancelled")]
    assert len(claude.dm.vision_images) == 1


def test_a_map_drawn_from_the_book_already_gets_no_draft(storage):
    module_id = _module(storage)
    caves = storage.modules.get(module_id).maps[0]
    storage.modules.put_map(module_id, replace(caves, source=f"{FROM_BOOK} asset:map-page-3.\n{GOOD}"))
    services = Claude().services(storage)

    assert asyncio.run(draw_book_maps(services, module_id)) == []


def test_book_drafts_wait_for_nothing_when_another_job_runs(storage):
    module_id = _module(storage)
    services = Claude().services(storage)

    async def scenario():
        running = await start_dungeon_map(services, module_id, "warren", DESCRIPTION)
        drawn = await draw_book_maps(services, module_id)
        await wait(services, running.id)
        return drawn

    assert asyncio.run(scenario()) == [], "the button on the sketch still draws it"
    assert [d["kind"] for d in drafts(storage, module_id)] == ["dungeon-map"]


# ----- the list -----


def test_a_discarded_draft_isnt_listed(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    first = _done(services, start_dungeon_map(services, module_id, "warren", DESCRIPTION))
    second = _done(services, start_dungeon_map(services, module_id, "pit", "A pit and a ledge."))

    listed = drafts(storage, module_id)
    assert [d["id"] for d in listed] == [second.id, first.id]
    assert set(listed[0]) == {"id", "kind", "name", "source", "warnings", "created_at", "replaces", "part", "page", "maps"}
    assert listed[0]["maps"] == [{"name": "pit", "title": "pit", "source": listed[0]["source"], "part": None}]

    discard_draft(storage, module_id, first.id)

    assert [d["id"] for d in drafts(storage, module_id)] == [second.id]
    assert storage.conversions.get(first.id).result["discarded"] is True
    with pytest.raises(KeyError):
        keep_draft(storage, module_id, first.id)


def test_a_draft_is_still_listed_after_twenty_later_conversions(storage):
    module_id = _module(storage)
    services = Claude().services(storage)
    done = _done(services, start_dungeon_map(services, module_id, "warren", DESCRIPTION))
    for n in range(21):
        later = storage.conversions.create("generate", f"Module {n}", "ready")
        storage.conversions.save(replace(later, status="done"))

    assert [d["id"] for d in drafts(storage, module_id)] == [done.id]


def test_another_modules_draft_is_neither_listed_nor_kept(storage):
    module_id = _module(storage)
    other = storage.modules.create("Elsewhere").id
    services = Claude().services(storage)
    done = _done(services, start_dungeon_map(services, module_id, "warren", DESCRIPTION))

    assert drafts(storage, other) == []
    with pytest.raises(KeyError):
        keep_draft(storage, other, done.id)
    with pytest.raises(KeyError):
        discard_draft(storage, other, done.id)


# ----- any book picture, for its part (faithful modules Task 3) -----

HOUSE_TEXT = """\
# The Haunted House

## 1. Kitchen

A cold kitchen.

## 2. Dining Room

A long table under dust.
"""
SHIP_TEXT = """\
# The Sea Ghost

## 1. Main Deck

The ship's waist.

## 2. Captain's Cabin

Charts and a locked chest.
"""
HOUSE_DRAFT = """\
map "Haunted House" {
  grid { cell 32 px  units feet 10  bounds 30 x 20 }
  room_numbers off
}

room "r1" { rect 1,1 6 x 5  label "1. Kitchen" }
room "r2" { rect 7,1 8 x 5  label "2. Dining Room" }

door between room.r1 and room.r2 { }
"""
SHIP_DRAFT = HOUSE_DRAFT.replace("1. Kitchen", "1. Main deck").replace("2. Dining Room", "2. Captain’s cabin")


def _book(storage) -> str:
    """A module with a house text (no map named), a ship text on the map `ship`, and the book's pictures: a map page,
    a full-page picture, a small crop and a second picture of one page."""
    module = storage.modules.create("Saltmarsh")
    page = _png()
    sha = storage.blobs.put(page, "image/png")
    storage.blobs.link(module.id, ATTACHMENT, sha)
    texts = [
        TextDoc("the-haunted-house", "The Haunted House", "gm", None, HOUSE_TEXT),
        TextDoc("the-sea-ghost", "The Sea Ghost", "gm", "ship", SHIP_TEXT),
    ]
    attachments = [
        Attachment(id, "image/png", sha, len(page), description, "gm")
        for id, description in (
            ("map-page-2", "Page 2: a map from the book (The Haunted House: ground floor)"),
            ("page-35", "Page 35: a map or full-page picture"),
            ("page-37", "Page 37: a map or full-page picture"),
            ("page-37-2", "Page 37: a map or full-page picture"),
            ("page-12", "Page 12, near “1. Kitchen”"),
        )
    ]
    storage.modules.put_map(module.id, ModuleMap("ship", "map", f"{SKETCHED} No map page was found.\n{GOOD}", True))
    save_source(storage, module.id, ModuleSource(texts=texts, attachments=attachments))
    return module.id


def test_any_page_picture_of_the_book_can_be_drafted(storage):
    module_id = _book(storage)
    services = Claude().services(storage)
    for page in ("page-37", "page-37-2", "map-page-2"):
        done = _done(services, start_book_map(services, module_id, None, page))
        assert done.status == "done", page
    for page in ("page-12", "page-9", "source-pdf"):
        with pytest.raises(ValueError, match="map page"):
            asyncio.run(start_book_map(services, module_id, None, page))
    with pytest.raises(KeyError):
        asyncio.run(start_book_map(services, module_id, None, "page-37", part="the-castle"))


def test_a_new_map_from_a_page_is_named_from_its_description(storage):
    module_id = _book(storage)
    services = Claude(vision=[f"```dmap\n{HOUSE_DRAFT}```"]).services(storage)

    done = _done(services, start_book_map(services, module_id, None, "map-page-2", part="the-haunted-house"))

    name = "the-haunted-house-ground-floor"
    assert done.target == {"module_id": module_id, "name": name, "page": "map-page-2", "part": "the-haunted-house"}
    result = done.result
    assert (result["name"], result["replaces"], result["part"], result["page"]) == (
        name,
        None,
        "the-haunted-house",
        "map-page-2",
    )
    [listed] = drafts(storage, module_id)
    assert (listed["replaces"], listed["part"], listed["page"]) == (None, "the-haunted-house", "map-page-2")

    kept = keep_draft(storage, module_id, done.id)

    assert kept.name == name and not kept.is_default
    maps = {m.name: m.source for m in storage.modules.get(module_id).maps}
    assert maps[name] == f"{FROM_BOOK} asset:map-page-2.\n{HOUSE_DRAFT}"
    assert maps["ship"].startswith(SKETCHED), "the ship's map is untouched"
    house = next(t for t in load_source(storage, module_id).texts if t.id == "the-haunted-house")
    assert house.map == name, "the part's text, which named no map, points at the new map"


def test_a_page_without_a_title_names_the_map_after_the_page(storage):
    module_id = _book(storage)
    services = Claude().services(storage)
    done = _done(services, start_book_map(services, module_id, None, "page-37"))
    assert (done.result["name"], done.result["replaces"], done.result["part"]) == ("page-37", None, None)


def test_rooms_come_from_the_part_only(storage):
    module_id = _book(storage)
    claude = Claude()
    services = claude.services(storage)

    _done(services, start_book_map(services, module_id, "ship", "page-35"))
    _done(services, start_book_map(services, module_id, None, "page-35", part="the-sea-ghost"))
    _done(services, start_book_map(services, module_id, None, "page-37"))

    on_map, of_part, of_none = claude.dm.vision_prompts
    for prompt in (on_map, of_part):
        assert 'label "1. Main Deck"' in prompt
        assert "1. Kitchen" not in prompt and "2. Dining Room" not in prompt, "no house heading on the ship's draft"
    # With neither a part nor a map, every part is offered, each under its id, and Claude names each level's part
    # (Task 4's amendment); Keep then checks each level against its own part.
    assert "the-haunted-house" in of_none and "the-sea-ghost" in of_none
    assert 'label "1. Kitchen"' in of_none and 'label "1. Main Deck"' in of_none
    assert "A cold kitchen." not in of_none, "headings only, never their paragraphs"


def test_keep_refuses_house_labels_on_the_ship(storage):
    module_id = _book(storage)
    services = Claude(vision=[f"```dmap\n{HOUSE_DRAFT}```"]).services(storage)
    done = _done(services, start_book_map(services, module_id, "ship", "page-35"))
    assert (done.result["replaces"], done.result["part"]) == ("ship", "the-sea-ghost")

    with pytest.raises(DraftMismatch) as refused:
        keep_draft(storage, module_id, done.id)

    assert len(refused.value.problems) == 2
    assert "1. Kitchen" in refused.value.problems[0] and "Main Deck" in refused.value.problems[0]
    assert "The Sea Ghost" in str(refused.value)
    assert {m.name: m.source for m in storage.modules.get(module_id).maps}["ship"].startswith(SKETCHED)

    kept = keep_draft(storage, module_id, done.id, force=True)

    assert kept.name == "ship" and kept.source == f"{FROM_BOOK} asset:page-35.\n{HOUSE_DRAFT}"


def test_keep_takes_a_draft_whose_labels_match_its_part(storage):
    module_id = _book(storage)
    services = Claude(vision=[f"```dmap\n{SHIP_DRAFT}```"]).services(storage)
    done = _done(services, start_book_map(services, module_id, "ship", "page-35"))
    assert keep_draft(storage, module_id, done.id).name == "ship", "case, punctuation and the key don't count"


def test_mismatch_finds_rooms_that_arent_the_parts_keys():
    ship = TextDoc("the-sea-ghost", "The Sea Ghost", "gm", None, SHIP_TEXT)
    many = GOOD.replace('"r1"', '"r7"').replace("room.r1", "room.r7").replace('"r2"', '"r8"').replace("room.r2", "room.r8")
    assert mismatch(HOUSE_DRAFT, ship) != []
    assert mismatch(SHIP_DRAFT, ship) == []
    [problem] = mismatch(many, ship)
    assert "3 of" in problem and "The Sea Ghost" in problem


# ----- one map per level (faithful modules Task 4) -----

LEVELS_HOUSE = """\
# The Haunted House

## 1. Kitchen

A cold kitchen.

## 3. Stairwell

Stairs up, and a trapdoor down.

## 4. Bedroom

Dust and a bed.

## 18. Cellar

Barrels.

## 19. Cave

Wet rock.
"""


def _level(level: str, part: str, rooms: list[tuple[str, str]], exits: str = "") -> str:
    lines = [f"# level: {level}", f"# part: {part}", f'map "{level}" {{', "  grid { cell 32 px  units feet 5  bounds 40 x 20 }", "  room_numbers off", "}", ""]
    for n, (room, label) in enumerate(rooms):
        lines.append(f'room "{room}" {{ rect {1 + 8 * n},1 8 x 5  label "{label}" }}')
    for a, b in itertools.pairwise(rooms):
        lines.append(f"door between room.{a[0]} and room.{b[0]} {{ }}")
    return "\n".join(lines) + "\n" + exits


def _levels(*levels: str) -> str:
    return "\n".join(f"```dmap\n{level}```" for level in levels)


GROUND = _level(
    "Ground floor", "the-haunted-house", [("r1", "1. Kitchen"), ("r3", "3. Stairwell")],
    'exit at 10,3 { to "the-haunted-house-2" at 2,2 }\nexit at 11,3 { to "the-haunted-house-3" at 2,2 }\n',
)
UPPER = _level("Upper floor", "the-haunted-house", [("r3", "3. Stairwell"), ("r4", "4. Bedroom")])
CELLAR = _level("Cellar", "the-haunted-house", [("r18", "18. Cellar")])
CAVES = _level("Caves", "the-haunted-house", [("r19", "19. Cave")])


def _levelled(storage) -> str:
    """A module with the house's text on no map, the ship's on `ship`, and the house's plate: the ship's key 1 has
    an entry, and so does the house's 18, with an encounter."""
    module = storage.modules.create("Saltmarsh")
    page = _png()
    sha = storage.blobs.put(page, "image/png")
    storage.blobs.link(module.id, ATTACHMENT, sha)
    texts = [
        TextDoc("the-haunted-house", "The Haunted House", "gm", None, LEVELS_HOUSE),
        TextDoc("the-sea-ghost", "The Sea Ghost", "gm", "ship", SHIP_TEXT),
    ]
    keys = [
        {"key": "sea-ghost-1", "title": "Main Deck", "text": "text:the-sea-ghost#1", "node": "map:ship#room.r1"},
        {"key": "18", "title": "Cellar", "text": "text:the-haunted-house#18", "encounter": "encounter:rats"},
    ]
    attachment = Attachment("map-page-2", "image/png", sha, len(page), "Page 2: a map from the book (The Haunted House)", "gm")
    storage.modules.put_map(module.id, ModuleMap("ship", "map", f"{SKETCHED} No map page was found.\n{GOOD}", True))
    save_source(storage, module.id, ModuleSource(texts=texts, keys=keys, attachments=[attachment]))
    return module.id


def test_a_book_draft_lists_its_levels(storage):
    module_id = _levelled(storage)
    services = Claude(vision=[_levels(GROUND, UPPER, CELLAR, CAVES)]).services(storage)

    done = _done(services, start_book_map(services, module_id, None, "map-page-2", part="the-haunted-house"))

    names = ["the-haunted-house-ground-floor", "the-haunted-house-upper-floor", "the-haunted-house-cellar", "the-haunted-house-caves"]
    maps = done.result["maps"]
    assert [m["name"] for m in maps] == names
    assert [m["title"] for m in maps] == ["Ground floor", "Upper floor", "Cellar", "Caves"]
    assert {m["part"] for m in maps} == {"the-haunted-house"}
    assert all(m["source"].startswith(f"{FROM_BOOK} asset:map-page-2.\n") for m in maps)
    assert 'to "the-haunted-house-upper-floor"' in maps[0]["source"]
    assert (done.result["name"], done.result["source"]) == (names[0], maps[0]["source"]), "for old readers"
    [listed] = drafts(storage, module_id)
    assert listed["maps"] == maps


def test_keep_saves_every_level_and_links_each_key_once(storage):
    module_id = _levelled(storage)
    services = Claude(vision=[_levels(GROUND, UPPER, CELLAR, CAVES)]).services(storage)
    done = _done(services, start_book_map(services, module_id, None, "map-page-2", part="the-haunted-house"))

    kept = keep_draft(storage, module_id, done.id)

    assert kept.name == "the-haunted-house-ground-floor"
    maps = {m.name: m for m in storage.modules.get(module_id).maps}
    assert set(maps) == {"ship", *(m["name"] for m in done.result["maps"])}
    assert maps["ship"].is_default and not kept.is_default, "the default map is unchanged"
    source = load_source(storage, module_id)
    by_text = {k["text"]: k for k in source.keys}
    assert [k["text"] for k in source.keys].count("text:the-haunted-house#3") == 1
    house = lambda anchor: by_text[f"text:the-haunted-house#{anchor}"]
    assert house("1") == {"key": "haunted-house-1", "title": "Kitchen", "text": "text:the-haunted-house#1",
                          "node": "map:the-haunted-house-ground-floor#room.r1"}  # fmt: skip
    assert house("3")["node"] == "map:the-haunted-house-ground-floor#room.r3", "a key on two levels is linked once"
    assert house("4")["node"] == "map:the-haunted-house-upper-floor#room.r4"
    assert house("18")["node"] == "map:the-haunted-house-cellar#room.r18"
    assert house("18")["encounter"] == "encounter:rats", "an entry's other fields are kept"
    assert house("19")["node"] == "map:the-haunted-house-caves#room.r19"
    assert by_text["text:the-sea-ghost#1"] == {
        "key": "sea-ghost-1", "title": "Main Deck", "text": "text:the-sea-ghost#1", "node": "map:ship#room.r1"
    }, "the ship's keys are untouched"
    texts = {t.id: t for t in source.texts}
    assert texts["the-haunted-house"].map == "the-haunted-house-ground-floor"
    links = {(link.text_id, link.anchor): link.map for link in derive(source, storage.modules.get(module_id).maps).links}
    assert links[("the-haunted-house", "4")] == "the-haunted-house-upper-floor"
    assert links[("the-haunted-house", "19")] == "the-haunted-house-caves"
    assert links[("the-sea-ghost", "1")] == "ship"


def test_keep_parses_each_level_once_and_before_its_transaction(storage, monkeypatch):
    """Review P24 (DEL-171): the levels were parsed again for every key entry, inside `keep_draft`'s transaction."""
    from delve.conversions import dungeon_maps

    module_id = _levelled(storage)
    services = Claude(vision=[_levels(GROUND, UPPER, CELLAR, CAVES)]).services(storage)
    done = _done(services, start_book_map(services, module_id, None, "map-page-2", part="the-haunted-house"))
    parsed: list[bool] = []
    inside = [False]
    real_parse, real_transaction = dungeon_maps.parse_source, storage.transaction

    def parse(source, *args):
        parsed.append(inside[0])
        return real_parse(source, *args)

    class Watched:
        def __enter__(self):
            inside[0] = True
            self.inner = real_transaction()
            return self.inner.__enter__()

        def __exit__(self, *exc):
            inside[0] = False
            return self.inner.__exit__(*exc)

    monkeypatch.setattr(dungeon_maps, "parse_source", parse)
    monkeypatch.setattr(storage, "transaction", Watched)
    keep_draft(storage, module_id, done.id)
    assert parsed == [False] * 4, "four levels, each parsed once, none while the write lock is held"


def test_keep_names_a_level_uniquely(storage):
    module_id = _levelled(storage)
    storage.modules.put_map(module_id, ModuleMap("the-haunted-house-cellar", "map", GOOD, False))
    services = Claude(vision=[_levels(GROUND, CELLAR)]).services(storage)
    done = _done(services, start_book_map(services, module_id, None, "map-page-2", part="the-haunted-house"))

    keep_draft(storage, module_id, done.id)

    maps = {m.name: m.source for m in storage.modules.get(module_id).maps}
    assert maps["the-haunted-house-cellar"] == GOOD, "a map of that name stays"
    assert maps["the-haunted-house-cellar-2"].startswith(FROM_BOOK)
    house = {k["text"]: k for k in load_source(storage, module_id).keys}["text:the-haunted-house#18"]
    assert house["node"] == "map:the-haunted-house-cellar-2#room.r18"


def test_keep_runs_the_mismatch_per_level(storage):
    module_id = _levelled(storage)
    wrong = _level("Main deck", "the-sea-ghost", [("r1", "1. Kitchen")])
    services = Claude(vision=[_levels(GROUND, wrong)]).services(storage)
    done = _done(services, start_book_map(services, module_id, None, "map-page-2"))
    assert [m["part"] for m in done.result["maps"]] == ["the-haunted-house", "the-sea-ghost"]

    with pytest.raises(DraftMismatch) as refused:
        keep_draft(storage, module_id, done.id)

    [problem] = refused.value.problems
    assert problem.startswith("Main deck: ") and "1. Kitchen" in problem and "Main Deck" in problem
    assert "The Sea Ghost" in str(refused.value)
    assert keep_draft(storage, module_id, done.id, force=True).name == "the-haunted-house-ground-floor"


def test_a_level_with_no_part_isnt_checked_or_linked(storage):
    module_id = _levelled(storage)
    lost = _level("Tower", "the-castle", [("r1", "1. Throne Room")])
    services = Claude(vision=[_levels(GROUND, lost)]).services(storage)
    done = _done(services, start_book_map(services, module_id, None, "map-page-2"))
    assert "map-no-part" in [w["code"] for w in done.result["warnings"]]

    keep_draft(storage, module_id, done.id)

    nodes = [k.get("node") for k in load_source(storage, module_id).keys]
    assert not any(node and "tower" in node for node in nodes)


def test_a_redraw_without_a_room_unlinks_its_key(storage):
    """Final review fix 2: a level kept over a map drops the `node` of the entries that point at its rooms the new
    source lacks, so the export still validates."""
    module_id = _levelled(storage)
    ground = _level("Ground floor", "the-haunted-house", [("r1", "1. Kitchen"), ("r3", "3. Stairwell")])
    first = Claude(vision=[_levels(ground)]).services(storage)
    done = _done(first, start_book_map(first, module_id, None, "map-page-2", part="the-haunted-house"))
    name = keep_draft(storage, module_id, done.id).name
    redrawn = _level("Ground floor", "the-haunted-house", [("r1", "1. Kitchen")])
    second = Claude(vision=[_levels(redrawn)]).services(storage)
    again = _done(second, start_book_map(second, module_id, name, "map-page-2", part="the-haunted-house"))

    keep_draft(storage, module_id, again.id)

    by_text = {k["text"]: k for k in load_source(storage, module_id).keys}
    assert by_text["text:the-haunted-house#1"]["node"] == f"map:{name}#room.r1"
    assert by_text["text:the-haunted-house#3"] == {"key": "3", "title": "Stairwell",
                                                   "text": "text:the-haunted-house#3"}  # fmt: skip
    assert by_text["text:the-sea-ghost#1"]["node"] == "map:ship#room.r1", "another map's entries are untouched"
    bundle = Bundle.load(export_module(storage, module_id).to_zip())
    assert [str(d) for d in check(bundle).diagnostics if d.severity == "error"] == []
