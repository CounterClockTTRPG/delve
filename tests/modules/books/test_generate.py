"""Generating a module from a request (plateau 5 Task 3): a JSON plan, a sketched map, one keyed text and entities."""

import asyncio
import json

import pytest

from delve.dice import SeededRng
from delve.modules.books.convert import Converted
from delve.modules.books.generate import MAP_NAME, GenerationError, generate_module, rolled_names
from delve.modules.books.sketch import DSL_REFERENCE, prompt
from delve.modules.dscn import parse_text, slugify
from delve.modules.source import derive
from delve.rules.classic.names import RACES
from tests.modules.books.test_sketch import GOOD, Scripted

REQUEST = "A small dungeon with kobolds, no plot. A bit of treasure."

PLAN = {
    "title": "The Kobold Caves",
    "summary": "Kobolds have dug in under the old mill.",
    "rooms": [
        {
            "key": "1",
            "name": "Entrance",
            "read_aloud": "Worn steps lead down into the dark.",
            "dm_text": "A door to the east opens on the hall (area 2).",
            "monsters": "",
            "treasure": "",
        },
        {
            "key": "2",
            "name": "Hall",
            "read_aloud": "A long hall, smelling of wet dog.",
            "dm_text": "The entrance is west; a passage south leads to the shrine (area C3).",
            "monsters": "6 kobolds",
            "treasure": "",
        },
        {
            "key": "C3",
            "name": "Shrine",
            "read_aloud": "A crude altar to a dragon.",
            "dm_text": "The only way out is north.",
            "monsters": ["Grik, the kobold chief", "2 kobolds"],
            "treasure": "A pouch of 40 sp under the altar.",
        },
    ],
    "npcs": [{"id": "grik", "name": "Grik", "role": "kobold chief", "location": "map:map#room.rC3"}],
    "encounters": [{"id": "hall-guards", "name": "Hall guards", "fixed": [{"creature": "monster:kobold", "count": 6}]}],
}


def _generate(complete: Scripted) -> tuple[Converted, list[tuple[str, int, int]]]:
    steps: list[tuple[str, int, int]] = []
    converted = asyncio.run(generate_module(REQUEST, complete, lambda *step: steps.append(step)))
    return converted, steps


def test_a_generated_module_links_its_rooms():
    complete = Scripted(f"```json\n{json.dumps(PLAN)}\n```", GOOD)

    converted, steps = _generate(complete)

    [text] = converted.source.texts
    assert (text.id, text.title, text.audience, text.map) == ("the-kobold-caves", "The Kobold Caves", "gm", None)
    [map_] = converted.maps
    assert (map_.name, map_.role, map_.source, map_.is_default) == (MAP_NAME, "map", GOOD, True)
    derived = derive(converted.source, converted.maps)
    assert sorted((link.key, link.node) for link in derived.links) == [
        ("1", "room.r1"),
        ("2", "room.r2"),
        ("C3", "room.rC3"),
    ]
    assert not [w for w in derived.warnings if w.code in ("key-without-room", "room-without-text")]
    assert [w.code for w in converted.warnings] == ["map-sketched"]
    assert converted.pictures == []
    assert steps == [("generating", 0, 1), ("generating", 1, 1), ("maps", 0, 1), ("maps", 1, 1)]

    plan_prompt, sketch_prompt = complete.prompts
    assert REQUEST in plan_prompt and DSL_REFERENCE in plan_prompt
    assert "## C3. Shrine" in sketch_prompt and "The only way out is north." in sketch_prompt


def test_the_plan_becomes_one_keyed_text_and_its_entities():
    converted, _ = _generate(Scripted(json.dumps(PLAN), GOOD))

    [text] = converted.source.texts
    doc = parse_text(text.markdown)
    assert doc.sections[0].heading == "The Kobold Caves"
    assert "Kobolds have dug in under the old mill." in text.markdown
    shrine = doc.section("c3")
    assert shrine is not None and shrine.explicit_anchor
    assert shrine.read_aloud == "A crude altar to a dragon."
    assert "Grik, the kobold chief" in shrine.gm_md and "A pouch of 40 sp under the altar." in shrine.gm_md
    assert [s.key for s in doc.keyed()] == ["1", "2", "C3"]
    assert converted.source.entities == {"npcs": PLAN["npcs"], "encounters": PLAN["encounters"]}


def test_a_generated_modules_dangling_refs_are_dropped():
    """Faithful modules Task 1: a ref the plan makes to nothing is dropped with a warning; one to the sketched map's
    room stays."""
    npcs = [PLAN["npcs"][0] | {"faction": "faction:kobolds"}]
    converted, _ = _generate(Scripted(json.dumps(PLAN | {"npcs": npcs}), GOOD))

    assert converted.source.entities["npcs"] == PLAN["npcs"]
    assert [(w.code, w.ref) for w in converted.warnings if w.code.startswith("ref-")] == [
        ("ref-dropped", "faction:kobolds")
    ]


def test_invalid_entities_are_dropped_with_a_warning():
    plan = PLAN | {
        "npcs": [{"name": "Grik"}, {"id": "BAD ID", "name": ""}],
        "encounters": "a few kobolds",
    }
    converted, _ = _generate(Scripted(json.dumps(plan), GOOD))

    assert converted.source.entities == {"npcs": [{"id": "grik", "name": "Grik"}]}
    dropped = [w for w in converted.warnings if w.code == "entity-dropped"]
    assert len(dropped) == 2
    assert any(w.ref == "npcs" for w in dropped)
    assert any(w.ref == "encounters" for w in dropped)


