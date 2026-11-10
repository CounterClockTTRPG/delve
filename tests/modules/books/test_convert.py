"""Converting a book: faithful Markdown by chunks, entity drafts and described pictures (plateau 5 Task 2).

The fake `complete` answers the convert prompt with the chunk's own source text (already Markdown in these books),
and the entities prompt with a JSON answer the test chooses, so every test knows exactly what Claude "said".
"""

import asyncio
import io
import json
import re
from importlib import resources

import pytest
from PIL import Image

from delve.modules.books.calls import Halt
from delve.modules.books.convert import (
    CHUNK_BUDGET,
    FRONT_MATTER,
    MIN_BOOK_PAGES,
    Converted,
    chunk_pages,
    convert_book,
    key_entities,
    link_handouts,
    map_title,
    merge_entities_mapped,
    numbers_changed,
)
from delve.modules.books.pdf import HandoutBox, PdfBook, PdfPage, Picture
from delve.modules.dscn import parse_text, sha256
from delve.modules.source import ModuleSource, TextDoc, Warning

PNG = b"\x89PNG\r\n\x1a\nnot really"


def _page(number: int, text: str, pictures: list[Picture] | None = None) -> PdfPage:
    return PdfPage(number, text, False, pictures or [])


def _book(*texts: str) -> PdfBook:
    return PdfBook([_page(n, t) for n, t in enumerate(texts, start=1)], [])


def _source_of(prompt: str) -> str:
    return re.search(r"<source>\n(.*)\n</source>", prompt, re.DOTALL).group(1)


class FakeClaude:
    """Answers the convert prompt through `chunk` (the source text by default) and the entities prompt with
    `entities` (by text id, else `{}`), and records every prompt."""

    def __init__(self, chunk=None, entities=None, dedupe=None):
        self.chunk = chunk or (lambda source: source)
        self.entities = entities or {}
        self.dedupe = dedupe or {}
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        await asyncio.sleep(0)
        if "<source>" in prompt:
            return self.chunk(_source_of(prompt))
        if "<records>" in prompt:
            kind = "factions" if "are the factions" in prompt else "npcs"
            return json.dumps(self.dedupe.get(kind, []))
        text_id = re.search(r"text:([a-z0-9._-]+)#", prompt).group(1)
        answer = self.entities.get(text_id, {})
        return answer if isinstance(answer, str) else json.dumps(answer)

    def convert_prompts(self) -> list[str]:
        return [p for p in self.prompts if "<source>" in p]


def _convert(book: PdfBook, claude: FakeClaude, *, progress=None, title="The Kobold Caves", **kw) -> Converted:
    calls = progress if progress is not None else []
    return asyncio.run(convert_book(book, title, claude, lambda *a: calls.append(a), **kw))


def _codes(warnings: list[Warning]) -> list[str]:
    return [w.code for w in warnings]


def test_the_prompts_are_package_data():
    prompts = resources.files("delve.modules.books").joinpath("prompts")
    assert "{{text}}" in prompts.joinpath("convert.md").read_text("utf-8")
    assert "{{text}}" in prompts.joinpath("entities.md").read_text("utf-8")


def test_the_prompts_keep_the_books_numbers_and_one_record_per_person():
    prompts = resources.files("delve.modules.books").joinpath("prompts")
    convert = " ".join(prompts.joinpath("convert.md").read_text("utf-8").split())
    entities = " ".join(prompts.joinpath("entities.md").read_text("utf-8").split())
    assert "never renumber, never fill in a row" in convert
    assert "One record per person, faction or quest" in entities
    assert "`location`, as `text:{{text_id}}#<anchor>`" in entities
    assert "characters for the players are not NPCs" in entities


def test_chunks_never_split_a_page():
    pages = [_page(n, "x" * size) for n, size in enumerate([5000, 5000, 5000, 20000, 100, 0, 3000], start=1)]

    chunks = chunk_pages(pages, budget=12_000)

    assert [[p.number for p in chunk] for chunk in chunks] == [[1, 2], [3], [4], [5, 6, 7]]
    assert [p for chunk in chunks for p in chunk] == pages
    assert chunk_pages([]) == []


def test_a_book_becomes_texts_by_chapter():
    book = _book(
        "These pages open the book.",
        "# Introduction\n\nThe kobolds came down from the hills.",
        "# The Caves\n\n## 1. Entrance\n\n> A dark mouth opens in the rock.\n\nTwo kobolds watch.",
        "# The Caves\n\nA second chapter with the same title.",
        "# Players' Introduction\n<!-- players -->\n\nYou have heard of the caves.",
    )
    claude = FakeClaude()

    converted = _convert(book, claude, concurrency=1)

    texts = converted.source.texts
    assert [(t.id, t.title, t.audience) for t in texts] == [
        ("introduction", "Introduction", "gm"),
        ("the-caves", "The Caves", "gm"),
        ("the-caves-2", "The Caves", "gm"),
        ("players-introduction", "Players' Introduction", "player"),
        (FRONT_MATTER, "Front matter", "gm"),
    ]
    assert texts[4].markdown == "These pages open the book.\n", "what comes before the first chapter, unkeyed"
    assert texts[0].markdown == "# Introduction\n\nThe kobolds came down from the hills.\n"
    caves = parse_text(texts[1].markdown).keyed()[0]
    assert (caves.key, caves.title, caves.read_aloud) == ("1", "Entrance", "A dark mouth opens in the rock.")
    assert "<!-- players -->" not in texts[3].markdown
    assert texts[3].map is None
    [prompt] = claude.convert_prompts()
    assert "pages 1–5 of “The Kobold Caves”" in prompt


def test_a_chunk_has_the_end_of_the_previous_one_as_context():
    long = "lorem " * 1500
    book = _book(long + "The first chunk ends here.", "# Next\n\n" + long, "The third page.")
    claude = FakeClaude()

    _convert(book, claude)

    first, second = claude.convert_prompts()
    assert "page 1 of “The Kobold Caves”" in first and "<context>" not in first
    assert "pages 2–3 of" in second
    context = re.search(r"<context>\n(.*)\n</context>", second, re.DOTALL).group(1)
    assert context.endswith("lorem The first chunk ends here.") and len(context) <= 300
    assert "end of page 1" in second and "don't repeat it" in second


def test_keyed_headings_get_anchors_and_duplicates_are_unique():
    book = _book("# Level One\n\n## 12. The Well\n\nWater.\n\n## C3. Guard Post\n\nGuards.\n\n## 12. The Well, Again\n")

    markdown = _convert(book, FakeClaude()).source.texts[0].markdown

    assert "## 12. The Well {#12}" in markdown
    assert "## C3. Guard Post {#c3}" in markdown
    assert "## 12. The Well, Again {#12-2}" in markdown
    assert parse_text(markdown).errors == []


SOURCE = "The goblins in the long hall play dice by the fire and do not hear the party come in quietly."


