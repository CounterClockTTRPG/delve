"""The history's writer (carry-the-party-on plan Task 5): one call for one audience's text, with the spec's sections in
order and Loose ends for the DM alone, then at most one call to shorten it, and a cut at a paragraph break."""

import asyncio

from delve.histories.writer import HISTORY_MAX_CHARS, write_history

SECTIONS = ("## The party", "## People met", "## Deeds", "## Grudges and debts", "## Loot")


class Fake:
    """The fake writer: the answers in turn, and the prompts it got."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


def test_dm_prompt_asks_for_loose_ends_table_prompt_does_not():
    dm, table = Fake("## The party\n\nMira lives."), Fake("## The party\n\nMira lives.")

    assert asyncio.run(write_history(dm, "THE-MATERIAL", "dm")) == "## The party\n\nMira lives."
    asyncio.run(write_history(table, "THE-MATERIAL", "table"))

    [dm_prompt], [table_prompt] = dm.prompts, table.prompts
    for prompt in (dm_prompt, table_prompt):
        assert "THE-MATERIAL" in prompt
        assert [prompt.index(section) for section in SECTIONS] == sorted(prompt.index(s) for s in SECTIONS)
        assert str(HISTORY_MAX_CHARS) in prompt
    assert "## Loose ends" in dm_prompt and dm_prompt.index("## Loot") < dm_prompt.index("## Loose ends")
    assert "Loose ends" not in table_prompt


def test_an_answer_in_a_fence_is_unfenced():
    fake = Fake("```markdown\n## The party\n\nMira lives.\n```")

    assert asyncio.run(write_history(fake, "material", "dm")) == "## The party\n\nMira lives."


def test_over_cap_shortens_once_then_cuts():
    paragraph = "x" * 900
    long = "\n\n".join([paragraph] * 10)  # 9018 characters
    still_long = "\n\n".join([paragraph] * 8)  # 7214 characters
    fake = Fake(long, still_long)

    text = asyncio.run(write_history(fake, "material", "table"))

    assert len(fake.prompts) == 2, "one call to shorten, never a second"
    assert "6000" in fake.prompts[1] and long in fake.prompts[1]
    assert len(text) <= HISTORY_MAX_CHARS == 6000
    assert text == "\n\n".join([paragraph] * 6), "cut at the last paragraph break under the cap"


def test_a_short_enough_shortening_is_kept():
    fake = Fake("y" * 7000, "## The party\n\nShorter.")

    assert asyncio.run(write_history(fake, "material", "dm")) == "## The party\n\nShorter."
