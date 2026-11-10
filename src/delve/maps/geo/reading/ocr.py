"""The words on a map picture, read by OCR: each with its box in the picture's pixels and its confidence (0–100).

`tesseract_words` is the OCR when `tesseract` is installed; tests use a fake (`tests/maps/geo/pictures.fake_ocr`), and
`DELVE_OCR=off`, which every test sets, turns tesseract off."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class OcrWord:
    text: str
    box: tuple[int, int, int, int]
    """`(x0, y0, x1, y1)` in the pixels of the image read, `x1` and `y1` past the word."""
    confidence: float


PictureOcr = Callable[[Image.Image], list[OcrWord]]
"""Reads the words of an image: a tile of the picture, whose `info["offset"]` (`TILE_OFFSET`) is where its top left
lies in the picture. The boxes it answers are in the tile's own pixels."""

TILE_OFFSET = "offset"


def tesseract_words() -> PictureOcr | None:
    """OCR with tesseract, or None when the `tesseract` binary or `pytesseract` is missing, or when `DELVE_OCR` is
    `off`."""
    if os.environ.get("DELVE_OCR") == "off" or shutil.which("tesseract") is None:
        return None
    try:
        import pytesseract
    except ImportError:
        return None

    def ocr(image: Image.Image) -> list[OcrWord]:
        # Sparse text: a map's labels are scattered, not set in paragraphs.
        data = pytesseract.image_to_data(image, config="--psm 11", output_type=pytesseract.Output.DICT)
        words = []
        for text, conf, x, y, w, h in zip(
            data["text"], data["conf"], data["left"], data["top"], data["width"], data["height"], strict=True
        ):
            text = str(text).strip()
            if text and float(conf) >= 0:
                words.append(OcrWord(text, (int(x), int(y), int(x) + int(w), int(y) + int(h)), float(conf)))
        return words

    return ocr
