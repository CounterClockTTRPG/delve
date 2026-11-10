"""A world map's picture cut into tiles, and the seat's fog over them (plan 7 Task 5, Review Focus 1 and 2): the
pyramid, edge tiles padded with fog, a partly known tile fogged where nothing is known, and a picture that isn't what it
claims or is too large refused before any tile is cut. The pictures are drawn here with Pillow."""

import io

import pytest
from PIL import Image

from delve.maps.geo import tiles
from delve.maps.geo.model import Frame, GeoMap, Grid, PictureRef

MAGENTA = (255, 0, 255)


def picture(width: int, height: int, colour=(40, 120, 200), fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, fmt)
    return out.getvalue()


def halves(width: int = 512, height: int = 256) -> bytes:
    """Green on the left half, magenta on the right."""
    image = Image.new("RGB", (width, height), (0, 160, 0))
    image.paste(MAGENTA, (width // 2, 0, width, height))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def geo_for(width_px: int, height_px: int, cell_px: int = 32) -> GeoMap:
    """Squares of `cell_px` picture pixels, at 1 km per pixel."""
    cols, rows = width_px // cell_px, height_px // cell_px
    grid = Grid("square", float(cell_px), cols, rows)
    ref = PictureRef("pic", width_px, height_px, km_per_px=1.0)
    return GeoMap(Frame(float(width_px), float(height_px)), grid, "p" * (cols * rows), (), ref)


def test_max_zoom_is_the_levels_above_one_tile():
    assert tiles.max_zoom(256, 100) == 0
    assert tiles.max_zoom(100, 100) == 0
    assert tiles.max_zoom(257, 10) == 1
    assert tiles.max_zoom(1000, 700) == 2
    assert tiles.max_zoom(13_706, 10_678) == 6


def test_a_picture_cuts_into_its_pyramid_with_padded_edges():
    image = tiles.open_picture(picture(1000, 700), "image/png")
    cut = {(z, x, y): data for z, x, y, data in tiles.cut_tiles(image)}
    assert sorted(cut) == sorted(
        [(2, x, y) for x in range(4) for y in range(3)] + [(1, x, y) for x in range(2) for y in range(2)] + [(0, 0, 0)]
    )
    edge = Image.open(io.BytesIO(cut[(2, 3, 2)]))
    assert edge.format == "JPEG" and edge.size == (256, 256)
    fog = tuple(int(tiles.FOG[i : i + 2], 16) for i in (1, 3, 5))
    # 1000 = 3 × 256 + 232 and 700 = 2 × 256 + 188: the rest of the edge tile is fog.
    assert all(abs(a - b) <= 8 for a, b in zip(edge.getpixel((250, 100)), fog, strict=True))
    assert all(abs(a - b) <= 8 for a, b in zip(edge.getpixel((100, 200)), fog, strict=True))
    assert all(abs(a - b) <= 8 for a, b in zip(edge.getpixel((100, 100)), (40, 120, 200), strict=True))
    top = Image.open(io.BytesIO(cut[(0, 0, 0)]))
    # Level 0 is the picture at a quarter: 250 × 175.
    assert all(abs(a - b) <= 8 for a, b in zip(top.getpixel((240, 170)), (40, 120, 200), strict=True))
    assert all(abs(a - b) <= 8 for a, b in zip(top.getpixel((253, 180)), fog, strict=True))


def test_a_picture_with_transparency_lies_on_fog():
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    out = io.BytesIO()
    image.save(out, "PNG")
    ((_, _, _, data),) = tiles.cut_tiles(tiles.open_picture(out.getvalue(), "image/png"))
    pixel = Image.open(io.BytesIO(data)).getpixel((5, 5))
    assert all(abs(a - b) <= 8 for a, b in zip(pixel, (0xD8, 0xCF, 0xBD), strict=True))


def test_bytes_that_arent_their_type_are_400():
    with pytest.raises(tiles.PictureRefused) as refused:
        tiles.open_picture(picture(20, 20, fmt="PNG"), "image/jpeg")
    assert refused.value.status == 400
    with pytest.raises(tiles.PictureRefused) as refused:
        tiles.open_picture(b"\x89PNG\r\n\x1a\n not really", "image/png")
    assert refused.value.status == 400
    with pytest.raises(tiles.PictureRefused) as refused:
        tiles.open_picture(picture(20, 20, fmt="GIF"), "image/gif")
    assert refused.value.status == 400


def test_a_picture_of_more_pixels_than_the_cap_is_422(monkeypatch):
    monkeypatch.setattr(tiles, "MAX_PICTURE_PIXELS", 10_000)
    tiles.open_picture(picture(100, 100), "image/png")  # at the cap
    for size in [(101, 100), (500, 500)]:  # over it, and over twice it (Pillow's own bomb error)
        with pytest.raises(tiles.PictureRefused) as refused:
            tiles.open_picture(picture(*size), "image/png")
        assert refused.value.status == 422
        assert "pixels" in refused.value.message


def test_a_picture_opens_from_a_path(tmp_path):
    path = tmp_path / "map.jpg"
    path.write_bytes(picture(30, 20, fmt="JPEG"))
    assert tiles.open_picture(path, "image/jpeg").size == (30, 20)
    assert tiles.picture_type(path.read_bytes()) == "image/jpeg"
    assert tiles.picture_type(b"GIF89a") is None


def test_the_mask_of_a_tile_follows_the_known_cells():
    geo = geo_for(512, 256)  # 16 × 8 cells of 32 px; tiles at zoom 1 are 256 px, so 8 × 8 cells each
    left = frozenset(r * 16 + c for r in range(8) for c in range(8))
    assert tiles.tile_mask(geo, left, 1, 0, 0, 1) == "all"
    assert tiles.tile_mask(geo, left, 1, 1, 0, 1) == "none"
    assert tiles.tile_mask(geo, frozenset(), 1, 0, 0, 1) == "none"
    half = frozenset(r * 16 + c for r in range(8) for c in range(12))
    mask = tiles.tile_mask(geo, half, 1, 1, 0, 1)
    assert isinstance(mask, Image.Image) and mask.mode == "L" and mask.size == (256, 256)
    assert mask.getpixel((60, 100)) == 255 and mask.getpixel((200, 100)) == 0
    # At zoom 0 the whole picture is one tile at half size: the known half is its left 128 px of 256.
    mask = tiles.tile_mask(geo, left, 0, 0, 0, 1)
    assert mask.getpixel((60, 60)) == 255 and mask.getpixel((200, 60)) == 0
    # Below the picture (padding) nothing is known.
    assert mask.getpixel((60, 200)) == 0


def test_a_partly_known_tile_is_fog_where_nothing_is_known():
    image = tiles.open_picture(halves(), "image/png")
    cut = {(z, x, y): data for z, x, y, data in tiles.cut_tiles(image)}
    geo = geo_for(512, 256)
    left = frozenset(r * 16 + c for r in range(8) for c in range(8))  # the green half
    fogged = Image.open(io.BytesIO(tiles.fog_tile(cut[(0, 0, 0)], tiles.tile_mask(geo, left, 0, 0, 0, 1))))
    assert fogged.format == "JPEG"
    pixels = fogged.convert("RGB").load()
    for x in range(132, 256):  # the magenta half, past a JPEG block's bleed
        for y in range(256):
            r, g, b = pixels[x, y]
            assert not (r > 200 and b > 200 and g < 120), (x, y, pixels[x, y])
    r, g, b = pixels[40, 60]
    assert g > 120 and r < 60  # the known half shows as printed
