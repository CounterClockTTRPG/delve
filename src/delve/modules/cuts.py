"""Cutting a module's picture (DEL-40): turn it by 90° steps, then cut a box of it.

Every cut is taken from the original's bytes, never from an earlier cut, so cuts don't compound. The header's size is
checked before anything is decoded (refused past `MAX_PIXELS`, the banners' limit too), and the cut keeps the
original's format with none of its metadata: a PNG stays a PNG, a JPEG a JPEG, a WebP a WebP, a still GIF becomes a PNG.
"""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps

MAX_PIXELS = 40_000_000
"""The largest picture decoded, in pixels; `delve.play.module_banners.BANNER_MAX_PIXELS` is this one."""
ROTATIONS = (0, 90, 180, 270)
"""The turns a cut takes, in degrees clockwise."""
MIN_SIDE = 8
"""The fewest pixels a side of a cut has."""
CUTTABLE = {"image/png", "image/jpeg", "image/webp", "image/gif"}
"""The pictures that can be cut; an SVG or a PDF can't."""

_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF"}
_SAVED = {"PNG": ("image/png", {}), "JPEG": ("image/jpeg", {"quality": 92}), "WEBP": ("image/webp", {"quality": 90})}


class CutRefused(ValueError):
    """The cut can't be made: the message says why, for the organiser."""


def cut_picture(
    data: bytes, media_type: str, rotate: int, box: tuple[float, float, float, float] | None
) -> tuple[bytes, str]:
    """The picture `data` turned clockwise by `rotate` and cut to `box` (fractions of the turned picture), with its type."""
    if media_type not in CUTTABLE:
        raise CutRefused("Only a PNG, JPEG, WebP or GIF picture can be cut.")
    if rotate not in ROTATIONS:
        raise CutRefused("A picture turns by 0, 90, 180 or 270 degrees.")
    expected = _FORMATS[media_type]
    too_large = CutRefused(f"That picture is too large: at most {MAX_PIXELS // 1_000_000} million pixels.")
    not_it = CutRefused("That picture can't be read.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data), formats=[expected])
    except Image.DecompressionBombError:
        raise too_large from None
    except (OSError, SyntaxError, ValueError):
        raise not_it from None
    if image.width * image.height > MAX_PIXELS:
        raise too_large
    try:
        image.load()
        upright = ImageOps.exif_transpose(image)
    except Image.DecompressionBombError:
        raise too_large from None
    except (OSError, SyntaxError, ValueError, EOFError):
        raise not_it from None
    turned = upright.rotate(-rotate, expand=True) if rotate else upright
    if box is not None:
        turned = turned.crop(_pixels(box, turned.width, turned.height))
    saved_as = "PNG" if expected == "GIF" else expected
    out_type, options = _SAVED[saved_as]
    if saved_as == "JPEG":
        turned = turned.convert("RGB")
    elif turned.mode == "P":
        turned = turned.convert("RGBA")
    # A fresh picture: nothing of the original's info (EXIF, colour profile, comments) comes along.
    clean = Image.new(turned.mode, turned.size)
    clean.paste(turned)
    out = io.BytesIO()
    clean.save(out, saved_as, **options)
    return out.getvalue(), out_type


def _pixels(box: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = box
    if not (0 <= x and 0 <= y and w > 0 and h > 0 and x + w <= 1 + 1e-6 and y + h <= 1 + 1e-6):
        raise CutRefused("The box must lie inside the picture.")
    left, top = round(x * width), round(y * height)
    right, bottom = min(width, round((x + w) * width)), min(height, round((y + h) * height))
    if right - left < MIN_SIDE or bottom - top < MIN_SIDE:
        raise CutRefused(f"The box must be at least {MIN_SIDE} pixels a side.")
    return left, top, right, bottom
