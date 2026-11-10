"""OSRIC's tables (DEL-299): the copy of the owner's OSRIC engine, its numbers for the classic engine, its lookups,
and the engine's checks and loads worked out on them."""

import json
from importlib import resources

import pytest
from delve_osric.data import CLASSES, load
from delve_osric.ruleset import OsricRuleset
from delve_osric.tables import SAVE_TYPES, TABLES

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import Sheet
from delve.rules.classic import checks, encumbrance
from delve.rules.classic.class_xp import progress

DATA = resources.files("delve_osric").joinpath("data")
REF = OsricRuleset().reference


def dice(*values: int) -> Dice:
    return Dice(ScriptedRng(values), MemoryRollLog(), "cmp_000000000001", "beat-1")


def test_every_table_cites_its_osric_section_and_the_notice_is_there():
    files = sorted(p.name for p in DATA.iterdir() if p.name.endswith(".json"))
    assert len(files) == 20
    for name in files:
        assert "OSRIC 3.0" in json.loads(DATA.joinpath(name).read_text("utf-8"))["_source"], name
    notice = DATA.joinpath("NOTICE.md").read_text("utf-8")
    assert "independent product published under the OSRIC 3.0 Third-Party License" in notice


def test_the_guides_prose_is_left_out():
    assert "_legend" not in load("turning") and "_paladin_note" not in load("turning")
    assert {"caveat", "defeating_monsters"}.isdisjoint(load("monster_xp")["_notes"])
    assert not any("ART TWO:" in s["description"] for s in load("spells")["spells"])


def test_the_counts():
    assert sorted(c for c in load("classes") if not c.startswith("_")) == sorted(CLASSES)
    assert len([a for a in load("ancestry") if not a.startswith("_")]) == 7
    assert len(load("spells")["spells"]) == 469


def test_class_saves_by_level():
    assert TABLES.group_saves("fighter", 1) == dict(zip(SAVE_TYPES, (14, 15, 16, 17, 17), strict=True))
    assert TABLES.group_saves("magic-user", 20)["spells"] == 6
    assert TABLES.class_group("Magic User") == "magic-user"


def test_the_engines_numbers():
    assert (TABLES.surprise_die, TABLES.surprise_on, TABLES.reaction_roll) == (6, 2, "1d100")
    assert TABLES.shock[16] == 95 and TABLES.resurrect[3] == 40
    assert TABLES.nonproficient["magic-user"] == 5 and TABLES.nonproficient["fighter"] == 2
    assert [TABLES.turning_column(level) for level in (0, 1, 8, 9, 13, 14, 19, 30)] == [None, 0, 7, 8, 8, 9, 10, 10]


def test_a_fighters_save_comes_from_osrics_class_table():
    base = checks.save_base_for(Sheet(cls="Fighter", levels={"fighter": 1}), "breath", REF, rules=TABLES)
    assert (int(base), base.basis) == (17, "OSRIC class table: fighter 1")
    result = checks.saving_throw(dice(17), save_type="bw", base=base, actor="chr_1", rules=TABLES)
    assert result.success and result.name == "Breath Weapons"


def test_a_2e_sheets_saves_read_under_osrics_names():
    assert checks.normalize_saves({"rod_staff_wand": 13}, rules=TABLES) == {"aimed_magic_items": 13}


def test_xp_progress_reads_osrics_class_levels():
    (row,) = progress(Sheet(cls="Magic-User", levels={"magic-user": 1}), 2600, REF, rules=TABLES)
    assert row["earned_level"] == 2


def test_turning_a_skeleton_at_first_level_needs_a_ten():
    result = checks.turning_undead(dice(10, 3, 4), REF, level=1, undead="skeleton", actor="chr_1", rules=TABLES)
    assert (result.undead, result.needed, result.turned, result.count) == ("Skeleton (Type 1)", 10, True, 7)


def test_a_reaction_is_a_d100_read_against_osrics_bands():
    result = checks.reaction(dice(60), rules=TABLES)
    assert (result.roll.notation, result.band) == ("1d100", "favourable")


def test_a_load_is_banded_over_the_strength_allowance():
    """Strength 12 allows 45 lb; each 40 lb over it is a band slower."""
    rules = TABLES.encumbrance
    assert encumbrance.str_band_for(12, rules=rules) == (45, 85, 125, 165)
    assert encumbrance.compute([("Rope", 1, 90.0)], strength=12, rules=rules)["band"] == "heavy"
    assert encumbrance.str_band_for(18, 100, rules=rules)[0] == 300


@pytest.mark.parametrize(
    ("ability", "score", "column", "value"),
    [("str", "18/76", "hit_prob", "+2"), ("dex", "16", "missile_adj", "+1"), ("con", "16", "hp_adj", "+2")],
)
def test_ability_rows_carry_the_engines_columns(ability, score, column, value):
    assert REF.ability(ability, score)["values"][column] == value


def test_lookups():
    assert [s["name"] for s in REF.spell("Magic Missile")] == ["Magic Missile"]
    assert {s["caster"] for s in REF.spell("cure", "cleric")} == {"cleric"}
    assert REF.class_levels("Fighter")[1]["xp_required"] == 2000
    assert REF.char_class("thief")["hit_die"] == "d6"
    assert REF.item("Bedroll")[0]["weight"] == 5.0
    assert REF.turning_undead()[0]["aliases"] == ["skeleton", "type 1"]
    assert all(hit["label"].startswith("OSRIC 3.0") for hit in REF.rules_search("surprise"))
