"""Reading a PDF: pages in reading order, OCR for scanned pages, and their pictures (plateau 5 Task 1)."""

import io
import os
import shutil
from pathlib import Path

import pytest
from PIL import Image

from delve.modules.books import pdf
from delve.modules.books.pdf import PdfBook, PdfError, ReadStopped, read_pdf, tesseract_ocr
from tests.fixtures import pdfs


def _read(tmp_path: Path, pages, ocr=None) -> PdfBook:
    return read_pdf(pdfs.write_pdf(tmp_path / "book.pdf", pages), ocr=ocr)


ENGLISH = (
    "The party comes down the old road to the village at dusk. A farmer stands by the gate, and he tells them that "
    "the miller's son went into the hills three days ago and has not come back. The hills are said to hold a cave "
    "where a band of goblins lives, and the villagers fear that the boy was taken. If the characters agree to look "
    "for him, the farmer offers them a meal, a bed in his barn and ten gold pieces each. The path to the cave is "
    "steep and narrow, and it winds between rocks and thorn bushes for an hour."
)
"""About eighty words of a scanned page's English, as OCR reads it."""


def test_two_columns_read_in_order(tmp_path):
    left = ["The left column starts here.", "It goes on down the page.", "And ends at the bottom."]
    right = ["The right column comes next.", "It is read after the left one.", "Then the page ends."]
    page = pdfs.two_column_page(left, right, heading="The Caves of the Kobold King and their Tunnels")

    book = _read(tmp_path, [page])

    assert [p.number for p in book.pages] == [1]
    text = book.pages[0].text
    order = [text.index(s) for s in ["The Caves", *left, *right]]
    assert order == sorted(order)
    assert book.pages[0].ocr is False
    assert book.warnings == []


def test_paragraphs_are_blocks(tmp_path):
    page = pdfs.text_page(["The first paragraph, line one,", "and line two.", (72, 140, "A second paragraph.")])

    text = _read(tmp_path, [page]).pages[0].text

    assert text == "The first paragraph, line one,\nand line two.\n\nA second paragraph."


def test_a_scanned_page_uses_ocr(tmp_path):
    seen: list[bytes] = []

    def ocr(png: bytes) -> str:
        seen.append(png)
        return " ".join([ENGLISH] * 3)

    book = _read(
        tmp_path, [pdfs.picture_page(), pdfs.text_page(["A page with enough text of its own to be read."])], ocr=ocr
    )

    assert book.pages[0].text == " ".join([ENGLISH] * 3)
    assert book.pages[0].ocr is True
    assert book.pages[0].pictures == []
    assert book.pages[1].ocr is False
    assert len(seen) == 1
    image = Image.open(io.BytesIO(seen[0]))
    assert image.format == "PNG"
    assert image.width == pytest.approx(612 / 72 * 300, abs=2)  # 300 dpi
    assert book.warnings == []


def test_a_picture_page_that_ocr_finds_no_text_in_keeps_its_picture(tmp_path):
    """A map plate: OCR reads next to nothing from it, so it is a picture, not a scanned page (plateau 5 Task 8)."""
    book = _read(tmp_path, [pdfs.picture_page(), pdfs.image_page(0.3)], ocr=lambda png: " 12 \n")

    for page in book.pages:
        assert (page.text, page.ocr, page.ocr_text) == ("", True, "12")
        assert [p.area for p in page.pictures] == [1.0]
    assert book.warnings == []


def test_a_scanned_map_page_with_a_legend_is_kept_as_a_picture(tmp_path):
    """C1: OCR reads a map's legend and room numbers, and the map was lost as text; now it is a map page."""
    legend = "FALSE DOOR SECRET DOOR STAIRS UP COVERED PIT 1 2 3 4 5 6 7 8 9 10 11 12"

    page = _read(tmp_path, [pdfs.picture_page()], ocr=lambda png: legend).pages[0]

    assert page.text == ""
    assert [p.area for p in page.pictures] == [1.0]
    assert page.map_page is True
    assert page.ocr_text == legend


