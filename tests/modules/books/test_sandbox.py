"""Generating an open sandbox in steps (DEL-349): an outline, a call per site, the region's text and map from the
outline, and a sketched floor plan per site joined to the region map by exits."""

import asyncio
import json
import math

import pytest

from delve.dice import SeededRng
from delve.maps.dsl.validate import validate
from delve.maps.sources import parse_source
from delve.modules.books.campaign import scope_request
from delve.modules.books.generate import GenerationError, plain_name, rolled_names
from delve.modules.books.sandbox import generate_sandbox, read_outline, region_map
from delve.modules.books.sketch import map_error
from delve.modules.source import derive

REQUEST = "An open sandbox: a frontier valley with a village as home base, low on cliches, a few secrets."

OUTLINE = {
    "title": "The Sallow Reach",
    "summary": "A valley of reed and chalk where the ferry decides who eats.",
    "party": {"levels": {"min": 1, "max": 3}},
    "intro": "Wind off the chalk. Everyone owes the ferry.",
    "region": {"width": 20, "height": 14},
    "terrain": [
        {"kind": "marsh", "name": "The Soak", "points": [[2, 9], [8, 8], [9, 13], [1, 13]]},
        {"kind": "lava", "name": "Unknown kind", "points": [[12, 2], [16, 2], [14, 5]]},
        {"kind": "forest", "name": "Too few points", "points": [[1, 1], [2, 2]]},
    ],
    "rivers": [{"name": "The Lisk", "points": [[0, 6], [20, 5]]}],
    "sites": [
        {"letter": "B", "name": "The Ferry", "kind": "crossing", "at": [10, 6], "rooms": 2, "summary": "The ferry."},
        {"letter": "A", "name": "Corve", "kind": "village", "at": [3, 3], "rooms": 2, "home": True, "summary": "Home."},
    ],
    "routes": [
        {"from": "A", "to": "B", "way": "road", "miles": 2, "danger": 1, "note": "A shrine at the oak."},
        {"from": "A", "to": "Q", "way": "road", "miles": 2, "danger": 1},
    ],
    "factions": [
        {
            "id": "the-tithe",
            "name": "The Tithe-house",
            "want": "the ferry's toll",
            "summary": "Six clerks.",
            "clock": ["Doubles the toll.", "Seizes the ferry.", "Owns the valley."],
            "relations": "Hate the ferrymen.",
        },
        {
            "id": "ferrymen",
            "name": "The Ferrymen",
            "want": "to keep the ferry",
            "clock": ["Strike.", "Sink the barge."],
        },
    ],
    "npcs": [
        {
            "id": "osla",
            "name": "Osla Renn",
            "role": "ferrywoman, human",
            "site": "B",
            "summary": "Wants her barge. Secret: she drowned a clerk.",
        }
    ],
    "rumours": [
        {"text": "The ferry is cursed.", "truth": "false", "really": "It is badly kept.", "points": ["B"]},
        {
            "text": "Corve's well is sweet.",
            "truth": "true",
            "really": "True: it is the valley's best.",
            "points": ["A"],
        },
    ],
    "secrets": [
        {
            "id": "second-bell",
            "name": "The second bell",
            "strange": True,
            "truth": "A bell rings under the river.",
            "clues": [{"site": "B", "clue": "A wet bell-rope coiled in the ferry house."}],
            "unfound": "Nothing.",
        }
    ],
    "open_ground": [{"name": "The Long Meadow", "at": [15, 10], "idea": "A farmstead."}],
    "wandering": {"check": "once per leg", "table": [{"roll": "1", "result": "A clerk with a ledger"}]},
}


def site(letter: str) -> dict:
    return {
        "intro": f"Site {letter}.",
        "rooms": [
            {
                "key": "1",
                "name": "Landing",
                "read_aloud": "Mud.",
                "dm_text": f"North to {letter}2; south to the region.",
            },
            {"key": f"{letter}2", "name": "House", "read_aloud": "A house.", "dm_text": f"South to {letter}1."},
        ],
        "wandering": {"check": "1 in 6 an hour", "table": [{"roll": "1", "result": "a dog"}]} if letter == "B" else {},
        "encounters": [{"id": f"site-{letter.lower()}-dogs", "name": "Dogs"}],
    }


def sketch(letter: str) -> str:
    return f"""\
map "Site {letter}" {{
  grid {{ cell 32 px  units feet 10  bounds 30 x 20 }}
  room_numbers off
}}

room "r{letter}1" {{ rect 1,1 6 x 5  label "{letter}1. Landing" }}
room "r{letter}2" {{ rect 7,1 8 x 5  label "{letter}2. House" }}

door between room.r{letter}1 and room.r{letter}2 {{ }}
"""


