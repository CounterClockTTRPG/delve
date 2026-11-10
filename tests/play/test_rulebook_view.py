"""`play.rulebook`: the reader's view of a ruleset's book. Monsters only for organisers, the campaign's homebrew items,
classes and races beside the book's, and a house rule's DM notes cut for everyone else (rulesets spec, decisions 3, 6
and 9), over OSRIC's book. The tests that need a book without races (AD&D 2e's) are in the 2e pack's copy of this
file."""

import pytest

from delve.config import Config
from delve.domain.reference import Section
from delve.play.context import NotFound
from delve.play.rulebook import RulebookView, cut_dm_notes, view_for
from delve.rules.catalog import make_ruleset
from delve.storage import open_storage
from tests.fixtures.rulesets import osric_catalogs

ITEM_BODY = (
    "## Description\n\nA ring of bone.\n\n## Mechanics\n\n- +1 to saves.\n\n## DM Notes\n\nSECRET-XYZZY: it whispers.\n"
)


@pytest.fixture
def storage(tmp_path):
    """The play storage, beside the reference's data dir rather than in it."""
    opened = open_storage(Config(data_dir=tmp_path / "play"))
    yield opened
    opened.close()


@pytest.fixture
def book():
    """OSRIC's book: any ruleset's reads the same through the view."""
    return make_ruleset("osric", osric_catalogs().rulesets).rulebook


def rule(storage, title, kind, body_md=ITEM_BODY, **options):
    return storage.house_rules.create(title=title, body_md=body_md, kind=kind, phases=["always"], **options)


def view(book, *rules, organiser=False):
    return RulebookView(book, organiser=organiser, rules=list(rules))


def keys(sections: list[Section]) -> list[str]:
    return [s.key for s in sections]


# --- monsters ------------------------------------------------------------------------------------------------------


def test_a_monster_crowds_no_one_out_of_a_readers_search(book):
    """The reader's search leaves the monsters out before it counts, so a short limit still finds the rest."""
    everything = view(book, organiser=True).search("e", 200)
    assert any(section == "monsters" for section, _, _ in everything)
    expected = [hit for hit in everything if hit[0] != "monsters"][:3]
    assert view(book).search("e", 3) == expected


# --- house rules ---------------------------------------------------------------------------------------------------


def test_house_rules_come_first_and_page_with_the_book(storage, book):
    rules = [rule(storage, title, "item") for title in ("Cutter", "Amber Eye", "Bone Ring")]
    reader = view(book, *rules)
    everything = reader.rows("items", {}, 0, 200)
    assert [r["name"] for r in everything.rows[:3]] == ["Amber Eye", "Bone Ring", "Cutter"]
    assert all(r["house_rule"] is False for r in everything.rows[3:])
    for offset, limit in ((0, 2), (2, 2), (3, 2), (1, 50), (50, 5)):
        page = reader.rows("items", {}, offset, limit)
        assert (page.total, page.offset) == (everything.total, offset)
        assert page.rows == everything.rows[offset : offset + limit]


def test_house_rules_filter_by_name(storage, book):
    ring = rule(storage, "Mortis Ring", "item")
    rule(storage, "Cutter", "item")
    reader = view(book, ring, *[r for r in storage.house_rules.list() if r.title == "Cutter"])
    found = reader.rows("items", {"q": "RING"}, 0, 50)
    assert [r["name"] for r in found.rows if r["house_rule"]] == ["Mortis Ring"]
    assert found.total == book.rows("items", {"q": "ring"}, 0, 50).total + 1
    # A facet filter the rule can't answer leaves it out; a blank one doesn't.
    assert not any(r["house_rule"] for r in reader.rows("items", {"rarity": "rare"}, 0, 50).rows)
    assert not any(r["house_rule"] for r in reader.rows("items", {"item_type": "Ring"}, 0, 50).rows)
    assert sum(r["house_rule"] for r in reader.rows("items", {"rarity": " ", "q": ""}, 0, 50).rows) == 2
    hits = [hit for hit in reader.search("mortis", 20) if hit[0] == "items"]
    assert hits[0] == ("items", f"hr-{ring.id}", "Mortis Ring")


