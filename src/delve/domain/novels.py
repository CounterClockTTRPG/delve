"""Novels (novelization plan Task 1): a campaign or a module told as a story, for the install's owner alone. A novel
is written outline first, then chapter by chapter, and each chapter is stored as it is written, so a novel that was
cut off keeps what it has and can be continued."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from delve.domain import data

NovelLength = Literal["recap", "short-story", "novella"]
NovelStatus = Literal["writing", "done", "failed", "cancelled"]


@dataclass(frozen=True)
class LengthSpec:
    """A length's target: about `words` in all, in `chapters` (the fewest and the most); a target, never checked."""

    words: int
    chapters: tuple[int, int]


LENGTHS: Mapping[NovelLength, LengthSpec] = {
    "recap": LengthSpec(1_500, (1, 1)),
    "short-story": LengthSpec(6_000, (3, 5)),
    "novella": LengthSpec(25_000, (8, 14)),
}


@dataclass(frozen=True)
class Chapter:
    """One chapter of the outline: its title and its summary, and its Markdown `text` (no heading) once written,
    None until then."""

    title: str
    summary: str
    text: str | None = None


@dataclass(frozen=True)
class Novel:
    """A novel of a campaign (`campaign_id`, with an optional range of `sessions`, first and last) or of a module
    (`module_id` at its `revision`): exactly one source is set. `tone` is a tone of `delve.dm.prompt.TONES`, or
    `custom` with `custom_tone`. `title` is the writer's (from the outline) until the owner renames it. `id` is
    given by storage when empty, and storage sets `created_at` and `updated_at`."""

    id: str
    title: str
    campaign_id: str | None = None
    module_id: str | None = None
    revision: int | None = None
    sessions: tuple[int, int] | None = None
    length: NovelLength = "recap"
    tone: str = "classic"
    custom_tone: str = ""
    language: str = "en"
    instructions: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    status: NovelStatus = "writing"
    error: str | None = None
    conversion_id: str | None = None
    cost_usd: float | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Novel:
        return data.from_dict(cls, raw)

    def to_dict(self) -> dict[str, Any]:
        return data.to_dict(self)
