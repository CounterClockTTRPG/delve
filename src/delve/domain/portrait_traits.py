"""portraitgen's traits, as a player's editor saves them (DEL-238): the whole drawing of a face, checked here.

A drawn portrait is usually a description and a seed, which the browser draws again the same way every time. One
edited in portraitgen's editor is its traits instead: every part, colour, decoration and fine-tune the player chose.
Those come from a player's browser and are drawn in every other seat's as SVG markup, so only the keys portraitgen
writes are taken, each as the kind of value it writes: a part's id, a colour as `#rrggbb`, a number in range. A
value that could close an attribute or open an element never gets through.
"""

from __future__ import annotations

import math
import re
from typing import Any

PART_KEYS = frozenset(
    {
        "theme", "presentation", "build", "age", "expression", "lighting", "framing", "style",
        "face", "ears", "eyes", "brows", "nose", "mouth", "hair", "facialHair", "clothing", "background", "frame",
    }
)  # fmt: skip
"""The keys whose value is one of portraitgen's ids; each one is required."""
COLOR_SLOTS = frozenset({"skin", "hair", "eyes", "clothing", "accent", "background"})
TWEAKS = {"eyeSize": (0.5, 2.0), "jaw": (0.5, 2.0), "hairLength": (0.0, 1.5), "saturation": (0.0, 2.0),
          "age": (0.0, 1.0), "turn": (-1.0, 1.0)}  # fmt: skip
"""The fine-tunes, each with the range taken (a little wider than the editor's sliders)."""
ALL_KEYS = PART_KEYS | {"version", "seed", "archetype", "turn", "tweaks", "colors", "accessories"}
MAX_ACCESSORIES = 24

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}")
_SEED = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


class TraitsError(ValueError):
    """Traits portraitgen didn't write: `where` names the key, the message says what was wrong with it."""

    def __init__(self, where: str, message: str) -> None:
        self.where = where
        super().__init__(f"{where}: {message}")


def _number(value: Any, low: float, high: float, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise TraitsError(where, "a number")
    if not low <= value <= high:
        raise TraitsError(where, f"between {low} and {high}")
    return float(value)


def _id(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise TraitsError(where, "one of portraitgen's ids")
    return value


def checked(raw: Any) -> dict[str, Any]:
    """`raw` as traits Delve keeps, a fresh dict of the checked values; `TraitsError` for anything else."""
    if not isinstance(raw, dict):
        raise TraitsError("traits", "an object")
    unknown = sorted(set(raw) - ALL_KEYS)
    if unknown:
        raise TraitsError(unknown[0], "not one of portraitgen's traits")
    missing = sorted((PART_KEYS | {"version", "seed", "colors", "accessories"}) - set(raw))
    if missing:
        raise TraitsError(missing[0], "missing")
    out: dict[str, Any] = {key: _id(raw[key], key) for key in sorted(PART_KEYS)}
    version = raw["version"]
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 99:
        raise TraitsError("version", "a whole number from 1 to 99")
    out["version"] = version
    if not isinstance(raw["seed"], str) or not _SEED.fullmatch(raw["seed"]):
        raise TraitsError("seed", "letters, digits and _.:- only, at most 64")
    out["seed"] = raw["seed"]
    archetype = raw.get("archetype")
    out["archetype"] = None if archetype is None else _id(archetype, "archetype")
    if "turn" in raw:
        out["turn"] = _number(raw["turn"], -1.0, 1.0, "turn")
    colors = raw["colors"]
    if not isinstance(colors, dict) or set(colors) != COLOR_SLOTS:
        raise TraitsError("colors", f"an object of {', '.join(sorted(COLOR_SLOTS))}")
    for slot, color in colors.items():
        if not isinstance(color, str) or not _COLOR.fullmatch(color):
            raise TraitsError(f"colors.{slot}", "a colour as #rrggbb")
    out["colors"] = {slot: colors[slot] for slot in sorted(COLOR_SLOTS)}
    accessories = raw["accessories"]
    if not isinstance(accessories, list) or len(accessories) > MAX_ACCESSORIES:
        raise TraitsError("accessories", f"a list of at most {MAX_ACCESSORIES}")
    out["accessories"] = [_id(a, f"accessories[{i}]") for i, a in enumerate(accessories)]
    if len(set(out["accessories"])) != len(out["accessories"]):
        raise TraitsError("accessories", "each one once")
    tweaks = raw.get("tweaks")
    if tweaks is not None:
        if not isinstance(tweaks, dict) or not set(tweaks) <= set(TWEAKS):
            raise TraitsError("tweaks", f"an object of {', '.join(TWEAKS)}")
        out["tweaks"] = {k: _number(v, *TWEAKS[k], f"tweaks.{k}") for k, v in tweaks.items()}
    return out
