"""A tiny PDF writer for tests: text at given positions, images, and broken files, with no PDF library.

Positions are in points on a US Letter page (612 × 792) by default, measured from the **top left**, as pdfplumber
reports them. Text is Helvetica, or its bold and oblique faces (standard fonts, so readers know their widths), and
images are 8-bit grey image XObjects.

**The parts:**
- `TextRun(x, top, text, size=10, font="Helvetica", spans=())`: one line of text starting at `x`, its top near `top`
  (readers add the ascent). `font` is one of `FONTS` (`Helvetica`, `Helvetica-Bold`, `Helvetica-Oblique`,
  `Helvetica-BoldOblique`); `spans` are `(text, font)` runs set straight after `text`, on the same line, for bold and
  italic within a line.
- `ImageBox(x, top, width, height, pixels=None)`: an image XObject drawn over that box. `pixels` is
  `(px_width, px_height, grey_bytes)`; without it the image is a small grey pattern.
- `Page(texts=[], images=[], width=612, height=792, lines=[])`: `lines` are stroked `(x0, top0, x1, top1)` lines.

**Writing:** `pdf_bytes(pages, *, encrypted=False) -> bytes`, and `write_pdf(path, pages, **kw) -> Path`. An
encrypted file has a Standard security handler that the empty password doesn't open.

**Pages to build with:**
- `text_page(lines, *, x=72, top=72, size=10, leading=14) -> Page`: `lines` are strings set one under the other, or
  `(x, top, text)` triples placed where they say.
- `two_column_page(left, right, *, heading=None, top=72) -> Page`: two columns of lines (left at x 72, right at
  x 324), and an optional full-width heading above them.
- `image_page(share, *, texts=(), pixels=None) -> Page`: one image covering `share` (0–1) of the page, centred, with
  optional `texts` (`TextRun`s or lines as in `text_page`, placed above the image).
- `picture_page(pixels=None) -> Page`: a full-page picture and no text, like a map plate or a scanned page.
- `drawn_page(cells=6, *, texts=()) -> Page`: a grid drawn in stroked lines (`2 × (cells + 1)` of them) and no
  image, like a map drawn in vectors.
- `word_pixels(word, *, size=64) -> (w, h, bytes)`: the word drawn in black on white with Pillow, for OCR.
- `book(n, *, words=12) -> list[Page]`: `n` short text pages, each saying "Page <i> …" in about `words` words.

**Broken files:**
- `encrypted_pdf(pages=None) -> bytes`: a one-page PDF with an encrypted trailer.
- `truncated_pdf(pages=None) -> bytes`: a valid PDF cut off half-way.
- `zero_page_pdf() -> bytes`: a valid PDF with no pages.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0
FONTS = ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique")


@dataclass(frozen=True)
class TextRun:
    x: float
    top: float
    text: str
    size: float = 10
    font: str = "Helvetica"
    spans: Sequence[tuple[str, str]] = ()
    """`(text, font)` runs set straight after `text`, on the same line."""


@dataclass(frozen=True)
class ImageBox:
    x: float
    top: float
    width: float
    height: float
    pixels: tuple[int, int, bytes] | None = None


@dataclass(frozen=True)
class Page:
    texts: Sequence[TextRun] = field(default_factory=list)
    images: Sequence[ImageBox] = field(default_factory=list)
    width: float = PAGE_WIDTH
    height: float = PAGE_HEIGHT
    lines: Sequence[tuple[float, float, float, float]] = field(default_factory=list)
    """Stroked lines `(x0, top0, x1, top1)`: vector drawing, as a drawn map is."""


def _escape(text: str) -> bytes:
    raw = text.encode("latin-1", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _grey_pattern() -> tuple[int, int, bytes]:
    return 8, 8, bytes(0x40 if (x + y) % 2 else 0xC0 for y in range(8) for x in range(8))


def _font(name: str) -> bytes:
    """The font's resource name: `/F1` for Helvetica, as before, and `/F2`… for the others."""
    return b"/F%d" % (FONTS.index(name) + 1)


def _content(page: Page) -> bytes:
    ops: list[bytes] = []
    for i, image in enumerate(page.images):
        bottom = page.height - image.top - image.height
        ops.append(b"q %.2f 0 0 %.2f %.2f %.2f cm /Im%d Do Q" % (image.width, image.height, image.x, bottom, i))
    for x0, top0, x1, top1 in page.lines:
        ops.append(b"%.2f %.2f m %.2f %.2f l S" % (x0, page.height - top0, x1, page.height - top1))
    for run in page.texts:
        # The text's top is about one size above its baseline.
        baseline = page.height - run.top - run.size
        shown = b"%s %.2f Tf (%s) Tj" % (_font(run.font), run.size, _escape(run.text))
        for text, font in run.spans:
            shown += b" %s %.2f Tf (%s) Tj" % (_font(font), run.size, _escape(text))
        ops.append(b"BT %.2f %.2f Td %s ET" % (run.x, baseline, shown))
    return b"\n".join(ops)


def _stream(header: bytes, data: bytes) -> bytes:
    return b"<< " + header + b" /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def _font_object(name: str) -> bytes:
    return b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % name.encode()


