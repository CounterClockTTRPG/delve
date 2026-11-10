"""An uploaded avatar (players and tavern Task D2): the picture a player sends becomes a `AVATAR_SIZE` px square
WebP for the blob store, made safe as every upload is (`delve.play.image_ingest`).

The bytes must be the type they are sent as (400), and the header's size is checked before anything is decoded (422
past `AVATAR_MAX_PIXELS`), so a small file that claims a huge picture costs nothing. A JPEG is drafted down to about
`AVATAR_WORK_SIZE` px as it is decoded, and every picture is reduced to at most that before it is converted, so no
full-size copy is made; at most `AVATARS_AT_ONCE` avatars are made at once, and one that waits `AVATAR_WAIT_S` for its
turn is 503 (Clara's final audit, finding 1). A phone photo is turned upright by its EXIF orientation, an animated
picture keeps its first frame, the picture is cropped from its centre, and the result keeps no metadata: no EXIF, no
colour profile, no camera.
"""

from __future__ import annotations

import threading

from PIL import Image, ImageOps

from delve.play.context import PlayError
from delve.play.image_ingest import clean_webp, upright_picture

AVATAR_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
AVATAR_LIMIT = 2 * 1024 * 1024
AVATAR_SIZE = 256
AVATAR_MAX_PIXELS = 16_000_000
AVATAR_WORK_SIZE = 1024
"""No picture bigger than this many px a side is converted or cropped: it is reduced first."""
AVATARS_AT_ONCE = 2
AVATAR_WAIT_S = 10.0
BUSY = "Busy: try again in a moment."
WEBP_QUALITY = 85


class AvatarRefused(PlayError):
    """A picture that can't be an avatar: `status` 400 (not the type it is sent as) or 422 (too many pixels)."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


_making = threading.BoundedSemaphore(AVATARS_AT_ONCE)


def square_avatar(data: bytes, media_type: str) -> bytes:
    """The avatar made of `data`, a picture of `media_type` (one of `AVATAR_TYPES`): WebP, `AVATAR_SIZE` square. 503
    when `AVATARS_AT_ONCE` others are being made for `AVATAR_WAIT_S`."""
    if not _making.acquire(timeout=AVATAR_WAIT_S):
        raise AvatarRefused(503, BUSY)
    try:
        return _square_avatar(data, media_type)
    finally:
        _making.release()


def _square_avatar(data: bytes, media_type: str) -> bytes:
    expected = AVATAR_TYPES.get(media_type)
    if expected is None:
        raise AvatarRefused(400, f"An avatar is one of {', '.join(AVATAR_TYPES)}.")
    upright = upright_picture(
        data, expected, max_pixels=AVATAR_MAX_PIXELS, work_size=AVATAR_WORK_SIZE, refused=AvatarRefused
    )
    square = ImageOps.fit(upright, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return clean_webp(square, WEBP_QUALITY)[0]
