"""Small copies of the banners for the cards (DEL-234): a module's or a campaign's list shows each banner as a card,
and loading every full picture (2,400 pixels wide and up) for a card some 400 wide was most of the page. A card asks
for `?size=card`, and gets a WebP `CARD_WIDTH` wide, made once from the picture and kept in `<data dir>/thumbs/`
under the picture's blob (the sha256 of its bytes), so it never goes stale. The lightbox and the details pages still
load the picture itself.
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

CARD_WIDTH = 800
"""A card's width, twice over for a sharp screen."""
QUALITY = 80
THUMB_TYPE = "image/webp"
_BLOB = re.compile(r"^[0-9a-f]{64}$")


def thumbs_dir(data_dir: Path) -> Path:
    return data_dir / "thumbs"


def forget(data_dir: Path, blobs: Iterable[str]) -> None:
    """Delete the card copies of pictures whose blobs a prune deleted (DEL-36)."""
    folder = thumbs_dir(data_dir)
    for blob in blobs:
        if _BLOB.fullmatch(blob):
            (folder / f"{blob}-{CARD_WIDTH}.webp").unlink(missing_ok=True)


def card_thumbnail(data_dir: Path, blob: str, data: bytes) -> bytes | None:
    """The card's copy of the picture `data`, whose blob is `blob`: the one kept, else made now and kept. None when
    the picture can't be read, or is already no wider than a card: then the picture itself is shown."""
    if not _BLOB.fullmatch(blob):
        return None
    path = thumbs_dir(data_dir) / f"{blob}-{CARD_WIDTH}.webp"
    try:
        return path.read_bytes()
    except FileNotFoundError:
        pass
    made = _shrink(data)
    if made is None:
        return None
    _keep(path, made)
    return made


def _shrink(data: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width <= CARD_WIDTH:
                return None
            height = max(1, round(picture.height * CARD_WIDTH / picture.width))
            small = picture.convert("RGB").resize((CARD_WIDTH, height), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            small.save(out, "WEBP", quality=QUALITY, method=4)
            return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        log.warning("a banner's card copy can't be made: %s", error)
        return None


def _keep(path: Path, data: bytes) -> None:
    """Write the copy atomically; one that can't be written is made again next time."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, path)
    except OSError as error:
        log.warning("a banner's card copy can't be kept: %s", error)
