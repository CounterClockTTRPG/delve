"""What a picture-reading step hands to Claude (plan 7 Task 6): a `Look` is the vision call with its choice made, and
`fit_for_vision` makes a picture, or a crop or a contact sheet of one, small enough to send.

`delve.maps` may not import `delve.dm`, so a reading gets its `Look` from whoever runs it (the conversions' `look_for`,
or a test's fake).
"""

from __future__ import annotations

import io
from collections.abc import Awaitable, Callable

from PIL import Image

Look = Callable[[str, bytes, str], Awaitable[str]]
"""`look(prompt, image, media_type)`: Claude's answer about the picture."""

VISION_MAX_SIDE = 1568
"""The longest side, in pixels, of a picture sent to Claude: larger ones are scaled down by Claude anyway."""


def fit_for_vision(image: Image.Image) -> tuple[bytes, str]:
    """`image` as a PNG no longer than `VISION_MAX_SIDE` on either side, keeping its proportions, and its media
    type."""
    fitted = image if image.mode in ("RGB", "RGBA", "L") else image.convert("RGBA")
    longest = max(fitted.size)
    if longest > VISION_MAX_SIDE:
        scale = VISION_MAX_SIDE / longest
        size = (max(1, round(fitted.width * scale)), max(1, round(fitted.height * scale)))
        fitted = fitted.resize(size, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    fitted.save(out, "PNG", optimize=True)
    return out.getvalue(), "image/png"
