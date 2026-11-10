"""A setting read from a folder of page files (DEL-351): pages with a TOML header, lore facts, world maps."""

from pathlib import Path

import pytest

from delve.domain.world import PLAIN_CALENDAR
from delve.setting.files import FileSetting, PageFileError, read_page

PAGE = """+++
title = "Pale Tower"
kind = "place"
aliases = ["The Pale Tower", "the Leaning Tower"]
categories = ["Hask", "Ruins"]

[fields]
type = "ruin"
realm = "Free City of Hask"
+++
A white tower a day upriver from [[Hask]].

::: dm
The [[Seven Lanterns|Lantern]] lies under it.
:::
"""

GOD = """+++
title = "Ferryman"
kind = "deity"

[fields]
rank = "small"
home = "Hask Ford"
+++
He takes a coin or a toe.
"""


def _setting(tmp_path: Path) -> FileSetting:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "pale-tower.md").write_text(PAGE)
    (pages / "ferryman.md").write_text(GOD)
    facts = tmp_path / "facts"
    facts.mkdir()
    (facts / "a.toml").write_text(
        '[[fact]]\ntext = "Hask has no bridge."\ncategory = "places"\n\n'
        '[[fact]]\ntext = "The Widow is the Warden\'s sister."\ncategory = "people"\ndm_only = true\n'
    )
    (facts / "b.toml").write_text('[[fact]]\ntext = "Aurel\'s symbol is a scale."\ncategory = "gods"\n')
    (tmp_path / "world.map").write_text("workspace world { model { } }\n")

    class Tiny(FileSetting):
        id = "tiny"
        title = "Tiny"
        KINDS = ("place", "deity", "lore")
        CALENDAR = PLAIN_CALENDAR
        MAPS = (("world", "The world"),)

    return Tiny(tmp_path)


def test_a_page_reads_its_header_and_text():
    page = read_page(PAGE)
    assert (page.title, page.kind, page.format) == ("Pale Tower", "place", "markdown")
    assert page.fields == {"type": "ruin", "realm": "Free City of Hask"}
    assert page.categories == ("Hask", "Ruins")
    assert page.text.startswith("A white tower")
    assert "::: dm" in page.text


@pytest.mark.parametrize(
    "text",
    ["no header", '+++\nkind = "place"\n+++\nx', '+++\ntitle = "X"\n+++\nx', '+++\ntitle = "X"\nkind = "place"\nx'],
)
def test_a_page_without_a_header_title_or_kind_is_refused(text):
    with pytest.raises(PageFileError):
        read_page(text)


def test_page_finds_a_title_or_an_alias_in_any_case_with_or_without_the(tmp_path):
    setting = _setting(tmp_path)
    for asked in ("Pale Tower", "the pale tower", "THE PALE TOWER", "The Leaning Tower", "leaning tower"):
        assert setting.page(asked).title == "Pale Tower"
    assert setting.page("Nowhere") is None


def test_lookup_by_kind_matches_title_and_fields(tmp_path):
    setting = _setting(tmp_path)
    assert [hit.title for hit in setting.lookup("place", "pale")] == ["Pale Tower"]
    assert [hit.title for hit in setting.lookup("place", "")] == ["Pale Tower"]
    hit = setting.lookup("deity", "ford")[0]
    assert (hit.kind, hit.key, hit.title, hit.text) == ("deity", "Ferryman", "Ferryman", "rank: small, home: Hask Ford")
    assert setting.lookup("lore", "") == []
    with pytest.raises(ValueError, match="unknown kind 'monster'"):
        setting.lookup("monster", "x")


def test_search_is_full_text_with_a_snippet_and_never_shows_dm_text(tmp_path):
    setting = _setting(tmp_path)
    hits = setting.search("upriver")
    assert [(hit.kind, hit.title) for hit in hits] == [("place", "Pale Tower")]
    assert "<<upriver>>" in hits[0].text
    assert setting.search("Lantern") == []
    assert setting.search("") == []
    assert setting.search("toe coin")[0].title == "Ferryman"
    assert setting.search("pale")[0].title == "Pale Tower"


def test_lore_facts_are_drawn_by_category_and_seed(tmp_path):
    setting = _setting(tmp_path)
    facts = setting.lore_facts(10)
    assert sorted(fact.text for fact in facts) == [
        "Aurel's symbol is a scale.",
        "Hask has no bridge.",
        "The Widow is the Warden's sister.",
    ]
    assert len({fact.id for fact in facts}) == 3
    assert [fact.dm_only for fact in facts if "Widow" in fact.text] == [True]
    assert {fact.source for fact in facts} == {"tiny"}
    assert [fact.text for fact in setting.lore_facts(5, "gods")] == ["Aurel's symbol is a scale."]
    assert setting.lore_facts(2, seed=7) == setting.lore_facts(2, seed=7)
    assert setting.lore_facts(0) == []


def test_world_maps_and_calendar(tmp_path):
    setting = _setting(tmp_path)
    (source,) = setting.world_maps()
    assert (source.name, source.title) == ("world", "The world")
    assert "workspace world" in source.dsl
    assert setting.calendar() is PLAIN_CALENDAR
    assert setting.kinds() == ("place", "deity", "lore")


def test_two_pages_with_one_title_are_refused(tmp_path):
    setting = _setting(tmp_path)
    (tmp_path / "pages" / "again.md").write_text(GOD)
    with pytest.raises(PageFileError, match="Ferryman"):
        type(setting)(tmp_path).page("Ferryman")


def test_a_page_of_an_unknown_kind_is_refused(tmp_path):
    setting = _setting(tmp_path)
    (tmp_path / "pages" / "odd.md").write_text('+++\ntitle = "Odd"\nkind = "monster"\n+++\nx')
    with pytest.raises(PageFileError, match="monster"):
        type(setting)(tmp_path).page("Odd")
