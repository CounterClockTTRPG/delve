"""The picture pages a reading leaves in doubt, classified by Claude's look at them (faithful modules A2).

The reading finds a map page by its OCR: a legend, room numbers or a plate's title (`pdf.plate_title`). A whole-page
picture it didn't find a map on (OCR read nothing, or isn't installed) is sent to Claude once, through an injected
`Look`, with `prompts/classify-page.md`. The answer says whether the page is a map (with its plate title) or holds
handouts (with their boxes); art, blank and text pages stay as they were. A failed call or an answer that can't be read
leaves the page as it was, with a `page-not-classified` warning, and the conversion goes on. The converter cuts each
handout from its page's picture (`cut`).
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import replace
from importlib import resources
from typing import Any

from PIL import Image

from delve.maps.vision import Look, fit_for_vision
from delve.modules.books.calls import Halt
from delve.modules.books.fences import unfenced
from delve.modules.books.pdf import HandoutBox, PdfBook, PdfPage, plate_title
from delve.modules.source import Warning

PAGE_KINDS = ("map", "handout", "art", "blank", "text")

Progress = Callable[[str, int, int], None]
"""`progress(step, done, total)`, as the converter's."""


def _prompt(number: int) -> str:
    template = resources.files("delve.modules.books").joinpath("prompts", "classify-page.md").read_text("utf-8")
    return template.replace("{{number}}", str(number))


def _in_doubt(page: PdfPage) -> bool:
    return not page.map_page and any(picture.area >= 1.0 for picture in page.pictures)


async def classify_pages(book: PdfBook, look: Look | None, progress: Progress) -> PdfBook:
    """`book` with each whole-page picture that isn't a map page already classified by `look`: a map page gets
    `map_page` and its `plate_title` (the answer's, else the OCR's), a handout page its `handouts`. With `look` None,
    or no such page, nothing is sent and `book` is returned as it is. `progress("classifying", done, total)` counts
    the pages sent."""
    doubtful = [page.number for page in book.pages if _in_doubt(page)]
    if look is None or not doubtful:
        return book
    pages = list(book.pages)
    warnings = list(book.warnings)
    progress("classifying", 0, len(doubtful))
    for done, number in enumerate(doubtful, start=1):
        index = next(i for i, page in enumerate(pages) if page.number == number)
        page, warning = await _classify(pages[index], look)
        pages[index] = page
        if warning is not None:
            warnings.append(warning)
        progress("classifying", done, len(doubtful))
    return replace(book, pages=pages, warnings=warnings)


async def _classify(page: PdfPage, look: Look) -> tuple[PdfPage, Warning | None]:
    picture = next(picture for picture in page.pictures if picture.area >= 1.0)
    try:
        with Image.open(io.BytesIO(picture.png)) as opened:
            image, media_type = fit_for_vision(opened)
        answer = _answer(await look(_prompt(page.number), image, media_type))
    except Halt:
        raise
    except Exception as e:  # noqa: BLE001 (a failed call or an unreadable answer leaves the page as it was)
        reason = str(e) or type(e).__name__
        return page, Warning(
            "page-not-classified",
            f"Page {page.number} couldn't be classified ({reason}); it stays a picture.",
            f"page:{page.number}",
        )
    if answer["kind"] == "map":
        title = answer.get("title")
        title = " ".join(title.split()) if isinstance(title, str) and title.strip() else plate_title(page.ocr_text)
        return replace(page, map_page=True, plate_title=title), None
    if answer["kind"] == "handout":
        return replace(page, handouts=tuple(_handouts(answer.get("handouts")))), None
    return page, None


def _answer(reply: str) -> dict[str, Any]:
    answer = json.loads(unfenced(reply))
    if not isinstance(answer, dict) or answer.get("kind") not in PAGE_KINDS:
        raise ValueError("the answer isn't a page kind")
    return answer


def _handouts(entries: Any) -> list[HandoutBox]:
    """The answer's handouts, each box clamped to the page; an entry that isn't one, or whose box is empty once
    clamped, is dropped."""
    handouts = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        box = entry.get("box")
        if not isinstance(box, list) or len(box) != 4 or not all(isinstance(v, int | float) for v in box):
            continue
        x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in box)
        if x1 <= x0 or y1 <= y0:
            continue
        title, key, part = entry.get("title"), entry.get("key"), entry.get("part")
        handouts.append(
            HandoutBox(
                (x0, y0, x1, y1),
                title if isinstance(title, str) else "",
                str(key) if isinstance(key, str | int) and str(key).strip() else None,
                part if isinstance(part, str) and part.strip() else None,
            )
        )
    return handouts


def cut(png: bytes, box: tuple[float, float, float, float]) -> bytes:
    """The `box` of the picture `png` (`(x0, y0, x1, y1)`, as fractions of it), cropped, as a PNG."""
    with Image.open(io.BytesIO(png)) as opened:
        width, height = opened.size
        x0, y0, x1, y1 = box
        crop = opened.crop((round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)))
        out = io.BytesIO()
        crop.save(out, "PNG")
    return out.getvalue()
