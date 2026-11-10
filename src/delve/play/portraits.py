"""Portraits in play: the render styles a campaign may draw its portraitgen portraits in (`PORTRAIT_STYLES`, the
vendored portraitgen's `RENDER_STYLES`), and the emote a character's sheet shows of its state (`sheet_emote`).
`illustrated`, the first style, is the look every portrait had before styles."""

import re
from collections.abc import Iterable
from typing import Literal

PORTRAIT_STYLES: tuple[str, ...] = ("illustrated", "realistic", "painterly", "inkwash", "engraving", "anime", "pixel")

SheetEmote = Literal["sleep", "afraid", "upset", "idle"]

# Conditions are free strings, in the DM's own words.
_DOWN = {"downed", "unconscious"}
_FEAR = re.compile(r"fear|frighten|afraid|scared|terrified", re.IGNORECASE)


def sheet_emote(hp: int, hp_max: int, conditions: Iterable[str]) -> SheetEmote:
    """What the sheet's portrait plays, the first that holds: `sleep` at 0 HP or less or `downed` / `unconscious`,
    `afraid` for a frightened condition, `upset` at a third of `hp_max` or less (rounded down), else `idle`."""
    conditions = list(conditions)
    if hp <= 0 or any(c.strip().lower() in _DOWN for c in conditions):
        return "sleep"
    if any(_FEAR.search(c) for c in conditions):
        return "afraid"
    if hp <= hp_max // 3:
        return "upset"
    return "idle"
