"""A picture pasted into table talk (DEL-294): made a clean WebP of at most `TALK_PICTURE_SIZE` px a side."""

import io

import pytest
from PIL import Image

from delve.play.talk_pictures import TALK_PICTURE_SIZE, TALK_PICTURE_WORK_SIZE, TalkPictureRefused, talk_picture
from tests.fixtures import avatars


def picture(size=(300, 200), fmt="PNG", exif: bytes | None = None, mode="RGB") -> bytes:
    image = Image.new(mode, size, (200, 30, 30, 0) if mode == "RGBA" else (200, 30, 30))
    out = io.BytesIO()
    image.save(out, fmt, **({"exif": exif} if exif else {}))
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_a_picture_becomes_a_webp_of_its_size():
    made = talk_picture(picture(), "image/png")
    image = opened(made.data)
    assert image.format == "WEBP" and image.size == (300, 200)
    assert (made.width, made.height, made.mime) == (300, 200, "image/webp")


def test_a_large_picture_is_reduced():
    image = opened(talk_picture(picture((5000, 2500), "JPEG"), "image/jpeg").data)
    assert image.size == (TALK_PICTURE_SIZE, TALK_PICTURE_SIZE // 2)


def test_a_big_picture_is_reduced_before_it_is_converted(monkeypatch):
    """As an avatar's: no full-size copy of a picture near the pixel cap is made, the reduction comes first."""
    seen: list[tuple[int, int]] = []
    real_convert = Image.Image.convert

    def convert(self, *args, **kwargs):
        seen.append(self.size)
        return real_convert(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "convert", convert)
    image = opened(talk_picture(avatars.zeros_png(6000, 6000), "image/png").data)
    assert image.size == (TALK_PICTURE_SIZE, TALK_PICTURE_SIZE)
    assert seen and all(max(size) <= TALK_PICTURE_WORK_SIZE for size in seen)


def test_a_photo_keeps_none_of_its_metadata():
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {2: (50.0, 51.0, 0.0)}  # GPS
    image = opened(talk_picture(picture(fmt="JPEG", exif=exif.tobytes()), "image/jpeg").data)
    assert not image.getexif() and "icc_profile" not in image.info


def test_a_transparent_picture_stays_transparent():
    image = opened(talk_picture(picture(mode="RGBA"), "image/png").data)
    assert image.mode == "RGBA"


def test_a_gif_keeps_its_first_frame():
    assert opened(talk_picture(picture(fmt="GIF"), "image/gif").data).format == "WEBP"


@pytest.mark.parametrize(
    ("data", "media_type", "status"),
    [
        (picture(), "image/jpeg", 400),
        (b"not a picture", "image/png", 400),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", 400),
    ],
    ids=["liar", "garbage", "svg"],
)
def test_refusals(data, media_type, status):
    with pytest.raises(TalkPictureRefused) as refused:
        talk_picture(data, media_type)
    assert refused.value.status == status


def test_a_picture_past_the_pixels_is_refused_before_it_is_decoded():
    from tests.modules.test_cuts import huge_png_header

    with pytest.raises(TalkPictureRefused) as refused:
        talk_picture(huge_png_header(), "image/png")
    assert refused.value.status == 422
