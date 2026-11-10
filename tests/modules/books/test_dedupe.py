"""Records Claude groups as one (faithful modules Task 9, C3): one call per kind, merged by `merge_entities_mapped`'s rules.

The fake `complete` answers the grouping the test chooses, and records every prompt.
"""

import asyncio
import json

import pytest

from delve.modules.books.calls import Halt
from delve.modules.books.dedupe import dedupe_entities
from delve.modules.books.repair import repair_refs
from delve.modules.source import ModuleSource


class Grouping:
    """Answers each kind's prompt with `answers[kind]` (a list of groups, or a string as it is)."""

    def __init__(self, **answers):
        self.answers = answers
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        await asyncio.sleep(0)
        kind = "factions" if "are the factions" in prompt else "npcs"
        answer = self.answers.get(kind, [])
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, str) else json.dumps(answer)


def _npc(id: str, name: str, summary: str = "", **more) -> dict:
    return {"id": id, "name": name, "summary": summary, "audience": "gm", **more}


NPCS = [
    _npc("ned", "Ned", "A captive. He says he is a cleric.", role="spy"),
    _npc("the-bosun", "The Bosun", "He runs the deck."),
    _npc("ned-2", "Ned Shakeshaft", "The spy of the smugglers."),
    _npc("bernhardt", "Bernhardt", "The young innkeeper."),
    _npc("bosun-2", "Bosun of the Sea Ghost", "Armed with a cutlass.", role="bosun"),
    _npc("ned-3", "the spy Ned", "", location="text:ship#17"),
]


def _dedupe(entities, complete):
    return asyncio.run(dedupe_entities(entities, complete))


def test_dedupe_merges_what_claude_groups():
    claude = Grouping(npcs=[["ned", "ned-2", "ned-3"], ["the-bosun", "bosun-2"], ["bernhardt"]])
    factions = [{"id": "smugglers", "name": "The Smugglers", "members": ["npc:ned-3", "npc:bosun-2"]}]

    entities, renamed, warnings = _dedupe({"npcs": NPCS, "factions": factions}, claude)

    assert len(claude.prompts) == 1, "one faction alone is not sent"
    assert "ned | Ned | spy | A captive." in claude.prompts[0]
    assert "bosun-2 | Bosun of the Sea Ghost | bosun | Armed with a cutlass." in claude.prompts[0]
    assert [n["id"] for n in entities["npcs"]] == ["ned", "the-bosun", "bernhardt"]
    ned = entities["npcs"][0]
    assert ned["summary"] == "A captive. He says he is a cleric.\n\nThe spy of the smugglers."
    assert (ned["role"], ned["location"]) == ("spy", "text:ship#17")
    assert entities["npcs"][1]["role"] == "bosun"
    assert renamed == {"npc:ned-2": "npc:ned", "npc:ned-3": "npc:ned", "npc:bosun-2": "npc:the-bosun"}
    assert [(w.code, w.message) for w in warnings] == [
        ("entities-merged", "Merged as one: Ned, Ned Shakeshaft, the spy Ned."),
        ("entities-merged", "Merged as one: The Bosun, Bosun of the Sea Ghost."),
    ]
    assert NPCS[0]["summary"] == "A captive. He says he is a cleric.", "the records passed in are unchanged"

    repaired, _ = repair_refs(ModuleSource(entities=entities), renamed)
    assert repaired.entities["factions"][0]["members"] == ["npc:ned", "npc:the-bosun"]


def test_dedupe_keeps_bernhardt_apart_when_not_grouped():
    records = [
        _npc("bernhardt", "Bernhardt", "The young innkeeper."),
        _npc("elder", "Bernhardt the elder", "His father."),
    ]
    claude = Grouping(npcs=[["bernhardt"], ["elder"]])

    entities, renamed, warnings = _dedupe({"npcs": records}, claude)

    assert entities["npcs"] == records and renamed == {} and warnings == []


@pytest.mark.parametrize(
    "answer",
    [
        "They are all different people.",
        json.dumps({"groups": [["ned", "ned-2"]]}),
        [["ned", "nobody"]],
        [["ned", "ned-2"], ["ned-2", "ned-3"]],
        [["ned", 2]],
        RuntimeError("claude failed"),
    ],
    ids=["prose", "not-a-list", "unknown-id", "in-two-groups", "not-an-id", "failed-call"],
)
def test_dedupe_survives_a_bad_answer(answer):
    claude = Grouping(npcs=answer, factions=[["a", "b"]])
    factions = [{"id": "a", "name": "A", "summary": "One."}, {"id": "b", "name": "B", "summary": "Two."}]

    entities, renamed, warnings = _dedupe({"npcs": NPCS, "factions": factions}, claude)

    assert entities["npcs"] == NPCS, "nothing of the kind is merged"
    assert [f["id"] for f in entities["factions"]] == ["a"], "the other kind still is"
    assert renamed == {"faction:b": "faction:a"}
    assert [(w.code, w.ref) for w in warnings] == [
        ("entities-not-deduplicated", "npcs"),
        ("entities-merged", "faction:a"),
    ]


def test_a_kind_of_one_record_and_the_other_kinds_are_not_sent():
    claude = Grouping()
    entities = {"npcs": [NPCS[0]], "encounters": [{"id": "x", "name": "X"}, {"id": "y", "name": "X too"}]}

    assert _dedupe(entities, claude) == (entities, {}, [])
    assert claude.prompts == []


def test_a_halt_stops_the_dedupe():
    """A failed call keeps the records as they are; a `Halt` (a thorough job's pause) goes through."""
    with pytest.raises(Halt):
        _dedupe({"npcs": NPCS}, Grouping(npcs=Halt("the usage limit")))