@pytest.mark.parametrize(
    "answer",
    [
        "",
        "The goblins play dice.",
        "This passage describes a hall where some goblins are.",
        (
            "Here is the Markdown of these pages, converted faithfully, with every one of its words kept as you asked:"
            "\n\n```markdown\nThe goblins play dice.\n```\n"
        ),
    ],
    ids=["empty", "short", "prose about the text", "fenced with prose"],
)
def test_bad_answers_become_warnings(answer):
    book = PdfBook([_page(3, "# The Hall"), _page(4, SOURCE + "\n\n> # not a heading")], [])

    converted = _convert(book, FakeClaude(chunk=lambda _: answer))

    assert _codes(converted.warnings) == ["conversion-short"]
    assert converted.warnings[0].ref == "pages:3-4"
    assert "3–4" in converted.warnings[0].message
    # The source is kept as plain paragraphs: its words, and none of its lines read as Markdown.
    [text] = converted.source.texts
    assert SOURCE in text.markdown
    assert parse_text(text.markdown).sections == []
    assert "\\# The Hall" in text.markdown and "\\> # not a heading" in text.markdown


def test_a_fenced_answer_with_prose_around_it_is_unwrapped():
    book = _book("# The Hall\n\n" + SOURCE)
    answer = "Here is the Markdown of the pages:\n\n```markdown\n{}\n```\n\nI kept every word.\n"

    converted = _convert(book, FakeClaude(chunk=lambda source: answer.format(source)))

    assert converted.warnings == []
    assert converted.source.texts[0].markdown == f"# The Hall\n\n{SOURCE}\n"


def test_a_text_with_one_short_code_block_keeps_its_prose():
    text = "# The Hall\n\n" + SOURCE + "\n\n```\nA riddle on the door.\n```\n\n" + SOURCE

    converted = _convert(_book(text), FakeClaude())

    assert converted.source.texts[0].markdown == text + "\n"


def test_a_fenced_answer_is_unwrapped():
    book = _book("# The Hall\n\n" + SOURCE)

    converted = _convert(book, FakeClaude(chunk=lambda source: f"```markdown\n{source}\n```"))

    assert converted.warnings == []
    assert converted.source.texts[0].markdown == f"# The Hall\n\n{SOURCE}\n"


def test_entity_drafts_are_validated():
    book = _book("# The Caves\n\n## 1. Entrance\n\nGrak the kobold chief waits.", "# Town\n\nA quiet town.")
    entities = {
        "the-caves": {
            "npcs": [
                {"id": "grak", "name": "Grak", "role": "kobold chief", "location": "text:the-caves#1"},
                {"id": "Bad Id", "name": "Nobody"},
                {"name": "Snik"},
            ],
            "encounters": [{"id": "kobold-patrol", "name": "Kobold patrol", "fixed": [{"creature": "monster:kobold"}]}],
            "factions": [],
            "quests": "not a list",
        },
        "town": "Here are the NPCs: none.",
    }

    claude = FakeClaude(entities=entities)
    converted = _convert(book, claude)

    # One entities prompt per text, holding the text with its anchors.
    entity_prompts = [p for p in claude.prompts if "<text>" in p]
    assert len(entity_prompts) == 2
    assert "## 1. Entrance {#1}" in entity_prompts[0] and "text:the-caves#<anchor>" in entity_prompts[0]
    assert converted.source.entities == {
        "npcs": [
            {"id": "grak", "name": "Grak", "role": "kobold chief", "location": "text:the-caves#1", "audience": "gm"},
            {"name": "Snik", "id": "snik", "audience": "gm"},
        ],
        "encounters": [
            {
                "id": "kobold-patrol",
                "name": "Kobold patrol",
                "fixed": [{"creature": "monster:kobold"}],
                "audience": "gm",
                "key": "key:1",
            }
        ],
    }
    dropped = [w for w in converted.warnings if w.code == "entity-dropped"]
    assert [w.ref for w in dropped] == ["text:the-caves", "text:the-caves"]
    assert "Nobody" in dropped[0].message and "quests" in dropped[1].message
    [not_read] = [w for w in converted.warnings if w.code == "entities-not-read"]
    assert not_read.ref == "text:town"