def test_a_handout_read_as_junk_is_kept_as_a_picture(tmp_path):
    """C5: a cover or a handout that OCR reads as noise keeps its picture, and the noise reaches no text."""
    junk = " ".join(["Ue A A NE OM TON NIL ON b i 10 wePr. Wena Sylar"] * 20)

    page = _read(tmp_path, [pdfs.picture_page()], ocr=lambda png: junk).pages[0]

    assert page.text == ""
    assert [p.area for p in page.pictures] == [1.0]
    assert page.map_page is False
    assert page.ocr_text == junk


def test_a_scanned_text_page_stays_text(tmp_path):
    """Review Focus 1: a scanned page of 400 real words is text, whatever pictures it has."""
    english = " ".join([ENGLISH] * 5)
    assert len(english.split()) >= 400

    page = _read(tmp_path, [pdfs.picture_page(), pdfs.image_page(0.3)], ocr=lambda png: english).pages

    for read in page:
        assert read.text == english
        assert read.ocr is True
        assert read.pictures == []
        assert read.map_page is False


def test_a_short_scanned_page_of_text_is_a_picture_with_a_warning(tmp_path):
    """Review: a scanned page with 40 real words or more, but under `MIN_TEXT_WORDS`, is kept as a picture, and says
    so, rather than losing its text silently."""
    words, real = pdf._real_words(ENGLISH)[1], pdf._real_words("SECRET DOOR\nStairs down")[1]
    assert pdf.MIN_PICTURE_TEXT_WORDS <= words < pdf.MIN_TEXT_WORDS and real < pdf.MIN_PICTURE_TEXT_WORDS
    reads = iter([ENGLISH, "SECRET DOOR\nStairs down"])

    book = _read(tmp_path, [pdfs.picture_page(), pdfs.picture_page()], ocr=lambda png: next(reads))

    short, caption = book.pages
    assert (short.text, short.ocr_text, [p.area for p in short.pictures]) == ("", ENGLISH, [1.0])
    assert caption.text == "" and [p.area for p in caption.pictures] == [1.0]
    [warning] = book.warnings
    assert (warning.code, warning.ref) == ("page-text-as-picture", "page:1")
    assert warning.message == "Page 1 has text that was kept as a picture; check it."


def test_a_text_layer_page_is_unchanged(tmp_path):
    """Review Focus 2: a born-digital page goes the old path; OCR isn't asked, and nothing is a map page."""
    words = ["A page of text with a picture in the middle of it, as books have."]
    pages = [pdfs.text_page(words), pdfs.image_page(0.3, texts=words), pdfs.image_page(0.6, texts=words)]

    book = _read(tmp_path, pages, ocr=lambda png: pytest.fail("a page with a text layer is not OCRed"))

    plain, pictured, whole = book.pages
    assert [p.text for p in book.pages] == [words[0]] * 3
    assert all(p.ocr is False and p.map_page is False and p.ocr_text == "" for p in book.pages)
    assert plain.pictures == []
    assert [p.area for p in pictured.pictures] == [pytest.approx(0.3, abs=0.01)]
    assert [p.area for p in whole.pictures] == [1.0]
    assert book.warnings == []


@pytest.mark.parametrize(
    ("text", "share"),
    [
        ("", 0.0),
        ("The old road goes to the village.", 1.0),
        ("TON NIL wePr. Wena Sylar", 1.0),
        ("Dungeonsjp)ragons' cee 1234 lll Advan", 0.4),
        ("a b c 12 xx", 0.0),
    ],
)
def test_real_share(text, share):
    assert pdf.real_share(text) == pytest.approx(share)


def test_without_tesseract_a_scanned_page_is_a_warning_and_a_picture(tmp_path):
    pages = [
        pdfs.picture_page(),
        pdfs.image_page(0.3),
        pdfs.text_page(["A page with enough text to need no OCR at all."]),
    ]

    book = _read(tmp_path, pages, ocr=None)

    assert [(w.code, w.ref) for w in book.warnings] == [("page-not-read", "page:1"), ("page-not-read", "page:2")]
    for page in book.pages[:2]:
        assert page.text == ""
        assert page.ocr is False
        assert [p.area for p in page.pictures] == [1.0]
        assert Image.open(io.BytesIO(page.pictures[0].png)).format == "PNG"
    assert book.pages[2].pictures == []


