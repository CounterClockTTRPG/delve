"""Portraits (portraits plan Tasks 2 and 9): the campaign's portrait style is one of portraitgen's render styles, read
from the vendored copy so that an update of it can't drift from Delve's list; and the emote a PC's sheet shows."""

import re
from pathlib import Path

import pytest

from delve.play.portraits import PORTRAIT_STYLES, sheet_emote

VENDORED = Path(__file__).parents[2] / "web" / "vendor" / "portraitgen" / "src"


def vendored_render_styles() -> set[str]:
    """portraitgen's RENDER_STYLES: the registry's built-in ones, and each `registerRenderStyle` in `src/styles/`."""
    registry = (VENDORED / "registry.js").read_text()
    built_in = re.search(r"export const RENDER_STYLES = \{(.*?)\n\};", registry, re.DOTALL)
    assert built_in, "registry.js has no RENDER_STYLES"
    styles = set(re.findall(r"^\s*(\w+): \{ id:", built_in.group(1), re.MULTILINE))
    for path in (VENDORED / "styles").glob("*.js"):
        styles |= set(re.findall(r"registerRenderStyle\(\{\s*id: '([\w-]+)'", path.read_text()))
    return styles


def test_portrait_styles_match_portraitgen():
    assert len(PORTRAIT_STYLES) == len(set(PORTRAIT_STYLES))
    assert set(PORTRAIT_STYLES) == vendored_render_styles()
    assert PORTRAIT_STYLES[0] == "illustrated"  # the look of every portrait before styles


@pytest.mark.parametrize(
    ("hp", "hp_max", "conditions", "emote"),
    [
        (7, 21, [], "upset"),  # ⌊21 / 3⌋ = 7
        (8, 21, [], "idle"),
        (0, 21, [], "sleep"),
        (-3, 21, [], "sleep"),
        (21, 21, ["Frightened"], "afraid"),
        (21, 21, ["magical FEAR"], "afraid"),
        (21, 21, ["scared stiff"], "afraid"),
        (21, 21, ["terrified"], "afraid"),
        (2, 21, ["afraid"], "afraid"),  # afraid wins over upset
        (5, 21, ["downed"], "sleep"),
        (21, 21, ["Unconscious"], "sleep"),
        (0, 21, ["frightened"], "sleep"),  # sleep wins over afraid
        (21, 21, ["poisoned", "prone"], "idle"),
        (0, 0, [], "sleep"),
        (3, 0, [], "idle"),  # hp_max 0: no division, and ⌊0 / 3⌋ = 0
        (1, 2, [], "idle"),  # ⌊2 / 3⌋ = 0
    ],
)
def test_sheet_emote(hp, hp_max, conditions, emote):
    assert sheet_emote(hp, hp_max, conditions) == emote
