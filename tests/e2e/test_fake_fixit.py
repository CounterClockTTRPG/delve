"""The fake fix-it answer of the browser spec (table voice and fixes Task F2.4): on the Sunken Shrine's sketched map,
the comment of `web/e2e/u-fixit.spec.ts` gets an exit in room 3, which the job applies and the map's renderer draws."""

from delve.conversions.fixit import _applied, _prompt
from delve.domain.modules import ModuleComment, ModuleMap
from delve.maps.dsl import render
from delve.maps.sources import parse_map
from delve.modules.books.fences import unfenced
from delve.modules.source import ModuleSource
from tests.e2e.fake_fixit import fixit_answer
from tests.e2e.test_books_and_quick_dungeons import SHRINE_MAP

COMMENT = "The exit from room 3 to the mill pond is not yet in place, fix it."
"""The spec's comment."""


def test_the_comment_gets_its_exit():
    sketch = "# Sketched from the room key: an invented layout. No map page was found in the book.\n"
    maps = [ModuleMap("the-sunken-shrine", "map", sketch + unfenced(SHRINE_MAP), True)]
    prompt = _prompt("The Sunken Shrine", ModuleSource(), maps, [ModuleComment("mcm_1", "mod_1", COMMENT)])

    summary, _, after = _applied(fixit_answer(prompt), ModuleSource(), maps)

    assert summary == "Added the exit from room 3 to the mill pond."
    assert 'exit at 11,9 { to "mill pond" at 1,1  label "Up to the mill pond" }' in after[0].source
    assert "data-exit-to" in render(parse_map(after, "the-sunken-shrine"), None)


def test_other_prompts_are_not_its():
    assert fixit_answer("You are converting part of a book.") is None