def test_a_short_page_without_images_is_not_a_warning(tmp_path):
    book = _read(tmp_path, [pdfs.text_page(["12"]), pdfs.Page()], ocr=None)

    assert [p.text for p in book.pages] == ["12", ""]
    assert book.warnings == []


def test_pictures_and_picture_pages(tmp_path):
    words = ["A page of text with a picture in the middle of it, as books have."]
    pages = [
        pdfs.image_page(0.3, texts=words),  # a picture on a page of text
        pdfs.image_page(0.02, texts=words),  # too small to keep
        pdfs.image_page(0.6, texts=words),  # a picture page: the whole page is rendered
    ]

    book = _read(tmp_path, pages)

    first, small, whole = book.pages
    assert [p.page for p in first.pictures] == [1]
    assert first.pictures[0].area == pytest.approx(0.3, abs=0.01)
    image = Image.open(io.BytesIO(first.pictures[0].png))
    assert image.format == "PNG"
    assert image.width == pytest.approx(612 * 0.3**0.5 / 72 * 150, abs=2)  # 150 dpi
    assert small.pictures == []
    assert [p.area for p in whole.pictures] == [1.0]
    assert Image.open(io.BytesIO(whole.pictures[0].png)).width == pytest.approx(612 / 72 * 150, abs=2)
    assert all(p.text.startswith("A page of text") for p in book.pages)
    assert [(w.code, w.ref) for w in book.warnings] == [("image-dropped", "page:2")]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (pdfs.encrypted_pdf(), "password"),
        (pdfs.truncated_pdf(), "can't be read"),
        (pdfs.zero_page_pdf(), "no pages"),
        (b"%PDF-1.4\nnot a pdf at all", "can't be read"),
    ],
    ids=["encrypted", "truncated", "zero-pages", "garbage"],
)
def test_broken_pdfs_raise(tmp_path, data, message):
    path = tmp_path / "broken.pdf"
    path.write_bytes(data)

    with pytest.raises(PdfError, match=message):
        read_pdf(path, ocr=None)


def test_a_book_of_many_pages(tmp_path):
    book = _read(tmp_path, pdfs.book(30))

    assert [p.number for p in book.pages] == list(range(1, 31))
    assert book.pages[29].text.startswith("Page 30 ")


def test_the_render_size_is_capped(tmp_path):
    assert pdf.MAX_RENDER_PIXELS == 50_000_000


@pytest.mark.parametrize("ocr", [None, lambda png: ""], ids=["no-ocr", "ocr"])
def test_an_oversized_page_is_rendered_at_a_lower_resolution(tmp_path, monkeypatch, ocr):
    """A 14400 × 14400 pt page at 150 dpi would be 900 million pixels; a small cap keeps the test light."""
    monkeypatch.setattr(pdf, "MAX_RENDER_PIXELS", 30_000)
    seen: list[bytes] = []

    def reading(png: bytes) -> str:
        seen.append(png)
        return ocr(png)

    huge = pdfs.Page(images=[pdfs.ImageBox(0, 0, 14400, 14400)], width=14400, height=14400)
    small = pdfs.Page(images=[pdfs.ImageBox(0, 0, 36, 36)], width=36, height=36)  # 150 × 150 pixels at 300 dpi
    book = _read(tmp_path, [huge, small], ocr=reading if ocr else None)

    too_large = [w for w in book.warnings if w.code == "page-too-large"]
    assert [w.ref for w in too_large] == ["page:1"]
    assert "lower resolution" in too_large[0].message
    for png in [*seen[:1], book.pages[0].pictures[0].png]:
        image = Image.open(io.BytesIO(png))
        assert image.width * image.height < 30_000
        assert image.width > 150
    assert [p.area for p in book.pages[0].pictures] == [1.0]


def test_a_picture_cropped_from_an_oversized_page_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_RENDER_PIXELS", 20_000)
    words = ["A page of text with a picture in the middle of it, as books have."]
    huge = pdfs.Page(
        texts=[pdfs.TextRun(72, 72, words[0])], images=[pdfs.ImageBox(0, 7200, 14400, 4800)], width=14400, height=14400
    )

    book = _read(tmp_path, [huge])

    assert [p.area for p in book.pages[0].pictures] == [pytest.approx(1 / 3, abs=0.01)]
    assert [(w.code, w.ref) for w in book.warnings] == [("page-too-large", "page:1")]


