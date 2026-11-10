"""Aun, Delve's own setting (DEL-351): its shipped pages all read, link to pages that exist, cover the first core's
list, name nothing of another setting, and its maps and calendar work."""

import re
from pathlib import Path

import pytest

from delve.maps.world.compile import compile_view
from delve.maps.world.parse import parse
from delve.setting.aun import DATA, KINDS, AunSetting
from delve.setting.calendar import RECKONING_CALENDAR
from delve.setting.text import player_text

PLANNED = Path(__file__).parents[2] / "docs" / "settings" / "aun-pages.md"
LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|[^\[\]]*)?\]\]")

# Names of published settings and fiction that must never appear in Aun's text: the likeness is of shape and tone.
FOREIGN = (
    "Greyhawk", "Oerth", "Flanaess", "Iuz", "Vecna", "Mordenkainen", "Circle of Eight", "Suel", "Oeridian",
    "Baklunish", "Nyr Dyv", "Selintan", "Pholtus", "Heironeous", "Hextor", "Cuthbert", "Boccob", "Nerull",
    "Faerûn", "Faerun", "Toril", "Waterdeep", "Elminster", "Harptos", "Netheril", "Krynn", "Solace", "Mystara",
    "Lankhmar", "Fafhrd", "Gray Mouser", "Melniboné", "Melnibone", "Elric", "Hyboria", "Cimmeria", "Conan",
    "Stygia", "Cugel", "Dying Earth", "Middle-earth", "Gondor", "Mordor", "Moradin", "Corellon", "Lolth",
)  # fmt: skip


@pytest.fixture(scope="module")
def aun() -> AunSetting:
    return AunSetting()


@pytest.fixture(scope="module")
def pages(aun):
    return [page for kind in KINDS for hit in aun.lookup(kind, "", 1000) if (page := aun.page(hit.title))]


def _planned() -> set[str]:
    """The titles `aun-pages.md` lists under "The pages": each run of names between ` · `."""
    text = PLANNED.read_text().split("## The pages", 1)[1].split("## Lore facts", 1)[0]
    text = re.sub(r"\n(?![ \t]*(?:- |\*\*|\n))[ \t]*", " ", text)  # a wrapped line joins the one before it
    titles = set()
    for line in (line for line in text.splitlines() if re.match(r"\s*(- |\*\*)", line)):
        body = re.sub(r"^\s*(-\s*)?(\*\*\w+\*\*\s*(\[\w\])?:?\s*)?(\[\w\]\s*)?", "", line)
        for part in body.split("·"):
            title = re.sub(r"\s*\[\w\]\s*$", "", part).strip()
            if title:
                titles.add(title)
    return titles


def test_every_page_reads_and_is_of_a_kind(aun, pages):
    files = list((DATA / "pages").glob("*.md"))
    assert len(pages) == len(files) >= 100
    assert {page.kind for page in pages} == set(KINDS)


def test_the_first_core_is_complete(aun):
    missing = sorted(title for title in _planned() if aun.page(title) is None)
    assert missing == []


def test_every_link_finds_its_page(aun, pages):
    broken = sorted(
        {f"{page.title} → {target}" for page in pages for target in LINK.findall(page.text) if not aun.page(target)}
    )
    assert broken == []


def test_aun_names_nothing_of_another_setting(pages):
    texts = [(f.name, f.read_text()) for f in (DATA / "pages").glob("*.md")]
    texts += [(f.name, f.read_text()) for f in (DATA / "facts").glob("*.toml")]
    texts += [(f.name, f.read_text()) for f in DATA.glob("*.map")]
    found = sorted(
        f"{name}: {word}" for name, text in texts for word in FOREIGN if re.search(rf"\b{re.escape(word)}\b", text)
    )
    assert found == []


def test_dm_sections_stay_out_of_player_text(pages):
    for page in pages:
        assert "::: dm" not in player_text(page.text), page.title


def test_lore_facts(aun):
    facts = aun.lore_facts(1000)
    assert len(facts) >= 60
    assert {fact.category for fact in facts} <= {"history", "gods", "places", "customs", "people"}


def test_the_maps_compile(aun):
    maps = aun.world_maps()
    assert [m.name for m in maps] == ["reaches", "hask-region"]
    for source in maps:
        view = compile_view(parse(source.dsl))
        assert view.features, source.name


def test_the_reckoning():
    assert RECKONING_CALENDAR.days_in_year == 365
    assert RECKONING_CALENDAR.date(RECKONING_CALENDAR.default_start, 1).label == "1 Isaine 1188 RY"
    assert RECKONING_CALENDAR.date((1188, 1), 2).label == "Hollow Days, day 2, 1188 RY"
    assert RECKONING_CALENDAR.date((1188, 1), 365).label == "30 Nameless Month 1188 RY"
