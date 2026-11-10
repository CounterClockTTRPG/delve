"""Map sketches (plateau 5 Task 3): a map in the map language from a room key, parsed by Delve and retried once."""

import asyncio
import io
from importlib import resources
from pathlib import Path

from PIL import Image

from delve.domain.modules import ModuleMap
from delve.modules.books.sketch import DSL_REFERENCE, Part, draw_from_page, dsl_reference, prompt, sketch_map
from delve.modules.source import ModuleSource, TextDoc, Warning, derive

DOCS = Path(__file__).resolve().parents[3] / "docs" / "maps"

KEYED = [
    ("1", "## 1. Entrance\n\nWorn steps lead down into the dark. A door to the east opens on the hall (area 2)."),
    ("2", "## 2. Hall\n\nA long hall. The entrance is to the west; a passage south leads to the shrine (area C3)."),
    ("C3", "## C3. Shrine\n\nA kobold shrine to a dragon. The only way out is north, back to the hall."),
]

GOOD = """\
map "Kobold Caves" {
  grid { cell 32 px  units feet 10  bounds 30 x 20 }
  room_numbers off
}

room "r1" { rect 1,1 6 x 5  label "1. Entrance" }
room "r2" { rect 7,1 8 x 5  label "2. Hall" }
room "rC3" { rect 7,6 8 x 6  label "C3. Shrine" }

door between room.r1 and room.r2 { }
door between room.r2 and room.rC3 { }
"""

BROKEN = GOOD.replace('room "r2" { rect 7,1 8 x 5', 'room "r2" { rect 7,1 8 x')
"""Line 7 doesn't parse: a rect without its height."""

UNKNOWN_ROOM = GOOD.replace("door between room.r2 and room.rC3 { }", "door at 11,6 { connects room.r9 }")
"""Parses, but a door names a room that isn't there: an error of the map's own validation."""


class Scripted:
    """A `complete` that answers from a script and records its prompts."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def __call__(self, text: str) -> str:
        self.prompts.append(text)
        return self.answers.pop(0)


def _sketch(complete: Scripted, **kw) -> tuple[str | None, list[Warning]]:
    return asyncio.run(sketch_map("caves", KEYED, complete, **kw))


def test_a_sketch_that_parses_is_kept_with_its_warning():
    complete = Scripted(f"Here is the map:\n\n```dmap\n{GOOD}```\n")

    source, warnings = _sketch(complete, page=7)

    assert source == GOOD
    assert warnings == [
        Warning("map-sketched", "Sketched from the room key: an invented layout; compare it with page 7.", "map:caves")
    ]
    [sent] = complete.prompts
    for key, text in KEYED:
        assert text in sent
    assert 'room "rC3"' in sent and 'label "C3. Shrine"' in sent
    assert DSL_REFERENCE in sent
    # The rooms link by themselves: their labels are the headings.
    doc = TextDoc("key", "Key", "gm", None, "\n\n".join(text for _, text in KEYED) + "\n")
    derived = derive(ModuleSource(texts=[doc]), [ModuleMap("caves", "map", source, True)])
    assert sorted(link.node for link in derived.links) == ["room.r1", "room.r2", "room.rC3"]


def test_without_a_page_the_warning_names_none():
    _, warnings = _sketch(Scripted(GOOD))
    assert warnings == [Warning("map-sketched", "Sketched from the room key: an invented layout.", "map:caves")]


def test_a_sketch_is_retried_once_with_the_parse_error():
    complete = Scripted(BROKEN, GOOD)

    source, warnings = _sketch(complete)

    assert source == GOOD
    assert [w.code for w in warnings] == ["map-sketched"]
    first, second = complete.prompts
    assert second.startswith(first)
    assert BROKEN in second
    assert "line 7" in second
    assert 'room "r2" { rect 7,1 8 x  label "2. Hall" }' in second


def test_a_map_its_own_validation_refuses_is_retried_too():
    complete = Scripted(UNKNOWN_ROOM, GOOD)
    source, _ = _sketch(complete)
    assert source == GOOD
    assert "r9" in complete.prompts[1]


def test_a_sketch_that_never_parses_is_a_warning():
    complete = Scripted("I can't draw this map from the text alone.", BROKEN)

    source, warnings = _sketch(complete, page=3)

    assert source is None
    [warning] = warnings
    assert warning.code == "map-not-drawn"
    assert warning.ref == "map:caves"
    assert warning.message.startswith("The map couldn't be drawn from the room key: ")
    assert "line 7" in warning.message
    assert len(complete.prompts) == 2


def test_no_keyed_rooms_no_sketch():
    complete = Scripted()
    assert asyncio.run(sketch_map("caves", [], complete)) == (None, [])
    assert complete.prompts == []


def test_an_include_is_only_a_built_in_library():
    """Claude's map can't read a file: an include that isn't a built-in library doesn't parse."""
    reads_a_file = 'include "/etc/hostname"\n' + GOOD
    source, warnings = _sketch(Scripted(reads_a_file, reads_a_file))
    assert source is None and [w.code for w in warnings] == ["map-not-drawn"]


def test_the_dsl_reference_is_current():
    """`prompts/dsl-reference.md` is built from docs/maps/; `make dsl-reference` rebuilds it."""
    assert DSL_REFERENCE == dsl_reference(DOCS), "prompts/dsl-reference.md is stale: run `make dsl-reference`"
    assert "## `room`" in DSL_REFERENCE and "## `door`" in DSL_REFERENCE
    assert "Ported from" not in DSL_REFERENCE and "](/docs/" not in DSL_REFERENCE


def test_the_prompts_are_package_files():
    books = resources.files("delve.modules.books")
    for name in ("sketch.md", "generate.md", "dsl-reference.md"):
        assert books.joinpath("prompts", name).is_file()
    assert "{{reference}}" in prompt("sketch.md") and "{{reference}}" in prompt("generate.md")


# ----- a page of the book, one map per level (faithful modules Task 4) -----

GROUND = """\
# level: Ground floor
# part: house
map "Ground floor" {
  grid { cell 32 px  units feet 5  bounds 30 x 20 }
  room_numbers off
}

