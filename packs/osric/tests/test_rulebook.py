"""OSRIC in the Rulesets area (DEL-305): its book over its data, its licence notice, and OSRIC offered to campaigns."""

from delve_osric.ruleset import OsricRuleset

from delve.domain.backends import Registry
from delve.rules import catalog
from delve.rules.catalog import catalog as catalog_of

BOOK = OsricRuleset().rulebook


def test_the_books_sections():
    sections = {s.key: (s.kind, s.count) for s in BOOK.sections()}
    assert sections["spells"] == ("list", 469) and sections["monsters"] == ("list", 438)
    assert sections["classes"] == ("list", 10) and sections["races"] == ("list", 7)
    assert sections["abilities"][0] == sections["turning"][0] == "table"


def test_rows_filters_and_entries():
    page = BOOK.rows("spells", {"caster": "illusionist", "q": "phantasmal"}, 0, 5)
    assert page.total >= 1 and all(r["caster"] == "illusionist" for r in page.rows)
    ranger = BOOK.entry("classes", "ranger")
    assert ranger.fields["hit_die"] == "d8" and len(ranger.table) == 20 and "Tracker" in ranger.text
    elf = BOOK.entry("races", "elf")
    assert {"class": "magic-user", "level": "11 (intelligence 18+), 10 (intelligence 17+), 9"} in elf.table
    bugbear = BOOK.entry("monsters", "bugbear")
    assert bugbear.fields["armor_class"] == "5 [15]" and "**Language.**" in bugbear.text
    assert BOOK.entry("spells", "no-such-spell") is None


def test_search_and_tables():
    assert ("monsters", "goblin", "Goblin") in BOOK.search("goblin", 10)
    (turning,) = BOOK.table("turning")
    assert turning["rows"][0]["undead_type"] == "Skeleton (Type 1)" and turning["rows"][0]["1"] == "10"
    assert BOOK.table("abilities")[0]["key"] == "strength"


def test_osric_carries_its_licence_notice():
    assert "independent product published under the OSRIC 3.0 Third-Party License" in OsricRuleset.notice
    assert "not affiliated with Mythmere Games LLC" in OsricRuleset.notice


def test_osric_is_offered_as_a_pack(osric_packs):
    cat = catalog_of(osric_packs)
    registry = Registry()
    catalog.register_rulesets(registry, cat)
    assert [(c.id, c.title) for c in registry.capabilities()] == [
        ("osric", "OSRIC 3.0"),
        ("fake-rules", "Fake ruleset (development)"),
    ]
    assert catalog.make_ruleset("osric", cat).id == "osric"


def test_the_rules_text_is_complete_and_names_only_real_tools():
    """DEL-300: Delve's own words for OSRIC's rules, each section with its title, guide and section number, naming
    only the DM's tools that exist (and a few sheet fields and arguments)."""
    import re

    from delve_osric import text

    from delve.dm.tools.host import all_specs

    sections = text.sections()
    assert len(sections) >= 70
    assert all(s.title and s.source in ("pg", "gmg") and s.number and len(s.body.split()) >= 80 for s in sections)
    tools = {spec.name for spec in all_specs()} | {"weapon_profs", "in_lair", "xp_earned"}
    named = {n for s in sections for n in re.findall(r"`([a-z][a-z0-9_]*)`", s.body)}
    assert named <= tools, sorted(named - tools)
    (surprise, *_) = OsricRuleset().reference.rules_search("surprise")
    assert surprise["section"] == "Surprise" and "<<" in surprise["snippet"]
