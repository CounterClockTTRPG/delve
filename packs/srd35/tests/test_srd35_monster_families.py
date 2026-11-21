"""The family monsters (DEL-389 part 3): the true dragons by age, a full stat block each from the SRD's age tables;
the elementals and animated objects by size and the other families' variants, rows of their own; a variant found by
its name in any order, and a family's bare name refused, naming its variants. On a fixture cut from the RTFs (the
general true dragon entry and the black dragon; OGL text) and on the committed data."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURE = Path(__file__).parent / "fixtures" / "rtf" / "dragons"
SOURCES = Path(__file__).resolve().parents[1] / "SOURCES.md"
sys.path.insert(0, str(SCRIPTS))

from delve_srd35 import data
from delve_srd35.engine import attack_line, combat
from delve_srd35.reference import Srd35Reference, family_refusal
from srd35_extract import families, rtf

from delve.rules.classic.combat import Combatant, CombatError

REF = Srd35Reference()
AGES = ("Wyrmling", "Very Young", "Young", "Juvenile", "Young Adult", "Adult", "Mature Adult", "Old", "Very Old",
        "Ancient", "Wyrm", "Great Wyrm")  # fmt: skip
OBJECT_SIZES = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan", "Colossal")
COLOURS = ("Black", "Blue", "Brass", "Bronze", "Copper", "Gold", "Green", "Red", "Silver", "White")


def first(name: str) -> dict:
    return REF.monster(name)[0]


# The committed data


def test_young_red_dragon():
    # Red Dragons by Age, Young: L, 13d12+39 (123), Str 25, +13/+24, Attack +19, Fort +11, Ref +8, Will +9, 6d10 (19);
    # its abilities: 21 (–1 size, +12 natural), touch 9, caster level 1st; Challenge Ratings: young 7.
    dragon = first("Young Red Dragon")
    assert (dragon["name"], dragon["id"], dragon["size"], dragon["type"]) == (
        "Young Red Dragon", "young-red-dragon", "Large", "Dragon")  # fmt: skip
    assert (dragon["cr"], dragon["hit_dice"], dragon["hp"], dragon["base_attack_grapple"]) == ("7", "13d12+39", 123,
                                                                                               "+13/+24")  # fmt: skip
    assert (dragon["armor_class"], dragon["touch"], dragon["flat_footed"]) == ("21 (–1 size, +12 natural)", 9, "21")
    assert dragon["saves"] == {"fort": "+11", "ref": "+8", "will": "+9"} and dragon["subtypes"] == ["Fire"]
    assert dragon["full_attack"] == ("Bite +19 melee (2d6+7) and 2 claws +14 melee (1d8+3) and 2 wings +14 melee "
                                     "(1d6+3) and tail slap +14 melee (1d8+10)")  # fmt: skip
    forms = attack_line.parse(dragon["full_attack"])
    assert [(f["name"], f["bonus"], f["damage"], f["count"]) for f in forms] == [
        ("bite", 19, "2d6+7", 1),
        ("claw", 14, "1d8+3", 2),
        ("wing", 14, "1d6+3", 2),
        ("tail slap", 14, "1d8+10", 1),
    ]
    assert "breath weapon (40-ft. cone of fire, 6d10, DC 19)" in dragon["special_attacks"]
    assert dragon["immune"] == ["fire", "sleep", "paralysis"] and "vulnerability to cold" in dragon["special_qualities"]
    assert "dr" not in dragon and "sr" not in dragon  # damage reduction from young adult, SR from young adult
    assert (dragon["level_adjustment"], dragon["advancement"], dragon["space_reach"]) == (
        "+6", "14–15 HD", "10 ft./5 ft. (10 ft. with bite)")  # fmt: skip


def test_an_old_dragon_has_its_ages_defences_and_attacks():
    # Mature adult red: DR 10/magic, SR 23, frightful presence DC 26, Huge (crush); the ancient gold gains its
    # spell-like abilities up to its age, the great wyrm red is Colossal with a tail sweep.
    mature = first("Mature Adult Red Dragon")
    assert (mature["dr"], mature["sr"]) == ([{"value": 10, "bypass": ["magic"]}], 23)
    assert "frightful presence (DC 26)" in mature["special_attacks"] and "crush (2d8+16, DC 28)" in mature[
        "special_attacks"]  # fmt: skip
    wyrm = first("Great Wyrm Red Dragon")
    assert (wyrm["size"], wyrm["dr"], wyrm["sr"], wyrm["cr"]) == ("Colossal", [{"value": 20, "bypass": ["magic"]}], 32,
                                                                   "26")  # fmt: skip
    assert "tail sweep (2d8+25, DC 40)" in wyrm["special_attacks"]
    gold = first("Ancient Gold Dragon")
    assert "spell-like abilities (bless, luck bonus, geas/quest, detect gems, sunburst)" in gold["special_attacks"]
    assert "spells (caster level 15th)" in gold["special_attacks"]
    silver = first("Wyrmling Silver Dragon")
    assert silver["immune"] == ["acid", "cold", "sleep", "paralysis"]


def test_every_colour_and_age_is_a_row():
    rows = {m["name"]: m for m in data.load("monsters")}
    for colour in COLOURS:
        for age in AGES:
            row = rows[f"{age} {colour} Dragon"]
            assert row["full_attack"].startswith("Bite +") and row["hp"] and row["cr"].isdigit(), row["name"]
        assert rows[f"{colour} Dragon"]["variants"] == [f"{age} {colour} Dragon" for age in AGES]
    assert not [n for n in rows if re.match(r"(?:Very young|Young adult|Mature adult|Very old|Great wyrm) ", n)]


def test_large_fire_elemental():
    # Fire Elemental, Large: 8d8+24 (60 hp), 2 slams +10 melee (2d6+2 plus 2d6 fire), DR 5/—, immunity to fire.
    elemental = first("Large Fire Elemental")
    assert (elemental["hit_dice"], elemental["full_attack"]) == ("8d8+24", "2 slams +10 melee (2d6+2 plus 2d6 fire)")
    assert elemental["dr"] == [{"value": 5, "bypass": ["—"]}] and "fire" in elemental["immune"]
    assert first("Fire Elemental")["variants"] == [f"{size} Fire Elemental" for size in
                                                  ("Small", "Medium", "Large", "Huge", "Greater", "Elder")]  # fmt: skip


@pytest.mark.parametrize(
    ("family", "variants"),
    [
        ("Animated Object", [f"{s} Animated Object" for s in OBJECT_SIZES]),
        ("Hydra", [f"{n}-headed Hydra" for n in ("Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve")]),
        ("Arrowhawk", ["Juvenile Arrowhawk", "Adult Arrowhawk", "Elder Arrowhawk"]),
        ("Salamander", ["Flamebrother Salamander", "Average Salamander", "Noble Salamander"]),
        ("Tojanida", ["Juvenile Tojanida", "Adult Tojanida", "Elder Tojanida"]),
        ("Xorn", ["Minor Xorn", "Average Xorn", "Elder Xorn"]),
        ("True Dragon", [f"{c} Dragon" for c in families.COLOURS]),
    ],
)
def test_a_family_names_its_variants(family, variants):
    assert first(family)["variants"] == variants
    for name in variants:
        assert first(name)["name"] == name


@pytest.mark.parametrize(
    ("asked", "found"),
    [
        ("red dragon, young", "Young Red Dragon"),
        ("young red dragon", "Young Red Dragon"),
        ("huge earth elemental", "Huge Earth Elemental"),
        ("earth elemental, huge", "Huge Earth Elemental"),
        ("young adult red dragon", "Young Adult Red Dragon"),  # not its skeleton
        ("Dragon, red, great wyrm", "Great Wyrm Red Dragon"),
    ],
)
def test_a_variant_is_found_in_any_order(asked, found):
    assert first(asked)["name"] == found


def test_phase_2s_lookups_are_unchanged():
    for name in ("Orc", "Wolf", "Gnoll", "Ogre", "Hill Giant", "Goblin", "Owlbear"):
        assert first(name.lower())["name"] == name


def test_dragon_alone_is_ambiguous():
    # "dragon" is the true dragon's general entry: it is no combatant, and its refusal names the colours and ages.
    found = first("dragon")
    assert found["name"] == "True Dragon"
    refusal = family_refusal(found)
    assert refusal is not None
    for word in (*COLOURS, *AGES):
        assert word.lower() in refusal.lower(), word
    with pytest.raises(CombatError) as refused:
        combat.combatant_from_monster(found, Combatant(id="e1", name="Dragon", side="enemy", hp=1, hp_max=1), {})
    assert str(refused.value) == refusal


@pytest.mark.parametrize("name", ["red dragon", "fire elemental", "hydra", "xorn", "Animated Object"])
def test_a_family_alone_is_refused_naming_its_variants(name):
    row = first(name)
    refusal = family_refusal(row)
    assert refusal is not None and all(v in refusal for v in row["variants"])
    with pytest.raises(CombatError):
        combat.combatant_from_monster(row, Combatant(id="e1", name=name, side="enemy", hp=1, hp_max=1), {})


def test_a_monster_not_a_family_is_no_refusal():
    assert family_refusal(first("orc")) is None and family_refusal(first("Young Red Dragon")) is None


def test_setting_up_a_fight_with_a_family_is_refused(srd35_call):
    out = srd35_call("setup_combat", enemies=[{"name": "red dragon", "count": 1}], surprise=False)
    assert "Young Red Dragon" in out["error"]
    out = srd35_call("setup_combat", enemies=[{"name": "red dragon, young", "count": 1}], surprise=False)
    assert "error" not in out, out


# Every row without a full attack has its reason


def _stated() -> dict[str, str]:
    """SOURCES.md's "Rows with no attacks of their own" list: each "- **Name:** reason." line, by name."""
    section = SOURCES.read_text(encoding="utf-8").split("### Rows with no attacks of their own", 1)[1]
    section = section.split("\n#", 1)[0]
    return dict(re.findall(r"^- \*\*(.+?):\*\* (.+)$", section, re.MULTILINE))


