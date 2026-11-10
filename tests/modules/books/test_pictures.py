"""A generated module's pictures (DEL-347): Claude chooses them from the module, a painter paints them, as handouts."""

import asyncio
import json

import pytest

from delve.modules.books.pictures import PICTURE_NOT_PAINTED, Planned, paint_pictures, plan_pictures
from delve.modules.dscn import sha256
from delve.modules.source import ModuleSource, TextDoc
from tests.modules.books.test_sketch import Scripted

SOURCE = ModuleSource(
    texts=[TextDoc("mansion", "The Mansion", "gm", None, "# The Mansion\n\n## 1. Hall\n\nA ghost walks here.\n")],
    entities={"npcs": [{"id": "ilse", "name": "Princess Ilse", "role": "the lost princess"}]},
)
ILSE = {
    "id": "princess-ilse",
    "kind": "person",
    "brief": "A pale young woman in a torn silver gown, seen from the waist up.",
    "description": "Princess Ilse: show her when the party finds her.",
}
MANSION = {
    "kind": "place",
    "subject": "The mansion",
    "brief": "A rotting mansion on a hill at dusk.",
    "description": "The mansion from the road: show it when the party first sees it.",
}


def _answer(*pictures) -> str:
    return json.dumps({"pictures": list(pictures)})


def _plan(complete, limit=6):
    return asyncio.run(plan_pictures(SOURCE, limit, complete))


def test_claude_chooses_from_the_whole_module_within_the_limit():
    complete = Scripted(_answer(ILSE, MANSION))
    planned, warnings = _plan(complete, limit=4)
    assert warnings == []
    assert [(p.id, p.aspect) for p in planned] == [("princess-ilse", "1:1"), ("the-mansion", "")]
    asked = complete.prompts[0]
    assert "A ghost walks here." in asked and "Princess Ilse" in asked and "at most 4" in asked


def test_never_more_than_the_limit_and_no_two_with_one_id():
    planned, _ = _plan(Scripted(_answer(ILSE, ILSE, MANSION)), limit=2)
    assert [p.id for p in planned] == ["princess-ilse", "princess-ilse-2"]


def test_a_picture_without_a_brief_or_description_is_left_out():
    planned, warnings = _plan(
        Scripted(_answer({**ILSE, "brief": ""}, {**ILSE, "description": " "}, "nonsense", MANSION))
    )
    assert [p.id for p in planned] == ["the-mansion"]
    assert warnings == []


def test_no_pictures_is_a_fair_answer():
    assert _plan(Scripted(_answer())) == ([], [])


def test_an_unreadable_answer_is_asked_once_more_then_a_warning():
    complete = Scripted("not json", "still not")
    planned, warnings = _plan(complete)
    assert planned == []
    assert [w.code for w in warnings] == [PICTURE_NOT_PAINTED]
    assert len(complete.prompts) == 2


def test_a_failed_call_is_a_warning_not_a_stop():
    async def stopped(prompt: str) -> str:
        raise RuntimeError("claude stopped: overloaded")

    planned, warnings = _plan(stopped)
    assert planned == []
    assert "overloaded" in warnings[0].message


PLANNED = [
    Planned("a", "first", "shows a", "1:1"),
    Planned("b", "second", "shows b", ""),
    Planned("c", "third", "shows c", ""),
]


def test_the_paintings_are_attachments_for_the_players_in_the_planned_order():
    steps = []

    async def paint(picture):
        return (picture.id.encode(), "image/webp")

    pictures, warnings = asyncio.run(paint_pictures(PLANNED, paint, lambda *step: steps.append(step)))
    assert warnings == []
    assert [(a.id, a.type, a.sha256, a.size, a.description, a.audience) for a, _ in pictures] == [
        ("a", "image/webp", sha256(b"a"), 1, "shows a", "player"),
        ("b", "image/webp", sha256(b"b"), 1, "shows b", "player"),
        ("c", "image/webp", sha256(b"c"), 1, "shows c", "player"),
    ]
    assert [data for _, data in pictures] == [b"a", b"b", b"c"]
    assert steps[0] == ("painting", 0, 3) and steps[-1] == ("painting", 3, 3)


@pytest.mark.parametrize("answer", [RuntimeError("no credit"), (b"<svg/>", "image/svg+xml"), (b"", "image/png")])
def test_a_picture_that_fails_is_a_warning_and_the_others_stay(answer):
    async def paint(picture):
        if picture.id == "b":
            if isinstance(answer, Exception):
                raise answer
            return answer
        return (b"x", "image/png")

    pictures, warnings = asyncio.run(paint_pictures(PLANNED, paint, lambda *step: None))
    assert [a.id for a, _ in pictures] == ["a", "c"]
    assert [(w.code, w.ref) for w in warnings] == [(PICTURE_NOT_PAINTED, "asset:b")]


def test_a_cancel_is_not_swallowed():
    async def paint(picture):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(paint_pictures(PLANNED, paint, lambda *step: None))
