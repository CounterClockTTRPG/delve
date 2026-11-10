"""The install's image style (DEL-202): every painting's style, from the campaign's tone (`TONE`, as before), a preset
of `PRESETS`, or the owner's own words (`CUSTOM`). Any style but the tone's replaces the tone's painter in the prompt
(`delve.images.replicate.full_prompt`).

The presets are Delve's three tone styles and ttrpg3's starter art styles (its `STARTER_ART_STYLES`), whose sample
pictures the web shows (`/image-styles/{id}.webp`); ttrpg3's negative prompts are left out, since FLUX takes none.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TONE = "tone"
CUSTOM = "custom"
CUSTOM_LIMIT = 1000
"""A custom style's length at most, in characters."""


@dataclass(frozen=True)
class ImageStylePreset:
    id: str
    name: str
    prompt: str
    sample: bool = False
    """Whether the web has a sample picture of it."""


# ttrpg2's three styles, which the campaign's tone picks among (`delve.images.replicate.TONE_STYLES`).
ELMORE = (
    "In the style of Larry Elmore and Clyde Caldwell. Painted oils, romantic heroic fantasy, heroic and luminous, "
    "epic scale. Rich colours, dramatic lighting."
)
BROM = (
    "In the style of Brom and Jeff Easley. Painted, high-contrast, gothic. Grim, weathered, realistic. Dark tones, "
    "worn equipment."
)
DITERLIZZI = (
    "In the style of Tony DiTerlizzi. Inked line work with watercolor, whimsical. Lighthearted, bright colours, "
    "cartoonish."
)

PRESETS: tuple[ImageStylePreset, ...] = (
    ImageStylePreset("elmore", "Heroic oils (Elmore and Caldwell)", ELMORE),
    ImageStylePreset("brom", "Gothic and grim (Brom and Easley)", BROM),
    ImageStylePreset("diterlizzi", "Ink and watercolour (DiTerlizzi)", DITERLIZZI),
    ImageStylePreset(
        "frazetta",
        "Heroic oil (Frazetta)",
        "Dramatic high-fantasy oil painting, muscular dynamic figures, smouldering earthy palette, dramatic "
        "chiaroscuro lighting, in the heroic pulp tradition of Frank Frazetta.",
        sample=True,
    ),
    ImageStylePreset(
        "vallejo",
        "Painterly realism (Vallejo)",
        "Richly rendered photorealistic fantasy oil painting, gleaming muscle and metal, lush airbrushed detail, in "
        "the polished style of Boris Vallejo.",
        sample=True,
    ),
    ImageStylePreset(
        "hildebrandt",
        "Luminous ink (Hildebrandt)",
        "Warm storybook fantasy illustration, soft luminous light, naturalistic detail, classic Tolkien-calendar "
        "feel in the tradition of the Brothers Hildebrandt.",
        sample=True,
    ),
    ImageStylePreset(
        "froud",
        "Watercolour faerie (Froud)",
        "Delicate watercolour fantasy illustration, earthy organic faerie creatures, soft muted palette, "
        "pen-and-wash texture in the tradition of Brian Froud.",
        sample=True,
    ),
    ImageStylePreset(
        "woodcut",
        "Ink engraving (woodcut)",
        "High-contrast black-ink woodcut engraving, dense cross-hatching, medieval grimoire frontispiece.",
        sample=True,
    ),
)
PRESET_IDS = frozenset(p.id for p in PRESETS)


@dataclass(frozen=True)
class ImageStyle:
    """The install's choice: `TONE`, a preset's id, or `CUSTOM` with its `custom` words."""

    preset: str = TONE
    custom: str = ""

    def to_json(self) -> dict[str, str]:
        return {"preset": self.preset, "custom": self.custom}


def parse(raw: Any) -> tuple[ImageStyle, str | None]:
    """The stored style, and what was wrong with it (None when nothing was): an unknown preset, a custom style
    without words, or one that isn't a mapping is the tone's."""
    if raw is None:
        return ImageStyle(), None
    if not isinstance(raw, Mapping):
        return ImageStyle(), "not a mapping"
    preset = raw.get("preset", TONE)
    custom = raw.get("custom", "")
    custom = " ".join(custom.split())[:CUSTOM_LIMIT] if isinstance(custom, str) else ""
    if preset == CUSTOM:
        return (ImageStyle(CUSTOM, custom), None) if custom else (ImageStyle(TONE, ""), "a custom style needs words")
    if preset == TONE or preset in PRESET_IDS:
        return ImageStyle(str(preset), custom), None
    return ImageStyle(TONE, custom), f"{preset!r} is not a preset"


def style_text(style: ImageStyle) -> str:
    """The words the style adds to a prompt; empty for the tone's, whose painter the provider picks."""
    if style.preset == CUSTOM:
        return style.custom
    return next((p.prompt for p in PRESETS if p.id == style.preset), "")


def stored_style_text(stored: Any) -> str:
    """The style's words from the stored settings (`{"image_style": {...}}`), whatever they hold."""
    raw = stored.get("image_style") if isinstance(stored, Mapping) else None
    return style_text(parse(raw)[0])
