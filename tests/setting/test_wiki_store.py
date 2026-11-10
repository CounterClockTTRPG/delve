"""The wiki reader core keeps for wiki setting packs (DEL-307): `SqliteWikiStore` over a pack's `pack.db`, its build,
and `WikiPack` opening it. Over the double of the Greyhawk pack, built from the tiny wiki of `tests/fixtures/reference`
(the queries were ttrpg2's; these tests were the reference store's)."""

import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from delve.domain.reference import LoreFact, ReferenceHit, SettingPage
from delve.packs.store import SnapshotCorrupt
from delve.setting.wiki import PACK_DB, SqliteWikiStore, WikiPack, build_wiki
from tests.fixtures.reference import LORE_FACTS
from tests.fixtures.rulesets import osric_packs_dir
from tests.fixtures.settings import GreyhawkSetting

DATA = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "greyhawk" / "data"
SNAPSHOTS = ("greyhawk.sql.gz", "lore_facts.sql.gz")
TABLES = ("organizations", "characters", "deities", "locations", "settlements", "realms")


@pytest.fixture(scope="module")
def wiki():
    opened = SqliteWikiStore(osric_packs_dir() / "greyhawk" / PACK_DB, "gh_", TABLES)
    yield opened
    opened.close()


def test_a_page_follows_redirects(wiki):
    page = wiki.page("Circle of Eight")
    assert isinstance(page, SettingPage)
    assert page.title == "Circle of Eight" and page.kind == "organizations"
    assert page.fields == {"name": "Circle of Eight", "type": "Cabal", "leader": "Mordenkainen"}
    assert "cabal of wizards" in page.text
    assert page.categories == ("Organizations",)

    assert wiki.page("circle of eight") == page  # ignoring case
    assert wiki.page("Circle of eight") == page  # a redirect
    mordenkainen = wiki.page("Mordy")  # two hops
    assert mordenkainen.title == "Mordenkainen" and mordenkainen.categories == ("Human characters", "Wizards")
    assert mordenkainen.fields == {"name": "Mordenkainen", "race": "Human", "class": "Wizard"}  # no empty fields
    assert wiki.page("Loop A") is None
    assert wiki.page("Blackmoor") is None
    assert wiki.page(" ") is None
    # A body of water is a location; a page without a typed row keeps the wiki's type.
    assert wiki.page("Nyr Dyv").kind == "locations"
    woolly_bay = wiki.page("Woolly Bay")
    assert woolly_bay.kind == "body_of_water" and woolly_bay.fields == {}


def test_the_rows_of_a_typed_table(wiki):
    deities = wiki.rows("deities", "", 10)
    assert [page.title for page in deities] == ["Boccob", "Iuz"]
    assert deities[0] == SettingPage(
        title="Boccob",
        kind="deities",
        fields={"name": "Boccob", "rank": "Greater god", "portfolio": "Magic"},
        text="'''Boccob''' the Uncaring is the god of magic.",
        categories=(),
    )
    assert [page.title for page in wiki.rows("deities", "iu", 10)] == ["Iuz"]
    assert [page.title for page in wiki.rows("deities", "", 1)] == ["Boccob"]
    assert wiki.rows("realms", "", 10) == []
    with pytest.raises(ValueError, match="unknown kind"):
        wiki.rows("pages", "", 10)


def test_search_quotes_each_word(wiki):
    """ttrpg2 doubled the quotes of a phrase query, so '"Circle of Eight"' failed; Delve quotes each word."""
    hits = wiki.search("Circle of Eight", 10)
    assert all(isinstance(hit, ReferenceHit) for hit in hits)
    assert hits[0].title == "Circle of Eight" and hits[0].key == "Circle of Eight"
    assert hits[0].kind == "organization" and "<<Circle>>" in hits[0].text
    assert wiki.search('"Circle of Eight"', 10) == hits
    assert wiki.search("Circle of Eight AND NEAR(", 10) == []  # words, not operators
    assert wiki.search("eight", 10)  # Hardby too: words, not a phrase
    assert len(wiki.search("eight", 1)) == 1
    assert wiki.search(' " ', 10) == []
    assert "Circle of eight" not in [hit.title for hit in wiki.search("circle", 10)]


