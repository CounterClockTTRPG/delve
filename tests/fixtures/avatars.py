"""Pictures to upload as avatars (players and tavern Task D2), made with Pillow: a plain PNG, a phone photo stored
sideways with its EXIF orientation, a 1×20000 strip, a two-frame WebP, and a PNG whose header declares far too many
pixels."""

import io
import struct
import zlib

from PIL import Image

RED, GREEN, BLUE = (220, 20, 20), (20, 200, 20), (20, 20, 220)


def _saved(image: Image.Image, format: str, **options) -> bytes:
    out = io.BytesIO()
    image.save(out, format, **options)
    return out.getvalue()


def png_600x400() -> bytes:
    image = Image.new("RGB", (600, 400), RED)
    image.paste(BLUE, (300, 0, 600, 400))
    return _saved(image, "PNG")


def exif_rotated_jpeg() -> bytes:
    """A 200×300 portrait photo, red at the top and blue at the bottom, stored as a 300×200 landscape with
    orientation 6 (turn it 90° clockwise to show it), as a phone does."""
    upright = Image.new("RGB", (200, 300), BLUE)
    upright.paste(RED, (0, 0, 200, 150))
    stored = upright.rotate(90, expand=True)  # counter-clockwise: the photo's top is on the left
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "PhonyCam"  # the camera's make: metadata the avatar must not keep
    return _saved(stored, "JPEG", exif=exif.tobytes(), quality=95)


def strip_1x20000() -> bytes:
    """A 1 px wide, 20000 px tall PNG: red, with a green band in its middle."""
    image = Image.new("RGB", (1, 20000), RED)
    image.paste(GREEN, (0, 9900, 1, 10100))
    return _saved(image, "PNG")


def two_frame_webp() -> bytes:
    """An animated WebP: a red frame, then a blue one."""
    first, second = Image.new("RGB", (64, 64), RED), Image.new("RGB", (64, 64), BLUE)
    return _saved(first, "WEBP", save_all=True, append_images=[second], duration=100, lossless=True)


def pixel_bomb_png(width: int = 8000, height: int = 8000) -> bytes:
    """A PNG header that says `width`×`height` (64 million pixels), with no picture behind it."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


def zeros_png(width: int, height: int) -> bytes:
    """A real `width`×`height` RGBA PNG of zeros, compressed row by row so making it costs no picture's memory:
    6320×6320 is about 155 KB that decodes to 160 MB."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    squeeze, row, parts = zlib.compressobj(9), b"\0" * (1 + 4 * width), []
    for _ in range(height):
        parts.append(squeeze.compress(row))
    parts.append(squeeze.flush())
    idat = b"".join(parts)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def big_jpeg(width: int = 4000, height: int = 3000) -> bytes:
    """A plain `width`×`height` JPEG, as a camera sends."""
    return _saved(Image.new("RGB", (width, height), GREEN), "JPEG", quality=80)
