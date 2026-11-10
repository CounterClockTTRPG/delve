"""The picture pages a reading leaves in doubt, classified by Claude's look at them (faithful modules Task 2, A2).

Claude is `FakeDM`'s vision call; the pages are Pillow pictures in a `PdfBook` built by hand.
"""

import asyncio
import io
import json

import pytest
from PIL import Image

from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice
from delve.maps.vision import VISION_MAX_SIDE
from delve.modules.books.calls import Halt
from delve.modules.books.classify import PAGE_KINDS, classify_pages, cut
from delve.modules.books.pdf import HandoutBox, PdfBook, PdfPage, Picture


def _png(width: int = 2000, height: int = 2600) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, "PNG")
    return out.getvalue()


def _picture_page(number: int, *, ocr_text: str = "", map_page: bool = False) -> PdfPage:
    return PdfPage(number, "", True, [Picture(number, _png(), 1.0)], map_page=map_page, ocr_text=ocr_text)


def _text_page(number: int) -> PdfPage:
    return PdfPage(number, "A page of text with a small picture.", False, [Picture(number, _png(200, 200), 0.3)])


def _look(dm: FakeDM):
    async def look(prompt: str, image: bytes, media_type: str) -> str:
        return await dm.vision_call(prompt, image, media_type, BackendChoice("fake", "fake-large"))

    return look


def _classify(book: PdfBook, dm: FakeDM | None) -> tuple[PdfBook, list[tuple[str, int, int]]]:
    heard: list[tuple[str, int, int]] = []
    look = _look(dm) if dm is not None else None
    classified = asyncio.run(classify_pages(book, look, lambda step, done, total: heard.append((step, done, total))))
    return classified, heard


def test_the_page_kinds():
    assert PAGE_KINDS == ("map", "handout", "art", "blank", "text")


def test_classify_marks_a_map_page():
    dm = FakeDM([], vision_handler=lambda *_: json.dumps({"kind": "map", "title": "The Sea Ghost: decks"}))
    book = PdfBook([_text_page(1), _picture_page(2, ocr_text="XYZ")], [])

    classified, heard = _classify(book, dm)

    text, plate = classified.pages
    assert text == book.pages[0]
    assert (plate.map_page, plate.plate_title, plate.handouts) == (True, "The Sea Ghost: decks", ())
    assert plate.pictures == book.pages[1].pictures
    [(media_type, size)] = dm.vision_images
    assert media_type == "image/png" and size > 0
    [prompt] = dm.vision_prompts
    assert "page 2" in prompt
    assert heard == [("classifying", 0, 1), ("classifying", 1, 1)]
    assert classified.warnings == []


def test_the_picture_is_fitted_for_vision():
    sent: list[bytes] = []

    async def look(prompt: str, image: bytes, media_type: str) -> str:
        sent.append(image)
        return '{"kind": "art", "title": null, "handouts": []}'

    asyncio.run(classify_pages(PdfBook([_picture_page(1)], []), look, lambda *_: None))

    [image] = sent
    assert max(Image.open(io.BytesIO(image)).size) == VISION_MAX_SIDE


def test_a_map_answer_without_a_title_keeps_the_ocr_plate_title():
    dm = FakeDM([], vision_handler=lambda *_: '```json\n{"kind": "map", "title": null}\n```')
    book = PdfBook([_picture_page(1, ocr_text="Ground floor\n12")], [])

    [page] = _classify(book, dm)[0].pages

    assert (page.map_page, page.plate_title) == (True, "Ground floor")