def test_a_house_rule_entry_is_only_in_its_own_section(storage, book):
    ring = rule(storage, "Mortis Ring", "item")
    reader = view(book, ring)
    assert reader.entry("classes", f"hr-{ring.id}") is None
    assert reader.entry("spells", f"hr-{ring.id}") is None
    assert reader.entry("items", "hr-hr_000000000000") is None
    assert reader.entry("items", "hr-") is None


# --- the DM notes --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        # "## DM Notes" between two sections: up to the next heading of its level.
        (
            "## Description\n\nA ring.\n\n## DM Notes\n\nSECRET-XYZZY\n\n## Rarity and Value\n\nRare.\n",
            "## Description\n\nA ring.\n\n## Rarity and Value\n\nRare.\n",
        ),
        # "## DM Notes" as the last section: to the end.
        ("## Description\n\nA ring.\n\n## DM Notes\n\nSECRET-XYZZY\n", "## Description\n\nA ring.\n"),
        # Spelled in other cases.
        ("Intro.\n\n## DM notes\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n## dm NOTES\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n## DM NOTES ##\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n## DM Notes:\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n##   DM   Notes  \n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n   ## DM Notes\n\nSECRET-XYZZY\n", "Intro.\n"),
        # At another level, under another heading: up to the next heading of its level or higher.
        (
            (
                "## Mechanics\n\n- +1.\n\n### DM Notes\n\nSECRET-XYZZY\n\n#### Deeper\n\nSECRET-XYZZY too\n\n"
                "### Usage\n\nWorn.\n\n## Value\n\n100 gp.\n"
            ),
            "## Mechanics\n\n- +1.\n\n### Usage\n\nWorn.\n\n## Value\n\n100 gp.\n",
        ),
        (
            "## Mechanics\n\n- +1.\n\n### DM Notes\n\nSECRET-XYZZY\n\n## Value\n\n100 gp.\n",
            "## Mechanics\n\n- +1.\n\n## Value\n\n100 gp.\n",
        ),
        ("# Ring\n\n#### DM Notes\n\nSECRET-XYZZY\n\n# Next\n\nKept.\n", "# Ring\n\n# Next\n\nKept.\n"),
        ("# DM Notes\n\nSECRET-XYZZY\n\n## Sub\n\nSECRET-XYZZY\n", ""),
        ("###### DM Notes\nSECRET-XYZZY\n###### Kept\nYes.\n", "###### Kept\nYes.\n"),
        # A heading underlined, not hashed.
        ("Intro.\n\nDM Notes\n--------\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\nDM notes\n===\n\nSECRET-XYZZY\n\n## Kept\n\nYes.\n", "Intro.\n"),
        # Twice: both go.
        (
            "## DM Notes\n\nSECRET-XYZZY\n\n## Mechanics\n\nKept.\n\n## DM notes\n\nSECRET-XYZZY\n",
            "## Mechanics\n\nKept.\n",
        ),
        # A "#" in a code block is no heading, and doesn't end the cut.
        (
            "Intro.\n\n## DM Notes\n\n```\n## Not a heading\nSECRET-XYZZY\n```\n\n## Kept\n\nYes.\n",
            "Intro.\n\n## Kept\n\nYes.\n",
        ),
        # Windows line ends.
        ("Intro.\r\n\r\n## DM Notes\r\n\r\nSECRET-XYZZY\r\n", "Intro.\r\n"),
        # Headings CommonMark renders anywhere: in a blockquote or a list item, to the end of it.
        ("## About\n\nok\n\n> ## DM Notes\n>\n> SECRET-XYZZY\n", "## About\n\nok\n"),
        ("## About\n\nok\n\n- ## DM Notes\n\n  SECRET-XYZZY\n", "## About\n\nok\n"),
        (
            "> ## DM Notes\n> SECRET-XYZZY\n>\n> ## Kept\n\n## DM Notes\n\nSECRET-XYZZY\n\n> ## Inside\n\n## Kept\n",
            "> ## Kept\n\n## Kept\n",
        ),
        # Underlined straight after a heading.
        ("## About\nDM Notes\n--------\n\nSECRET-XYZZY\n", "## About\n"),
        # A backtick line with a backtick in its info string opens no fence.
        ("## About\n\n```a`b\n\n## DM Notes\n\nSECRET-XYZZY\n", "## About\n\n```a`b\n"),
        # A link's text counts.
        ("## [DM Notes](#x)\n\nSECRET-XYZZY\n", ""),
        # A "#" in an HTML block is no heading, and doesn't end the cut.
        ("## DM Notes\n\n<div>\n## x\n</div>\n\nSECRET-XYZZY\n", ""),
        # Apostrophes, more words and an id: the heading still counts.
        ("Intro.\n\n## DM's Notes\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n## DM\u2019s notes\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n## DM Notes {#notes}\n\nSECRET-XYZZY\n\n## Kept\n\nYes.\n", "Intro.\n\n## Kept\n\nYes.\n"),
        ("## DM Notes on pricing are below\n\nSECRET-XYZZY\n", ""),
        # The backstop: the words left anywhere else cut from their line to the end.
        ("Intro.\n\n**DM Notes**\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n#DM Notes is no heading\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n    ## DM Notes (indented code)\n\nSECRET-XYZZY\n", "Intro.\n"),
        ("Intro.\n\n```\n## DM Notes\nSECRET-XYZZY\n```\n", "Intro.\n\n```\n"),
        ("Intro.\n\nSome text about DM notes: SECRET-XYZZY\n", "Intro.\n"),
    ],
)
def test_dm_notes_are_cut(markdown, expected):
    assert cut_dm_notes(markdown) == expected
    assert "SECRET-XYZZY" not in cut_dm_notes(markdown)