room "r1" { rect 1,1 6 x 5  label "1. Kitchen"
  exit at 3,3 { to "house-2" at 2,2 }
}
room "r2" { rect 7,1 8 x 5  label "2. Dining Room" }

door between room.r1 and room.r2 { }
"""
CELLAR = """\
# level: Cellar
# part: house
map "Cellar" {
  grid { cell 32 px  units feet 5  bounds 30 x 20 }
  room_numbers off
}

room "r18" { rect 1,1 6 x 5  label "18. Cellar"
  exit at 2,2 { to "house-1" at 3,3 }
}
"""
HOUSE = Part("house", "The Haunted House", [("1", "1. Kitchen"), ("2", "2. Dining Room"), ("18", "18. Cellar")])
SHIP = Part("ship", "The Sea Ghost", [("1", "1. Main Deck")])


def _picture() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), (240, 236, 220)).save(out, "PNG")
    return out.getvalue()


class Looking:
    """A `look` that answers from a script and records its prompts and pictures."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.images: list[tuple[bytes, str]] = []

    async def __call__(self, text: str, image: bytes, media_type: str) -> str:
        self.prompts.append(text)
        self.images.append((image, media_type))
        return self.answers.pop(0)


def _draw(look: Looking, parts=(HOUSE, SHIP)):
    return asyncio.run(draw_from_page("house", _picture(), "image/png", list(parts), look))


def _blocks(*levels: str) -> str:
    return "Here are the levels.\n\n" + "\n".join(f"```dmap\n{level}```\n" for level in levels)


def test_draw_from_page_reads_two_levels():
    look = Looking(_blocks(GROUND, CELLAR))

    levels, warnings = _draw(look)

    assert [(lv.name, lv.title, lv.part) for lv in levels] == [
        ("house-ground-floor", "Ground floor", "house"),
        ("house-cellar", "Cellar", "house"),
    ]
    ground, cellar = levels
    assert 'to "house-cellar" at 2,2' in ground.source and 'to "house-ground-floor" at 3,3' in cellar.source
    assert "# level:" not in ground.source and "# part:" not in ground.source
    assert [w.code for w in warnings] == ["map-from-book"]
    [sent] = look.prompts
    assert "house" in sent and 'room "r18", label "18. Cellar"' in sent and 'room "r1", label "1. Main Deck"' in sent
    assert DSL_REFERENCE in sent
    [(image, media_type)] = look.images
    assert media_type == "image/png" and image


def test_draw_from_page_keeps_the_scale():
    levels, _ = _draw(Looking(_blocks(CELLAR)))
    [cellar] = levels
    assert "units feet 5" in cellar.source
    assert cellar.name == "house", "a page of one level is the map itself"


def test_a_not_connected_level_is_warned():
    _, warnings = _draw(Looking(_blocks(GROUND.replace("door between room.r1 and room.r2 { }\n", ""), CELLAR)))
    [warning] = [w for w in warnings if w.code == "map-warning"]
    assert warning.ref == "map:house-ground-floor" and "not connected" in warning.message


def test_a_level_with_a_bad_part_has_none():
    levels, warnings = _draw(Looking(_blocks(GROUND, CELLAR.replace("# part: house", "# part: castle"))))
    assert [lv.part for lv in levels] == ["house", None]
    [no_part] = [w for w in warnings if w.code == "map-no-part"]
    assert no_part.ref == "map:house-cellar"


def test_one_part_given_is_every_levels_part():
    levels, warnings = _draw(Looking(f"```dmap\n{GOOD}```"), parts=[HOUSE])
    assert [(lv.name, lv.part) for lv in levels] == [("house", "house")]
    assert [w.code for w in warnings] == ["map-from-book"]


def test_a_broken_level_is_asked_for_again_with_every_error():
    look = Looking(_blocks(GROUND, BROKEN), _blocks(GROUND, CELLAR))

    levels, _ = _draw(look)

    assert [lv.name for lv in levels] == ["house-ground-floor", "house-cellar"]
    first, second = look.prompts
    assert second.startswith(first) and "line 7" in second
    assert len(look.images) == 2, "the retry sends the page again"


def test_a_level_still_broken_is_left_out_and_none_drawn_is_a_warning():
    levels, warnings = _draw(Looking(_blocks(GROUND, BROKEN), _blocks(GROUND, BROKEN)))
    assert [lv.name for lv in levels] == ["house-ground-floor"]
    assert "map-not-drawn" in [w.code for w in warnings]

    levels, warnings = _draw(Looking("I can't read this page.", BROKEN))
    assert levels == []
    [warning] = warnings
    assert warning.code == "map-not-drawn" and warning.ref == "map:house"
    assert warning.message.startswith("The map couldn't be drawn from the book's map: ")
