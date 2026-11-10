"""A picture pasted into table talk (DEL-294): what a seat sends becomes a clean WebP of at most `TALK_PICTURE_SIZE`
px a side, for the blob store.

As an avatar (`delve.play.avatars`), through `delve.play.image_ingest`: the bytes must be the type they are sent as
(400), the header's size is checked before anything is decoded (422 past `TALK_PICTURE_MAX_PIXELS`), a JPEG is
drafted down and every picture reduced to `TALK_PICTURE_WORK_SIZE` before it is converted, at most
`AT_ONCE` pictures are made at once (503 after `WAIT_S`), a phone photo is turned upright by its EXIF orientation, an
animated picture keeps its first frame, and the result keeps no metadata: no EXIF (a phone photo's GPS position),
no colour profile, no camera.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from PIL import Image

from delve.modules.cuts import MAX_PIXELS
from delve.play.context import PlayError
from delve.play.image_ingest import clean_webp, upright_picture

TALK_PICTURE_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF"}
TALK_PICTURE_LIMIT = 8 * 1024 * 1024
TALK_PICTURE_SIZE = 2048
"""The longest side of a pasted picture as the table sees it."""
TALK_PICTURE_WORK_SIZE = 2 * TALK_PICTURE_SIZE
"""No picture bigger than this many px a side is converted: it is reduced first, and resampled to its size after."""
TALK_PICTURE_MAX_PIXELS = MAX_PIXELS
AT_ONCE = 2
WAIT_S = 10.0
WEBP_QUALITY = 85


class TalkPictureRefused(PlayError):
    """A picture that can't go into table talk: `status` 400 (not the type it is sent as), 422 (too many pixels) or
    503 (busy)."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class TalkPicture:
    data: bytes
    width: int
    height: int
    mime: str = "image/webp"


_making = threading.BoundedSemaphore(AT_ONCE)


def talk_picture(data: bytes, media_type: str) -> TalkPicture:
    """The picture made of `data`, of `media_type` (one of `TALK_PICTURE_TYPES`)."""
    if not _making.acquire(timeout=WAIT_S):
        raise TalkPictureRefused(503, "Busy: try again in a moment.")
    try:
        return _talk_picture(data, media_type)
    finally:
        _making.release()


def _talk_picture(data: bytes, media_type: str) -> TalkPicture:
    expected = TALK_PICTURE_TYPES.get(media_type)
    if expected is None:
        raise TalkPictureRefused(400, f"A picture is one of {', '.join(TALK_PICTURE_TYPES)}.")
    upright = upright_picture(
        data,
        expected,
        max_pixels=TALK_PICTURE_MAX_PIXELS,
        work_size=TALK_PICTURE_WORK_SIZE,
        refused=TalkPictureRefused,
    )
    if max(upright.size) > TALK_PICTURE_SIZE:
        upright.thumbnail((TALK_PICTURE_SIZE, TALK_PICTURE_SIZE), Image.Resampling.LANCZOS, reducing_gap=2.0)
    webp, clean = clean_webp(upright, WEBP_QUALITY)
    return TalkPicture(webp, clean.width, clean.height)
