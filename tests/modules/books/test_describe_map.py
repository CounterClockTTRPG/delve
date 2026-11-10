"""Dungeon maps drawn by Claude (plan 7 Task 13): from a description (`describe_map`), and from the book's own map page
through the vision call (`draw_from_page`). Both parse the answer and ask once more on an error, as `sketch_map`
does."""

import asyncio
import io

from PIL import Image

from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice
from delve.maps.vision import VISION_MAX_SIDE
from delve.modules.books.sketch import (
    DESCRIBED,
    DSL_REFERENCE,
    FROM_BOOK,
    Part,
    describe_map,
    draw_from_page,
    prompt,
)
from delve.modules.source import Warning
from tests.modules.books.test_sketch import BROKEN, GOOD, KEYED, Scripted

CAVES = Part("caves", "The Kobold Caves", [(key, text.splitlines()[0].lstrip("# ")) for key, text in KEYED])
DESCRIPTION = "A kobold warren: an entrance, a long hall, and a shrine to a dragon at the back."


def _page(width=2000, height=1400) -> bytes:
    """A map page as the conversion stores it: a PNG, larger than a vision call takes."""
    out = io.BytesIO()
    Image.new("RGB", (width, height), (240, 236, 220)).save(out, "PNG")
    return out.getvalue()


def _look(dm: FakeDM):
    async def look(text: str, image: bytes, media_type: str) -> str:
        return await dm.vision_call(text, image, media_type, BackendChoice("fake", "fake-large"))

    return look


def test_the_headers_name_how_a_map_was_drawn():
    assert DESCRIBED == "# Drawn from a description."
    assert FROM_BOOK == "# Drawn from the book's map"


def test_a_described_map_that_parses_is_kept_with_its_warning():
    complete = Scripted(f"```dmap\n{GOOD}```")

    source, warnings = asyncio.run(describe_map("warren", DESCRIPTION, [], complete))

    assert source == GOOD
    assert warnings == [Warning("map-described", "Drawn from a description: an invented layout.", "map:warren")]
    [sent] = complete.prompts
    assert DESCRIPTION in sent and DSL_REFERENCE in sent
    assert "has no room key" in sent


def test_the_keyed_rooms_go_in_the_prompt_as_r_key():
    complete = Scripted(GOOD)

    asyncio.run(describe_map("warren", DESCRIPTION, KEYED, complete))

    [sent] = complete.prompts
    assert 'room "r1", label "1. Entrance"' in sent
    assert 'room "rC3", label "C3. Shrine"' in sent
    for _, text in KEYED:
        assert text in sent


def test_a_described_map_is_retried_once_then_not_drawn():
    complete = Scripted(BROKEN, GOOD)
    source, warnings = asyncio.run(describe_map("warren", DESCRIPTION, KEYED, complete))
    assert source == GOOD and [w.code for w in warnings] == ["map-described"]
    first, second = complete.prompts
    assert second.startswith(first) and "line 7" in second

    complete = Scripted(BROKEN, BROKEN)
    source, warnings = asyncio.run(describe_map("warren", DESCRIPTION, KEYED, complete))
    assert source is None
    [warning] = warnings
    assert warning.code == "map-not-drawn" and warning.ref == "map:warren"
    assert warning.message.startswith("The map couldn't be drawn from the description: ")
    assert len(complete.prompts) == 2


def test_a_page_is_sent_through_look_as_one_png():
    dm = FakeDM([], vision_handler=lambda text, image, media_type: f"```dmap\n{GOOD}```")

    [level], warnings = asyncio.run(draw_from_page("caves", _page(), "image/png", [CAVES], _look(dm)))

    assert (level.name, level.source, level.part) == ("caves", GOOD, "caves")
    assert warnings == [
        Warning("map-from-book", "Drawn by Claude from the book's map: compare it with the page.", "map:caves")
    ]
    [(media_type, size)] = dm.vision_images
    assert media_type == "image/png" and size > 0
    [sent] = dm.vision_prompts
    assert 'room "r2", label "2. Hall"' in sent and DSL_REFERENCE in sent


def test_the_page_is_fitted_for_vision():
    seen: list[bytes] = []

    def handler(text, image, media_type):
        seen.append(image)
        return GOOD

    dm = FakeDM([], vision_handler=handler)
    asyncio.run(draw_from_page("caves", _page(3000, 1000), "image/png", [CAVES], _look(dm)))

    with Image.open(io.BytesIO(seen[0])) as sent:
        assert sent.format == "PNG" and max(sent.size) == VISION_MAX_SIDE


def test_a_page_map_is_retried_once_with_the_page_again_then_not_drawn():
    answers = [BROKEN, BROKEN]
    dm = FakeDM([], vision_handler=lambda text, image, media_type: answers.pop(0))

    levels, warnings = asyncio.run(draw_from_page("caves", _page(), "image/png", [CAVES], _look(dm)))

    assert levels == []
    [warning] = warnings
    assert warning.code == "map-not-drawn"
    assert warning.message.startswith("The map couldn't be drawn from the book's map: ")
    assert len(dm.vision_images) == 2
    first, second = dm.vision_prompts
    assert second.startswith(first) and "line 7" in second


def test_the_new_prompts_are_package_files():
    for name in ("describe-map.md", "book-map.md"):
        text = prompt(name)
        assert "{{reference}}" in text and "{{name}}" in text
    assert "{{description}}" in prompt("describe-map.md") and "{{rooms}}" in prompt("describe-map.md")
    assert "{{parts}}" in prompt("book-map.md")