def pdf_bytes(pages: Sequence[Page], *, encrypted: bool = False) -> bytes:
    """A PDF of `pages`, with a correct cross-reference table."""
    objects: dict[int, bytes] = {3: _font_object("Helvetica")}
    fonts = [b"/F1 3 0 R"]
    number = 4
    used = {font for page in pages for run in page.texts for font in (run.font, *(f for _, f in run.spans))}
    for name in FONTS[1:]:
        if name in used:
            objects[number] = _font_object(name)
            fonts.append(b"%s %d 0 R" % (_font(name), number))
            number += 1
    kids: list[int] = []
    for page in pages:
        page_id, content_id = number, number + 1
        number += 2
        xobjects = []
        for i, image in enumerate(page.images):
            w, h, grey = image.pixels or _grey_pattern()
            objects[number] = _stream(
                b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8"
                % (w, h),
                grey,
            )
            xobjects.append(b"/Im%d %d 0 R" % (i, number))
            number += 1
        objects[content_id] = _stream(b"", _content(page))
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R"
            b" /Resources << /Font << %s >> /XObject << %s >> >> >>"
            % (page.width, page.height, content_id, b" ".join(fonts), b" ".join(xobjects))
        )
        kids.append(page_id)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
    doc_id = hashlib.md5(repr(pages).encode()).hexdigest().encode()
    encrypt = b""
    if encrypted:
        # RC4 40-bit (V 1, R 2) with O and U that no empty password produces: the file needs a password.
        objects[number] = b"<< /Filter /Standard /V 1 /R 2 /P -44 /O <%s> /U <%s> >>" % (
            hashlib.sha256(b"owner").hexdigest().encode(),
            hashlib.sha256(b"user").hexdigest().encode(),
        )
        encrypt = b" /Encrypt %d 0 R" % number
        number += 1

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for n in sorted(objects):
        offsets[n] = len(out)
        out += b"%d 0 obj\n" % n + objects[n] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for n in range(1, size):
        out += b"%010d 00000 n \n" % offsets[n] if n in offsets else b"0000000000 65535 f \n"
    out += b"trailer\n<< /Size %d /Root 1 0 R /ID [<%s> <%s>]%s >>\n" % (size, doc_id, doc_id, encrypt)
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


def write_pdf(path: Path, pages: Sequence[Page], **kw: bool) -> Path:
    path.write_bytes(pdf_bytes(pages, **kw))
    return path


def _runs(
    lines: Iterable[str | tuple[float, float, str] | TextRun], x: float, top: float, size: float, leading: float
) -> list[TextRun]:
    runs = []
    for i, line in enumerate(lines):
        if isinstance(line, TextRun):
            runs.append(line)
        elif isinstance(line, tuple):
            runs.append(TextRun(line[0], line[1], line[2], size))
        else:
            runs.append(TextRun(x, top + i * leading, line, size))
    return runs


def text_page(
    lines: Iterable[str | tuple[float, float, str]],
    *,
    x: float = 72,
    top: float = 72,
    size: float = 10,
    leading: float = 14,
) -> Page:
    return Page(texts=_runs(lines, x, top, size, leading))


def two_column_page(left: Sequence[str], right: Sequence[str], *, heading: str | None = None, top: float = 72) -> Page:
    texts = []
    if heading is not None:
        texts.append(TextRun(72, top, heading, 18))
        top += 40
    texts += _runs(left, 72, top, 10, 14)
    texts += _runs(right, 324, top, 10, 14)
    return Page(texts=texts)


def image_page(
    share: float,
    *,
    texts: Iterable[str | tuple[float, float, str] | TextRun] = (),
    pixels: tuple[int, int, bytes] | None = None,
) -> Page:
    """One image covering `share` of the page, centred and with the page's proportions."""
    scale = share**0.5
    width, height = PAGE_WIDTH * scale, PAGE_HEIGHT * scale
    image = ImageBox((PAGE_WIDTH - width) / 2, (PAGE_HEIGHT - height) / 2, width, height, pixels)
    return Page(texts=_runs(texts, 72, 20, 10, 12), images=[image])


def picture_page(pixels: tuple[int, int, bytes] | None = None) -> Page:
    return Page(images=[ImageBox(0, 0, PAGE_WIDTH, PAGE_HEIGHT, pixels)])


def drawn_page(cells: int = 6, *, texts: Iterable[str | tuple[float, float, str] | TextRun] = ()) -> Page:
    """A grid of `cells` × `cells` squares drawn in stroked lines and no image, like a map drawn in vectors."""
    left, top, size = 72.0, 144.0, 468.0
    step = size / cells
    lines = [(left + i * step, top, left + i * step, top + size) for i in range(cells + 1)]
    lines += [(left, top + i * step, left + size, top + i * step) for i in range(cells + 1)]
    return Page(texts=_runs(texts, 72, 72, 10, 12), lines=lines)


def word_pixels(word: str, *, size: int = 64) -> tuple[int, int, bytes]:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=size)
    left, top, right, bottom = font.getbbox(word)
    pad = size // 2
    image = Image.new("L", (right - left + 2 * pad, bottom - top + 2 * pad), 255)
    ImageDraw.Draw(image).text((pad - left, pad - top), word, fill=0, font=font)
    return image.width, image.height, image.tobytes()


def book(n: int, *, words: int = 12) -> list[Page]:
    filler = " ".join(f"word{i}" for i in range(max(words - 2, 0)))
    return [text_page([f"Page {i} {filler}".strip()]) for i in range(1, n + 1)]


def encrypted_pdf(pages: Sequence[Page] | None = None) -> bytes:
    return pdf_bytes(pages or [text_page(["A secret page that needs a password to read."])], encrypted=True)


def truncated_pdf(pages: Sequence[Page] | None = None) -> bytes:
    whole = pdf_bytes(pages or [text_page(["A page that is cut off before it ends."])])
    return whole[: len(whole) // 2]


def zero_page_pdf() -> bytes:
    return pdf_bytes([])
