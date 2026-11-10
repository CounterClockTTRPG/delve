"""Tracing aids (thorough conversion Task 3), from the WGR1 QA's `rot.py` and `tile.py`: a map scan turned
square to the page, and a piece of it cut with a labelled grid of the map's squares, so an agent can read a wall's
square from the picture.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

MAJOR = 5
"""Every `MAJOR`th grid line is drawn thicker."""


def rotate(src: Path, out: Path, degrees: float) -> tuple[int, int]:
    """`src` turned counter-clockwise by `degrees` (negative: clockwise), the canvas grown to hold it and filled
    white, written to `out`; its size."""
    with Image.open(src) as image:
        turned = image.convert("RGB").rotate(degrees, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")
    turned.save(out)
    return turned.size


def tile(
    src: Path,
    out: Path,
    box: tuple[int, int, int, int],
    square: float,
    origin: tuple[float, float],
    width: int,
) -> tuple[int, int]:
    """The squares `[x0, x1) × [y0, y1)` of `box` cut from `src`, where a square is `square` pixels and square 0,0
    starts at pixel `origin`, with every square's line drawn and numbered (columns red, rows blue), shrunk to fit
    `width` pixels, written to `out`; its size."""
    x0, y0, x1, y1 = box
    ox, oy = origin

    def px(n: int, o: float) -> int:
        return round(o + n * square)

    crop = (px(x0, ox), px(y0, oy), px(x1, ox), px(y1, oy))
    with Image.open(src) as image:
        piece = image.convert("RGBA").crop(crop)
    sheet = Image.new("RGB", piece.size, "white")
    sheet.paste(piece, mask=piece.split()[3])
    draw = ImageDraw.Draw(sheet)
    font = max(12, round(square / 3))
    for n in range(x0, x1 + 1):
        x = px(n, ox) - crop[0]
        major = n % MAJOR == 0
        draw.line([(x, 0), (x, sheet.height)], fill=(230, 0, 0) if major else (255, 150, 150), width=3 if major else 1)
        draw.text((x + 4, 4), str(n), fill=(230, 0, 0), font_size=font)
    for n in range(y0, y1 + 1):
        y = px(n, oy) - crop[1]
        major = n % MAJOR == 0
        draw.line([(0, y), (sheet.width, y)], fill=(0, 0, 230) if major else (150, 150, 255), width=3 if major else 1)
        draw.text((4, y + 4), str(n), fill=(0, 0, 230), font_size=font)
    sheet.thumbnail((width, width))
    sheet.save(out)
    return sheet.size