def test_a_long_text_is_sent_for_entities_in_chunks():
    """A book without `#` chapters is one text; its entity pass is cut at headings, else at paragraphs, under the
    conversion's budget, and the records of every chunk are merged with unique ids."""
    section = "word " * (CHUNK_BUDGET // 10)
    paragraph = "para " * (CHUNK_BUDGET // 10)
    book = _book(
        "## 1. Entrance\n\n" + section,
        "## 2. Hall\n\n" + section,
        "## 3. Shrine\n\n" + section,
        "## 4. Long Cave\n\n" + "\n\n".join([paragraph] * 4),
    )
    seen: list[str] = []

    async def complete(prompt: str) -> str:
        if "<source>" in prompt:
            return _source_of(prompt)
        text = re.search(r"<text>\n(.*)\n</text>", prompt, re.DOTALL).group(1)
        seen.append(text)
        return json.dumps({"npcs": [{"id": "grak", "name": f"Grak {len(seen)}"}]})

    calls: list[tuple] = []
    converted = asyncio.run(convert_book(book, "Book", complete, lambda *a: calls.append(a), concurrency=2))

    assert [t.id for t in converted.source.texts] == ["book"]
    assert len(seen) > 2 and all(len(chunk) <= CHUNK_BUDGET for chunk in seen)
    # Cut at headings: every heading starts a chunk; the long cave is cut at its paragraphs.
    assert sum(chunk.startswith("## ") for chunk in seen) == 4
    assert all("## " not in chunk[1:] for chunk in seen)
    assert "".join(sorted(seen)).count("para") == 4 * (CHUNK_BUDGET // 10)
    assert sorted(seen) == sorted(set(seen))
    ids = [r["id"] for r in converted.source.entities["npcs"]]
    assert ids[:2] == ["grak", "grak-2"] and len(ids) == len(seen) == len(set(ids))
    assert [c for c in calls if c[0] == "entities"] == [("entities", 0, 1), ("entities", 1, 1)]


def test_a_failed_entity_call_is_a_warning():
    book = _book("# One\n\nGrak.", "# Two\n\nSnik.")

    async def complete(prompt: str) -> str:
        if "<source>" in prompt:
            return _source_of(prompt)
        if "text:two#" in prompt:
            raise RuntimeError("claude exited with 1")
        return json.dumps({"npcs": [{"id": "grak", "name": "Grak"}]})

    converted = asyncio.run(convert_book(book, "Book", complete, lambda *a: None))

    assert [t.id for t in converted.source.texts] == ["one", "two"]
    assert converted.source.entities == {"npcs": [{"id": "grak", "name": "Grak", "audience": "gm"}]}
    [not_read] = converted.warnings
    assert (not_read.code, not_read.ref) == ("entities-not-read", "text:two")
    assert "Two" in not_read.message


def test_a_halt_while_reading_the_entities_stops_the_conversion():
    """A failed entity call is a warning; a `Halt` (a thorough job's pause at the usage limit) goes through."""
    book = _book("# One\n\nGrak.", "# Two\n\nSnik.")

    async def complete(prompt: str) -> str:
        if "<source>" in prompt:
            return _source_of(prompt)
        raise Halt("the usage limit")

    with pytest.raises(Halt):
        asyncio.run(convert_book(book, "Book", complete, lambda *a: None))


def test_a_chunk_is_drafted_with_draft_when_given():
    """`draft` is the chunks' call (the quick conversion's, tried again); the entities still use `complete`."""
    book = _book("# One\n\nGrak.")
    drafted: list[str] = []

    async def draft(prompt: str) -> str:
        drafted.append(prompt)
        return _source_of(prompt)

    async def complete(prompt: str) -> str:
        assert "<source>" not in prompt
        return "{}"

    converted = asyncio.run(convert_book(book, "Book", complete, lambda *a: None, draft=draft))

    assert len(drafted) == 1 and [t.id for t in converted.source.texts] == ["one"]


def test_what_the_conversion_marks_for_the_players_is_a_warning():
    book = _book("# Handout\n<!-- players -->\n\nYou have heard of the caves.", "# Caves\n\nGrak.")
    entities = {"caves": {"npcs": [{"id": "grak", "name": "Grak", "audience": "player"}, {"id": "snik", "name": "S"}]}}

    converted = _convert(book, FakeClaude(entities=entities))

    marked = [w for w in converted.warnings if w.code == "audience-player"]
    assert [(w.ref, w.message) for w in marked] == [
        ("text:handout", "Marked for the players by the conversion; check it."),
        ("npc:grak", "Marked for the players by the conversion; check it."),
    ]
    assert _codes(converted.warnings) == ["audience-player", "audience-player"]


def test_entity_ids_are_unique_across_texts():
    book = _book("# One\n\nGrak.", "# Two\n\nGrak the younger.")
    grak = {"npcs": [{"id": "grak", "name": "Grak"}]}
    younger = {"npcs": [{"id": "grak", "name": "Grak the younger"}]}

    converted = _convert(book, FakeClaude(entities={"one": grak, "two": younger}))

    assert [r["id"] for r in converted.source.entities["npcs"]] == ["grak", "grak-2"]


def test_pictures_become_described_attachments():
    small = Picture(2, PNG, 0.2)
    other = Picture(2, PNG + b"2", 0.3)
    whole = Picture(4, PNG + b"4", 1.0)
    book = PdfBook(
        [
            _page(1, "# The Caves\n\n## 1. Entrance\n\nA dark mouth."),
            _page(2, "## 2. The Well Room\n\nWater drips.", [small, other]),
            _page(3, "Still the well room."),
            _page(4, "", [whole]),
        ],
        [Warning("page-not-read", "Page 9 has no text.", "page:9")],
    )

    converted = _convert(book, FakeClaude())

    attachments = converted.source.attachments
    assert [(a.id, a.type, a.audience, a.description) for a in attachments] == [
        ("page-2", "image/png", "gm", "Page 2, near “2. The Well Room”"),
        ("page-2-2", "image/png", "gm", "Page 2, near “2. The Well Room”"),
        ("page-4", "image/png", "gm", "Page 4: a map or full-page picture"),
    ]
    assert [(a.sha256, a.size) for a in attachments] == [(sha256(p.png), len(p.png)) for p in (small, other, whole)]
    assert converted.pictures == list(zip(attachments, [small.png, other.png, whole.png], strict=True))
    assert _codes(converted.warnings) == ["page-not-read", *["image-to-describe"] * 3]
    assert [w.ref for w in converted.warnings[1:]] == ["asset:page-2", "asset:page-2-2", "asset:page-4"]


def test_a_picture_before_any_heading_names_its_page_only():
    book = PdfBook([_page(1, "Some words before any heading.", [Picture(1, PNG, 0.2)])], [])

    [attachment] = _convert(book, FakeClaude()).source.attachments

    assert attachment.description == "Page 1"


def test_progress_counts_pages():
    """`converting` counts the pages of the chunks done out of the book's pages, whatever order the chunks finish in
    (the lead's ruling for plan Review Focus 1)."""
    sizes = [3000, 3000, 3000, 11000, 4000, 4000]  # chunks: pages 1-3, page 4, pages 5-6
    pages = [_page(n, f"# Chapter {n}\n\n" + "word " * (size // 5)) for n, size in enumerate(sizes, start=1)]
    assert [[p.number for p in chunk] for chunk in chunk_pages(pages)] == [[1, 2, 3], [4], [5, 6]]
    calls: list[tuple] = []

    async def complete(prompt: str) -> str:
        if "<source>" not in prompt:
            return "{}"
        source = _source_of(prompt)
        await asyncio.sleep(0.03 if "Chapter 1" in source else 0.02 if "Chapter 4" in source else 0)
        return source

    converted = asyncio.run(convert_book(PdfBook(pages, []), "Book", complete, lambda *a: calls.append(a)))

    converting = [c for c in calls if c[0] == "converting"]
    assert converting == [("converting", 0, 6), ("converting", 2, 6), ("converting", 3, 6), ("converting", 6, 6)]
    entities = [c for c in calls if c[0] == "entities"]
    assert entities[0] == ("entities", 0, 6) and entities[-1] == ("entities", 6, 6)
    assert [c[0] for c in calls if c[0] not in ("converting", "entities")] == ["pictures"]
    # Whatever order the chunks finish in, the texts are in page order.
    assert [t.title for t in converted.source.texts] == [f"Chapter {n}" for n in range(1, 7)]


def test_a_failed_call_stops_the_conversion():
    """The first failed call cancels every call still running or waiting: after the raise, nothing more is asked
    and no more progress is heard."""
    pages = [_page(n, f"# Chapter {n}\n\n" + "word " * 3000) for n in range(1, 7)]
    log: list[str] = []

    async def complete(prompt: str) -> str:
        log.append("call")
        await asyncio.sleep(0)
        if "Chapter 2" in prompt:
            raise RuntimeError("claude exited with 1")
        await asyncio.sleep(0.05)  # slow, but it would succeed
        log.append("answered")
        return _source_of(prompt)

    async def run() -> int:
        try:
            await convert_book(PdfBook(pages, []), "Book", complete, lambda *a: log.append(f"progress {a[0]}"))
        except RuntimeError:
            seen = len(log)
            await asyncio.sleep(0.2)
            return seen
        raise AssertionError("convert_book didn't raise")

    seen = asyncio.run(run())

    assert len(log) == seen, log[seen:]
    # Only the three calls let in by the limit were made, and none of them answered.
    assert log == ["progress converting", "call", "call", "call"]


def test_concurrency_limits_the_calls_at_once():
    running = 0
    most = 0

    async def complete(prompt: str) -> str:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.01)
        running -= 1
        return _source_of(prompt) if "<source>" in prompt else "{}"

    pages = [_page(n, f"# Chapter {n}\n\n" + "word " * 3000) for n in range(1, 10)]
    asyncio.run(convert_book(PdfBook(pages, []), "Book", complete, lambda *a: None, concurrency=2))

    assert most == 2


def test_a_page_without_words_is_not_sent():
    book = PdfBook([_page(1, ""), _page(2, "   ")], [])
    claude = FakeClaude()

    converted = _convert(book, claude)

    assert claude.prompts == []
    assert converted.source.texts == []
    assert converted.warnings == []


# --- the book's numbers, same-name entities, entities keyed (walkthrough fixes Task 3) -------------------------------


def test_numbers_changed_finds_a_renumbered_sequence():
    """C4: the book's rounds 1, 4, 5, 7, 8, 9, 10 became 1, 4, 5, 6, 7, 8, 9."""
    rounds = "Round {}: the riders come closer."
    source = "\n".join(rounds.format(n) for n in (1, 4, 5, 7, 8, 9, 10)) + "\n34"
    markdown = "\n".join(f"- {rounds.format(n)}" for n in (1, 4, 5, 6, 7, 8, 9))

    assert numbers_changed([source], markdown) == ["10"]
    assert numbers_changed([source], source) == []
    stats = "UK7\nAC 5; HD 3-8; MM(80); 1500 gp\n26"
    assert numbers_changed([stats], "AC 5; HD 8-8; MM(89); 1500 gp") == ["3", "80"]

    book = _book("# Approach\n\n" + source)
    converted = _convert(book, FakeClaude(chunk=lambda _: "# Approach\n\n" + markdown))
    [changed] = [w for w in converted.warnings if w.code == "numbers-changed"]
    assert changed.ref == "pages:1-1"
    assert "10" in changed.message and "page 1" in changed.message


def test_a_numbers_warning_lists_up_to_ten():
    source = "\n".join(["Rows of the table", *(f"row {n}" for n in range(1, 31)), "Page 26"])
    changed = numbers_changed([source], "rows")
    assert len(changed) == 30
    converted = _convert(_book(source), FakeClaude(chunk=lambda s: re.sub(r"\d+", "x", s)))
    [warning] = [w for w in converted.warnings if w.code == "numbers-changed"]
    assert "10" in warning.message and "11" not in warning.message and "… and 20 more" in warning.message


def test_a_pages_header_and_footer_are_not_counted_as_numbers():
    """Review: each source page's first and last line that isn't empty are its header and footer ("Page 26",
    "UK7 26"), which the Markdown leaves out."""
    pages = ["UK7 26\n\nRoom 1: 5 orcs.", "Page 27\n\nRoom 2: 3 goblins.\n\nUK7 27"]
    markdown = "Room 1: 5 orcs.\n\nRoom 2: 3 goblins."

    assert numbers_changed(pages, markdown) == []
    assert numbers_changed(pages, markdown.replace("3 goblins", "4 goblins")) == ["3"]

    converted = _convert(
        PdfBook([_page(n, t) for n, t in enumerate(pages, start=1)], []), FakeClaude(lambda _: markdown)
    )
    assert "numbers-changed" not in _codes(converted.warnings)


def test_merge_entities_mapped_joins_same_name_records():
    """Review Focus 3: by exact name after trimming and case-folding, never fuzzy."""
    records = [
        {"id": "tchoeh", "name": "Tcho'eh", "summary": "A shaman of the hill tribe.", "audience": "gm"},
        {"id": "tchoeh-2", "name": " tcho'EH ", "summary": "", "role": "shaman", "audience": "gm"},
        {"id": "bernhardt", "name": "Bernhardt", "summary": "The young innkeeper.", "audience": "gm"},
        {"id": "tchoeh-3", "name": "Tcho'eh", "summary": "He knows the pass.\n", "role": "elder", "audience": "player"},
        {"id": "bernhardt-the-elder", "name": "Bernhardt the elder", "summary": "His father.", "audience": "gm"},
        {"id": "tchoeh-4", "name": "Tcho'eh", "summary": "A shaman of the hill tribe.", "audience": "gm"},
    ]

    merged = merge_entities_mapped(records)[0]

    assert merged == [
        {
            "id": "tchoeh",
            "name": "Tcho'eh",
            "summary": "A shaman of the hill tribe.\n\nHe knows the pass.",
            "audience": "gm",
            "role": "shaman",
        },
        records[2],
        records[4],
    ]
    assert records[0]["summary"] == "A shaman of the hill tribe."


def test_a_converted_book_merges_its_entities_across_texts():
    book = _book("# One\n\nTcho'eh waits.", "# Two\n\nTcho'eh again.")
    entities = {
        "one": {"npcs": [{"id": "tchoeh", "name": "Tcho'eh", "summary": "A shaman."}]},
        "two": {"npcs": [{"id": "tchoeh", "name": "Tcho'eh", "summary": "He knows the pass."}], "factions": []},
    }

    converted = _convert(book, FakeClaude(entities=entities))

    assert converted.source.entities["npcs"] == [
        {"id": "tchoeh", "name": "Tcho'eh", "summary": "A shaman.\n\nHe knows the pass.", "audience": "gm"}
    ]


KEYED = "# Key\n\n## 3. Farmhouse {#3}\n\nA farm.\n\n## 4. The Destroyed Caravan {#4}\n\nWagons.\n\n## C7. Pass {#c7}\n"


def _keyed_source(**entities) -> ModuleSource:
    return ModuleSource(texts=[TextDoc("key", "Key", "gm", None, KEYED)], entities=entities)


def test_key_entities_links_an_encounter_named_by_area():
    source = _keyed_source(
        encounters=[
            {"id": "wolves", "name": "Wolves", "summary": "Six wolves circle the wagons in area 4."},
            {"id": "caravan", "name": "the destroyed caravan", "summary": "Bandits."},
            {"id": "guards", "name": "Guards", "summary": "Two guards at the pass, in c7."},
        ],
        npcs=[
            {"id": "farmer", "name": "Farmer Jon", "location": "text:key#3"},
            {"id": "ghost", "name": "Ghost", "summary": "Haunts room 4 at night."},
        ],
    )

    keyed = key_entities(source)

    assert keyed.keys == [
        {"key": "3", "title": "Farmhouse", "text": "text:key#3", "npcs": ["npc:farmer"]},
        {
            "key": "4",
            "title": "The Destroyed Caravan",
            "text": "text:key#4",
            "npcs": ["npc:ghost"],
            "encounter": "encounter:wolves",
        },
        {"key": "C7", "title": "Pass", "text": "text:key#c7", "npcs": [], "encounter": "encounter:guards"},
    ]
    encounters = {e["id"]: e for e in keyed.entities["encounters"]}
    assert encounters["wolves"]["key"] == "key:4" and encounters["caravan"]["key"] == "key:4"
    assert encounters["guards"]["key"] == "key:C7"
    npcs = {n["id"]: n for n in keyed.entities["npcs"]}
    assert npcs["ghost"]["location"] == "text:key#4" and npcs["farmer"]["location"] == "text:key#3"
    assert source.keys == [] and "key" not in source.entities["encounters"][0]


def test_key_entities_leaves_an_unplaced_encounter_unkeyed():
    source = _keyed_source(
        encounters=[{"id": "patrol", "name": "Patrol", "summary": "Rides the roads in 2 groups, near area 9."}],
        npcs=[{"id": "hermit", "name": "Hermit", "location": "text:elsewhere#3"}],
    )

    keyed = key_entities(source)

    assert [(k["key"], k["npcs"], "encounter" in k) for k in keyed.keys] == [
        ("3", [], False),
        ("4", [], False),
        ("C7", [], False),
    ]
    assert keyed.entities == source.entities


def test_key_entities_skips_an_area_named_as_a_source():
    """Backlog Fixes 8: "guards from area 3" come from 3, they aren't in it; the next area the summary names keys them."""
    source = _keyed_source(
        encounters=[
            {"id": "guards", "name": "Guards", "summary": "Guards from area 3 rush in."},
            {"id": "archers", "name": "Archers", "summary": "Archers from the area 3 loft shoot into area 4."},
        ]
    )

    keyed = key_entities(source)

    encounters = {e["id"]: e for e in keyed.entities["encounters"]}
    assert "key" not in encounters["guards"]
    assert encounters["archers"]["key"] == "key:4"
    assert [(k["key"], k.get("encounter")) for k in keyed.keys] == [
        ("3", None),
        ("4", "encounter:archers"),
        ("C7", None),
    ]


def test_key_entities_still_keys_in_area():
    source = _keyed_source(encounters=[{"id": "lurker", "name": "Lurker", "summary": "Lurks in area 3."}])

    keyed = key_entities(source)

    assert keyed.entities["encounters"][0]["key"] == "key:3"


def test_key_entities_keys_the_far_end_of_an_area():
    """ "The far end of area 12" is in area 12: "of" doesn't name a source, as "from" does."""
    text = TextDoc("key", "Key", "gm", None, "# Key\n\n## 11. Gallery\n\nDust.\n\n## 12. Hall\n\nPillars.\n")
    encounter = {"id": "lurker", "name": "Lurker", "summary": "Lurks at the far end of area 12."}
    source = ModuleSource(texts=[text], entities={"encounters": [encounter]})

    keyed = key_entities(source)

    assert keyed.entities["encounters"][0]["key"] == "key:12"


def test_a_converted_book_keys_its_entities():
    book = _book("# Key\n\n## 4. The Destroyed Caravan\n\nWagons, and six wolves.")
    entities = {"key": {"encounters": [{"id": "wolves", "name": "Wolves", "summary": "Six wolves in area 4."}]}}

    converted = _convert(book, FakeClaude(entities=entities))

    assert converted.source.keys == [
        {
            "key": "4",
            "title": "The Destroyed Caravan",
            "text": "text:key#4",
            "npcs": [],
            "encounter": "encounter:wolves",
        }
    ]


def test_a_converted_book_repairs_its_dangling_refs():
    """Faithful modules Task 1: a ref to a merged-away record is rewritten to the one kept, and one to nothing is
    dropped, each with a warning that joins the job's."""
    book = _book("# One\n\nThe bosun.", "# Two\n\nThe bosun again.")
    entities = {
        "one": {"npcs": [{"id": "the-bosun", "name": "The Bosun"}]},
        "two": {
            "npcs": [{"id": "bosun-2", "name": "the bosun"}],
            "factions": [{"id": "crew", "name": "The Crew", "members": ["npc:bosun-2", "npc:mate"]}],
        },
    }

    converted = _convert(book, FakeClaude(entities=entities))

    assert converted.source.entities["factions"][0]["members"] == ["npc:the-bosun"]
    repairs = [(w.code, w.ref) for w in converted.warnings if w.code.startswith("ref-")]
    assert repairs == [("ref-rewritten", "npc:bosun-2"), ("ref-dropped", "npc:mate")]


def test_a_bare_key_heading_keys_its_two_encounters():
    """Plateau 7 Task 20: "## 31." is keyed (the format's `_KEY_RX`), and a second encounter in the room is keyed to it
    by its record's `key`, which the DM's `module_key` lists under `encounters`."""
    book = _book("# Key\n\n## 31.\n\nSix wolves and their keeper.\n\n## Treasure:\n\nNone.")
    encounters = [
        {"id": "wolves", "name": "Wolves", "summary": "Six wolves in area 31."},
        {"id": "keeper", "name": "Keeper", "summary": "Their keeper, in area 31."},
    ]

    converted = _convert(book, FakeClaude(entities={"key": {"encounters": encounters}}))

    [key] = converted.source.keys
    assert (key["key"], key["title"], key["encounter"]) == ("31", "", "encounter:wolves")
    assert [r["key"] for r in converted.source.entities["encounters"]] == ["key:31", "key:31"]


# --- entities in their own part, and merged (faithful modules Task 9) ------------------------------------------------

HOUSE = "# Part One — The Haunted House\n\n## 7. Kitchen\n\nPots.\n\n## 11. Study\n\nBooks.\n\n## 14. Cellar\n\nDamp.\n\n## 17. Attic\n\nDust."
SHIP = (
    "# Part Two — The Sea Ghost Ship\n\n## 7. Main Deck\n\nRopes.\n\n## 11. Bosun's Cabin\n\nA hammock.\n\n"
    "## 14. Hold\n\nCrates.\n\n## 17. Brig\n\nA cell."
)


def test_ship_npcs_stay_on_the_ship():
    """C2: a record is placed in its own part first, so the ship's 11 is never the house's 11."""
    ship = "part-two-the-sea-ghost-ship"
    entities = {
        ship: {
            "npcs": [
                {"id": "bosun", "name": "The Bosun", "location": "key:11"},
                {"id": "prisoner", "name": "Prisoner", "summary": "Chained in area 17."},
            ],
            "encounters": [
                {"id": "smugglers", "name": "Smugglers", "summary": "Four smugglers load crates in area 14."},
                {"id": "boarding", "name": "Boarding", "key": "key:7"},
            ],
        }
    }

    converted = _convert(_book(HOUSE, SHIP), FakeClaude(entities=entities))

    keys = {k["key"]: k for k in converted.source.keys}
    assert sorted(keys) == sorted(
        f"{part}-{n}" for part in ("haunted-house", "sea-ghost-ship") for n in (7, 11, 14, 17)
    )
    assert keys["sea-ghost-ship-11"]["npcs"] == ["npc:bosun"] and keys["sea-ghost-ship-17"]["npcs"] == ["npc:prisoner"]
    assert keys["sea-ghost-ship-14"]["encounter"] == "encounter:smugglers"
    assert keys["sea-ghost-ship-7"]["encounter"] == "encounter:boarding"
    assert all(not k["npcs"] and "encounter" not in k for name, k in keys.items() if name.startswith("haunted"))
    npcs = {n["id"]: n for n in converted.source.entities["npcs"]}
    assert npcs["bosun"]["location"] == f"text:{ship}#11"
    encounters = {e["id"]: e for e in converted.source.entities["encounters"]}
    assert encounters["boarding"]["key"] == "key:sea-ghost-ship-7", "the encounter's own key is overwritten"
    assert encounters["smugglers"]["key"] == "key:sea-ghost-ship-14"
    assert not [w for w in converted.warnings if w.code.startswith("ref-")]


def test_a_record_of_one_part_takes_an_exact_text_ref_into_another():
    source = ModuleSource(
        texts=[TextDoc("house", "The House", "gm", None, HOUSE), TextDoc("ship", "The Ship", "gm", None, SHIP)],
        entities={
            "npcs": [
                {"id": "ghost", "name": "Ghost", "location": "text:ship#14"},
                {"id": "cook", "name": "Cook", "location": "key:7"},
            ]
        },
    )

    keyed = key_entities(source, {"npc:ghost": "house", "npc:cook": "house"})

    npcs = {n["id"]: n for n in keyed.entities["npcs"]}
    assert npcs["ghost"]["location"] == "text:ship#14" and npcs["cook"]["location"] == "text:house#7"
    keys = {k["key"]: k for k in keyed.keys}
    assert keys["ship-14"]["npcs"] == ["npc:ghost"] and keys["house-7"]["npcs"] == ["npc:cook"]


def test_every_keyed_heading_has_an_entry():
    markdown = "# Key\n\n## 18. Hall {#18}\n\n## 19. **Pantry** {#19}\n\n## 20. Stair {#20}\n\n## 25. Loft {#25}\n\n## 26. Roof {#26}\n"
    source = ModuleSource(texts=[TextDoc("key", "Key", "gm", None, markdown)])

    keyed = key_entities(source)

    assert keyed.keys == [
        {"key": key, "title": title, "text": f"text:key#{key}", "npcs": []}
        for key, title in [("18", "Hall"), ("19", "Pantry"), ("20", "Stair"), ("25", "Loft"), ("26", "Roof")]
    ]


def test_the_well_snake_is_keyed_by_its_creature():
    markdown = (
        "# Key\n\n## 3. The Well {#3}\n\nA giant snake lurks in the water.\n\n## 4. Garden {#4}\n\nWeeds, and a "
        "spider.\n\n## 5. Larder {#5}\n\nThree giant rats and a spider.\n"
    )
    encounters = [
        {"id": "snake", "name": "Something in the well", "fixed": [{"creature": "monster:giant-snake"}]},
        {"id": "rats", "name": "Group of Giant Rats"},
        {"id": "spiders", "name": "Spider", "summary": "A hungry one."},
    ]
    source = ModuleSource(texts=[TextDoc("key", "Key", "gm", None, markdown)], entities={"encounters": encounters})

    keyed = key_entities(source)

    found = {e["id"]: e.get("key") for e in keyed.entities["encounters"]}
    assert found == {"snake": "key:3", "rats": "key:5", "spiders": None}, "a spider in two rooms is placed nowhere"


def test_a_converted_book_merges_what_claude_groups():
    book = _book("# One\n\nNed, a captive.", "# Two\n\nNed Shakeshaft, the spy.")
    entities = {
        "one": {"npcs": [{"id": "ned", "name": "Ned", "summary": "A captive."}]},
        "two": {
            "npcs": [{"id": "ned-shakeshaft", "name": "Ned Shakeshaft", "summary": "The spy."}],
            "factions": [{"id": "spies", "name": "Spies", "members": ["npc:ned-shakeshaft"]}],
        },
    }

    converted = _convert(book, FakeClaude(entities=entities, dedupe={"npcs": [["ned", "ned-shakeshaft"]]}))

    assert [n["id"] for n in converted.source.entities["npcs"]] == ["ned"]
    assert converted.source.entities["factions"][0]["members"] == ["npc:ned"]
    assert ("entities-merged", "npc:ned") in [(w.code, w.ref) for w in converted.warnings]
    assert ("ref-rewritten", "npc:ned-shakeshaft") in [(w.code, w.ref) for w in converted.warnings]


def test_map_title_prefers_the_plate_title():
    page = PdfPage(
        2, "", True, [], map_page=True, ocr_text="MAP C – THE CLOUD CASTLE\nSECRET DOOR", plate_title="HAUNTED HOUSE"
    )
    assert map_title(page) == "HAUNTED HOUSE"
    assert (
        map_title(PdfPage(2, "", True, [], map_page=True, ocr_text="MAP C – THE CLOUD CASTLE"))
        == "MAP C – THE CLOUD CASTLE"
    )
    assert map_title(PdfPage(2, "", True, [], ocr_text="MAP C", plate_title="HAUNTED HOUSE")) is None


def test_a_short_answer_keeps_a_line_that_opens_in_bold():
    """A line starting `**bold**` (Task 14 keeps the book's bold) isn't escaped when the source is kept as it is."""
    book = _book("**Treasure:** a silver dagger and twelve copper pieces.\n* not a list item\n***")

    [text] = _convert(book, FakeClaude(chunk=lambda source: "")).source.texts

    assert text.markdown.splitlines()[:3] == [
        "**Treasure:** a silver dagger and twelve copper pieces.",
        "\\* not a list item",
        "\\***",
    ]


# --- book map pages and title pages (walkthrough fixes Task 2) -------------------------------------------------------


def _picture_page(number: int, ocr_text: str, *, map_page: bool = False) -> PdfPage:
    return PdfPage(
        number, "", True, [Picture(number, PNG + bytes([number]), 1.0)], map_page=map_page, ocr_text=ocr_text
    )


def test_a_map_page_becomes_a_book_map_attachment():
    book = PdfBook(
        [
            _page(1, "# The Cloud Castle\n\n## 1. Gate\n\nA gate of cloud."),
            _picture_page(2, "MAP C – THE CLOUD CASTLE\nSECRET DOOR\nSTAIRS 1 2 3 4 5 6 7 8", map_page=True),
            _picture_page(3, "FALSE DOOR SECRET DOOR\nSTAIRS UP COVERED PIT\n1 2 3 4 5 6 7 8 9 10", map_page=True),
            _picture_page(4, "", map_page=False),
        ],
        [],
    )

    converted = _convert(book, FakeClaude())

    assert [(a.id, a.description, a.audience) for a in converted.source.attachments] == [
        ("map-page-2", "Page 2: a map from the book (MAP C – THE CLOUD CASTLE)", "gm"),
        ("map-page-3", "Page 3: a map from the book", "gm"),
        ("page-4", "Page 4: a map or full-page picture", "gm"),
    ]
    assert [(w.code, w.ref) for w in converted.warnings] == [
        ("book-map", "asset:map-page-2"),
        ("book-map", "asset:map-page-3"),
        ("image-to-describe", "asset:page-4"),
    ]
    assert "Page 2: a map from the book (MAP C – THE CLOUD CASTLE)" in converted.warnings[0].message
    assert all(not text.markdown.count("SECRET DOOR") for text in converted.source.texts), "no OCR in a text"


def test_a_picture_title_page_starts_a_chapter():
    book = PdfBook(
        [
            _page(1, "# Mount Ederglow\n\nThe mountain rises."),
            _picture_page(2, "\nDeath in the Skies\nUe A A NE\nThe castle sails."),
            _page(3, "The castle drifts over the plain.\n\n## 12. The Assault\n\nGiants attack."),
            _picture_page(4, "Map 11", map_page=True),
            _page(5, "Still the assault."),
        ],
        [],
    )

    converted = _convert(book, FakeClaude())

    assert [(t.id, t.title) for t in converted.source.texts] == [
        ("mount-ederglow", "Mount Ederglow"),
        ("death-in-the-skies", "Death in the Skies"),
    ]
    skies = converted.source.texts[1].markdown
    assert skies.startswith("# Death in the Skies\n") and "The castle drifts" in skies and "Still the assault" in skies
    assert "Map 11" not in skies, "a map page's title is the map's, never a chapter"
    assert "The mountain rises." in converted.source.texts[0].markdown


def test_a_title_page_the_text_already_heads_adds_no_second_heading():
    book = PdfBook([_picture_page(1, "Death in the Skies"), _page(2, "# Death in the Skies\n\nThe castle sails.")], [])

    [text] = _convert(book, FakeClaude()).source.texts

    assert text.markdown.count("Death in the Skies") == 1


def test_a_running_header_or_caption_on_an_illustration_page_starts_no_chapter():
    """Review: an illustration in the middle of a room key is no title page when its title-like line is a running
    header (on two other pages or more), the module's title, not the page's first line, or on a page of many words."""
    book = PdfBook(
        [
            _page(1, "# The Cloud Castle\n\nDark Clouds Gather\n\n## 1. Gate\n\nA gate of cloud."),
            _picture_page(2, "Dark Clouds Gather\nA giant on the stair"),
            _page(3, "Dark Clouds Gather\n\n## 2. Hall\n\nThe hall is cold."),
            _picture_page(4, "The Kobold Caves"),
            _picture_page(5, "~ ~\nThe Guard"),
            _picture_page(
                6,
                "The Throne Room\nthe king of the clouds sits here on a throne of mist and his guards stand around him "
                "in a ring of silver",
            ),
            _page(7, "## 3. Throne\n\nThe king sits."),
        ],
        [],
    )

    assert [[p.number for p in chunk] for chunk in chunk_pages(book.pages, title="The Kobold Caves")] == [
        [1, 2, 3, 4, 5, 6, 7]
    ]
    converted = _convert(book, FakeClaude())
    assert [t.title for t in converted.source.texts] == ["The Cloud Castle"]
    assert [s.key for s in parse_text(converted.source.texts[0].markdown).keyed()] == ["1", "2", "3"]


def test_a_title_page_whose_chapter_says_its_title_again_still_starts_a_chapter():
    """A title on its title page and once more as its chapter's heading is no running header."""
    book = PdfBook(
        [
            _page(1, "# Mount Ederglow\n\nThe mountain rises."),
            _picture_page(2, "Death in the Skies"),
            _page(3, "DEATH IN THE SKIES\n\nThe castle sails."),
        ],
        [],
    )

    assert [t.title for t in _convert(book, FakeClaude()).source.texts] == ["Mount Ederglow", "Death in the Skies"]


# --- front matter apart (faithful modules Task 10) -------------------------------------------------------------------

COVER = "# Dungeon Module U1\n\nThe Sinister Secret of Saltmarsh, an adventure for character levels 1-3."
ADS = "# Sea Ghost\n\nOrder the next module of the series at your hobby shop now."


def _body(n: int) -> str:
    return f"## {n}. Room {n}\n\nThe room numbered {n} is dusty and quiet."


def _long_book(first: str, last: str) -> PdfBook:
    middle = ["# Part One — The Haunted House\n\n" + _body(1), *(_body(n) for n in range(2, MIN_BOOK_PAGES - 1))]
    return _book(first, *middle, last)


def test_the_cover_and_the_back_page_are_front_matter_and_no_chapter():
    book = _long_book(COVER, ADS)
    assert [[p.number for p in c] for c in chunk_pages(book.pages)] == [[1], list(range(2, MIN_BOOK_PAGES)), [8]]

    texts = _convert(book, FakeClaude()).source.texts

    assert [(t.id, t.title, t.audience) for t in texts] == [
        ("part-one-the-haunted-house", "Part One — The Haunted House", "gm"),
        (FRONT_MATTER, "Front matter", "gm"),
    ]
    front = texts[1].markdown
    assert "## Dungeon Module U1" in front and "## Sea Ghost" in front and "Order the next module" in front
    assert [s.level for s in parse_text(front).sections] == [2, 2], "its headings make no chapter"
    assert "Sea Ghost" not in texts[0].markdown


def test_a_picture_cover_or_back_page_is_no_title_page():
    cover = _picture_page(1, "The Sinister Secret")
    back = _picture_page(MIN_BOOK_PAGES, "Sea Ghost")
    book = _long_book("", "")
    book = PdfBook([cover, *book.pages[1:-1], back], [])

    assert [t.title for t in _convert(book, FakeClaude()).source.texts] == ["Part One — The Haunted House"]


def test_a_keyed_heading_on_the_first_page_keeps_it_a_chapter():
    book = _long_book("# The Caves\n\n" + _body(0), ADS)

    texts = _convert(book, FakeClaude()).source.texts

    assert [t.id for t in texts] == ["the-caves", "part-one-the-haunted-house", FRONT_MATTER]


def test_the_text_before_the_first_chapter_joins_the_front_matter_unless_it_is_keyed():
    credits = "Credits: design by Dave J. Browne with Don Turnbull. Editing by the TSR staff."
    book = _book(f"{credits}\n\n# Part One — The House\n\n" + _body(1))
    assert [t.id for t in _convert(book, FakeClaude()).source.texts] == ["part-one-the-house", FRONT_MATTER]

    keyed = _book(_body(0) + "\n\n# Part One — The House\n\n" + _body(1))
    assert [t.id for t in _convert(keyed, FakeClaude()).source.texts] == ["the-kobold-caves", "part-one-the-house"]


def test_a_short_book_has_no_front_matter_apart():
    book = _book(COVER, ADS)
    assert [t.title for t in _convert(book, FakeClaude()).source.texts] == ["Dungeon Module U1", "Sea Ghost"]


# --- handouts (faithful modules Task 12) -----------------------------------------------------------------------------


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "PNG")
    return out.getvalue()


def _handout_page(number: int, *handouts: HandoutBox) -> PdfPage:
    return PdfPage(number, "", True, [Picture(number, _png(1000, 1300), 1.0)], handouts=handouts)


HOUSE_22 = "# Part One — The Haunted House\n\n## 9. Study\n\nA desk.\n\n## 22. Secret Room\n\nA parchment."
SHIP_9 = "# Part Two — The Sea Ghost Ship\n\n## 9. Captain's Cabin\n\nCharts and a sea chest."


def test_a_handout_page_gives_a_player_attachment_per_box():
    parchment = HandoutBox((0.1, 0.1, 0.5, 0.4), "The alchemist's parchment", "22")
    chart = HandoutBox((0.5, 0.5, 1.0, 1.0), "A sea chart", "9", "ship")
    book = PdfBook([_page(1, HOUSE_22), _page(2, SHIP_9), _handout_page(3, parchment, chart)], [])

    converted = _convert(book, FakeClaude())

    attachments = {a.id: a for a in converted.source.attachments}
    assert [(a.id, a.audience) for a in converted.source.attachments] == [
        ("page-3", "gm"),
        ("handout-3-1", "player"),
        ("handout-3-2", "player"),
    ]
    assert attachments["handout-3-1"].description == "Handout from page 3: The alchemist's parchment"
    pictures = {a.id: png for a, png in converted.pictures}
    sizes = {}
    for id in ("handout-3-1", "handout-3-2"):
        with Image.open(io.BytesIO(pictures[id])) as image:
            sizes[id] = image.size
    assert sizes == {"handout-3-1": (400, 390), "handout-3-2": (500, 650)}
    assert ("audience-player", "asset:handout-3-1") in [(w.code, w.ref) for w in converted.warnings]
    assert ("audience-player", "asset:handout-3-2") in [(w.code, w.ref) for w in converted.warnings]

    keys = {k["key"]: k for k in converted.source.keys}
    assert keys["22"]["assets"] == ["asset:handout-3-1"], "the parchment, on the house's 22"
    assert keys["sea-ghost-ship-9"]["assets"] == ["asset:handout-3-2"], "the chart, on the ship's 9"
    assert "assets" not in keys["haunted-house-9"]
    assert {a.id for a in converted.source.player_images()} == {"handout-3-1", "handout-3-2"}, (
        "show_image may show them"
    )


def test_a_handout_whose_key_two_parts_share_is_not_linked_without_its_part():
    source = ModuleSource(
        texts=[TextDoc("house", "The House", "gm", None, HOUSE_22), TextDoc("ship", "The Ship", "gm", None, SHIP_9)]
    )
    keyed = key_entities(source)
    handouts = [
        ("handout-3-1", HandoutBox((0, 0, 1, 1), "A sea chart", "9")),
        ("handout-3-2", HandoutBox((0, 0, 1, 1), "A drawing", "40")),
        ("handout-3-3", HandoutBox((0, 0, 1, 1), "A map of the coast")),
    ]

    linked, warnings = link_handouts(keyed, handouts)

    assert all("assets" not in k for k in linked.keys)
    assert [(w.code, w.ref) for w in warnings] == [
        ("handout-not-linked", "asset:handout-3-1"),
        ("handout-not-linked", "asset:handout-3-2"),
        ("handout-not-linked", "asset:handout-3-3"),
    ]


# --- questions (plateau 7 Task 20) -----------------------------------------------------------------------------------


def _asking(*questions: dict) -> str:
    return "```questions\n" + json.dumps(list(questions)) + "\n```"


def test_the_convert_prompt_asks_for_questions_at_the_end():
    template = resources.files("delve.modules.books").joinpath("prompts", "convert.md").read_text("utf-8")
    assert "```questions" in template and "at most 5" in template


def test_questions_are_parsed_and_stripped_from_the_text():
    filler = "The walls drip. " * (CHUNK_BUDGET // 20)
    book = _book(f"# The Caves\n\n## 1. Entrance\n\n{filler}", f"## 2. Hall\n\n{filler}")
    asked = [
        _asking({"text": "Is the entrance guarded at night?", "default": "Yes, by the same two kobolds."}),
        _asking({"text": "Do the kobolds sleep all day?", "default": "Only until noon."}, {"text": "   "}),
    ]
    answers = iter(asked)
    claude = FakeClaude(chunk=lambda source: f"{source}\n\n{next(answers)}")

    converted = _convert(book, claude, concurrency=1)

    markdown = "\n".join(t.markdown for t in converted.source.texts)
    assert "questions" not in markdown and "Is the entrance" not in markdown
    assert [(q.id, q.text, q.default) for q in converted.questions] == [
        ("q1", "Is the entrance guarded at night?", "Yes, by the same two kobolds."),
        ("q2", "Do the kobolds sleep all day?", "Only until noon."),
    ]


def test_at_most_five_questions_are_kept_and_a_bad_block_is_none():
    many = [{"text": f"Question {n}?", "default": f"Answer {n}."} for n in range(1, 8)]
    book = _book("# The Caves\n\nTwo kobolds watch the entrance of the caves.")
    converted = _convert(book, FakeClaude(chunk=lambda source: f"{source}\n\n{_asking(*many)}"))
    assert [q.text for q in converted.questions] == [f"Question {n}?" for n in range(1, 6)]

    broken = FakeClaude(chunk=lambda source: f"{source}\n\n```questions\nnot json\n```")
    converted = _convert(book, broken)
    assert converted.questions == []
    assert "not json" not in converted.source.texts[0].markdown


ROSTER = """# Pregenerated Characters

| Name | Race | Class | Level | AL | S | I | W | D | C | Ch | hp |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Aldon | ½E | F/M | 3/3 | CG | 18/76 | 15 | 9 | 14 | 13 | 11 | 17 |
| Tarla | H | C | 4 | LG | 12 | 10 | 16 | 9 | 14 | 13 | 22 |
"""


def _pregen(**kw):
    return {
        "id": "aldon",
        "name": "Aldon",
        "race": "½E",
        "class": "F/M",
        "level": "3/3",
        "alignment": "CG",
        "gear": ["long sword", "chain mail"],
        "background": "A wanderer from the north.",
        "stats": {"adnd2e": {"ability_scores": {"str": "18/76", "int": 15}, "hp_max": 17}},
        **kw,
    }


def test_the_roster_gives_the_modules_pregens():
    """The book's roster of pregenerated characters (U1's page 29) becomes `pregens`, for the players, valid against
    `$defs.pregen`; a pregen Claude also listed as a person is no NPC, and its refs go to the pregen. The roster's
    text stays a `gm` text."""
    entities = {
        "pregenerated-characters": {
            "npcs": [{"id": "aldon-npc", "name": "Aldon"}, {"id": "ned", "name": "Ned"}],
            "factions": [{"id": "party", "name": "The party", "members": ["npc:aldon-npc"]}],
            "pregens": [
                _pregen(),
                {"id": "tarla", "name": "Tarla", "race": "H", "class": "C", "level": 4, "alignment": "LG"},
                {"id": "nameless", "race": "H"},
                {"id": "bad-level", "name": "Bad", "level": ["3"]},
            ],
        }
    }

    converted = _convert(_book(ROSTER), FakeClaude(entities=entities))

    pregens = converted.source.entities["pregens"]
    assert pregens == [
        {**_pregen(), "audience": "player"},
        {
            "id": "tarla",
            "name": "Tarla",
            "race": "H",
            "class": "C",
            "level": 4,
            "alignment": "LG",
            "audience": "player",
        },
    ]
    assert [r["name"] for r in converted.source.entities["npcs"]] == ["Ned"]
    assert converted.source.entities["factions"][0]["members"] == ["pregen:aldon"]
    dropped = [w.message for w in converted.warnings if w.code == "entity-dropped"]
    assert len(dropped) == 2 and "pregen" in dropped[0] and "“Bad”" in dropped[1]
    assert not [w for w in converted.warnings if w.code == "audience-player" and w.ref.startswith("pregen:")]
    [text] = converted.source.texts
    assert text.audience == "gm" and "| Aldon | ½E |" in text.markdown


def test_the_entities_prompt_asks_for_the_roster_as_pregens():
    entities = " ".join(
        resources.files("delve.modules.books").joinpath("prompts", "entities.md").read_text("utf-8").split()
    )
    assert '"pregens": [{"id": "…", "name": "…", "race": "…"' in entities
    assert "roster of pregenerated characters" in entities and "½E" in entities