def test_a_plan_read_on_the_retry_is_used():
    complete = Scripted("Sure! Here's a fun dungeon.", json.dumps(PLAN), GOOD)

    converted, _ = _generate(complete)

    assert converted.source.texts[0].title == "The Kobold Caves"
    first, second = complete.prompts[:2]
    assert second.startswith(first) and "isn't JSON" in second


def test_an_unreadable_plan_fails_after_one_retry():
    complete = Scripted("not json at all", json.dumps({"title": "Empty", "rooms": []}))

    with pytest.raises(GenerationError) as raised:
        _generate(complete)

    assert str(raised.value) == "The module couldn't be generated: the plan has no rooms."
    assert len(complete.prompts) == 2
    assert "isn't JSON" in complete.prompts[1]


@pytest.mark.parametrize(
    ("rooms", "reason"),
    [
        ([{"key": "1"}], "room 1 has no name"),
        ([{"key": "Hall", "name": "Hall"}], "the key “Hall” isn't a room key"),
        ([{"key": "1", "name": "A"}, {"key": "1", "name": "B"}], "two rooms have the key 1"),
    ],
)
def test_a_plan_with_bad_rooms_is_refused(rooms, reason):
    bad = json.dumps(PLAN | {"rooms": rooms})
    with pytest.raises(GenerationError, match=reason):
        _generate(Scripted(bad, bad))


def test_a_map_that_is_not_drawn_still_gives_the_module():
    converted, _ = _generate(Scripted(json.dumps(PLAN), "no map", "still no map"))

    assert converted.maps == []
    assert [s.key for s in parse_text(converted.source.texts[0].markdown).keyed()] == ["1", "2", "C3"]
    assert [w.code for w in converted.warnings] == ["map-not-drawn", "ref-rewritten"]
    assert converted.source.entities["npcs"][0]["location"] == "text:the-kobold-caves#c3"


@pytest.mark.parametrize(("title", "id"), [("???", "text"), ("_Secret Lair", "secret-lair"), ("-.Pit", "pit")])
def test_the_text_id_is_a_good_id(title, id):
    converted, _ = _generate(Scripted(json.dumps(PLAN | {"title": title}), GOOD))

    assert converted.source.texts[0].id == id


def test_records_marked_for_the_players_are_a_warning():
    npcs = [{"id": "grik", "name": "Grik", "audience": "player"}, {"id": "snik", "name": "Snik", "audience": "gm"}]
    converted, _ = _generate(Scripted(json.dumps(PLAN | {"npcs": npcs}), GOOD))

    [marked] = [w for w in converted.warnings if w.code == "audience-player"]
    assert (marked.ref, marked.message) == ("npc:grik", "Marked for the players by the conversion; check it.")


def test_generate_writes_party_size_and_levels():
    """C11: the party the request asks for goes into the module's manifest; a request that says none leaves it out."""
    party = {"size": {"min": 4, "max": 6}, "levels": {"min": 1, "max": 3}, "notes": "needs a cleric"}
    converted, _ = _generate(Scripted(json.dumps(PLAN | {"party": party}), GOOD))
    assert converted.metadata == {"party": party}

    converted, _ = _generate(Scripted(json.dumps(PLAN | {"party": {"size": 5, "levels": "low"}}), GOOD))
    assert converted.metadata == {"party": {"size": 5}}

    for none in ({}, {"party": {}}, {"party": "a few"}):
        converted, _ = _generate(Scripted(json.dumps(PLAN | none), GOOD))
        assert converted.metadata == {}
    complete = Scripted(json.dumps(PLAN), GOOD)
    _generate(complete)
    assert '"party": {"size"' in complete.prompts[0]


def test_generate_names_come_from_the_rolled_list():
    """Every person is named from 12 names rolled per race, so a generated module has no stock names."""
    rolled = rolled_names(SeededRng(7))
    assert set(rolled) == set(RACES) and all(len(names) == 12 for names in rolled.values())
    assert rolled == rolled_names(SeededRng(7))
    name = rolled["kobold"][0]
    plan = PLAN | {"npcs": [{"id": slugify(name), "name": name, "role": "kobold chief"}]}
    complete = Scripted(json.dumps(plan), GOOD)

    converted = asyncio.run(generate_module(REQUEST, complete, lambda *step: None, rng=SeededRng(7)))

    prompt = complete.prompts[0]
    for race, names in rolled.items():
        assert f"- {race}: {', '.join(names)}" in prompt
    assert "named from these lists" in prompt
    assert [npc["name"] for npc in converted.source.entities["npcs"]] == [name]


def test_the_plans_questions_are_read_and_kept_out_of_the_plan():
    asked = [{"text": "Should Grik bargain?", "default": "He bargains for his life."}]
    answer = f"```json\n{json.dumps(PLAN)}\n```\n\n```questions\n{json.dumps(asked)}\n```"

    converted, _ = _generate(Scripted(answer, GOOD))

    assert [(q.id, q.text, q.default) for q in converted.questions] == [
        ("q1", "Should Grik bargain?", "He bargains for his life.")
    ]
    assert converted.source.texts[0].title == "The Kobold Caves"


def test_an_unfenced_plan_with_questions_is_read():
    asked = [{"text": "Is the mill haunted?", "default": "No."}]
    answer = f"{json.dumps(PLAN)}\n\n```questions\n{json.dumps(asked)}\n```"
    converted, _ = _generate(Scripted(answer, GOOD))
    assert [q.text for q in converted.questions] == ["Is the mill haunted?"]
    assert "```questions" in prompt("generate.md")
