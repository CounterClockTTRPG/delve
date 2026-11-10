"""Generating a campaign in steps (DEL-134): scope, outline, the campaign's texts, a call per level, a map per level."""

import asyncio
import json

import pytest

from delve.dice import SeededRng
from delve.maps.sources import parse_source
from delve.modules.books.campaign import (
    ANSWERS_HEADING,
    Answer,
    Connection,
    generate_campaign,
    join_levels,
    scope_request,
    with_answers,
)
from delve.modules.books.generate import GenerationError
from delve.modules.source import derive

REQUEST = "A sprawling multi-level dungeon for characters from level 1, campaign-sized."

OUTLINE = {
    "title": "The Weeping Deep",
    "summary": "A cave-in traps the party in a dungeon of salt.",
    "party": {"size": {"min": 4, "max": 6}, "levels": {"min": 1, "max": 5}},
    "history": "Dug by salt miners, sealed by a flood.",
    "thread": "A sword that remembers its wielder wants revenge.",
    "factions": [{"id": "salt-choir", "name": "The Salt Choir", "summary": "Singing ghouls.", "levels": ["A", "B"]}],
    "levels": [
        {"letter": "A", "name": "The Gallery", "levels": {"min": 1, "max": 2}, "rooms": 2, "summary": "Upper mine."},
        {"letter": "B", "name": "The Brine", "levels": {"min": 3, "max": 5}, "rooms": 2, "summary": "Flooded halls."},
    ],
    "connections": [{"from": "A2", "to": "B1", "how": "A cracked shaft."}, {"from": "A1", "to": "Q9", "how": "bad"}],
}

CAMPAIGN = {
    "texts": [{"title": "History", "markdown": "### The miners\n\nThey dug too deep."}],
    "npcs": [{"id": "maera", "name": "Maera", "role": "envoy", "faction": "faction:salt-choir"}],
    "factions": [{"id": "salt-choir", "name": "The Salt Choir", "goals": ["sing"]}],
    "quests": [{"id": "the-way-up", "name": "The way up", "stakes": "Daylight."}],
}


def level(letter: str, *, numbers_only: bool = False) -> dict:
    key = (lambda n: str(n)) if numbers_only else (lambda n: f"{letter}{n}")
    return {
        "intro": f"Level {letter} is cold.",
        "rooms": [
            {"key": key(1), "name": "Stair", "read_aloud": "Steps.", "dm_text": f"East to {letter}2.", "monsters": ""},
            {"key": key(2), "name": "Shaft", "read_aloud": "A shaft.", "dm_text": "West.", "treasure": "10 gp"},
        ],
        "wandering": {
            "check": "1 in 6 a turn",
            "table": [{"roll": "1", "result": "2 rats"}, {"roll": "2-6", "result": "nothing"}],
        },
        "encounters": [{"id": f"level-{letter.lower()}-rats", "name": "Rats"}],
    }


def sketch(letter: str) -> str:
    return f"""\
map "Level {letter}" {{
  grid {{ cell 32 px  units feet 10  bounds 30 x 20 }}
  room_numbers off
}}

room "r{letter}1" {{ rect 1,1 6 x 5  label "{letter}1. Stair" }}
room "r{letter}2" {{ rect 7,1 8 x 5  label "{letter}2. Shaft" }}

door between room.r{letter}1 and room.r{letter}2 {{ }}
"""


