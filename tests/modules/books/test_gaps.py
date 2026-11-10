"""Glyphs the text layer lost, read from the page's picture (faithful modules Task 13, D3).

Claude is a fake `Look` that answers by the numbered lines it is sent; the pages are a hand-built `PdfBook`, and the
page's picture a small Pillow image.
"""

import asyncio
import io
import json
import re

from PIL import Image

from delve.modules.books.gaps import GAP, MAX_GAP_PAGES, fill_gaps
from delve.modules.books.pdf import PdfBook, PdfPage
from delve.modules.source import ModuleSource, TextDoc

GOBLINS = """# The Cellar

## 3. The Store

Two goblins guard the barrels.

Goblins (2): AC 7; HD ; hp 4; #AT 1; D 1-6."""
ROSTER = """# The Roster

| Name | Race | Sex | Class |
|---|---|---|---|
| 18. Ned Shakeshaft | H | M | F |
| 19. Theodore Dobbins |  | M | T |
| 20. Lia Blackwood | E | F | M |"""


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(out, "PNG")
    return out.getvalue()


def _book() -> PdfBook:
    return PdfBook(
        [
            PdfPage(1, "THE CELLAR 3. The Store Two goblins guard the barrels.\nGoblins (2): AC 7; HD ; hp 4;", False),
            PdfPage(2, "A page with nothing lost on it.", False),
            PdfPage(5, "THE ROSTER Name Race Sex Class 18. Ned Shakeshaft H M F\n19. Theodore Dobbins M T", False),
        ],
        [],
    )


def _source() -> ModuleSource:
    return ModuleSource(
        texts=[
            TextDoc("the-cellar", "The Cellar", "gm", None, GOBLINS),
            TextDoc("the-roster", "The Roster", "gm", None, ROSTER),
        ],
        entities={
            "encounters": [
                {"id": "goblins", "name": "Goblins", "description": "Goblins (2): AC 7; HD ; hp 4; #AT 1; D 1-6."}
            ]
        },
    )


class FakeLook:
    """Answers each numbered line through `fix(line)`; records the prompts and the pages' pictures it got."""

    def __init__(self, fix) -> None:
        self.fix = fix
        self.prompts: list[str] = []
        self.images: list[tuple[bytes, str]] = []

    async def __call__(self, prompt: str, image: bytes, media_type: str) -> str:
        self.prompts.append(prompt)
        self.images.append((image, media_type))
        lines = re.findall(r"^(\d+)\. (.*)$", prompt.split("<lines>")[1], re.MULTILINE)
        return json.dumps([{"n": int(n), "line": self.fix(line)} for n, line in lines])


def _fill(source: ModuleSource, book: PdfBook, look):
    rendered: list[int] = []

    async def page_image(number: int) -> bytes:
        rendered.append(number)
        return _png()

    filled, warnings = asyncio.run(fill_gaps(source, book, look, page_image))
    return filled, warnings, rendered


def _hit_dice(line: str) -> str:
    return line.replace("HD ;", "HD ½;")


def test_the_gap_pattern():
    assert GAP.search("AC 7; HD ; hp 4")
    assert GAP.search("MV 12; #AT , D 1-6")
    assert GAP.search("| 19. Theodore Dobbins |  | M |")
    assert not GAP.search("AC 7; HD 1; hp 4; THAC0 20")
    assert not GAP.search("THAC ; no field"), "a field name inside a word isn't one"


def test_a_lost_half_is_read_from_the_page_and_filled_in_the_records_too():
    look = FakeLook(_hit_dice)

    filled, warnings, rendered = _fill(
        ModuleSource(texts=_source().texts[:1], entities=_source().entities), _book(), look
    )

    assert "Goblins (2): AC 7; HD ½; hp 4; #AT 1; D 1-6." in filled.texts[0].markdown
    assert filled.entities["encounters"][0]["description"] == "Goblins (2): AC 7; HD ½; hp 4; #AT 1; D 1-6."
    assert rendered == [1], "only the page the line is on is drawn"
    [(_, media_type)] = look.images
    assert media_type == "image/png"
    assert "page 1" in look.prompts[0]
    [warning] = warnings
    assert warning.code == "text-filled"
    assert warning.message == "Read from page 1's picture: “HD ;” → “HD ½;”. Check it."
    assert warning.ref == "text:the-cellar"


