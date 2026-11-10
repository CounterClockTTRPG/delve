"""Reading a PDF: each page's text in reading order, OCR for scanned pages, and the pictures worth keeping.

pdfplumber (with pdfminer.six for the text and pypdfium2 for rendering) reads the file; PyMuPDF is not used, because
it is AGPL. The reading order and the OCR threshold come from ttrpg3's `ingest.py`.
"""

from __future__ import annotations

import io
import math
import os
import re
import shutil
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect

from delve.modules.source import Warning

MIN_PAGE_CHARS = 40
"""A page with fewer characters of text than this is read as scanned, and goes to OCR."""
MIN_TEXT_WORDS = 150
"""A scanned page is text only when OCR reads at least this many words from it (see `real_share` for a word)."""
MIN_REAL_SHARE = 0.6
"""… and at least this share of what it read looks like words; otherwise it is a picture page (a map, a handout)."""
MIN_PICTURE_TEXT_WORDS = 40
"""A picture page whose OCR reads at least this many words (but under `MIN_TEXT_WORDS`) gets a `page-text-as-picture`
warning: it may be a short page of text."""
MAP_WORDS = frozenset({"door", "secret", "stairs", "trap", "pit", "scale", "map", "north", "corridor", "legend"})
MIN_MAP_WORDS = 2
"""A picture page whose OCR holds at least this many of `MAP_WORDS` is a map page."""
MIN_MAP_NUMBERS = 8
"""… or at least this many different 1–3-digit numbers: a map's room numbers."""
PLATE_WORDS = frozenset(
    {
        "house",
        "cellar",
        "cellars",
        "floor",
        "floors",
        "deck",
        "decks",
        "level",
        "levels",
        "map",
        "plan",
        "cavern",
        "caverns",
        "caves",
        "dungeon",
    }
)
"""… or a line of its OCR holding one of these words is a plate's title (`plate_title`): "HAUNTED HOUSE", "Ground
floor"."""
TITLE_PAGE_PLATE_WORDS = frozenset({"house", "dungeon"})
"""Plate words that a title page's OCR (at most `TITLE_PAGE_WORDS` words) holds as often as a plate's ("Dungeon
Module U1"): there they make no plate title, and the page is left to the vision classifier."""
TITLE_PAGE_WORDS = 15
"""A title page has at most this many words (`real_words`) in its OCR: the converter's chapter title page."""
PLATE_TITLE_WORDS = 8
PLATE_TITLE_CHARS = 60
"""A plate's title is a line of one to `PLATE_TITLE_WORDS` words and at most `PLATE_TITLE_CHARS` characters."""
COLUMN_GAP = 0.15
"""A gap between the blocks' left edges wider than this share of the page width is a column boundary."""
PICTURE_SHARE = 0.03
"""An image covering at least this share of the page is kept as a picture; a smaller one is left out, with one
`image-dropped` warning per page."""
PICTURE_PAGE_SHARE = 0.5
"""A page whose pictures cover at least this share of it is a picture page: the whole page is rendered."""
MIN_DRAWING_OBJECTS = 10
"""A short page with at least this many vector objects (curves, rectangles, lines) is a drawing: a picture page."""
OCR_DPI = 300
PICTURE_DPI = 150
MAX_RENDER_PIXELS = 50_000_000
"""A render stays under this many pixels: a larger page is rendered at a lower resolution, with a warning."""

Ocr = Callable[[bytes], str]
"""Reads the text of a PNG."""


class PdfError(ValueError):
    """The PDF can't be read: it is encrypted, corrupt, or has no pages."""


class ReadStopped(Exception):
    """`read_pdf`'s `should_stop` answered True: the reading was stopped before the next page."""


@dataclass(frozen=True)
class Picture:
    page: int
    png: bytes
    area: float
    """Its share of the page (0–1); 1.0 is the whole page, rendered for a picture page or a page not read."""


