"""A module's banner (DEL-123): a picture uploaded or picked from the module's own (a converted book's cover, a
handout), cut to the banner's 21:9 band, or painted (`paint`, the campaign banner's brief and image choice).

A picture is checked as an avatar is (`delve.play.avatars`): the bytes must be the type they are sent as (400), the
header's size is checked before anything is decoded (422 past `BANNER_MAX_PIXELS`), a JPEG is drafted down as it is
decoded and every picture is reduced to at most `BANNER_WORK_SIZE` px a side before it is cut, at most
`BANNERS_AT_ONCE` are made at once (503 after `BANNER_WAIT_S`), and the result keeps no metadata. The crop position
(0 the top, 1 the bottom; across, for a picture wider than 21:9) chooses which band is kept, as CSS `object-position`
does with the same percentage, so the page's preview is the banner.
"""

from __future__ import annotations

import asyncio
import io
import logging
import threading
import warnings
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from delve.domain.image_styles import stored_style_text
from delve.domain.settings import Job
from delve.images.provider import ImageFile, ImageRequest
from delve.modules.cuts import MAX_PIXELS
from delve.modules.source import load_source
from delve.play import banners
from delve.play.avatars import AVATAR_TYPES
from delve.play.context import NotFound, PlayError

if TYPE_CHECKING:
    from delve.play.table import AppServices

BANNER_TYPES = AVATAR_TYPES
BANNER_LIMIT = 16 * 1024 * 1024
BANNER_MAX_PIXELS = MAX_PIXELS
BANNER_WORK_SIZE = 2400
"""No picture bigger than this many px a side is converted or cut: it is reduced first."""
BANNER_WIDTH, BANNER_HEIGHT = 1680, 720
"""The banner's size at most: 21:9, as a campaign's is painted."""
BANNERS_AT_ONCE = 2
BANNER_WAIT_S = 10.0
WEBP_QUALITY = 85
MIME = "image/webp"
_LABELS = {"PNG": "PNG", "JPEG": "JPEG", "WEBP": "WebP"}


class BannerRefused(PlayError):
    """A picture that can't be a banner: `status` 400 (not the type it is sent as, or not a picture of the module),
    404 (no such picture), 422 (too many pixels) or 503 (busy)."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


_making = threading.BoundedSemaphore(BANNERS_AT_ONCE)


def band(data: bytes, media_type: str, position: float = 0.5) -> bytes:
    """The banner cut from `data`, a picture of `media_type` (one of `BANNER_TYPES`): WebP, 21:9, at most
    `BANNER_WIDTH` wide, the band at `position` (0 to 1) of the picture's height, or of its width when it is wider."""
    if not _making.acquire(timeout=BANNER_WAIT_S):
        raise BannerRefused(503, "Busy: try again in a moment.")
    try:
        return _band(data, media_type, min(1.0, max(0.0, position)))
    finally:
        _making.release()


def _band(data: bytes, media_type: str, position: float) -> bytes:
    expected = BANNER_TYPES.get(media_type)
    if expected is None:
        raise BannerRefused(400, f"A banner is one of {', '.join(BANNER_TYPES)}.")
    not_it = BannerRefused(400, f"That picture isn't a {_LABELS[expected]}.")
    too_large = BannerRefused(422, f"That picture is too large: at most {BANNER_MAX_PIXELS // 1_000_000} million pixels.")
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
    if image.width * image.height > BANNER_MAX_PIXELS:
        raise too_large
    try:
        image.seek(0)
        if image.format == "JPEG":
            image.draft("RGB", (BANNER_WORK_SIZE, BANNER_WORK_SIZE))
        image.load()
        upright = ImageOps.exif_transpose(_reduced(image))
    except Image.DecompressionBombError:
        raise too_large from None
    except (OSError, SyntaxError, ValueError, EOFError):
        raise not_it from None
    upright = upright.convert("RGB")
    width, height = upright.size
    if width * BANNER_HEIGHT <= height * BANNER_WIDTH:  # taller than 21:9: a band across, at `position` down
        cut = max(1, round(width * BANNER_HEIGHT / BANNER_WIDTH))
        top = round(position * (height - cut))
        box = (0, top, width, top + cut)
    else:  # wider: a band down, at `position` across
        cut = max(1, round(height * BANNER_WIDTH / BANNER_HEIGHT))
        left = round(position * (width - cut))
        box = (left, 0, left + cut, height)
    cropped = upright.crop(box)
    if cropped.width > BANNER_WIDTH:
        cropped = cropped.resize((BANNER_WIDTH, BANNER_HEIGHT), Image.Resampling.LANCZOS, reducing_gap=2.0)
    # A fresh picture: nothing of the upload's info (EXIF, colour profile, comments) comes along.
    clean = Image.new("RGB", cropped.size)
    clean.paste(cropped)
    out = io.BytesIO()
    clean.save(out, "WEBP", quality=WEBP_QUALITY)
    return out.getvalue()


def _reduced(image: Image.Image) -> Image.Image:
    if max(image.size) <= BANNER_WORK_SIZE:
        return image
    scale = BANNER_WORK_SIZE / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    if image.mode in ("LA", "RGBA"):
        return image.resize(size, Image.Resampling.NEAREST)
    return image.resize(size, Image.Resampling.LANCZOS, reducing_gap=2.0)