@pytest.mark.parametrize(
    "markdown",
    [
        "",
        "A rule with no headings at all.",
        "## Description\n\nA ring.\n\n## Mechanics\n\n- +1 to saves.\n",
        "## Notes\n\nKept.\n\n## The DM\n\nKept.\n",
        "## DMs\n\nThe admin's notes.\n",
        "> ## Quoted\n\n- ## Listed\n\n<div>\n## x\n</div>\n\n```a`b\n",
        "Ends without a line end",
        "Windows.\r\n\r\n## Mechanics\r\n\r\nKept.\r\n",
    ],
)
def test_a_rule_without_dm_notes_shows_whole(markdown):
    assert cut_dm_notes(markdown) == markdown


def test_the_entry_is_cut_for_a_reader_only(storage, book):
    ring = rule(storage, "Mortis Ring", "item")
    reader = view(book, ring).entry("items", f"hr-{ring.id}")
    assert reader.text == "## Description\n\nA ring of bone.\n\n## Mechanics\n\n- +1 to saves.\n"
    assert "SECRET-XYZZY" not in repr(reader)
    organiser = view(book, ring, organiser=True).entry("items", f"hr-{ring.id}")
    assert organiser.text == ITEM_BODY


# --- view_for ------------------------------------------------------------------------------------------------------


def test_view_for_without_a_campaign_is_the_book_alone(book):
    for organiser in (False, True):
        alone = view_for(book, "adnd2e", None, None, organiser)
        assert alone.rules == []
        assert [s.count for s in alone.sections()] == [
            s.count for s in book.sections() if organiser or s.key != "monsters"
        ]


def test_view_for_an_unknown_campaign(storage, book):
    with pytest.raises(NotFound):
        view_for(book, "adnd2e", storage, "cmp_nope", True)