class Fake:
    """A `complete` that answers each kind of prompt by what it asks, as the levels are asked at once."""

    def __init__(self, **overrides: list[str]) -> None:
        self.overrides = {k: list(v) for k, v in overrides.items()}
        self.prompts: list[str] = []

    def kind(self, text: str) -> str:
        if "You plan a campaign-sized adventure" in text:
            return "outline"
        if "campaign-wide texts" in text:
            return "campaign"
        if "You write one level" in text:
            return "level-" + text.split("keyed `")[1][0]
        if "schematic map" in text or "You draw the map of a place" in text:
            return "map-" + text.split("## The room key")[1].split('room "r')[1][0]
        if "decide how big" in text:
            return "scope"
        raise AssertionError(text[:200])

    async def __call__(self, text: str) -> str:
        return self.answer(text)

    def answer(self, text: str) -> str:
        self.prompts.append(text)
        kind = self.kind(text)
        if self.overrides.get(kind):
            return self.overrides[kind].pop(0)
        if kind == "outline":
            return json.dumps(OUTLINE)
        if kind == "campaign":
            return json.dumps(CAMPAIGN)
        if kind.startswith("level-"):
            return f"```json\n{json.dumps(level(kind[-1]))}\n```"
        if kind.startswith("map-"):
            return f"```dmap\n{sketch(kind[-1])}```"
        return json.dumps({"scale": "campaign", "questions": []})


def _run(fake: Fake):
    steps: list[tuple[str, int, int]] = []
    converted = asyncio.run(generate_campaign(REQUEST, fake, lambda *s: steps.append(s), rng=SeededRng(1)))
    return converted, steps


def test_a_campaign_is_written_level_by_level_each_with_its_own_map():
    converted, steps = _run(Fake())

    titles = [t.title for t in converted.source.texts]
    assert titles == ["The Weeping Deep", "History", "Level A: The Gallery", "Level B: The Brine"]
    a, b = converted.source.texts[2:]
    assert (a.map, b.map) == ("level-a", "level-b")
    assert "## Wandering monsters" in a.markdown and "| 2-6 | nothing |" in a.markdown
    assert [(m.name, m.is_default) for m in converted.maps] == [("level-a", True), ("level-b", False)]
    derived = derive(converted.source, converted.maps)
    assert sorted((link.key, link.node) for link in derived.links) == [
        ("A1", "room.rA1"),
        ("A2", "room.rA2"),
        ("B1", "room.rB1"),
        ("B2", "room.rB2"),
    ]
    entities = converted.source.entities
    assert [n["id"] for n in entities["npcs"]] == ["maera"]
    assert [f["id"] for f in entities["factions"]] == ["salt-choir"]
    assert [q["id"] for q in entities["quests"]] == ["the-way-up"]
    assert sorted(e["id"] for e in entities["encounters"]) == [
        "level-a-rats",
        "level-a-wandering",
        "level-b-rats",
        "level-b-wandering",
    ]
    wandering = {e["id"]: e for e in entities["encounters"] if e.get("wandering")}
    assert {i: e["where"] for i, e in wandering.items()} == {  # DEL-321: each level's table rolls on its own map
        "level-a-wandering": ["map:level-a"],
        "level-b-wandering": ["map:level-b"],
    }
    assert converted.metadata == {"party": OUTLINE["party"]}
    assert ("levels", 2, 2) in steps and ("maps", 2, 2) in steps
    assert [s[0] for s in steps][:4] == ["planning", "planning", "campaign", "campaign"]


def test_the_levels_are_joined_both_ways_at_their_rooms():
    converted, _ = _run(Fake())

    a, b = (parse_source(m.source) for m in converted.maps)
    [down] = a.exits
    [up] = b.exits
    assert down.target_map == "level-b" and up.target_map == "level-a"
    assert down.position == pytest.approx(up.target_position, abs=0.2)  # B's way up lands where A's way down is
    # The connection to a level the outline doesn't have was never kept.
    assert not [w for w in converted.warnings if w.code == "exit-not-joined"]


def test_a_level_keyed_by_numbers_only_gets_its_letter():
    converted, _ = _run(Fake(**{"level-B": [json.dumps(level("B", numbers_only=True))]}))

    assert "B1. Stair" in converted.source.texts[3].markdown


