"""The novel's writer (novelization plan Task 4): an outline, then chapter by chapter, with a running summary."""

import asyncio
import json

import pytest

from delve.dm.prompt import TONES
from delve.domain.novels import Chapter
from delve.novels.writer import Choices, WriterError, outline, running_summary, write_chapter


class Recording:
    """A fake `complete`: answers in order (the last one again when they run out), and records every prompt."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers[min(len(self.prompts), len(self.answers)) - 1]


CAMPAIGN = """# The Crypt of Saint Vellis

## Session 1: Into the crypt

Aldric opens the bronze door. The ghoul falls.

## The module: what was there, played or not

Area 7. The reliquary, never reached.
"""
MODULE = """# The Crypt of Saint Vellis

## 1. The bronze door

> A bronze door, green with age.
"""
INSTRUCTIONS = "Tell it from Mira's point of view."


def _outline_answer(count: int, title: str = "The Bronze Door") -> str:
    chapters = [{"title": f"Chapter {n}", "summary": f"What happens in part {n}."} for n in range(1, count + 1)]
    return json.dumps({"title": title, "chapters": chapters})


def _outline(complete: Recording, material: str, choices: Choices) -> tuple[str, list[Chapter]]:
    kind = "campaign" if material is CAMPAIGN else "module"
    return asyncio.run(outline(complete, kind, material, choices))


def test_a_campaigns_outline_prompt_holds_the_faithfulness_rule_the_tone_the_instructions_and_the_language() -> None:
    complete = Recording(_outline_answer(4))
    choices = Choices("short-story", "grimdark", "", "nl", INSTRUCTIONS)
    title, chapters = _outline(complete, CAMPAIGN, choices)
    assert title == "The Bronze Door"
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"]
    assert all(c.text is None for c in chapters)
    [prompt] = complete.prompts
    assert "faithful to the record" in prompt
    assert "invent no outcome" in prompt
    assert TONES["grimdark"] in prompt
    assert f"> {INSTRUCTIONS}" in prompt
    assert "Dutch" in prompt
    assert CAMPAIGN.strip() in prompt
    assert "3 to 5 chapters" in prompt
    assert "about 6000 words" in prompt


def test_a_modules_outline_prompt_holds_the_party_run_rule() -> None:
    complete = Recording(_outline_answer(1))
    _outline(complete, MODULE, Choices("recap", "classic", "", "en", ""))
    [prompt] = complete.prompts
    assert "a party's run through" in prompt
    assert "faithful to the record" not in prompt
    assert "English" in prompt
    assert "1 chapter" in prompt


def test_a_custom_tone_is_the_owners_text() -> None:
    complete = Recording(_outline_answer(1))
    _outline(complete, MODULE, Choices("recap", "custom", "Like a sea shanty, salt and rhythm.", "en", ""))
    assert "Like a sea shanty, salt and rhythm." in complete.prompts[0]


def test_an_outline_that_isnt_json_is_asked_for_again_with_the_error() -> None:
    complete = Recording("Here is my outline: chapter one, the door.", f"```json\n{_outline_answer(3)}\n```")
    title, chapters = _outline(complete, CAMPAIGN, Choices("short-story", "classic", "", "en", ""))
    assert title == "The Bronze Door"
    assert len(chapters) == 3
    assert len(complete.prompts) == 2
    assert "isn't JSON" in complete.prompts[1]
    assert "Here is my outline" in complete.prompts[1]


def test_an_outline_with_no_chapters_twice_fails() -> None:
    complete = Recording(_outline_answer(0))
    with pytest.raises(WriterError, match="The outline couldn't be read: the outline has no chapters"):
        _outline(complete, CAMPAIGN, Choices("short-story", "classic", "", "en", ""))
    assert len(complete.prompts) == 2
    assert "has no chapters" in complete.prompts[1]


def test_an_outline_that_isnt_json_twice_fails() -> None:
    complete = Recording("no", "still no")
    with pytest.raises(WriterError, match="The outline couldn't be read"):
        _outline(complete, CAMPAIGN, Choices("recap", "classic", "", "en", ""))
    assert len(complete.prompts) == 2


def test_forty_chapters_for_a_recap_are_clamped_to_one_keeping_every_summary() -> None:
    complete = Recording(_outline_answer(40))
    _, chapters = _outline(complete, CAMPAIGN, Choices("recap", "classic", "", "en", ""))
    assert len(complete.prompts) == 1
    [chapter] = chapters
    assert chapter.title == "Chapter 1"
    assert "part 1." in chapter.summary and "part 40." in chapter.summary


def test_too_many_chapters_for_a_novella_are_clamped_to_its_most() -> None:
    complete = Recording(_outline_answer(20))
    _, chapters = _outline(complete, CAMPAIGN, Choices("novella", "classic", "", "en", ""))
    assert len(chapters) == 14
    assert "part 14." in chapters[-1].summary and "part 20." in chapters[-1].summary


def test_fewer_chapters_than_the_range_are_kept() -> None:
    complete = Recording(_outline_answer(2))
    _, chapters = _outline(complete, CAMPAIGN, Choices("short-story", "classic", "", "en", ""))
    assert len(chapters) == 2
    assert len(complete.prompts) == 1


CHAPTERS = [
    Chapter("The Door", "Aldric opens the bronze door.", "SECRET-CHAPTER-ONE-TEXT"),
    Chapter("The Ghoul", "The ghoul falls to Mira's fire.", "SECRET-CHAPTER-TWO-TEXT"),
    Chapter("The Reliquary", "They find the empty reliquary.", "SECRET-LATER-CHAPTER-TEXT"),
    Chapter("Home", "The road back to town.", None),
]


def test_the_running_summary_is_the_outlines_summaries_of_the_written_chapters() -> None:
    summary = running_summary(CHAPTERS[:2])
    assert "Aldric opens the bronze door." in summary
    assert "The ghoul falls to Mira's fire." in summary
    assert "SECRET-CHAPTER" not in summary
    assert running_summary([Chapter("Home", "The road back.", None)]) == ""
    assert running_summary([]) == ""


def test_a_chapter_prompt_holds_the_outline_and_the_running_summary_and_no_later_chapters_text() -> None:
    complete = Recording("```markdown\nMira lifted the lantern.\n```")
    choices = Choices("short-story", "heroic", "", "en", INSTRUCTIONS)
    so_far = running_summary(CHAPTERS[:1])
    text = asyncio.run(write_chapter(complete, "campaign", CAMPAIGN, choices, "The Bronze Door", CHAPTERS, 1, so_far))
    assert text == "Mira lifted the lantern."
    [prompt] = complete.prompts
    assert "The Bronze Door" in prompt
    for chapter in CHAPTERS:
        assert chapter.title in prompt and chapter.summary in prompt
    assert so_far in prompt
    assert "chapter 2 of 4" in prompt.lower()
    assert "SECRET-" not in prompt
    assert CAMPAIGN.strip() in prompt
    assert TONES["heroic"] in prompt
    assert f"> {INSTRUCTIONS}" in prompt
    assert "faithful to the record" in prompt


def test_a_chapter_answer_loses_a_heading_the_writer_added() -> None:
    complete = Recording("## Chapter 1: The Door\n\nThe door was cold.")
    text = asyncio.run(
        write_chapter(complete, "module", MODULE, Choices("recap", "classic", "", "en", ""), "T", CHAPTERS[:1], 0, "")
    )
    assert text == "The door was cold."


def test_the_first_chapter_says_nothing_came_before() -> None:
    complete = Recording("The door was cold.")
    asyncio.run(
        write_chapter(complete, "module", MODULE, Choices("recap", "classic", "", "en", ""), "T", CHAPTERS[:1], 0, "")
    )
    assert "This is the first chapter." in complete.prompts[0]


def test_a_novella_asks_for_its_words_shared_over_its_chapters() -> None:
    chapters = [Chapter(f"Part {n}", f"Summary {n}.") for n in range(1, 11)]
    complete = Recording("Prose.")
    asyncio.run(
        write_chapter(complete, "campaign", CAMPAIGN, Choices("novella", "classic", "", "en", ""), "T", chapters, 0, "")
    )
    assert f"about {25_000 // 10} words" in complete.prompts[0]