class Fake:
    def __init__(self, **overrides: list[str]) -> None:
        self.overrides = {k: list(v) for k, v in overrides.items()}
        self.prompts: list[str] = []

    def kind(self, text: str) -> str:
        if "You plan an open sandbox" in text:
            return "outline"
        if "You write one place of an open sandbox" in text:
            return "site-" + text.split("keyed `")[1][0]
        if "schematic map" in text or "You draw the map of a place" in text:
            return "map-" + text.split("## The room key")[1].split('room "r')[1][0]
        if "decide how big" in text:
            return "scope"
        raise AssertionError(text[:200])

    async def __call__(self, text: str) -> str:
        self.prompts.append(text)
        kind = self.kind(text)
        if self.overrides.get(kind):
            return self.overrides[kind].pop(0)
        if kind == "outline":
            return json.dumps(OUTLINE)
        if kind.startswith("site-"):
            return json.dumps(site(kind[-1]))
        if kind.startswith("map-"):
            return f"```dmap\n{sketch(kind[-1])}```"
        return json.dumps({"scale": "sandbox", "questions": []})


def _run(fake: Fake):
    steps: list[tuple[str, int, int]] = []
    converted = asyncio.run(generate_sandbox(REQUEST, fake, lambda *s: steps.append(s), rng=SeededRng(1)))
    return converted, steps


def test_a_sandbox_has_a_region_text_and_map_and_a_text_and_floor_plan_per_site():
    converted, steps = _run(Fake())

    texts = converted.source.texts
    assert [t.title for t in texts] == ["The Sallow Reach", "A. Corve", "B. The Ferry"]
    assert [t.map for t in texts] == ["region", "site-a", "site-b"]
    assert [t.id for t in texts] == ["the-sallow-reach", "a-corve", "b-the-ferry"]
    assert [(m.name, m.is_default) for m in converted.maps] == [("region", True), ("site-a", False), ("site-b", False)]
    region = texts[0].markdown
    for heading in ("## Travel", "## Rumours", "## The factions", "## Secrets", "## Room to grow", "## On the roads"):
        assert heading in region
    assert "| 1 | The ferry is cursed. | False. It is badly kept. | B |" in region
    assert "| 2 | Corve's well is sweet. | True. It is the valley's best. | A |" in region  # no "True. True:"
    assert "| A–B | road | 7.6 mi |" in region  # never shorter than the straight line
    assert "never learn one" in region and "next free letter (C)" in region
    assert "1–3 The Tithe-house, 4–6 The Ferrymen" in region
    assert "**Ways from here:**" in texts[1].markdown and "To **B. The Ferry**" in texts[1].markdown
    derived = derive(converted.source, converted.maps)
    assert sorted(link.key for link in derived.links) == ["A1", "A2", "B1", "B2"]
    entities = converted.source.entities
    assert [n["id"] for n in entities["npcs"]] == ["osla"]
    tithe = entities["factions"][0]
    assert tithe["goals"] == ["the ferry's toll"] and tithe["clocks"][0]["segments"] == 3
    wandering = {e["id"]: e for e in entities["encounters"] if e.get("wandering")}
    assert wandering["region-wandering"]["where"] == ["map:region"]
    assert wandering["region-wandering"]["kind"] == "wilderness"
    assert wandering["site-b-wandering"]["where"] == ["map:site-b"]
    assert [s[0] for s in steps if s[1] == 0] == ["planning", "sites", "maps"]


def test_the_site_prompt_carries_its_people_its_clues_and_the_rumours_about_it():
    fake = Fake()
    _run(fake)
    ferry = next(p for p in fake.prompts if "You write one place" in p and "keyed `B1`" in p)
    assert "Osla Renn" in ferry.split("### Who is found here")[1].split("###")[0]
    assert "A wet bell-rope" in ferry and "“The ferry is cursed.” False: It is badly kept." in ferry
    corve = next(p for p in fake.prompts if "You write one place" in p and "keyed `A1`" in p)
    assert "A wet bell-rope" not in corve and "nobody named" in corve


def test_the_region_map_is_drawn_from_the_outline_and_joined_to_the_sites():
    converted, _ = _run(Fake())
    region = converted.maps[0].source
    assert map_error(region) is None
    parsed = parse_source(region)
    assert [d for d in validate(parsed) if d.severity == "error"] == []
    assert "units miles 1" in region and "bounds 20 x 14" in region
    assert 'area "the_soak_1" kind swamp' in region and "kind inlay" in region and 'slice "the_lisk_1"' in region
    assert "lava" not in region and "Too few points" not in region
    assert "line_feature" in region and region.count("corridor ") == 1  # the route to Q is dropped
    assert 'to "site-a"' in region and 'to "site-b"' in region
    assert "line_style dotted" in region and "size 0.4" not in region  # the routes dotted, the exits unlabelled
    assert 'label "The Soak" at ' in region
    for name in ("site-a", "site-b"):
        assert 'to "region"' in next(m.source for m in converted.maps if m.name == name)


