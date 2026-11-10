"""A picture a seat uploads, made safe to keep (players and tavern Task D2, DEL-294): what an avatar
(`delve.play.avatars`) and a table-talk picture (`delve.play.talk_pictures`) share.

The bytes must be the type they are sent as (400), and the header's size is checked before anything is decoded (422
past the caller's pixel cap), so a small file that claims a huge picture costs nothing. A JPEG is drafted down to
about the caller's work size as it is decoded, and every picture is reduced to at most that before it is converted,
so no full-size copy is made (Clara's final audit, finding 1). A phone photo is turned upright by its EXIF
orientation, an animated picture keeps its first frame, and the WebP made of it keeps no metadata: no EXIF (a phone
photo's GPS position), no colour profile, no camera.
"""

from __future__ import annotations

import io
import warnings
from collections.abc import Callable

from PIL import Image, ImageOps

__all__ = ["clean_webp", "upright_picture"]

_LABELS = {"PNG": "PNG", "JPEG": "JPEG", "WEBP": "WebP", "GIF": "GIF"}


def _reduced(image: Image.Image, work_size: int) -> Image.Image:
    """`image` at most `work_size` a side. Pillow resamples a picture with alpha through a full-size premultiplied
    copy, so one is reduced by nearest pixel; the caller's own resampling comes after, at this size."""
    if max(image.size) <= work_size:
        return image
    scale = work_size / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    if image.mode in ("LA", "RGBA"):
        return image.resize(size, Image.Resampling.NEAREST)
    return image.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)


def upright_picture(
    data: bytes,
    expected: str,
    *,
    max_pixels: int,
    work_size: int,
    refused: Callable[[int, str], Exception],
) -> Image.Image:
    """`data` decoded as a picture of Pillow format `expected`: its first frame, upright, at most `work_size` a side,
    RGB or (when it has any transparency) RGBA. A picture that isn't `expected` is `refused(400, …)`, one of more than
    `max_pixels` `refused(422, …)`."""
    not_it = refused(400, f"That picture isn't a {_LABELS.get(expected, expected)}.")
    too_large = refused(422, f"That picture is too large: at most {max_pixels // 1_000_000} million pixels.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data), formats=[expected])
    except Image.DecompressionBombError:
        raise too_large from None
    except (OSError, SyntaxError, ValueError):
        raise not_it from None
    if image.format != expected:
        raise not_it
    if image.width * image.height > max_pixels:
        raise too_large
    try:
        image.seek(0)
        if image.format == "JPEG":
            image.draft("RGB", (work_size, work_size))
        image.load()
        upright = ImageOps.exif_transpose(_reduced(image, work_size))
    except Image.DecompressionBombError:
        raise too_large from None
    except (OSError, SyntaxError, ValueError, EOFError):
        raise not_it from None
    has_alpha = upright.mode in ("RGBA", "LA", "PA") or "transparency" in upright.info
    return upright.convert("RGBA" if has_alpha else "RGB")


def clean_webp(image: Image.Image, quality: int) -> tuple[bytes, Image.Image]:
    """`image` as a WebP of a fresh picture, so nothing of the upload's info (EXIF, colour profile, comments) comes
    along; and that fresh picture."""
    clean = Image.new(image.mode, image.size)
    clean.paste(image)
    out = io.BytesIO()
    clean.save(out, "WEBP", quality=quality)
    return out.getvalue(), clean
