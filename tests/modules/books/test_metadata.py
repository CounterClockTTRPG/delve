import asyncio
import json

import pytest

from delve.modules.books.calls import Halt
from delve.modules.books.metadata import METADATA_CHARS, UNREAD, complete_metadata, merged, module_text, parse
from delve.modules.source import TextDoc

TEXTS = [
    TextDoc("front-matter", "Front matter", "gm", None, "Credits: Design: Lawrence Schick."),
    TextDoc("the-mountain", "The Mountain", "gm", None, "## 1. Entrance\n\nA cold wind."),
]
FOUND = {
    "summary": "Three weapons stolen into a volcano.",
    "authors": [{"name": "Lawrence Schick", "role": "author"}],
    "system": "adnd2e",
    "party": {"levels": {"min": 5, "max": 10}, "size": {"min": 4, "max": 8}},
    "tags": ["S2", "dungeon", "AD&D 1e"],
}


def _run(existing, reply):
    prompts = []

    async def complete(prompt: str) -> str:
        prompts.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return asyncio.run(complete_metadata(existing, TEXTS, "White Plume Mountain", complete)), prompts


def test_an_empty_module_gets_what_the_text_gives():
    (metadata, warnings), (prompt,) = _run({}, "```json\n" + json.dumps(FOUND) + "\n```")

    assert metadata == FOUND and warnings == []
    assert "White Plume Mountain" in prompt and "Lawrence Schick" in prompt and "## 1. Entrance" in prompt


def test_only_the_empty_fields_are_filled():
    existing = {"system": "other", "tags": [], "party": {"levels": {"min": 7, "max": 7}}, "setting": "Greyhawk"}

    (metadata, _), _ = _run(existing, json.dumps(FOUND))

    assert metadata["system"] == "other" and metadata["setting"] == "Greyhawk", "a field the module has is kept"
    assert metadata["tags"] == FOUND["tags"], "an empty field is filled"
    assert metadata["party"] == {"levels": {"min": 7, "max": 7}, "size": {"min": 4, "max": 8}}
    assert merged({"a": 1}, {"a": 2, "b": 3}) == {"a": 1, "b": 3}


def test_fields_that_dont_fit_the_schema_are_dropped():
    reply = {**FOUND, "authors": "Lawrence Schick", "language": "English", "cover": "asset:x", "maps": []}

    assert parse(json.dumps(reply)) == {k: v for k, v in FOUND.items() if k != "authors"}


def test_an_unreadable_answer_or_a_failed_call_keeps_the_metadata_with_a_warning():
    for reply in ("Sorry, I can't.", RuntimeError("claude stopped (exit code 1): API Error: 529")):
        (metadata, warnings), _ = _run({"setting": "Greyhawk"}, reply)
        assert metadata == {"setting": "Greyhawk"}
        assert [w.code for w in warnings] == [UNREAD]


def test_the_text_sent_is_capped():
    long = [TextDoc("t", "T", "gm", None, "x" * (METADATA_CHARS + 10))]

    assert len(module_text(long)) == METADATA_CHARS


def test_a_halt_stops_the_metadata():
    """A failed call is a warning; a `Halt` (a thorough job's pause) goes through."""
    with pytest.raises(Halt):
        _run({}, Halt("the usage limit"))
