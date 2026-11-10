"""An uploaded avatar (players and tavern Task D2): what a phone sends becomes a 256 px square WebP, upright,
centre-cropped, its first frame only, with no metadata; a picture that isn't its type is 400, and one with too many
pixels 422 before it is decoded. Nothing bigger than `AVATAR_WORK_SIZE` is converted, and at most two avatars are made
at once (Clara's final audit, finding 1)."""

import io
import threading

import pytest
from PIL import Image, JpegImagePlugin

from delve.play import avatars as avatar_module
from delve.play.avatars import AVATAR_SIZE, AVATAR_WORK_SIZE, AvatarRefused, square_avatar
from delve.play.context import PlayError
from tests.fixtures import avatars
from tests.fixtures.avatars import BLUE, GREEN, RED


def opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def near(pixel, colour, tolerance=40) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


def test_avatar_is_256_square_webp():
    image = opened(square_avatar(avatars.png_600x400(), "image/png"))
    assert image.format == "WEBP" and image.size == (AVATAR_SIZE, AVATAR_SIZE) == (256, 256)
    assert image.mode in ("RGB", "RGBA")
    # Cropped from the middle 400×400: red on the left, blue on the right.
    assert near(image.getpixel((10, 128)), RED) and near(image.getpixel((245, 128)), BLUE)


def test_avatar_exif_rotated_upright():
    image = opened(square_avatar(avatars.exif_rotated_jpeg(), "image/jpeg"))
    assert image.size == (256, 256)
    assert near(image.getpixel((128, 2)), RED) and near(image.getpixel((128, 253)), BLUE)


def test_avatar_strip_is_centre_cropped():
    image = opened(square_avatar(avatars.strip_1x20000(), "image/png"))
    assert image.size == (256, 256)
    assert all(near(image.getpixel(xy), GREEN) for xy in ((0, 0), (128, 128), (255, 255)))


def test_avatar_first_frame_only():
    image = opened(square_avatar(avatars.two_frame_webp(), "image/webp"))
    assert getattr(image, "n_frames", 1) == 1
    assert near(image.getpixel((128, 128)), RED)


def test_avatar_type_mismatch_is_400():
    for data, media_type in (
        (avatars.png_600x400(), "image/jpeg"),
        (avatars.exif_rotated_jpeg(), "image/webp"),
        (b"not a picture at all", "image/png"),
        (avatars.png_600x400()[:200], "image/png"),
    ):
        with pytest.raises(AvatarRefused) as refused:
            square_avatar(data, media_type)
        assert refused.value.status == 400 and "That picture isn't a" in refused.value.message
    assert isinstance(refused.value, PlayError)


def test_avatar_pixel_bomb_is_422():
    for bomb in (avatars.pixel_bomb_png(), avatars.pixel_bomb_png(20000, 20000)):
        with pytest.raises(AvatarRefused) as refused:
            square_avatar(bomb, "image/png")
        assert refused.value.status == 422
        assert refused.value.message == "That picture is too large: at most 16 million pixels."


def test_avatar_has_no_metadata():
    data = square_avatar(avatars.exif_rotated_jpeg(), "image/jpeg")
    image = opened(data)
    assert not image.getexif() and "exif" not in image.info and "icc_profile" not in image.info
    assert b"PhonyCam" not in data and b"EXIF" not in data


def test_avatar_zeros_bomb_refused_before_decoding(monkeypatch):
    """155 KB of PNG that decodes to 160 MB (6320×6320 RGBA) is past the cap: 422, and nothing is decoded."""
    bomb = avatars.zeros_png(6320, 6320)
    assert len(bomb) < 160_000
    loaded = []
    monkeypatch.setattr(Image.Image, "load", lambda self: loaded.append(self.size))
    with pytest.raises(AvatarRefused) as refused:
        square_avatar(bomb, "image/png")
    assert refused.value.status == 422 and loaded == []


def _sizes_converted(monkeypatch) -> list[tuple[int, int]]:
    seen: list[tuple[int, int]] = []
    real_convert = Image.Image.convert

    def convert(self, *args, **kwargs):
        seen.append(self.size)
        return real_convert(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "convert", convert)
    return seen


def test_avatar_just_under_the_cap_is_reduced_before_convert(monkeypatch):
    seen = _sizes_converted(monkeypatch)
    image = opened(square_avatar(avatars.zeros_png(4000, 4000), "image/png"))
    assert image.size == (256, 256)
    assert seen and all(max(size) <= AVATAR_WORK_SIZE == 1024 for size in seen)


def test_avatar_jpeg_drafted_before_load(monkeypatch):
    drafted = []
    real_draft = JpegImagePlugin.JpegImageFile.draft

    def draft(self, mode, size):
        drafted.append(size)
        return real_draft(self, mode, size)

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", draft)
    seen = _sizes_converted(monkeypatch)
    image = opened(square_avatar(avatars.big_jpeg(), "image/jpeg"))
    assert image.size == (256, 256) and near(image.getpixel((128, 128)), GREEN)
    assert drafted == [(AVATAR_WORK_SIZE, AVATAR_WORK_SIZE)]
    assert seen and all(max(size) <= AVATAR_WORK_SIZE for size in seen)


def test_avatar_two_at_once_then_busy(monkeypatch):
    """A third avatar waits `AVATAR_WAIT_S` for one of the two being made, then is 503."""
    monkeypatch.setattr(avatar_module, "AVATAR_WAIT_S", 0.05)
    started, release = threading.Barrier(3), threading.Event()
    real_make = avatar_module._square_avatar

    def slow(data, media_type):
        started.wait(5)
        release.wait(5)
        return real_make(data, media_type)

    monkeypatch.setattr(avatar_module, "_square_avatar", slow)
    results = []
    workers = [
        threading.Thread(target=lambda: results.append(square_avatar(avatars.png_600x400(), "image/png")))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    started.wait(5)
    with pytest.raises(AvatarRefused) as refused:
        square_avatar(avatars.png_600x400(), "image/png")
    assert (refused.value.status, refused.value.message) == (503, "Busy: try again in a moment.")
    release.set()
    for worker in workers:
        worker.join()
    assert len(results) == 2
    monkeypatch.setattr(avatar_module, "_square_avatar", real_make)
    assert opened(square_avatar(avatars.png_600x400(), "image/png")).size == (256, 256), "the places are given back"
