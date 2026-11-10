"""A module's own wandering tables (DEL-321): which records are ones, where they apply and the die each takes."""

from delve.domain.wandering import countable, fits, is_wandering, table, wandering_tables

RATS = {"roll": "1-3", "count": "1d6", "creature": "monster:giant-rat"}


def test_a_record_says_whether_it_is_a_wandering_table():
    assert is_wandering({"id": "crypt-roamers", "table": [RATS], "wandering": True})
    assert not is_wandering({"id": "wandering-monsters", "table": [RATS], "wandering": False})
    assert not is_wandering({"id": "crypt-roamers", "wandering": True})  # no table at all
    assert is_wandering({"id": "cellar-quiet", "wandering": True, "table": []})  # a place with none
    assert not is_wandering({"id": "wandering-monsters", "table": []})


def test_an_older_record_reads_as_one_by_its_name_unless_it_is_a_rooms_own():
    """Older modules say nothing: the names they use, and not a table keyed to one room."""
    for name in (
        "Wandering Monsters",
        "W100 wandering monsters",
        "Random Encounter Chart",
        "Area One: Random Monsters",
    ):
        assert is_wandering({"id": "x", "name": name, "table": [RATS]}), name
    assert is_wandering({"id": "level-2-random-encounters", "name": "Level 2", "table": [RATS]})
    assert is_wandering({"id": "road-encounters-table", "name": "Road Encounters Table", "table": [RATS]})
    assert not is_wandering({"id": "equipment", "name": "Equipment", "table": [RATS]})
    assert not is_wandering({"id": "wandering-ghost", "name": "Wandering ghost", "key": "key:C2", "table": [RATS]})


def test_where_and_else_the_older_location():
    assert table({"id": "t", "table": [RATS], "where": ["map:upper", "key:C2"]}).where == ("map:upper", "key:C2")
    assert table({"id": "t", "table": [RATS], "location": "text:key-to-the-upper-level"}).where == (
        "text:key-to-the-upper-level",
    )
    assert table({"id": "t", "table": [RATS]}).where == ()


def rolls(*printed):
    return table({"id": "t", "table": [{"roll": r, "result": "x"} for r in printed]})


def test_the_die_from_the_lines():
    assert rolls("1-3", "4-5", "6").dice == "1d6"
    assert rolls("1", "2-6", "7-11", "12-14", "15-19", "20").dice == "1d20"
    assert rolls("01–05", "06-95", "96-00").dice == "1d100"  # an en dash; 00 is 100
    assert rolls("1", "2-3", "4-5", "6-8", "9-0").dice == "1d10"  # a d10's 0 is 10
    assert rolls("2", "3-6", "7", "8-11", "12").dice == "2d6"
    assert rolls("14", "15-20").dice is None  # part of a table: the DM picks
    assert rolls("A", "B").dice is None


def test_a_roll_lands_on_its_line():
    t = rolls("1-3", "4-5", "6")
    assert [t.line(n).roll for n in (1, 3, 4, 6)] == ["1-3", "1-3", "4-5", "6"]
    assert t.line(7) is None
    assert rolls("96-00").line(100).roll == "96-00"


def test_tables_in_the_modules_order_and_counts_to_roll():
    records = [
        {"id": "a-wandering", "table": [RATS]},
        {"id": "trap", "name": "Trap", "table": [RATS]},
        {"id": "b", "wandering": True, "table": [RATS], "kind": "Dungeon"},
    ]
    assert [(t.id, t.kind) for t in wandering_tables(records)] == [("a-wandering", ""), ("b", "dungeon")]
    assert countable("1d6") and countable("2d4+1") and not countable("2-8") and not countable("3")


def test_a_kind_fits_its_terrains():
    assert fits("", "dungeon") and fits("random", "urban")
    assert fits("dungeon", "dungeon") and not fits("dungeon", "forest")
    assert fits("wilderness", "forest") and fits("wilderness", "road") and not fits("wilderness", "dungeon")
    assert not fits("urban", "dungeon")
