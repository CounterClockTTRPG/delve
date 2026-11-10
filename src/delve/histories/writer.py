"""The history's writer (carry-the-party-on plan Task 5): one audience's text from its rendered material.

`write_history` asks for Markdown with the design's sections, in order: The party, People met, Deeds, Grudges and
debts, Loot, and Loose ends for the DM alone (open quests and the secrets the party never uncovered). The table's
prompt never names Loose ends; what keeps DM-only material out of the table's text is its material, filtered in
`delve.histories.material`, not this prompt. An answer longer than `HISTORY_MAX_CHARS` is asked to be shortened
once; one still too long is cut at its last paragraph break under the cap. Every Claude call goes through the
injected `complete(prompt)`.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from importlib import resources
from typing import Literal

from delve.modules.books.fences import unfenced

__all__ = ["HISTORY_MAX_CHARS", "SECTIONS", "Complete", "write_history"]

Complete = Callable[[str], Awaitable[str]]

HISTORY_MAX_CHARS = 6000
"""The most characters each of a history's two texts holds: the DM reads its text every session."""

SECTIONS = (
    ("The party", "who travelled, who died along the way, and how the survivors stand."),
    ("People met", "each NPC that matters, what they are to the party, alive or dead, and where last seen."),
    ("Deeds", "what the party did that people would talk about."),
    ("Grudges and debts", "who wants the party harmed and why, who owes the party, and whom the party owes."),
    ("Loot", "the treasure and items of note the party carries out, and where any special item came from."),
)
LOOSE_ENDS = ("Loose ends", "the quests left open and the secrets the party never uncovered.")

READERS = {
    "dm": (
        "The DM of the party's next campaign, who reads it at the start of every session. It is the DM's alone: it may "
        "hold everything in the material, the secrets and what the party never learned included."
    ),
    "table": (
        "The players at the table, and the DM. It holds only what the whole table was told; the material holds no "
        "more than that."
    ),
}

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

_SHORTEN = """Shorten this history to at most {max} characters. Keep its sections, its headings and their order, and \
what a DM would bring back in a scene: names, places, grudges, debts and items. Answer with the shortened history as \
Markdown, and nothing else.

{text}
"""


def _prompt() -> str:
    return resources.files("delve.histories").joinpath("prompts", "history.md").read_text("utf-8")


def _fill(template: str, **values: str) -> str:
    """`template` with each `{{name}}` replaced by its value, in one pass, so a value is never filled in itself."""
    return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), template)


def _sections(audience: Literal["dm", "table"]) -> str:
    sections = (*SECTIONS, LOOSE_ENDS) if audience == "dm" else SECTIONS
    return "\n".join(f"- `## {heading}`: {what}" for heading, what in sections)


def _cut(text: str) -> str:
    """`text` up to its last paragraph break within the cap (a line break, or the cap, when it has none)."""
    if len(text) <= HISTORY_MAX_CHARS:
        return text
    for brk in ("\n\n", "\n"):
        end = text.rfind(brk, 0, HISTORY_MAX_CHARS + 1)
        if end > 0:
            return text[:end].rstrip()
    return text[:HISTORY_MAX_CHARS]


async def write_history(complete: Complete, material_text: str, audience: Literal["dm", "table"]) -> str:
    """The history for `audience` ("dm" or "table") from its rendered material, as Markdown of at most
    `HISTORY_MAX_CHARS` characters."""
    prompt = _fill(
        _prompt(),
        reader=READERS[audience],
        sections=_sections(audience),
        max=str(HISTORY_MAX_CHARS),
        material=material_text.strip(),
    )
    text = unfenced(await complete(prompt)).strip()
    if len(text) > HISTORY_MAX_CHARS:
        text = unfenced(await complete(_SHORTEN.format(max=HISTORY_MAX_CHARS, text=text))).strip()
    return _cut(text)