@dataclass(frozen=True)
class HandoutBox:
    """A handout on a picture page, as Claude's look at the page found it (`classify`)."""

    box: tuple[float, float, float, float]
    """`(x0, y0, x1, y1)`, as fractions of the page."""
    title: str
    key: str | None = None
    """The printed key of the room it belongs to, when the page says."""
    part: str | None = None
    """The part (the house, the ship) it belongs to, when the page says."""


@dataclass(frozen=True)
class PdfPage:
    number: int
    """From 1."""
    text: str
    """In reading order: blocks separated by a blank line, a block's lines by a newline."""
    ocr: bool
    pictures: list[Picture] = field(default_factory=list)
    map_page: bool = False
    """A picture page whose OCR reads like a map's legend or room numbers."""
    ocr_text: str = ""
    """What OCR read, kept for finding maps and headings; never module text."""
    plate_title: str | None = None
    """A map page's title, from its OCR (`plate_title`) or Claude's look at it."""
    handouts: tuple[HandoutBox, ...] = ()
    """The handouts on a picture page, from Claude's look at it."""


@dataclass(frozen=True)
class PdfBook:
    pages: list[PdfPage]
    warnings: list[Warning]


def tesseract_ocr() -> Ocr | None:
    """OCR with tesseract, or None when the `tesseract` binary or `pytesseract` is missing, or when `DELVE_OCR` is
    `off` (as every test sets it)."""
    if os.environ.get("DELVE_OCR") == "off" or shutil.which("tesseract") is None:
        return None
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None

    def ocr(png: bytes) -> str:
        with Image.open(io.BytesIO(png)) as image:
            return pytesseract.image_to_string(image)

    return ocr


