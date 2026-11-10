"""A world map's base picture as a pyramid of tiles, and the seat's fog over them (spec §3.5).

A picture is opened with a cap on its pixels (`MAX_PICTURE_PIXELS`), and refused (`PictureRefused`) when its bytes
aren't the type it claims (400) or it is larger (422). `cut_tiles` cuts it into `TILE_SIZE` tiles, as Leaflet's
`CRS.Simple` reads them: at `max_zoom` a tile pixel is a picture pixel, and each lower level halves the one above.
Edge tiles are padded with `FOG`.

A tile's pixels map to the map's km through the picture's `km_per_px`, the picture's top left being the frame's.
`tile_mask` is the known cells' outlines over a tile, and `fog_tile` covers the rest with opaque `FOG`, so a seat's
browser never gets what lies under it.
"""

from __future__ import annotations

import io
import math
import threading
import warnings
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw

from delve.domain.world import TILE_SIZE
from delve.maps.geo.grid import cell_polygon, cells_within
from delve.maps.geo.model import GeoMap

MAX_PICTURE_PIXELS = 200_000_000
"""The largest picture Delve takes, in pixels: the owner's 146-million-pixel Flanaess fits."""

PICTURE_TYPES = ("image/png", "image/jpeg", "image/webp")

FOG = "#d8cfbd"

JPEG_QUALITY = 85

_FINE = 4
"""How much finer than a tile the known cells are drawn for its mask."""

_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}

_OPENING = threading.Lock()
"""Pillow's `MAX_IMAGE_PIXELS` is a module global: one picture opens at a time."""