def test_classify_reads_handouts():
    answer = {
        "kind": "handout",
        "title": None,
        "handouts": [
            {"box": [0.1, 0.1, 0.5, 0.4], "title": "A parchment", "key": "22", "part": None},
            {"box": [0.6, -0.2, 1.3, 0.9], "title": "A sea chart", "key": "9", "part": "ship"},
            {"box": [0.7, 0.7, 0.7, 0.9], "title": "Empty", "key": None, "part": None},
        ],
    }
    dm = FakeDM([], vision_handler=lambda *_: f"Here is what I see:\n\n```json\n{json.dumps(answer)}\n```")

    [page] = _classify(PdfBook([_picture_page(5)], []), dm)[0].pages

    assert page.map_page is False
    assert page.handouts == (
        HandoutBox((0.1, 0.1, 0.5, 0.4), "A parchment", "22", None),
        HandoutBox((0.6, 0.0, 1.0, 0.9), "A sea chart", "9", "ship"),
    )


def test_an_art_page_stays_as_it_was():
    dm = FakeDM([], vision_handler=lambda *_: '{"kind": "art", "title": "A sea hag"}')
    book = PdfBook([_picture_page(1)], [])

    classified, _ = _classify(book, dm)

    assert classified.pages == book.pages
    assert classified.warnings == []


def test_classify_survives_a_bad_answer():
    answers = iter(["I think this is a map of a house.", '{"kind": "poster"}', "[1, 2]"])

    def handler(prompt: str, image: bytes, media_type: str) -> str:
        answer = next(answers, None)
        if answer is None:
            raise RuntimeError("claude stopped (exit code 1): overloaded")
        return answer

    book = PdfBook([_picture_page(n) for n in (1, 2, 3, 4)], [])

    classified, heard = _classify(book, FakeDM([], vision_handler=handler))

    assert classified.pages == book.pages
    assert [(w.code, w.ref) for w in classified.warnings] == [
        ("page-not-classified", "page:1"),
        ("page-not-classified", "page:2"),
        ("page-not-classified", "page:3"),
        ("page-not-classified", "page:4"),
    ]
    assert "overloaded" in classified.warnings[3].message
    assert heard[-1] == ("classifying", 4, 4)


def test_the_books_warnings_are_kept():
    from delve.modules.source import Warning

    earlier = Warning("page-not-read", "Page 1 has no text to read.", "page:1")
    book = PdfBook([_picture_page(1)], [earlier])

    classified, _ = _classify(book, FakeDM([], vision_handler=lambda *_: "prose"))

    assert [w.code for w in classified.warnings] == ["page-not-read", "page-not-classified"]


def test_classify_sends_nothing_without_pictures():
    dm = FakeDM([], vision_handler=lambda *_: '{"kind": "map"}')
    book = PdfBook([_text_page(1), _picture_page(2, map_page=True), PdfPage(3, "Text only.", False)], [])

    classified, heard = _classify(book, dm)

    assert classified == book
    assert dm.vision_prompts == []
    assert heard == []


def test_classify_sends_nothing_without_a_look():
    book = PdfBook([_picture_page(1)], [])

    classified, heard = _classify(book, None)

    assert classified is book
    assert heard == []


# --- handouts cut from their page (faithful modules Task 12, D2) -----------------------------------------------------


def test_cut_crops_the_box_as_a_png():
    out = io.BytesIO()
    page = Image.new("RGB", (400, 200), "white")
    page.paste((200, 30, 30), (100, 50, 300, 150))
    page.save(out, "PNG")

    cut_png = cut(out.getvalue(), (0.25, 0.25, 0.75, 0.75))

    with Image.open(io.BytesIO(cut_png)) as handout:
        assert (handout.format, handout.size) == ("PNG", (200, 100))
        assert handout.getpixel((0, 0)) == (200, 30, 30) and handout.getpixel((199, 99)) == (200, 30, 30)


def test_a_halt_while_looking_stops_the_classifying():
    """A failed look leaves the page a picture; a `Halt` (a thorough job's pause at the usage limit) isn't such a
    failure, and goes through."""

    async def look(prompt: str, image: bytes, media_type: str) -> str:
        raise Halt("the usage limit")

    with pytest.raises(Halt):
        asyncio.run(classify_pages(PdfBook([_picture_page(1)], []), look, lambda *_: None))
