"""Keyed text conventions (§5.2) and the module converter."""
from __future__ import annotations

from delve.modules.dscn import add_anchors, parse_text, refs_in_markdown
from delve.modules.dscn.text import parse_heading

DOC = """---
title: Level 1
audience: gm
---

# Level one

## W101. Dwarven Guard Post {#w101}

> Two stone benches flank a narrow arrow slit.
>
> The air smells of old pipe smoke.

> A second quote straight after still counts.

The sergeant ([[npc:dwarf-sergeant]]) is a ghost.

> A later quote is just a quote.

#### Treasure

40 gp in a loose stone.

## W102: Guardroom

No read-aloud here.

## Dr. Who's lair

Not keyed: "Dr" has no digit.

```
## W999. Inside a fence — not a heading
```

## Note: also not keyed
"""


def test_front_matter_and_sections():
    doc = parse_text(DOC)
    assert doc.front_matter == {"title": "Level 1", "audience": "gm"}
    assert [s.key for s in doc.keyed()] == ["W101", "W102"]
    w101 = doc.section("w101")
    assert w101.title == "Dwarven Guard Post" and w101.explicit_anchor
    assert "Two stone benches" in w101.read_aloud and "second quote" in w101.read_aloud
    assert "later quote" not in w101.read_aloud
    assert "later quote" in w101.gm_md and "40 gp" in w101.gm_md  # sub-heading belongs
    w102 = doc.section("w102")
    assert w102.read_aloud == "" and not w102.explicit_anchor
    assert doc.section("w999") is None  # fenced
    assert w101.line == 8  # 1-based, counting the front matter


def test_level_one_heading_is_a_title_not_a_key():
    doc = parse_text("# WGR1: Greyhawk Ruins\n\n## W101. Guard Post\n")
    assert [s.key for s in doc.keyed()] == ["W101"]
    assert add_anchors("# WGR1: Greyhawk Ruins\n")[1] == 0


def test_duplicate_anchor_is_an_error():
    doc = parse_text("## A1. x {#a}\n\n## A2. y {#a}\n")
    assert doc.errors and "duplicate anchor #a" in doc.errors[0][1]


def test_refs_in_markdown():
    md = "See [the sergeant](npc:dwarf) and [[faction:iuz]] ![](asset:pic) [web](https://x.y)"
    assert refs_in_markdown(md) == ["npc:dwarf", "faction:iuz", "asset:pic"]


def test_add_anchors_converts_module_headings():
    src = (
        "# Tower\n\n### W101. Dwarven Guard Post\n\ntext\n\n"
        "### W103. Records Chest *(locked)*\n\n"
        "## Players' Background (read aloud)\n\nLong ago...\n\nAnd then.\n\n## Rumours\n\n- x\n"
    )
    out, n = add_anchors(src)
    assert n == 2
    assert "### W101. Dwarven Guard Post {#w101}" in out
    assert "### W103. Records Chest *(locked)* {#w103}" in out
    assert "> Long ago..." in out and "> And then." in out
    assert "- x" in out and "> - x" not in out  # stops at the next heading
    doc = parse_text(out)
    assert "Long ago" in doc.sections[3].read_aloud
    # Idempotent: a second pass adds nothing.
    assert add_anchors(out) == (out, 0)


def test_a_bare_key_heading_is_keyed_and_a_word_with_a_colon_is_not():
    """Plateau 7 Task 20: "## 31." is the room 31 with an empty title; the digit guard keeps "## Treasure:" and
    "## Epilogue." unkeyed."""
    assert parse_heading("31.")[2:] == ("31", "")
    assert parse_heading("C3:")[2:] == ("C3", "")
    assert parse_heading("31. The Well")[2:] == ("31", "The Well")
    for raw in ("Treasure:", "Epilogue.", "Note: also not keyed", "31.5 gp"):
        assert parse_heading(raw)[2] is None, raw
    doc = parse_text("## 31.\n\nA bare room.\n\n## Treasure:\n\n40 gp.\n")
    assert [(s.key, s.title) for s in doc.keyed()] == [("31", "")]


def test_a_heading_with_a_long_run_of_spaces_parses_in_linear_time():
    """The heading pattern took cubic time on a run of spaces: 2,000 of them held an import for 8 s (DEL-152, audit
    finding 4). Now 50,000 take a moment, and the heading reads as before."""
    import time

    start = time.monotonic()
    doc = parse_text(f"## W1.{' ' * 50_000}x\n\n## A2. Title {' ' * 50_000}#\n\n## Note{' ' * 50_000}\n")
    assert time.monotonic() - start < 1.0
    assert [(s.key, s.title) for s in doc.sections] == [("W1", "x"), ("A2", "Title"), (None, "Note")]


def test_closing_hashes_and_spaces_leave_a_heading_as_before():
    doc = parse_text("## W101. Guard Post ##  \n\n### C#\n\n## Title # #\n")
    assert [s.heading for s in doc.sections] == ["W101. Guard Post", "C", "Title #"]


def test_front_matter_with_yaml_aliases_is_ignored():
    """An alias can make a few hundred bytes of YAML into gigabytes (DEL-152, audit finding 5)."""
    doc = parse_text("---\na: &a [x, x]\nb: [*a, *a]\n---\n\n# T\n")
    assert doc.front_matter == {}