def read_pdf(
    path: Path,
    *,
    ocr: Ocr | None,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> PdfBook:
    """The pages of the PDF at `path`. Raises `PdfError` for one that is encrypted, corrupt or empty.

    `should_stop` is asked before each page; when it answers True, the reading raises `ReadStopped`. `progress` hears
    the pages read out of the book's pages after each page.
    """
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                raise PdfError("The PDF has no pages.")
            pages: list[PdfPage] = []
            warnings: list[Warning] = []
            for number, page in enumerate(pdf.pages, start=1):
                if should_stop is not None and should_stop():
                    raise ReadStopped(f"The reading was stopped before page {number}.")
                pages.append(_read_page(number, page, ocr, warnings))
                if progress is not None:
                    progress(number, len(pdf.pages))
            return PdfBook(pages=pages, warnings=warnings)
    except (PdfError, ReadStopped):
        raise
    except Exception as e:  # pdfminer and pdfium raise many kinds, often wrapped
        if isinstance(e.args[0] if e.args else None, PDFPasswordIncorrect) or isinstance(e, PDFPasswordIncorrect):
            raise PdfError("The PDF is encrypted: it needs a password to open.") from e
        reason = str(e.args[0] if e.args else e) or type(e).__name__
        raise PdfError(f"The PDF can't be read: {reason}.") from e


def render_page(path: Path, number: int, dpi: int = OCR_DPI) -> bytes:
    """Page `number` (from 1) of the PDF at `path` as a PNG at `dpi`, or lower to stay under `MAX_RENDER_PIXELS`:
    the picture a lost glyph is read from (`gaps`). `PdfError` for a page the book doesn't have."""
    with pdfplumber.open(path) as pdf:
        if not 1 <= number <= len(pdf.pages):
            raise PdfError(f"The PDF has no page {number}.")
        return _render(pdf.pages[number - 1], dpi)[0]


def _read_page(number: int, page: Any, ocr: Ocr | None, warnings: list[Warning]) -> PdfPage:
    lowered: list[bool] = []

    def render(target: Any, dpi: int) -> bytes:
        png, was_lowered = _render(target, dpi)
        lowered.append(was_lowered)
        return png

    read = _page(number, page, ocr, warnings, render)
    if any(lowered):
        warnings.append(
            Warning(
                code="page-too-large",
                message=f"Page {number} is too large to render in full; it was rendered at a lower resolution.",
                ref=f"page:{number}",
            )
        )
    return read


def _page(
    number: int, page: Any, ocr: Ocr | None, warnings: list[Warning], render: Callable[[Any, int], bytes]
) -> PdfPage:
    text = _page_text(page)
    images = [_clip(page, image) for image in page.images]
    images = [box for box in images if box is not None]
    if len(text.strip()) < MIN_PAGE_CHARS and images:
        # Scanned: the page is a picture of its text.
        if ocr is not None:
            read = ocr(render(page, OCR_DPI)).strip()
            if _is_text(read):
                return PdfPage(number, read, True, [], ocr_text=read)
            # OCR read a legend, labels or noise: a map plate or a picture, not a scanned page of text, so it is kept,
            # and what OCR read reaches no text.
            picture = Picture(number, render(page, PICTURE_DPI), 1.0)
            if MIN_PICTURE_TEXT_WORDS <= _real_words(read)[1] < MIN_TEXT_WORDS:
                warnings.append(
                    Warning(
                        code="page-text-as-picture",
                        message=f"Page {number} has text that was kept as a picture; check it.",
                        ref=f"page:{number}",
                    )
                )
            return PdfPage(
                number, "", True, [picture], map_page=_is_map(read), ocr_text=read, plate_title=plate_title(read)
            )
        warnings.append(
            Warning(
                code="page-not-read",
                message=f"Page {number} has no text to read, and OCR isn't available (install tesseract); "
                "its image is kept instead.",
                ref=f"page:{number}",
            )
        )
        return PdfPage(number, text, False, [Picture(number, render(page, PICTURE_DPI), 1.0)])
    if len(text.strip()) < MIN_PAGE_CHARS and _drawing_objects(page) >= MIN_DRAWING_OBJECTS:
        # Drawn in vectors, as a map often is: its few words are labels, and the drawing is kept as a picture page.
        return PdfPage(number, text, False, [Picture(number, render(page, PICTURE_DPI), 1.0)])
    return PdfPage(number, text, False, _pictures(number, page, images, render, warnings))


def _tokens(text: str) -> list[str]:
    return [token.strip(string.punctuation + "‘’“”") for token in text.split()]


def _looks_like_a_word(token: str) -> bool:
    """Letters only, with a vowel, and not one letter repeated."""
    lowered = token.lower()
    return token.isalpha() and any(c in "aeiouy" for c in lowered) and len(set(lowered)) > 1


def _real_words(text: str) -> tuple[int, int]:
    """The tokens of three or more characters, and how many of them look like words."""
    long = [token for token in _tokens(text) if len(token) >= 3]
    return len(long), sum(1 for token in long if _looks_like_a_word(token))


def real_share(text: str) -> float:
    """The share of the tokens of three or more characters that look like words; 0.0 when there are none."""
    long, words = _real_words(text)
    return words / long if long else 0.0


def real_words(text: str) -> int:
    """How many of the tokens of three or more characters look like words."""
    return _real_words(text)[1]


def _is_text(read: str) -> bool:
    """OCR read a page of text: enough words, and mostly words rather than noise."""
    long, words = _real_words(read)
    return words >= MIN_TEXT_WORDS and words / long >= MIN_REAL_SHARE


_NUMBER = re.compile(r"\d{1,3}")


def _is_map(read: str) -> bool:
    tokens = [token.lower() for token in _tokens(read)]
    numbers = {token for token in tokens if _NUMBER.fullmatch(token)}
    return (
        len(MAP_WORDS.intersection(tokens)) >= MIN_MAP_WORDS
        or len(numbers) >= MIN_MAP_NUMBERS
        or plate_title(read) is not None
    )


def plate_title(read: str) -> str | None:
    """The plate's title in OCR `read`: its first line of one to `PLATE_TITLE_WORDS` words and at most
    `PLATE_TITLE_CHARS` characters that holds a `PLATE_WORDS` word (whole, in any case), whitespace collapsed. None
    when no line does.

    On a title page (at most `TITLE_PAGE_WORDS` words), `TITLE_PAGE_PLATE_WORDS` alone make no title; when another
    plate word makes one, the title is still the first line holding any plate word ("HAUNTED HOUSE" over "Ground
    floor")."""
    words = PLATE_WORDS - TITLE_PAGE_PLATE_WORDS if real_words(read) <= TITLE_PAGE_WORDS else PLATE_WORDS
    lines = [" ".join(line.split()) for line in read.splitlines()]
    lines = [line for line in lines if 1 <= len(line.split()) <= PLATE_TITLE_WORDS and len(line) <= PLATE_TITLE_CHARS]

    def holding(line: str, plate: frozenset[str]) -> bool:
        return any(token.lower() in plate for token in _tokens(line))

    if not any(holding(line, words) for line in lines):
        return None
    return next(line for line in lines if holding(line, PLATE_WORDS))


def _drawing_objects(page: Any) -> int:
    return len(page.curves) + len(page.rects) + len(page.lines)


def _clip(page: Any, image: dict[str, Any]) -> tuple[float, float, float, float] | None:
    x0, top, x1, bottom = page.bbox
    box = (max(image["x0"], x0), max(image["top"], top), min(image["x1"], x1), min(image["bottom"], bottom))
    return box if box[2] > box[0] and box[3] > box[1] else None


def _pictures(
    number: int,
    page: Any,
    boxes: list[tuple[float, float, float, float]],
    render: Callable[[Any, int], bytes],
    warnings: list[Warning],
) -> list[Picture]:
    page_area = float(page.width * page.height)
    shares = [(box, (box[2] - box[0]) * (box[3] - box[1]) / page_area) for box in boxes]
    kept = [(box, share) for box, share in shares if share >= PICTURE_SHARE]
    if sum(share for _, share in kept) >= PICTURE_PAGE_SHARE:
        return [Picture(number, render(page, PICTURE_DPI), 1.0)]
    if dropped := len(shares) - len(kept):
        warnings.append(
            Warning(
                code="image-dropped",
                message=f"Page {number}: {dropped} small images (under {PICTURE_SHARE * 100:g} % of the page) were "
                "left out.",
                ref=f"page:{number}",
            )
        )
    return [Picture(number, render(page.crop(box), PICTURE_DPI), round(share, 4)) for box, share in kept]


def _render(page: Any, dpi: int) -> tuple[bytes, bool]:
    """The page as a PNG, and whether its resolution was lowered to stay under `MAX_RENDER_PIXELS`."""
    resolution = _resolution(page, dpi)
    out = io.BytesIO()
    page.to_image(resolution=resolution).original.save(out, format="PNG")
    return out.getvalue(), resolution < dpi


def _resolution(page: Any, dpi: float) -> float:
    """`dpi`, or lower so that the render stays under `MAX_RENDER_PIXELS`.

    A cropped page is rendered whole and then cut, so the size that counts is its root page's.
    """
    root = page if page.is_original else page.root_page
    width, height = float(root.width), float(root.height)

    def pixels(resolution: float) -> int:
        scale = resolution / 72
        return math.ceil(width * scale) * math.ceil(height * scale)

    if pixels(dpi) < MAX_RENDER_PIXELS:
        return dpi
    resolution = 72 * math.sqrt(MAX_RENDER_PIXELS / (width * height))
    while pixels(resolution) >= MAX_RENDER_PIXELS:
        resolution *= 0.99
    return resolution


# Reading order: words become lines, lines become blocks, and blocks are sorted by column.


@dataclass
class _Box:
    x0: float
    top: float
    x1: float
    bottom: float
    text: str

    @property
    def height(self) -> float:
        return self.bottom - self.top


def _page_text(page: Any) -> str:
    """The page's text in reading order, its bold and italic runs marked (`_line`)."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, extra_attrs=["fontname"])
    blocks = _blocks(_lines(words))
    return "\n\n".join(block.text for block in _order_blocks(blocks, float(page.width)))


def _lines(words: list[dict[str, Any]]) -> list[_Box]:
    """Words on one baseline make a line, split where the gap between two words is wider than the text is high."""
    rows: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        height = word["bottom"] - word["top"]
        if rows and abs(rows[-1][0]["top"] - word["top"]) <= height / 2:
            rows[-1].append(word)
        else:
            rows.append([word])
    lines: list[_Box] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        current = [row[0]]
        for word in row[1:]:
            if word["x0"] - current[-1]["x1"] > current[-1]["bottom"] - current[-1]["top"]:
                lines.append(_line(current))
                current = []
            current.append(word)
        lines.append(_line(current))
    return lines


def _line(words: list[dict[str, Any]]) -> _Box:
    return _Box(
        min(w["x0"] for w in words),
        min(w["top"] for w in words),
        max(w["x1"] for w in words),
        max(w["bottom"] for w in words),
        _marked(words),
    )


_BOLD = ("bold", "black", "heavy")
_ITALIC = ("italic", "oblique")


def _style(word: dict[str, Any]) -> tuple[bool, bool]:
    """Whether the word is bold and whether it is italic, from its font's name (`ABCDEF+Garamond-BoldItalic`)."""
    font = str(word.get("fontname", "")).casefold()
    return any(name in font for name in _BOLD), any(name in font for name in _ITALIC)


def _marked(words: list[dict[str, Any]]) -> str:
    """The line's words, each run of one style wrapped once: `**bold**`, `*italic*`, `***both***`. A line wholly bold
    is a heading, which Claude makes one: its bold isn't marked."""
    styles = [_style(word) for word in words]
    if all(bold for bold, _ in styles):
        styles = [(False, italic) for _, italic in styles]
    marks = {(False, False): "", (True, False): "**", (False, True): "*", (True, True): "***"}
    line, run, style = "", "", styles[0]
    for n, (word, word_style) in enumerate(zip(words, styles, strict=True)):
        # A word split from the one before by a change of font alone ("Codex" and ",") is joined without a space.
        space = "" if n == 0 else " " if word["x0"] - words[n - 1]["x1"] > _JOINED * _height(word) else ""
        if n and word_style != style:
            line += f"{marks[style]}{run}{marks[style]}{space}"
            run, space, style = "", "", word_style
        run += space + word["text"]
    return line + f"{marks[style]}{run}{marks[style]}"


_JOINED = 0.1
"""Two words closer than this share of their height are one word in two fonts."""


def _height(word: dict[str, Any]) -> float:
    return float(word["bottom"] - word["top"])


def _blocks(lines: list[_Box]) -> list[_Box]:
    """A line joins the block above it when they overlap across and the gap between them is under a line's height."""
    blocks: list[_Box] = []
    for line in sorted(lines, key=lambda b: (b.top, b.x0)):
        for block in reversed(blocks):
            last_height = block.height / max(block.text.count("\n") + 1, 1)
            overlaps = line.x0 < block.x1 and block.x0 < line.x1
            if overlaps and 0 <= line.top - block.bottom < min(last_height, line.height):
                block.x0, block.x1 = min(block.x0, line.x0), max(block.x1, line.x1)
                block.bottom = line.bottom
                block.text += "\n" + line.text
                break
        else:
            blocks.append(_Box(line.x0, line.top, line.x1, line.bottom, line.text))
    return blocks


def _order_blocks(blocks: list[_Box], page_width: float, *, gap: float = COLUMN_GAP) -> list[_Box]:
    """Columns left to right, each top to bottom; blocks that reach into the next column come first (ttrpg3).

    Columns are found by clustering the blocks' left edges: a gap between two consecutive left edges wider than `gap`
    of the page width is a boundary.
    """
    lefts = sorted({round(b.x0, 1) for b in blocks})
    # A boundary, and the left edge of the column it starts.
    boundaries = [((a + b) / 2, b) for a, b in pairwise(lefts) if b - a > gap * page_width]

    def column(block: _Box) -> int:
        return sum(1 for boundary, _ in boundaries if block.x0 >= boundary)

    def full_width(block: _Box) -> bool:
        return any(block.x0 < boundary and block.x1 > next_left for boundary, next_left in boundaries)

    return sorted(blocks, key=lambda b: (not full_width(b), column(b), b.top, b.x0))