def test_a_roster_row_is_filled_and_its_table_sent_whole():
    look = FakeLook(lambda line: line.replace("|  |", "| ½ |"))

    filled, warnings, rendered = _fill(ModuleSource(texts=_source().texts[1:]), _book(), look)

    assert "| 19. Theodore Dobbins | ½ | M | T |" in filled.texts[0].markdown
    assert rendered == [5]
    sent = look.prompts[0].split("<lines>")[1]
    assert "18. Ned Shakeshaft" in sent and "20. Lia Blackwood" in sent, "every row of the table goes"
    assert "|---|" not in sent
    assert [w.code for w in warnings] == ["text-filled"]


def test_a_half_added_to_another_row_of_the_table_is_accepted():
    def fix(line: str) -> str:
        line = line.replace("|  |", "| ½ |")
        return line.replace("| 20. Lia Blackwood | E |", "| 20. Lia Blackwood | ½E |")

    filled, warnings, _ = _fill(ModuleSource(texts=_source().texts[1:]), _book(), FakeLook(fix))

    markdown = filled.texts[0].markdown
    assert "| 19. Theodore Dobbins | ½ | M | T |" in markdown
    assert "| 20. Lia Blackwood | ½E | F | M |" in markdown
    assert "| 18. Ned Shakeshaft | H | M | F |" in markdown
    assert [w.code for w in warnings] == ["text-filled", "text-filled"]


def test_an_answer_that_changes_a_word_too_is_refused():
    look = FakeLook(lambda line: _hit_dice(line).replace("Goblins", "Kobolds"))
    source = _source()

    filled, warnings, _ = _fill(ModuleSource(texts=source.texts[:1], entities=source.entities), _book(), look)

    assert filled.texts[0].markdown == GOBLINS
    assert filled.entities == source.entities
    [warning] = warnings
    assert warning.code == "text-gap"
    assert warning.message == (
        "Page 1's text layer lost a character here: “Goblins (2): AC 7; HD ; hp 4; #AT 1; D 1-6.”. "
        "Check it against the page."
    )


def test_an_answer_that_leaves_the_gap_is_refused():
    filled, warnings, _ = _fill(ModuleSource(texts=_source().texts[:1]), _book(), FakeLook(lambda line: line))

    assert filled.texts[0].markdown == GOBLINS
    assert [w.code for w in warnings] == ["text-gap"]


def test_a_failed_call_warns_and_the_conversion_goes_on():
    async def look(prompt: str, image: bytes, media_type: str) -> str:
        raise RuntimeError("claude stopped")

    filled, warnings, _ = _fill(_source(), _book(), look)

    assert filled == _source()
    assert [w.code for w in warnings] == ["text-gap", "text-gap"]


def test_no_look_warns_and_sends_nothing():
    filled, warnings, rendered = _fill(_source(), _book(), None)

    assert filled == _source()
    assert rendered == []
    assert [(w.code, w.ref) for w in warnings] == [("text-gap", "text:the-cellar"), ("text-gap", "text:the-roster")]
    assert warnings[1].message.startswith("Page 5's text layer lost a character here: “| 19. Theodore Dobbins |  |")


def test_a_book_without_gaps_sends_nothing():
    look = FakeLook(_hit_dice)
    source = ModuleSource(texts=[TextDoc("t", "T", "gm", None, "# T\n\nGoblins: AC 7; HD 1; hp 4.")])

    filled, warnings, rendered = _fill(source, _book(), look)

    assert (filled, warnings, rendered, look.prompts) == (source, [], [], [])


def test_at_most_twelve_pages_are_sent():
    pages = [PdfPage(n, f"Monster number {n} here: AC 7; HD ;", False) for n in range(1, 15)]
    texts = [
        TextDoc(f"t{n}", f"T{n}", "gm", None, f"# T{n}\n\nMonster number {n} here: AC 7; HD ;") for n in range(1, 15)
    ]
    look = FakeLook(_hit_dice)

    _, warnings, rendered = _fill(ModuleSource(texts=texts), PdfBook(pages, []), look)

    assert rendered == list(range(1, MAX_GAP_PAGES + 1))
    assert [w.code for w in warnings] == ["text-filled"] * MAX_GAP_PAGES + ["text-gap"] * 2
