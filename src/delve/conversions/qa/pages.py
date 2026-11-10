"""The book's pages as the agents read them (thorough conversion Task 3): `p-NNN.png`, the page as an image, and
`ocr-NNN.txt`, its text layer in reading order, or what OCR reads from it when the page has no text layer, as
`read_pdf` decides. `NNN` is the page number from 1, three digits: `p-027.png` is page 27.

The agents treat the images as the truth and the text as a help for copying: it has the text layer's and OCR's errors.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from delve.modules.books.pdf import MIN_PAGE_CHARS, OCR_DPI, Ocr, PdfError, _page_text, _render

PAGE_DPI = 150
"""The pages the agents read."""
SCAN_DPI = 200
"""The map pages the trace agents read."""


def page_image(number: int) -> str:
    return f"p-{number:03d}.png"


def page_text(number: int) -> str:
    return f"ocr-{number:03d}.txt"


def render_pages(
    pdf: Path,
    out: Path,
    *,
    dpi: int = PAGE_DPI,
    first: int | None = None,
    last: int | None = None,
    ocr: Ocr | None = None,
) -> list[int]:
    """Pages `first` to `last` (from 1, both included; the whole book by default) of `pdf` written to `out`, which is
    made when missing; the page numbers written. `PdfError` for a PDF that can't be read or a range it doesn't have."""
    try:
        with pdfplumber.open(pdf) as book:
            count = len(book.pages)
            start, end = first or 1, last or count
            if not 1 <= start <= end <= count:
                raise PdfError(f"The PDF has pages 1 to {count}, not {start} to {end}.")
            out.mkdir(parents=True, exist_ok=True)
            for number in range(start, end + 1):
                page = book.pages[number - 1]
                (out / page_image(number)).write_bytes(_render(page, dpi)[0])
                text = _page_text(page)
                if len(text.strip()) < MIN_PAGE_CHARS and ocr is not None:
                    text = ocr(_render(page, OCR_DPI)[0]).strip()
                (out / page_text(number)).write_text(text + "\n" if text else "")
            return list(range(start, end + 1))
    except PdfError:
        raise
    except Exception as e:  # pdfminer and pdfium raise many kinds
        raise PdfError(f"The PDF can't be read: {e}.") from e