def test_every_monster_has_a_full_attack_or_a_stated_reason():
    blank = {m["name"] for m in data.load("monsters") if not str(m.get("full_attack") or "").strip()}
    stated = _stated()
    assert blank - set(stated) == set()  # each blank row is listed with its reason
    assert set(stated) - blank == set()  # and no listed row has gained a full attack
    for name in blank:
        row = first(name)
        if "variants" in row:
            assert stated[name].startswith("a family"), name
        else:
            assert stated[name].startswith(("a template", "a subrace")), name


# The extraction, on the fixture


def test_the_dragons_from_the_fixture():
    rows = {r["name"]: r for r in families.dragons(FIXTURE)}
    assert list(rows) == [f"{age} Black Dragon" for age in AGES]
    wyrmling = rows["Wyrmling Black Dragon"]
    # Black Dragons by Age, Wyrmling: T, 4d12+4 (30), Str 11, +4/–4, Attack +6, 2d4 (13); 15 (+2 size,+3 natural).
    assert (wyrmling["size"], wyrmling["hit_dice"], wyrmling["hp"], wyrmling["cr"]) == ("Tiny", "4d12+4", 30, "3")
    assert wyrmling["full_attack"] == "Bite +6 melee (1d4) and 2 claws +1 melee (1d3)"
    assert wyrmling["special_attacks"] == "breath weapon (30-ft. line of acid, 2d4, DC 13)"
    assert wyrmling["special_qualities"] == ("Blindsense 60 ft., darkvision 120 ft., keen senses, low-light vision, "
                                             "immunity to acid, sleep, and paralysis, water breathing")  # fmt: skip
    assert (wyrmling["touch"], wyrmling["flat_footed"], wyrmling["level_adjustment"]) == (12, "15", "+3")
    great = rows["Great Wyrm Black Dragon"]
    assert great["special_attacks"] == (
        "breath weapon (120-ft. line of acid, 24d4, DC 36), crush (4d6+19, DC 36), tail sweep (2d6+19, DC 36), "
        "frightful presence (DC 33), spell-like abilities (darkness, corrupt water, plant growth, insect plague, "
        "charm reptiles), spells (caster level 15th)")  # fmt: skip
    assert (great["dr"], great["sr"], great["advancement"]) == ([{"value": 20, "bypass": ["magic"]}], 28, "38+ HD")
    orc = next(m for m in data.load("monsters") if m["id"] == "orc")
    assert set(wyrmling) - set(rtf.DEFENCES) == set(orc) - set(rtf.DEFENCES)  # the keys of any monster row


def test_no_dragon_file_no_dragons(tmp_path):
    assert families.dragons(tmp_path) == []


def test_a_family_with_too_few_variants_is_an_error():
    rows = [
        {"id": "xorn", "name": "Xorn", "full_attack": ""},
        {"id": "minor-xorn", "name": "Minor Xorn", "full_attack": "Bite +6 melee (2d8+2)", "hp": 17},
    ]
    with pytest.raises(ValueError, match="Xorn"):
        families.variants(rows)
