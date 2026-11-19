"""SRD 3.5's book in the Rulesets area (DEL-384): its sections, columns and facets, the rows of a section by its
filters, and an entry's page."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def book():
    from delve_srd35.ruleset import Srd35Ruleset

    return Srd35Ruleset().rulebook


SECTIONS = ["classes", "races", "skills", "feats", "spells", "monsters", "items", "abilities", "rules"]


def test_the_book_has_its_sections_in_order(book):
    sections = book.sections()
    assert [s.key for s in sections] == SECTIONS
    assert all(s.kind == ("table" if s.key == "abilities" else "list") and s.count > 0 for s in sections)


def test_section_columns_and_facets_match_the_spec(book):
    assert book.columns("classes") == ("hit_die", "skill_points", "type")
    assert book.columns("races") == ("size", "speed", "la")
    assert book.columns("skills") == ("key_ability", "trained_only", "armor_check")
    assert book.columns("feats") == ("type", "prerequisites")
    assert book.columns("spells") == ("school", "level")
    assert book.columns("monsters") == ("size", "type", "cr")
    assert book.columns("items") == ("item_type", "price")
    assert book.columns("rules") == ("source", "chapter")
    assert [f.key for f in book.facets("spells")] == ["class", "level", "school"]
    assert [f.key for f in book.facets("monsters")] == ["size", "type", "cr"]
    assert [f.key for f in book.facets("classes")] == ["type"]
    assert book.facets("races") == []


def test_spells_filter_by_class_and_level(book):
    page = book.rows("spells", {"class": "wizard", "level": "3", "q": "fire"}, 0, 50)
    names = [r["name"] for r in page.rows]
    assert "Fireball" in names and page.total == len(names)
    fireball = next(r for r in page.rows if r["name"] == "Fireball")
    assert fireball["level"] == "Sor/Wiz 3" and fireball["school"] == "Evocation"
    assert book.rows("spells", {"class": "cleric", "q": "fireball"}, 0, 50).total == 0
    wizard = dict(next(f for f in book.facets("spells") if f.key == "class").options)
    assert wizard["wizard"] > 100


def test_monsters_filter_by_type_and_cr(book):
    page = book.rows("monsters", {"type": "Giant", "cr": "3"}, 0, 50)
    assert page.total >= 1 and all(r["type"] == "Giant" and r["cr"] == "3" for r in page.rows)


def test_a_class_entry_carries_its_level_table_in_its_text(book):
    """The SRD's own table, where the SRD prints it and with every column (DEL-394); not a second one under it."""
    entry = book.entry("classes", "fighter")
    assert entry.name == "Fighter" and entry.fields["hit_die"] == "d10"
    assert entry.table is None
    assert "**Table: The Fighter**\n\n| Level | Base Attack Bonus | Fort Save | Ref Save | Will Save | Special |" in entry.text
    assert "| 6th | +6/+1 | +5 | +2 | +2 | Bonus feat |" in entry.text
    assert "Bonus Feats" in entry.text


def test_an_entrys_fields_read_as_the_srd_prints_them(book):
    """Class skills by name, abilities in the SRD's order, bonuses signed (DEL-394)."""
    fighter = book.entry("classes", "fighter").fields
    assert fighter["class_skills"] == "Climb, Craft, Handle Animal, Intimidate, Jump, Ride, Swim"
    orc = book.entry("races", "half-orcs").fields
    assert orc["ability_adjustments"] == "Str +2, Int –2, Cha –2" and orc["favored_class"] == "Barbarian"
    assert book.entry("skills", "balance").fields["key_ability"] == "Dex"
    goblin = book.entry("monsters", "goblin").fields
    assert goblin["abilities"] == "Str 11, Dex 13, Con 12, Int 10, Wis 9, Cha 6"
    assert goblin["saves"] == "Fort +3, Ref +1, Will –1"
    assert goblin["skills"] == "Hide +5, Listen +2, Move Silently +5, Ride +4, Spot +2"
    assert (goblin["size"], goblin["type"], goblin["subtypes"]) == ("Small", "Humanoid", "Goblinoid")


def test_entries_of_each_list_have_their_text(book):
    assert "magical arrow of acid" in book.entry("spells", "acid-arrow").text
    assert book.entry("monsters", "aboleth").fields["cr"] == "7"
    assert book.entry("feats", "power-attack").fields["prerequisites"] == "Str 13"
    assert "appraise" in book.entry("skills", "appraise").text.lower()
    rules = book.rows("rules", {"q": "attacks of opportunity"}, 0, 5).rows
    assert rules and book.entry("rules", rules[0]["id"]).text
    assert book.entry("spells", "nothing") is None and book.entry("abilities", "x") is None


def test_the_ability_table(book):
    (table,) = book.table("abilities")
    assert len(table["rows"]) == 45 and table["rows"][17] == {"score": "18", "modifier": "+4",
                                                              "bonus_spells": "1 1 1 1 0 0 0 0 0"}  # fmt: skip
    with pytest.raises(KeyError):
        book.table("turning")


def test_search_finds_across_sections(book):
    hits = book.search("cleave", 10)
    assert ("feats", "cleave", "Cleave") in hits
    assert book.search("", 10) == []


def test_the_book_leaves_the_engines_rows_alone(book):
    """The book shows a feat's prerequisites as their line; the data the engine reads keeps them structured."""
    from delve_srd35.data import load

    assert all(isinstance(f["prerequisites"], str) for f in book._rows_of("feats"))
    cleave = next(f for f in load("feats") if f["id"] == "cleave")
    assert cleave["prerequisites"] == [
        {"ability": "str", "kind": "ability", "min": 13},
        {"feat": "power-attack", "kind": "feat"},
    ]