def test_render_page_draws_one_page_under_the_cap(tmp_path, monkeypatch):
    """Faithful modules D3: the gap reading draws the page a lost glyph is on."""
    monkeypatch.setattr(pdf, "MAX_RENDER_PIXELS", 30_000)
    path = pdfs.write_pdf(tmp_path / "book.pdf", [pdfs.text_page(["Page one."]), pdfs.text_page(["Page two."])])

    png = pdf.render_page(path, 2, dpi=72)

    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG"
    assert image.width * image.height < 30_000
    with pytest.raises(PdfError):
        pdf.render_page(path, 3)


def test_should_stop_is_asked_before_each_page(tmp_path):
    asked: list[int] = []

    def should_stop() -> bool:
        asked.append(len(asked) + 1)
        return len(asked) == 3

    with pytest.raises(ReadStopped):
        read_pdf(pdfs.write_pdf(tmp_path / "book.pdf", pdfs.book(5)), ocr=None, should_stop=should_stop)

    assert asked == [1, 2, 3]
    book = read_pdf(tmp_path / "book.pdf", ocr=None, should_stop=lambda: False)
    assert len(book.pages) == 5


def test_progress_hears_each_page_read(tmp_path):
    heard: list[tuple[int, int]] = []
    read_pdf(pdfs.write_pdf(tmp_path / "book.pdf", pdfs.book(3)), ocr=None, progress=lambda d, t: heard.append((d, t)))
    assert heard == [(1, 3), (2, 3), (3, 3)]


def test_a_page_drawn_in_vectors_is_a_picture_page(tmp_path):
    pages = [
        pdfs.drawn_page(6, texts=["1", "2"]),  # a map drawn in lines, with room numbers
        pdfs.drawn_page(2),  # a few rules: not a drawing
        pdfs.drawn_page(6, texts=["A page with enough text of its own to be read, and a drawing."]),
    ]

    book = _read(tmp_path, pages, ocr=lambda png: pytest.fail("a drawn page is not OCRed"))

    drawn, ruled, text = book.pages
    assert [p.area for p in drawn.pictures] == [1.0]
    assert Image.open(io.BytesIO(drawn.pictures[0].png)).width == pytest.approx(612 / 72 * 150, abs=2)
    assert drawn.ocr is False
    assert drawn.text.split() == ["1", "2"]
    assert ruled.pictures == []
    assert text.pictures == []
    assert book.warnings == []


def test_tesseract_ocr_is_off_in_tests(monkeypatch):
    """Tests never run `tesseract`: the autouse fixture sets `DELVE_OCR=off`, and `tesseract_ocr()` answers None
    under it, installed or not."""
    assert os.environ["DELVE_OCR"] == "off"
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert tesseract_ocr() is None


def test_a_plate_title_makes_a_map_page():
    """A2: a plate's title ("HAUNTED HOUSE", "Ground floor") marks a map page that has no legend and no room
    numbers."""
    read = "HAUNTED HOUSE\nGround floor"

    assert pdf.plate_title(read) == "HAUNTED HOUSE"
    assert pdf._is_map(read) is True
    assert pdf.plate_title("The   Sea Ghost:\tmain   deck") == "The Sea Ghost: main deck"
    assert pdf.plate_title("The Cellars") == "The Cellars"


@pytest.mark.parametrize(
    "read",
    [
        "",
        "A note for the players",
        "This line is far too long to be the title of a plate, though it names a map",
        "THE HOUSE THAT WAS LEFT TO ROT BY THE SEA FOR YEARS",  # more than eight words
        "Mapmaker's guild",  # a plate word only as a part of a word
    ],
)
def test_no_plate_title(read):
    assert pdf.plate_title(read) is None