def use_upload(storage, module_id: str, data: bytes, media_type: str, position: float):
    """The module, with the uploaded picture's band as its banner."""
    blob = storage.blobs.put(band(data, media_type, position), MIME)
    return storage.modules.set_banner(module_id, blob, MIME, "uploaded")


def use_picture(storage, module_id: str, attachment_id: str, position: float):
    """The module, with the band of one of its own pictures (an attachment of a PNG, JPEG or WebP) as its banner."""
    attachment = load_source(storage, module_id).attachment(attachment_id)
    if attachment is None:
        raise BannerRefused(404, "The module has no such picture.")
    if attachment.type not in BANNER_TYPES:
        raise BannerRefused(400, "Only a PNG, JPEG or WebP picture can be a banner.")
    data = storage.blobs.get(attachment.sha256)
    if data is None:
        raise BannerRefused(404, "That picture's file is missing.")
    blob = storage.blobs.put(band(data, attachment.type, position), MIME)
    return storage.modules.set_banner(module_id, blob, MIME, f"picture:{attachment_id}")


# ----- painting -----

PAINTING_ALREADY = "A banner is being painted already."
PAID_FOR_OWNER = "Only the owner may paint with a paid image model."
INTERRUPTED = "Delve stopped while it was painting: paint it again."
_painting: dict[str, asyncio.Task] = {}  # by module id, kept from the garbage collector
log = logging.getLogger(__name__)


def module_brief(module, hint: str = "") -> str:
    """The painter's brief of a module's banner: its world, from what any player may know."""
    meta = module.metadata or {}
    summary, description, setting = (meta.get(key) if isinstance(meta.get(key), str) else "" for key in
                                     ("summary", "description", "setting"))  # fmt: skip
    return banners.brief(module.title, summary, description, setting, hint)


def paint(services: AppServices, module_id: str, hint: str = "", *, owner: bool) -> object:
    """Start painting the module's banner, in the event loop; the module, marked painting. `PlayError` while one is
    being painted, and for a paid model when the caller isn't the owner; `NotFound` for no such module."""
    storage = services.storage
    module = storage.modules.get(module_id)
    if module is None:
        raise NotFound(f"No module '{module_id}'.")
    if module.banner is not None and module.banner.status == "painting" and module_id in _painting:
        raise PlayError(PAINTING_ALREADY)
    if services.image_paid(Job.IMAGE_SCENE) and not owner:
        raise PlayError(PAID_FOR_OWNER)
    prompt = module_brief(module, hint)
    module = storage.modules.banner_painting(module_id, prompt)
    task = asyncio.create_task(_paint_logged(services, module_id, prompt))
    _painting[module_id] = task
    task.add_done_callback(lambda done: _painting.pop(module_id, None) if _painting.get(module_id) is done else None)
    return module


async def _paint_logged(services: AppServices, module_id: str, prompt: str) -> None:
    try:
        await painted(services, module_id, prompt)
    except asyncio.CancelledError:
        raise
    except Exception:  # the banner stays painting until the next start fails it
        log.exception("painting the banner of %s failed", module_id)


async def painted(services: AppServices, module_id: str, prompt: str):
    """Paint the banner and land it, or mark it failed with the provider's reason; the module as it ends. A banner
    removed (or painted again) meanwhile is left as it is."""
    storage = services.storage
    try:
        if services.images is None:
            raise PlayError(f"No provider does the {Job.IMAGE_SCENE} job.")
        provider, choice = services.images(Job.IMAGE_SCENE)
        style = stored_style_text(storage.settings.load())
        result = await provider.generate(ImageRequest(Job.IMAGE_SCENE, prompt, choice, style=style, aspect="21:9"))
        if not isinstance(result, ImageFile):
            raise PlayError("The provider answered no picture.")
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 (a painting always ends, never a banner stuck painting)
        reason = str(error) or type(error).__name__
        if not _still_painting(storage, module_id, prompt):
            return storage.modules.get(module_id)
        return _changed(services, storage.modules.banner_failed(module_id, reason))
    if not _still_painting(storage, module_id, prompt):
        return storage.modules.get(module_id)
    sha = storage.blobs.put(result.data, result.mime)
    return _changed(services, storage.modules.set_banner(module_id, sha, result.mime, "painted"))


def _still_painting(storage, module_id: str, prompt: str) -> bool:
    """Whether the module still waits for this painting: not removed, nor painted again since."""
    module = storage.modules.get(module_id)
    return module is not None and module.banner is not None and module.banner.status == "painting" and (
        module.banner.prompt == prompt
    )


def _changed(services: AppServices, module):
    services.publish("modules", {"id": module.id})
    return module


def interrupted(storage) -> list[str]:
    """At start: the module banners a stopped Delve left painting are failed, to be painted again; their ids."""
    stopped = [m.id for m in storage.modules.list() if m.banner is not None and m.banner.status == "painting"]
    for module_id in stopped:
        storage.modules.banner_failed(module_id, INTERRUPTED)
    return stopped