class PictureRefused(Exception):
    """A picture Delve won't take: `status` 400 (not the image it claims to be) or 422 (too many pixels)."""

    def __init__(self, status: Literal[400, 422], message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def picture_type(data: bytes) -> str | None:
    """The `PICTURE_TYPES` type the bytes start like, by their magic bytes; None for another."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _head(source: bytes | Path) -> bytes:
    if isinstance(source, bytes):
        return source[:16]
    with source.open("rb") as f:
        return f.read(16)


def open_picture(source: bytes | Path, mime: str) -> Image.Image:
    """The picture in `source`, opened but not yet decoded. `PictureRefused` 400 when it isn't a `mime` picture, 422
    when it has more than `MAX_PICTURE_PIXELS`."""
    if mime not in PICTURE_TYPES:
        raise PictureRefused(400, f"A world map's picture is PNG, JPEG or WebP, not {mime}.")
    if picture_type(_head(source)) != mime:
        raise PictureRefused(400, f"The picture isn't the {mime} it claims to be.")
    cap = MAX_PICTURE_PIXELS
    too_large = PictureRefused(422, f"The picture has more than {cap:,} pixels; make it smaller first.")
    with _OPENING:
        before = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = cap
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                image = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
        except Image.DecompressionBombError:
            raise too_large from None
        except (OSError, SyntaxError, ValueError):
            raise PictureRefused(400, f"The picture isn't the {mime} it claims to be.") from None
        finally:
            Image.MAX_IMAGE_PIXELS = before
    if image.format != _FORMATS[mime]:
        raise PictureRefused(400, f"The picture isn't the {mime} it claims to be.")
    if image.width * image.height > cap:
        raise too_large
    return image


def max_zoom(width_px: int, height_px: int) -> int:
    """The zoom at which a tile pixel is a picture pixel: ⌈log2(the longer side / 256)⌉, at least 0."""
    side = max(width_px, height_px)
    return max(0, math.ceil(math.log2(side / TILE_SIZE))) if side > TILE_SIZE else 0


def _flat(image: Image.Image) -> Image.Image:
    """The picture as RGB, anything transparent lying on fog."""
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        out = Image.new("RGB", rgba.size, FOG)
        out.paste(rgba, mask=rgba.getchannel("A"))
        return out
    return image if image.mode == "RGB" else image.convert("RGB")


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=JPEG_QUALITY)
    return out.getvalue()


def _tiles_of(level: Image.Image, z: int) -> Iterator[tuple[int, int, int, bytes]]:
    for y in range(math.ceil(level.height / TILE_SIZE)):
        for x in range(math.ceil(level.width / TILE_SIZE)):
            box = (x * TILE_SIZE, y * TILE_SIZE, min((x + 1) * TILE_SIZE, level.width), min((y + 1) * TILE_SIZE, level.height))
            tile = Image.new("RGB", (TILE_SIZE, TILE_SIZE), FOG)
            tile.paste(level.crop(box), (0, 0))
            yield z, x, y, _jpeg(tile)


def cut_tiles(image: Image.Image) -> Iterator[tuple[int, int, int, bytes]]:
    """Every tile of the picture, `(z, x, y, JPEG bytes)`, from `max_zoom` down to 0. Each level is the one above
    halved, so only two are in memory at once."""
    top = max_zoom(image.width, image.height)
    level = _flat(image)
    for z in range(top, -1, -1):
        yield from _tiles_of(level, z)
        if z:
            level = level.reduce(2)


def tile_mask(
    geo: GeoMap, cells: Collection[int], z: int, x: int, y: int, max_zoom: int
) -> Literal["all", "none"] | Image.Image:
    """The known cells over the tile `z/x/y`: an `L` mask, 255 where a known cell lies; `"all"` when the whole tile
    is known and `"none"` when none of it is. A map without its picture knows none of it."""
    if geo.picture is None or not cells:
        return "none"
    km_per_tile_px = geo.picture.km_per_px * 2 ** (max_zoom - z)
    span = TILE_SIZE * km_per_tile_px
    left, top = x * span, y * span
    centre = (left + span / 2, top + span / 2)
    reach = span / math.sqrt(2) + geo.grid.size_km
    known = [i for i in cells_within(geo.grid, centre, reach) if i in cells]
    if not known:
        return "none"
    # Pillow fills a polygon's edge pixels too, so the cells are drawn at `_FINE` times the size, and a pixel is known
    # only when all of its fine pixels are: a pixel the edge of the known area crosses stays fog.
    fine = Image.new("L", (TILE_SIZE * _FINE, TILE_SIZE * _FINE), 0)
    draw = ImageDraw.Draw(fine)
    scale = _FINE / km_per_tile_px
    for i in known:
        draw.polygon([((px - left) * scale, (py - top) * scale) for px, py in cell_polygon(geo.grid, i)], fill=255)
    mask = fine.reduce(_FINE).point(lambda v: 255 if v == 255 else 0)
    draw = ImageDraw.Draw(mask)
    # Past the picture's edge there is only padding: it stays fog, and doesn't count against "all".
    width = min(TILE_SIZE, math.ceil(geo.picture.width_px / 2 ** (max_zoom - z)) - x * TILE_SIZE)
    height = min(TILE_SIZE, math.ceil(geo.picture.height_px / 2 ** (max_zoom - z)) - y * TILE_SIZE)
    if width <= 0 or height <= 0:
        return "none"
    if width < TILE_SIZE:
        draw.rectangle((width, 0, TILE_SIZE, TILE_SIZE), fill=0)
    if height < TILE_SIZE:
        draw.rectangle((0, height, TILE_SIZE, TILE_SIZE), fill=0)
    if mask.getextrema()[1] == 0:
        return "none"
    if mask.crop((0, 0, width, height)).getextrema()[0] == 255:
        return "all"
    return mask


def fog_tile(tile: bytes, mask: Image.Image) -> bytes:
    """The tile with opaque `FOG` wherever the mask is 0."""
    image = Image.open(io.BytesIO(tile)).convert("RGB")
    fogged = Image.new("RGB", image.size, FOG)
    fogged.paste(image, mask=mask.point(lambda v: 255 if v else 0))
    return _jpeg(fogged)