def test_house_and_dungeon_alone_dont_make_a_title_page_a_plate():
    """The party's amendment: on a page that passes the title-page test (at most `TITLE_PAGE_WORDS` words), "house"
    and "dungeon" alone are not plate words, so a cover ("Dungeon Module U1") is left to the vision classifier."""
    cover = "DUNGEON MODULE U1\nThe Sinister Secret of Saltmarsh"
    assert pdf.real_words(cover) <= pdf.TITLE_PAGE_WORDS

    assert pdf.plate_title(cover) is None
    assert pdf.plate_title("THE HAUNTED HOUSE") is None
    assert pdf._is_map(cover) is False
    longer = cover + "\n" + ENGLISH  # not a title page: "Dungeon" counts again
    assert pdf.plate_title(longer) == "DUNGEON MODULE U1"


def test_a_scanned_plate_keeps_its_title(tmp_path):
    page = _read(tmp_path, [pdfs.picture_page()], ocr=lambda png: "THE SEA GHOST\nMain deck").pages[0]

    assert page.map_page is True
    assert page.plate_title == "Main deck", "the first line holding a plate word"
    assert page.handouts == ()


def test_bold_and_italic_are_kept(tmp_path):
    """D4: a run of bold or italic words within a line is wrapped once, from each word's font."""
    page = pdfs.Page(
        texts=[
            pdfs.TextRun(
                72, 72, "The witch casts ", spans=[("sleep", "Helvetica-Bold"), (" on the party.", "Helvetica")]
            ),
            pdfs.TextRun(72, 86, "As told in ", spans=[("The Codex", "Helvetica-Oblique"), (", page 4.", "Helvetica")]),
            pdfs.TextRun(
                72, 100, "Both: ", spans=[("magic missile", "Helvetica-BoldOblique"), (" and a shield.", "Helvetica")]
            ),
        ]
    )

    text = _read(tmp_path, [page]).pages[0].text

    assert text.splitlines() == [
        "The witch casts **sleep** on the party.",
        "As told in *The Codex*, page 4.",
        "Both: ***magic missile*** and a shield.",
    ]


def test_a_wholly_bold_line_stays_bare(tmp_path):
    """A line all in bold is a heading: Claude makes it one, so it gets no marks."""
    page = pdfs.Page(
        texts=[
            pdfs.TextRun(72, 72, "12. The Well Room", size=14, font="Helvetica-Bold"),
            pdfs.TextRun(72, 100, "A well stands in the middle of the room, its rope long gone."),
        ]
    )

    assert _read(tmp_path, [page]).pages[0].text.split("\n\n") == [
        "12. The Well Room",
        "A well stands in the middle of the room, its rope long gone.",
    ]


def test_the_marks_change_no_numbers_and_no_word_count():
    """`numbers_changed` and the short check read the source with its marks against Claude's Markdown."""
    from delve.modules.books.convert import _words, numbers_changed

    marked = "Header\nThe **giant centipede** (*AC 9; HD ¼; hp 2*) bites for 1d3.\nFooter"
    plain = "The giant centipede (AC 9; HD ¼; hp 2) bites for 1d3."

    assert numbers_changed([marked], plain) == []
    assert _words(marked) == _words(plain) + 2  # the header and the footer, not the marks


def test_small_pictures_are_kept_from_3_percent(tmp_path):
    """D5: an illustration of 5 % of the page is kept; a 1 % ornament is left out, with one warning per page."""
    words = "A page of text with pictures in it, as books have."
    page = pdfs.Page(
        texts=[pdfs.TextRun(72, 20, words)],
        images=[
            pdfs.ImageBox(72, 100, 612 * 0.25, 792 * 0.2),  # 5 %
            pdfs.ImageBox(72, 400, 61.2, 79.2),  # 1 %
            pdfs.ImageBox(300, 400, 61.2, 79.2),  # 1 %
        ],
    )

    book = _read(tmp_path, [page, pdfs.image_page(0.3, texts=[words])])

    kept, other = book.pages
    assert pdf.PICTURE_SHARE == 0.03
    assert [p.area for p in kept.pictures] == [pytest.approx(0.05, abs=0.001)]
    assert [p.area for p in other.pictures] == [pytest.approx(0.3, abs=0.01)]
    [warning] = book.warnings
    assert (warning.code, warning.ref) == ("image-dropped", "page:1")
    assert warning.message == "Page 1: 2 small images (under 3 % of the page) were left out."
