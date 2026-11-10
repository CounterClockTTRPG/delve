"""The novel's writer (novelization plan Task 4): an outline first, then chapter by chapter.

`outline` asks for a JSON plan `{title, chapters: [{title, summary}]}`. A plan that can't be read is asked for once
more, with the reason; then the writing fails with "The outline couldn't be read: <reason>." A plan with more chapters
than its length allows is clamped: the extra chapters' summaries join the last chapter kept. Fewer are kept as they
are, as the lengths are targets.

`write_chapter` writes one chapter from the material, the outline and the running summary of the chapters before it.
`running_summary` is the outline's summaries of the chapters written, so it costs no call and Continue rebuilds it
from what is stored. Every Claude call goes through the injected `complete(prompt)`.

The writer takes the material as its kind and its text (`Material.kind` and `render(material)` of
`delve.novels.material`), so the job renders it once for all its calls.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal

from delve.dm.prompt import TONES
from delve.domain.novels import LENGTHS, Chapter, NovelLength
from delve.domain.settings import LANGUAGE_NAMES
from delve.modules.books.fences import unfenced

Complete = Callable[[str], Awaitable[str]]
Kind = Literal["campaign", "module"]

LANGUAGES = LANGUAGE_NAMES
"""The novel's languages (Delve's UI languages), by their code, as the prompts name them."""

LENGTH_NAMES: dict[NovelLength, str] = {"recap": "recap", "short-story": "short story", "novella": "novella"}

CLASSIC = (
    "Tell it as classic fantasy adventure: clear, vivid prose, with the wonder and danger of the places, and a good "
    "pace. Neither grim nor comic."
)
"""The tone `classic`, which `TONES` leaves empty because it is the DM procedure's own voice."""

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_HEADING = re.compile(r"\A(?:#{1,6} [^\n]*\n+)+")

_RETRY = """

---

Your plan:

{answer}

It couldn't be read: {reason}. Answer again with the whole plan as one JSON object, and nothing else.
"""


class WriterError(ValueError):
    """The outline couldn't be read, twice: "The outline couldn't be read: <reason>." """


class _Unreadable(ValueError):
    pass


@dataclass(frozen=True)
class Choices:
    """The owner's choices for a novel: its length, its tone (`custom` takes `custom_tone`), its language (`en`,
    `nl`) and the instructions, which may be empty."""

    length: NovelLength
    tone: str
    custom_tone: str
    language: str
    instructions: str


def _prompt(name: str) -> str:
    return resources.files("delve.novels").joinpath("prompts", name).read_text("utf-8")


def _fill(template: str, **values: str) -> str:
    """`template` with each `{{name}}` replaced by its value, in one pass, so a value is never filled in itself."""
    return _PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), template)


def _tone(choices: Choices) -> str:
    if choices.tone == "custom":
        return choices.custom_tone.strip() or CLASSIC
    return TONES.get(choices.tone) or CLASSIC


def _instructions(choices: Choices) -> str:
    text = choices.instructions.strip()
    if not text:
        return "None."
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _common(kind: Kind, material: str, choices: Choices) -> dict[str, str]:
    return {
        "length": LENGTH_NAMES[choices.length],
        "language": LANGUAGES.get(choices.language, choices.language),
        "rules": _prompt(f"{kind}.md").strip(),
        "tone": _tone(choices),
        "instructions": _instructions(choices),
        "material": material.strip(),
    }


def _chapter_range(length: NovelLength) -> str:
    least, most = LENGTHS[length].chapters
    if least == most:
        return f"{least} chapter" if least == 1 else f"{least} chapters"
    return f"{least} to {most} chapters"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _read_outline(answer: str) -> tuple[str, list[Chapter]]:
    body = unfenced(answer)
    if not body.startswith("{"):
        body = body[body.find("{") : body.rfind("}") + 1]
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as error:
        raise _Unreadable(f"the outline isn't JSON ({error.msg})") from None
    if not isinstance(raw, dict):
        raise _Unreadable("the outline isn't a JSON object")
    title = _text(raw.get("title"))
    if not title:
        raise _Unreadable("the outline has no title")
    if not isinstance(raw.get("chapters"), list) or not raw["chapters"]:
        raise _Unreadable("the outline has no chapters")
    chapters = []
    for n, item in enumerate(raw["chapters"], start=1):
        if not isinstance(item, dict) or not _text(item.get("title")) or not _text(item.get("summary")):
            raise _Unreadable(f"chapter {n} has no title or no summary")
        chapters.append(Chapter(_text(item["title"]), _text(item["summary"])))
    return title, chapters


def _clamped(chapters: list[Chapter], length: NovelLength) -> list[Chapter]:
    """At most the length's chapters: the extra chapters' summaries join the last one kept."""
    most = LENGTHS[length].chapters[1]
    if len(chapters) <= most:
        return chapters
    kept, extra = chapters[: most - 1], chapters[most - 1 :]
    return [*kept, Chapter(extra[0].title, " ".join(chapter.summary for chapter in extra))]


async def outline(complete: Complete, kind: Kind, material: str, choices: Choices) -> tuple[str, list[Chapter]]:
    """The novel's title and its chapters, with their summaries and no text, from the rendered `material`."""
    prompt = _fill(
        _prompt("outline.md"),
        **_common(kind, material, choices),
        words=str(LENGTHS[choices.length].words),
        chapters=_chapter_range(choices.length),
    )
    answer = await complete(prompt)
    try:
        title, chapters = _read_outline(answer)
    except _Unreadable as error:
        answer = await complete(prompt + _RETRY.format(answer=answer.strip(), reason=error))
        try:
            title, chapters = _read_outline(answer)
        except _Unreadable as again:
            raise WriterError(f"The outline couldn't be read: {again}.") from None
    return title, _clamped(chapters, choices.length)


def _outline_text(chapters: list[Chapter]) -> str:
    return "\n".join(f"{n}. **{chapter.title}**: {chapter.summary}" for n, chapter in enumerate(chapters, start=1))


def running_summary(chapters: list[Chapter]) -> str:
    """What happened in the chapters written so far: the outline's summaries of those with a text."""
    return "\n".join(
        f"Chapter {n}, {chapter.title}: {chapter.summary}"
        for n, chapter in enumerate(chapters, start=1)
        if chapter.text is not None
    )


async def write_chapter(
    complete: Complete,
    kind: Kind,
    material: str,
    choices: Choices,
    title: str,
    chapters: list[Chapter],
    index: int,
    so_far: str,
) -> str:
    """Chapter `index` (from 0) of `chapters`, as Markdown with no heading. The prompt carries the outline's titles
    and summaries, never a chapter's text; `so_far` is the running summary of the chapters before it."""
    chapter = chapters[index]
    prompt = _fill(
        _prompt("chapter.md"),
        **_common(kind, material, choices),
        title=title,
        number=str(index + 1),
        count=str(len(chapters)),
        chapter=chapter.title,
        words=str(LENGTHS[choices.length].words // len(chapters)),
        outline=_outline_text(chapters),
        so_far=so_far.strip() or "This is the first chapter.",
    )
    answer = unfenced(await complete(prompt))
    return _HEADING.sub("", answer).strip()