def test_a_site_that_cant_be_read_is_left_out_and_the_others_stand():
    converted, _ = _run(Fake(**{"site-B": ["nope", "still nope"]}))
    assert [t.title for t in converted.source.texts] == ["The Sallow Reach", "A. Corve"]
    assert any(w.code == "site-not-written" for w in converted.warnings)


def test_an_outline_that_cant_be_read_twice_fails():
    with pytest.raises(GenerationError, match="outlined"):
        _run(Fake(outline=["nope", "nope"]))


def test_the_outline_keeps_one_home_and_clamps_the_points():
    raw = OUTLINE | {
        "sites": [
            {"letter": "A", "name": "One", "at": [-5, 99], "home": True},
            {"letter": "B", "name": "Two", "at": [4, 4], "home": True},
        ]
    }
    outline = read_outline(json.dumps(raw))
    assert [s.home for s in outline.sites] == [True, False]
    assert outline.sites[0].at == (0.0, 14.0)
    assert map_error(region_map(outline)) is None


def test_a_sandbox_request_is_scoped_as_one():
    async def answer(_: str) -> str:
        return json.dumps({"scale": "sandbox", "questions": []})

    assert asyncio.run(scope_request(REQUEST, answer)).scale == "sandbox"


def test_monster_names_lose_their_stock_epithets():
    assert plain_name("bugbear", "Drush Hide-Wearer") == "Drush"
    assert plain_name("halforc", "Krang the Cleaver") == "Krang"
    assert plain_name("human", "Garrick Whitmore") == "Garrick Whitmore"
    rolled = rolled_names(SeededRng(3))
    assert all(" " not in name for race in ("goblin", "bugbear", "orc", "halforc") for name in rolled[race])


def test_site_maps_are_designed_for_their_kind_not_sketched_as_a_schematic():
    fake = Fake()
    _run(fake)
    maps = [p for p in fake.prompts if "You draw the map of a place" in p]
    assert len(maps) == 2 and not any("schematic map" in p for p in fake.prompts)
    corve = next(p for p in maps if 'room "rA' in p.split("## The room key")[1])
    assert "An outdoor site and its buildings: A. Corve, a village." in corve
    ferry = next(p for p in maps if 'room "rB' in p.split("## The room key")[1])
    assert "A place: B. The Ferry, a crossing." not in ferry or "outdoor" in ferry  # a crossing is outdoors
    assert "Shapes follow what the room is" in corve


def test_the_exit_into_a_site_lands_below_its_first_rooms_label():
    converted, _ = _run(Fake())
    site_a = next(m.source for m in converted.maps if m.name == "site-a")
    # rA1 is rect 1,1 6 x 5: its centre is 4,3.5; a small room, so the exit is halfway to its bottom wall.
    assert "exit at 4,4.75 {" in site_a and 'to "site-a" at 4,4.75' in converted.maps[0].source


def test_open_ground_moves_off_the_sites_and_rivers_and_river_names_are_placed():
    raw = OUTLINE | {"open_ground": [{"name": "On the ferry", "at": [10, 6], "idea": "x"}]}
    outline = read_outline(json.dumps(raw))
    ground = outline.open_ground[0]["at"]
    assert ground != (10.0, 6.0) and math.dist(ground, (10, 6)) > 3
    source = region_map(outline)
    assert 'label "The Lisk" at ' in source and " rotate " in source


def test_a_label_placed_on_a_feature_is_let_free():
    from delve.modules.books.sketch import free_labels

    source = """\
include "core.dmap"
map "Hut" {
  grid { cell 32 px  units feet 10  bounds 20 x 20 }
  room_numbers off
}
room "rA1" {
  rect 1,1 8 x 6
  label "A1. Hut" at 5,4
  feature stairs-down at 5,4
}
"""
    freed = free_labels(source)
    assert '  label "A1. Hut"\n' in freed and "feature stairs-down at 5,4" in freed
    assert free_labels("not a map") == "not a map"


@pytest.mark.parametrize("calls", [("site-A", "site-B"), ("map-A", "map-B")])
def test_a_failed_call_stops_the_others_at_once(calls):
    """A provider's failure fails the job, and the calls still running stop with it."""
    first, second = calls
    fake = Fake()
    answer = Fake.__call__
    state = {"cancelled": False}
    asked = asyncio.Event()

    async def broken(text: str) -> str:
        kind = fake.kind(text)
        if kind == second:
            asked.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise
        if kind == first:
            await asked.wait()
            raise RuntimeError("claude stopped (exit code 1): API Error: 529 Overloaded")
        return await answer(fake, text)

    async def scenario():
        with pytest.raises(RuntimeError, match="Overloaded"):
            await generate_sandbox(REQUEST, broken, lambda *s: None, rng=SeededRng(1))
        return state["cancelled"]  # before `asyncio.run` cancels what is left

    assert asyncio.run(scenario())
