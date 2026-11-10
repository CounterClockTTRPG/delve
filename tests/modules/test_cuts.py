import io
import struct
import zlib

import pytest
from PIL import Image

from delve.modules.cuts import CutRefused, cut_picture
from delve.modules.source import Attachment, Cut, ModuleSource

RED = (255, 0, 0)
BLUE = (0, 0, 255)


def halves(fmt: str = "PNG") -> bytes:
    """200×100: the left half red, the right half blue."""
    image = Image.new("RGB", (200, 100), BLUE)
    image.paste(Image.new("RGB", (100, 100), RED), (0, 0))
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def colours(image: Image.Image) -> set[tuple[int, int, int]]:
    return {c for _, c in image.convert("RGB").getcolors(maxcolors=100_000)}


def test_a_box_cuts_that_part():
    data, media_type = cut_picture(halves(), "image/png", 0, (0.5, 0, 0.5, 1))
    image = opened(data)
    assert media_type == "image/png" and image.format == "PNG"
    assert image.size == (100, 100)
    assert colours(image) == {BLUE}


def test_a_turn_comes_before_the_box():
    whole, _ = cut_picture(halves(), "image/png", 90, None)
    assert opened(whole).size == (100, 200)
    top, _ = cut_picture(halves(), "image/png", 90, (0, 0, 1, 0.5))
    image = opened(top)
    assert image.size == (100, 100)
    assert colours(image) == {RED}  # turned clockwise, the left half is on top


def test_formats_are_kept_and_a_gif_becomes_a_png():
    data, media_type = cut_picture(halves("JPEG"), "image/jpeg", 0, (0, 0, 0.5, 1))
    assert media_type == "image/jpeg" and opened(data).format == "JPEG"
    data, media_type = cut_picture(halves("GIF"), "image/gif", 0, (0, 0, 0.5, 1))
    assert media_type == "image/png" and opened(data).format == "PNG"


def huge_png_header() -> bytes:
    """A PNG whose header claims 10000×10000 pixels: past the 40 M limit, refused before decoding."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", 10_000, 10_000, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


@pytest.mark.parametrize(
    ("data", "media_type", "rotate", "box"),
    [
        (halves(), "image/png", 45, None),
        (halves(), "image/png", 0, (0.9, 0, 0.2, 1)),
        (halves(), "image/png", 0, (0, 0, 0.01, 1)),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", 0, None),
        (huge_png_header(), "image/png", 0, None),
        (b"not a picture", "image/png", 0, None),
    ],
    ids=["rotate-45", "outside", "too-thin", "svg", "too-large", "not-a-png"],
)
def test_refusals(data, media_type, rotate, box):
    with pytest.raises(CutRefused):
        cut_picture(data, media_type, rotate, box)


def test_an_attachment_with_a_cut_round_trips():
    cut = Cut("abc", "image/png", 10, 90, (0, 0, 1, 0.5), True)
    source = ModuleSource(attachments=[Attachment("a", "image/png", "def", 5, "A cabin", "player", cut=cut)])
    again = ModuleSource.from_json(source.to_json())
    assert again.attachments[0].cut == cut
    plain = ModuleSource(attachments=[Attachment("b", "image/png", "def", 5, "A cabin", "player")]).to_json()
    del plain["attachments"][0]["cut"]  # a source saved before cuts
    assert ModuleSource.from_json(plain).attachments[0].cut is None