def test_a_level_that_cant_be_read_twice_is_left_out_and_its_way_unjoined():
    converted, _ = _run(Fake(**{"level-B": ["no", "still no"]}))

    assert [t.title for t in converted.source.texts][-1] == "Level A: The Gallery"
    codes = [w.code for w in converted.warnings]
    assert "level-not-written" in codes and "exit-not-joined" in codes
    assert [m.name for m in converted.maps] == ["level-a"]


def test_an_outline_that_cant_be_read_twice_fails():
    with pytest.raises(GenerationError, match="outlined"):
        _run(Fake(outline=["no", "{}"]))


def test_each_level_is_told_its_ways_to_the_others():
    fake = Fake()
    _run(fake)

    [b_prompt] = [p for p in fake.prompts if fake.kind(p) == "level-B"]
    assert "**B1** leads to A2: A cracked shaft." in b_prompt
    assert "The Salt Choir" in b_prompt  # the outline is in every level's prompt


def test_scope_reads_the_scale_and_questions():
    answer = json.dumps({"scale": "campaign", "questions": [{"text": "How many levels?", "default": "Five."}]})
    scope = asyncio.run(scope_request(REQUEST, Fake(scope=[answer])))

    assert scope.scale == "campaign"
    assert [(q.id, q.text, q.default) for q in scope.questions] == [("s1", "How many levels?", "Five.")]


def test_the_scope_names_the_installs_game_else_osric():
    """DEL-307: the game a generated module is for is the install's ruleset's, never one core names."""
    answer = json.dumps({"scale": "module", "questions": []})
    named, plain = Fake(scope=[answer]), Fake(scope=[answer])
    asyncio.run(scope_request(REQUEST, named, game="Swords of the Test"))
    asyncio.run(scope_request(REQUEST, plain))
    assert "the module is for Swords of the Test unless" in named.prompts[0]
    assert "the module is for OSRIC 3.0 unless" in plain.prompts[0] and "{{game}}" not in plain.prompts[0]


def test_a_scope_that_cant_be_read_is_a_small_module():
    scope = asyncio.run(scope_request(REQUEST, Fake(scope=["?", "??"])))

    assert (scope.scale, scope.questions) == ("module", [])


def test_the_answers_follow_the_request():
    text = with_answers("A dungeon.", [Answer("How many levels?", "Five.", "Seven"), Answer("Tone?", "Grim.")])

    assert text == f"A dungeon.\n\n{ANSWERS_HEADING}\n\n- How many levels? **Seven**\n- Tone? Grim. (assumed)"
    assert with_answers("A dungeon. ", []) == "A dungeon."


def test_join_levels_warns_for_a_missing_room():
    maps = {"level-a": sketch("A")}
    joined, warnings = join_levels(maps, {"A1": "level-a"}, [Connection("A1", "B1", "")])

    assert joined == maps
    assert [w.code for w in warnings] == ["exit-not-joined"]


class Broken(Fake):
    """A `complete` whose `first` call (a level's or a map's) fails as the provider fails, while `second` is still
    being answered; `cancelled` says whether `second` was stopped."""

    def __init__(self, first: str, second: str) -> None:
        super().__init__()
        self.first, self.second = first, second
        self.cancelled = False
        self.asked = asyncio.Event()

    async def __call__(self, text: str) -> str:
        kind = self.kind(text)
        if kind == self.second:
            self.asked.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if kind == self.first:
            await self.asked.wait()
            raise RuntimeError("claude stopped (exit code 1): API Error: 529 Overloaded")
        return self.answer(text)


@pytest.mark.parametrize("calls", [("level-A", "level-B"), ("map-A", "map-B")])
def test_a_failed_call_stops_the_others_at_once(calls):
    """A provider's failure fails the job, and the calls still running stop with it, not left asking Claude for a
    job that has ended."""
    fake = Broken(*calls)

    async def scenario():
        with pytest.raises(RuntimeError, match="Overloaded"):
            await generate_campaign(REQUEST, fake, lambda *s: None, rng=SeededRng(1))
        return fake.cancelled  # before `asyncio.run` cancels what is left

    assert asyncio.run(scenario())