def test_lore_facts_never_include_campaign_facts(wiki):
    facts = wiki.lore_facts(100)
    assert all(isinstance(fact, LoreFact) for fact in facts)
    kept = [text for text, category, enabled, _ in LORE_FACTS if enabled and category != "campaign"]
    assert sorted(fact.text for fact in facts) == sorted(kept)
    assert {fact.category for fact in facts} == {"greyhawk", "history", "monster", "rules"}
    assert wiki.lore_facts(100, category="campaign") == []
    assert {fact.category for fact in wiki.lore_facts(100, category="greyhawk")} == {"greyhawk"}
    assert len(wiki.lore_facts(2)) == 2
    assert wiki.lore_facts(0) == []


def test_lore_facts_with_a_seed_are_the_same_draw(wiki):
    draw = wiki.lore_facts(3, seed=7)
    assert wiki.lore_facts(3, seed=7) == draw
    assert {fact.id for fact in wiki.lore_facts(4, seed=7)} >= {fact.id for fact in draw}
    orders = {tuple(fact.id for fact in wiki.lore_facts(4, seed=seed)) for seed in range(20)}
    assert len(orders) > 1  # a seed shuffles


def test_lore_facts_leave_out_the_excluded_categories(wiki):
    facts = wiki.lore_facts(100, exclude=["monster"])
    assert facts and "monster" not in {fact.category for fact in facts}
    assert {fact.category for fact in wiki.lore_facts(100, exclude=["monster", "history"])} == {"greyhawk", "rules"}
    draw = wiki.lore_facts(3, seed=7, exclude=["monster"])
    assert wiki.lore_facts(3, seed=7, exclude=["monster"]) == draw
    assert wiki.lore_facts(100, category="monster", exclude=["monster"]) == []


def test_one_store_answers_many_threads_at_once(wiki):
    """Two seats polling play/state while the DM's tools look things up all share one store, from the server's
    threadpool (the walkthrough's HTTP 500s: sqlite3.InterfaceError from one connection used by threads at once)."""

    def lookups(_: int) -> tuple:
        return (wiki.page("Mordy"), wiki.search("eight", 5), wiki.lore_facts(3, seed=7))

    expected = lookups(0)
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert all(result == expected for result in pool.map(lookups, range(400)))


def test_the_store_is_read_only(wiki):
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        wiki._conn.execute("DELETE FROM gh_pages")


def test_the_build_checks_the_sums_and_leaves_no_half_file(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(DATA, data)
    db = tmp_path / PACK_DB
    assert build_wiki(data, db, SNAPSHOTS, "gh_")
    assert SqliteWikiStore(db, "gh_", TABLES).page("Iuz").kind == "deities"
    (data / "greyhawk.sql.gz").write_bytes(b"not the snapshot")
    with pytest.raises(SnapshotCorrupt):
        build_wiki(data, tmp_path / "other.db", SNAPSHOTS, "gh_")
    assert not (tmp_path / "other.db").exists()
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".building")] == []


def test_a_wiki_pack_opens_its_db_and_again_once_rebuilt(tmp_path):
    root = tmp_path / "greyhawk"
    shutil.copytree(DATA, root / "data")
    pack = WikiPack(GreyhawkSetting, "gh_", SNAPSHOTS)
    assert pack.store(root) is None and pack.setting(root, frozenset()).page("Iuz") is None  # no pack.db yet
    pack.build(root, root / PACK_DB)
    first = pack.store(root)
    assert pack.store(root) is first
    assert pack.setting(root, frozenset()).page("Iuz").title == "Iuz"
    pack.build(root, root / PACK_DB)
    assert pack.store(root) is not first
