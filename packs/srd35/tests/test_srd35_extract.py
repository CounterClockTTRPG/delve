"""The SRD 3.5 extraction (DEL-383), on a fixture tree of sections copied from the SRD's Markdown conversion."""

from __future__ import annotations

import filecmp
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURE = Path(__file__).parent / "fixtures" / "srd"
sys.path.insert(0, str(SCRIPTS))

from srd35_extract import kinds
from srd35_extract.common import tables


def run(src: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "extract.py"), str(src), str(out)], capture_output=True, text=True, check=False
    )


@pytest.fixture(scope="module")
def extracted(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("srd35")
    done = run(FIXTURE, out)
    assert done.returncode == 0, done.stderr
    return out


def data(out: Path, kind: str):
    return json.loads((out / "data" / f"{kind}.json").read_text(encoding="utf-8"))


def by_id(out: Path, kind: str) -> dict:
    return {row["id"]: row for row in data(out, kind)}


def test_extract_is_deterministic(extracted, tmp_path):
    again = tmp_path / "again"
    assert run(FIXTURE, again).returncode == 0
    compared = filecmp.dircmp(extracted, again)
    assert not compared.diff_files and not compared.left_only and not compared.right_only
    for sub in ("data", "rules"):
        inner = filecmp.dircmp(extracted / sub, again / sub)
        assert not inner.diff_files and not inner.left_only and not inner.right_only, sub


def test_a_class_has_its_level_table(extracted):
    fighter = by_id(extracted, "classes")["fighter"]
    assert (fighter["type"], fighter["hit_die"]) == ("base", "d10")
    sixth = next(row for row in fighter["levels"] if row["level"] == 6)
    assert (sixth["bab"], sixth["fort"], sixth["ref"], sixth["will"]) == ("+6/+1", "+5", "+2", "+2")
    assert "climb" in fighter["class_skills"] and "swim" in fighter["class_skills"]
    assert len(fighter["levels"]) == 20


def test_a_casters_table_has_its_spells_per_day(extracted):
    wizard = by_id(extracted, "classes")["wizard"]
    first = wizard["levels"][0]
    assert first["level"] == 1 and first["spells_per_day"]["0"] == "3" and first["spells_per_day"]["1"] == "1"


def test_npc_and_prestige_classes_are_typed(extracted):
    classes = by_id(extracted, "classes")
    assert classes["warrior"]["type"] == "npc" and classes["duelist"]["type"] == "prestige"
    assert "definitions-of-terms" not in classes


def test_spell_levels_are_per_class(extracted):
    spells = by_id(extracted, "spells")
    assert spells["fireball"]["levels"] == {"sorcerer": 3, "wizard": 3}
    assert spells["fireball"]["school"] == "Evocation" and spells["fireball"]["descriptors"] == ["Fire"]
    assert spells["cure-light-wounds"]["levels"]["cleric"] == 1
    assert spells["acid-arrow"]["text"].startswith("A magical arrow of acid")


def test_feat_prerequisites_are_structured(extracted):
    cleave = by_id(extracted, "feats")["cleave"]
    assert {"kind": "ability", "ability": "str", "min": 13} in cleave["prerequisites"]
    assert {"kind": "feat", "feat": "power-attack"} in cleave["prerequisites"]
    assert cleave["prerequisites_text"] == "" and "fighter" in cleave["type"]


def test_an_unparsed_prerequisite_is_kept_as_text(extracted):
    feats = by_id(extracted, "feats")
    extra = feats["extra-turning"]
    assert "turn or rebuke" in extra["prerequisites_text"]
    familiar = feats["improved-familiar"]
    assert familiar["prerequisites_text"] and familiar["benefit"]


def test_skills_carry_their_ability_and_flags(extracted):
    skills = by_id(extracted, "skills")
    assert (skills["hide"]["key_ability"], skills["hide"]["armor_check"]) == ("dex", True)
    assert (skills["heal"]["key_ability"], skills["heal"]["armor_check"]) == ("wis", False)
    assert skills["climb"]["armor_check"] is True


def test_races_carry_their_adjustments(extracted):
    races = by_id(extracted, "races")
    assert races["dwarves"]["ability_adjustments"] == {"cha": -2, "con": 2}
    assert races["dwarves"]["speed"] == 20 and races["halflings"]["size"] == "Small"
    assert "favored-class" not in races
    assert races["dwarves"]["favored_class"] == "Fighter"  # the class; the rest of its sentence stays in the text


def test_monsters_keep_all_statblock_fields(extracted):
    ogre = by_id(extracted, "monsters")["aboleth"]  # the conversion's ogre has its size, type and subtypes shifted
    for field in ("hit_dice", "armor_class", "base_attack_grapple", "attack", "full_attack", "space_reach",
                  "saves", "abilities", "skills", "feats", "environment", "organization", "cr", "treasure",
                  "alignment"):  # fmt: skip
        assert ogre[field], field
    assert ogre["type"] == "Aberration" and ogre["size"] == "Huge" and ogre["cr"] == "7"


def test_magic_items_and_armor_are_items(extracted):
    items = by_id(extracted, "items")
    assert items["bag-of-holding"]["item_type"] == "wondrous" and items["bag-of-holding"]["caster_level"] == 9
    assert items["amulet-of-health"]["price"].startswith("4,000 gp")
    assert any(row["item_type"] == "armor" and row["caster_level"] is None for row in items.values())


def test_rules_split_at_headings(extracted):
    files = sorted((extracted / "rules").glob("*.md"))
    titles = [f.read_text(encoding="utf-8").split("\n", 2)[1] for f in files]
    assert 'title: "How Combat Works"' in titles and not any("Table of Contents" in t for t in titles)
    assert not any("legal" in f.name for f in files)


def test_the_ability_table_follows_the_srds_rule():
    table = kinds.abilities()
    modifiers = {row["score"]: row["modifier"] for row in table["modifiers"]}
    assert (modifiers[1], modifiers[10], modifiers[11], modifiers[18], modifiers[45]) == (-5, 0, 0, 4, 17)
    bonus = {row["score"]: row for row in table["bonus_spells"]}
    assert (bonus[12]["1"], bonus[12]["2"], bonus[18]["1"], bonus[18]["4"], bonus[18]["5"]) == (1, 0, 1, 1, 0)
    assert (bonus[20]["1"], bonus[20]["5"], bonus[20]["6"]) == (2, 1, 0)


def test_the_ability_rule_matches_the_srds_clean_rows():
    """The SRD's own table, where its rows came through the conversion clean ("44–45 +17 … 5 4 4 4 4 3 3 3 3"). The
    conversion isn't in the repository: set DELVE_SRD35_SOURCE to its folder to run this."""
    import os

    folder = os.environ.get("DELVE_SRD35_SOURCE", "")
    source = Path(folder) / "Basic Rules and Legal" / "basics-and-ability-scores.md"
    if not folder or not source.exists():
        pytest.skip("DELVE_SRD35_SOURCE isn't set to the SRD conversion")
    import re

    table = {row["score"]: row for row in kinds.abilities()["bonus_spells"]}
    checked = 0
    for line in source.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s+(\d+)--(\d+)\s+\+(\d+)\s+—?-*\s+((?:\d\s+){8}\d)\s*$", line)
        if match:
            low, modifier, spells = int(match.group(1)), int(match.group(3)), match.group(4).split()
            assert kinds.abilities()["modifiers"][low - 1]["modifier"] == modifier
            assert [str(table[low][str(n)]) for n in range(1, 10)] == spells, low
            checked += 1
    assert checked >= 5


def test_missing_source_file_exits_2(tmp_path):
    done = run(tmp_path / "nothing", tmp_path / "out")
    assert done.returncode == 2 and "has no" in done.stderr


def test_simple_tables_split_by_their_rule():
    text = "  ----- -----------\n  Level Base Attack\n  1st   +1\n  ----- -----------\n\n  : Table: X\n"
    (table,) = [t for t in tables(text) if t.caption == "Table: X"]
    assert table.header == ("Level", "Base Attack") and table.rows == (("1st", "+1"),)


def test_prerequisites_parse_each_kind():
    parsed, left = kinds._prerequisites("Dex 13, Dodge, Mobility, base attack bonus +4, caster level 3rd, Ride 1 rank.")
    assert left == []
    assert parsed == [
        {"kind": "ability", "ability": "dex", "min": 13},
        {"kind": "feat", "feat": "dodge"},
        {"kind": "feat", "feat": "mobility"},
        {"kind": "bab", "min": 4},
        {"kind": "caster_level", "min": 3},
        {"kind": "skill", "skill": "ride", "min": 1},
    ]


def test_statblock_pairs_read_strings_as_well_as_pairs():
    assert kinds._pairs([{"Listen": "16"}, "Spot +8", "Hide"]) == {"listen": "16", "spot": "+8", "hide": ""}


def test_a_monster_split_over_two_records_is_one():
    """The conversion gives the frost giant twice: its statblock, then the rest of its description alone."""
    merged = kinds._merged(
        [
            {"name": "Frost Giant", "cr": "9", "description": ["First part."]},
            {"name": "Frost Giant", "cr": None, "description": ["Second part."]},
            {"name": "Ogre", "cr": "3"},
        ]
    )
    assert [r["name"] for r in merged] == ["Frost Giant", "Ogre"]
    assert merged[0]["cr"] == "9" and merged[0]["description"] == ["First part.", "Second part."]


def test_spell_fields_read_with_either_colon_form(tmp_path):
    """Part of the conversion writes `**Level::**`: a spell is read the same either way."""
    (tmp_path / "Spells").mkdir()
    (tmp_path / "Spells" / "Spells.md").write_text(
        "# Spells\n\n## Mage Armor\n\n*   Conjuration (Creation) [Force]\n*   **Level::** Sor/Wiz 1\n"
        "*   **Range::** Touch\n\nAn invisible field of force.\n",
        encoding="utf-8",
    )
    (spell,) = kinds.spells(tmp_path)
    assert spell["levels"] == {"sorcerer": 1, "wizard": 1} and spell["range"] == "Touch"
    assert spell["text"] == "An invisible field of force."


def test_spell_fields_read_with_either_bullet(tmp_path):
    (tmp_path / "Spells").mkdir()
    (tmp_path / "Spells" / "Spells.md").write_text(
        "# Spells\n\n## Passwall\n\n- Transmutation\n- **Level::** Sor/Wiz 5\n- **Range::** Touch\n\nYou create a passage.\n",
        encoding="utf-8",
    )
    (spell,) = kinds.spells(tmp_path)
    assert (spell["school"], spell["levels"], spell["text"]) == (
        "Transmutation",
        {"sorcerer": 5, "wizard": 5},
        "You create a passage.",
    )


def test_a_spell_that_functions_like_another_takes_its_empty_entries(tmp_path):
    """R13: the SRD prints a variant's own entries only; the rest are the named spell's, through a chain, from "mass
    X" as "X, Mass", and from a plain name too. A field the variant prints stays its own."""
    (tmp_path / "Spells").mkdir()
    (tmp_path / "Spells" / "Spells.md").write_text(
        "# Spells\n\n## Cure Light Wounds\n\n- Conjuration (Healing)\n- **Level:** Clr 1\n- **Components:** V, S\n"
        "- **Casting Time:** 1 standard action\n- **Range:** Touch\n- **Duration:** Instantaneous\n"
        "- **Saving Throw:** Will half (harmless)\n- **Spell Resistance:** Yes (harmless)\n\nCures 1d8.\n\n"
        "## Cure Moderate Wounds\n\n- Conjuration (Healing)\n- **Level:** Clr 2\n\n"
        "This spell functions like _cure light wounds_, except that it cures 2d8.\n\n"
        "## Cure Light Wounds, Mass\n\n- Conjuration (Healing)\n- **Level:** Clr 5\n"
        "- **Range:** Close (25 ft. + 5 ft./2 levels)\n\nThis spell functions like _cure moderate wounds_, except "
        "more.\n\n## Cure Moderate Wounds, Mass\n\n- Conjuration (Healing)\n- **Level:** Clr 6\n\n"
        "This spell functions like _mass cure light wounds_, except 2d8.\n\n"
        "## Hold Portal\n\n- Abjuration\n- **Level:** Sor/Wiz 1\n- **Component:** V\n\nHolds a door.\n\n"
        "## Holding Portal\n\n- Abjuration\n- **Level:** Sor/Wiz 2\n\nThis spell functions like hold portal, "
        "except longer.\n",
        encoding="utf-8",
    )
    spells = {s["id"]: s for s in kinds.spells(tmp_path)}
    moderate = spells["cure-moderate-wounds"]
    assert (moderate["components"], moderate["range"], moderate["saving_throw"]) == ("V, S", "Touch",
                                                                                     "Will half (harmless)")  # fmt: skip
    assert spells["cure-light-wounds-mass"]["range"] == "Close (25 ft. + 5 ft./2 levels)"
    assert spells["cure-light-wounds-mass"]["components"] == "V, S"
    mass = spells["cure-moderate-wounds-mass"]
    assert (mass["range"], mass["duration"]) == ("Close (25 ft. + 5 ft./2 levels)", "Instantaneous")
    assert spells["hold-portal"]["components"] == "V" and spells["holding-portal"]["components"] == "V"
    assert spells["cure-light-wounds"]["text"] == "Cures 1d8."


def test_a_spell_headed_a_level_deeper_is_its_own(tmp_path):
    """Part of the conversion heads spells at `###`: each is a spell, and the one before keeps only its own text."""
    (tmp_path / "Spells").mkdir()
    (tmp_path / "Spells" / "Spells.md").write_text(
        "# Spells\n\n## Dancing Lights\n\n- Evocation [Light]\n- **Level::** Sor/Wiz 0\n\nFour lights.\n\n"
        "### Daze\n\n- Enchantment (Compulsion)\n- **Level::** Sor/Wiz 0\n\nA humanoid is dazed.\n",
        encoding="utf-8",
    )
    spells = {s["id"]: s for s in kinds.spells(tmp_path)}
    assert sorted(spells) == ["dancing-lights", "daze"]
    assert spells["dancing-lights"]["text"] == "Four lights." and spells["daze"]["text"] == "A humanoid is dazed."


def test_a_simple_table_after_styling_junk_keeps_its_header():
    """The conversion leaves blank and `"` lines between a table's rule and its header (the Bard's table)."""
    text = (
        "  ----- -----------\n" + " " * 20 + "\n" + " " * 8 + "display: block;\n" + " " * 19 + '"\n'
        "  Level Base Attack\n  1st   +0\n  2nd   +1\n  ----- -----------\n\n  : Table: The Bard\n"
    )
    (table,) = [t for t in tables(text) if t.caption == "Table: The Bard"]
    assert table.header == ("Level", "Base Attack") and table.rows == (("1st", "+0"), ("2nd", "+1"))


def test_class_tables_find_their_level_row():
    """The NPC classes head the column "NPC Level"; the Loremaster's table has its title as its first row."""
    from srd35_extract.common import Section, Table

    def levels(table: Table) -> list[dict]:
        original = kinds.tables
        kinds.tables = lambda text: [table]
        try:
            return kinds._class_table(Section("X", "", 2))
        finally:
            kinds.tables = original

    npc = Table("Table: The Warrior", ("NPC Level", "Base Attack Bonus", "Fort Save", "Ref Save", "Will Save"),
                (("1st", "+1", "+2", "+0", "+0"),))  # fmt: skip
    assert levels(npc)[0] == {"level": 1, "bab": "+1", "fort": "+2", "ref": "+0", "will": "+0", "special": "",
                              "spells_per_day": {}}  # fmt: skip
    titled = Table("", ("Table : The Loremaster", "", "", "", ""),
                   (("Level", "Base Attack Bonus", "Fort Save", "Ref Save", "Will Save"),
                    ("1st", "+0", "+0", "+0", "+2")))  # fmt: skip
    assert levels(titled)[0]["will"] == "+2"


def test_a_class_table_is_the_one_with_its_attack_bonus():
    """The sorcerer's Spells Known table comes before its class table; the class table is the one with the BAB."""
    from srd35_extract.common import Section, Table

    known = Table("Table: Sorcerer Spells Known", ("Level", "0", "1st"), (("1st", "4", "2"),))
    main = Table("Table: The Sorcerer", ("Level", "Base Attack Bonus", "Fort Save", "Ref Save", "Will Save", "Special",
                 "0", "1st"), (("1st", "+0", "+0", "+0", "+2", "Summon familiar", "5", "3"),))  # fmt: skip
    original = kinds.tables
    kinds.tables = lambda text: [known, main]
    try:
        (first,) = kinds._class_table(Section("Sorcerer", "", 2))
    finally:
        kinds.tables = original
    assert (first["will"], first["special"], first["spells_per_day"]) == ("+2", "Summon familiar", {"0": "5", "1": "3"})


def test_a_skills_parts_at_its_own_level_are_its_text(tmp_path):
    """skills-i heads a skill and its Check and Action at the same level: they are the skill's, up to the next skill."""
    basic = tmp_path / "Basic Rules and Legal"
    basic.mkdir()
    (basic / "skills-i.md").write_text(
        "# SKILLS I\n\n## Skill Descriptions\n\n### Appraise [(Int)]\n\n### Check\nYou can appraise objects.\n\n"
        "### Action\nOne minute.\n\n### Balance [(Dex; Armor Check Penalty)]\n\n### Check\nYou can walk on a ledge.\n",
        encoding="utf-8",
    )
    (basic / "skills-ii.md").write_text("# SKILLS II\n", encoding="utf-8")
    skills = {s["id"]: s for s in kinds.skills(tmp_path)}
    assert sorted(skills) == ["appraise", "balance"]
    assert "You can appraise objects." in skills["appraise"]["text"] and "One minute." in skills["appraise"]["text"]
    assert "ledge" not in skills["appraise"]["text"] and "ledge" in skills["balance"]["text"]


def test_a_monsters_shifted_size_and_split_type_are_repaired():
    """Only the repairs that are certain: a two-word type split into type and subtype is joined, and a size found in
    the type field (the name in the size field) moves back; anything else is kept as the conversion has it."""
    assert kinds._size_and_type({"size": "Large", "type": "Magical", "subtypes": ["Beast"]}) == (
        "Large",
        "Magical Beast",
        [],
    )
    assert kinds._size_and_type({"size": "Medium", "type": "Monstrous", "subtypes": ["Humanoid", "Aquatic"]}) == (
        "Medium",
        "Monstrous Humanoid",
        ["Aquatic"],
    )
    assert kinds._size_and_type({"size": "Basilisk", "type": "Medium", "subtypes": ["Magical", "Beast"]}) == (
        "Medium",
        "Magical Beast",
        [],
    )
    assert kinds._size_and_type({"size": "Huge", "type": "Aberration", "subtypes": ["Aquatic"]}) == (
        "Huge",
        "Aberration",
        ["Aquatic"],
    )
    # A monster given as a classed character ("1st-Level Warrior") has its name and level where its size and type go.
    assert kinds._size_and_type(
        {"size": "Goblin", "type": "1st-Level", "subtypes": ["Warrior", "Small", "Humanoid", "Goblinoid"]}
    ) == ("Small", "Humanoid", ["Goblinoid"])
    assert kinds._size_and_type({"size": "M", "type": "Black Dragon(Young)", "subtypes": None}) == (
        "M",
        "Black Dragon(Young)",
        [],
    )


def test_a_product_identity_plane_is_swapped_for_its_description():
    """The conversion gives the chaos beast's environment as a Product Identity plane name; the pack says which kind
    of plane it is instead (SOURCES.md)."""
    assert kinds.scrubbed("Ever-Changing Chaos of Limbo") == "A chaotic neutral-aligned plane"
    assert kinds.scrubbed("Temperate forests") == "Temperate forests"


def test_a_feat_keeps_its_prerequisites_as_printed(extracted):
    feats = by_id(extracted, "feats")
    assert feats["cleave"]["prerequisites_line"] == "Str 13, Power Attack"
    assert feats["power-attack"]["prerequisites_line"] == "Str 13"


def test_the_feat_format_example_is_not_a_feat(tmp_path):
    """The SRD shows how a feat reads under the heading "Feat Name"; that isn't a feat."""
    basic = tmp_path / "Basic Rules and Legal"
    basic.mkdir()
    (basic / "feats.md").write_text(
        "# FEATS\n\n## Feat Descriptions\n\n### Feat Name \n**Benefit:** What the feat enables.\n\n"
        "### Alertness \n***Feat Type: General***\n\n**Benefit:** You get a +2 bonus on Listen checks.\n",
        encoding="utf-8",
    )
    assert [f["id"] for f in kinds.feats(tmp_path)] == ["alertness"]


def test_spells_per_day_are_keyed_by_the_printed_level():
    """A paladin's spells start at 1st level: its columns are 1st to 4th, not 0 to 3 (review, Important 1)."""
    from srd35_extract.common import Section, Table

    paladin = Table("Table: The Paladin", ("Level", "Base Attack Bonus", "Fort Save", "Ref Save", "Will Save",
                    "Special", "1st", "2nd", "3rd", "4th"), (("14th", "+14/+9/+4", "+9", "+4", "+4", "", "2", "1", "1",
                    "0"),))  # fmt: skip
    original = kinds.tables
    kinds.tables = lambda text: [paladin]
    try:
        (row,) = kinds._class_table(Section("Paladin", "", 2))
    finally:
        kinds.tables = original
    assert row["spells_per_day"] == {"1": "2", "2": "1", "3": "1", "4": "0"}


def test_skill_points_are_the_first_paragraph_under_either_heading():
    """The base classes' table follows the skill points; prestige classes head them "at Each Level" (Important 2)."""
    assert kinds._skill_points(
        {"skill points at each additional level": "2 + Int modifier.\n\n  ---- ----\n  Level"}
    ) == ("2 + Int modifier")
    assert kinds._skill_points({"skill points at each level": "4 + Int modifier.\n"}) == "4 + Int modifier"


def test_a_level_row_that_doesnt_follow_on_is_dropped():
    from srd35_extract.common import Section, Table

    table = Table("Table: The Monk", ("Level", "Base Attack Bonus", "Fort Save", "Ref Save", "Will Save"),
                  (("1st", "+0", "+2", "+2", "+2"), ("2nd", "+1", "+3", "+3", "+3"), ("1 The monk's", "", "", "", "")))  # fmt: skip
    original = kinds.tables
    kinds.tables = lambda text: [table]
    try:
        rows = kinds._class_table(Section("Monk", "", 2))
    finally:
        kinds.tables = original
    assert [r["level"] for r in rows] == [1, 2]


def test_real_classes_have_clean_skill_points(extracted):
    classes = by_id(extracted, "classes")
    assert classes["fighter"]["skill_points"] == "2 + Int modifier"
    assert classes["duelist"]["skill_points"]
    assert all("—" not in c["skill_points"] and "<" not in c["skill_points"] for c in classes.values())


def test_item_types_come_from_their_heading_by_whole_words():
    """Not by part of a word in the title: "Bag of Devouring" is no ring, "Bracers of Armor" no armor (Important 5)."""
    wondrous = ("MAGIC ITEMS V", "Wondrous Item Descriptions")
    assert kinds._item_type((*wondrous, "Bag of Devouring")) == "wondrous"
    assert kinds._item_type((*wondrous, "Boots of Striding and Springing")) == "wondrous"
    assert kinds._item_type((*wondrous, "Bracers of Armor")) == "wondrous"
    assert kinds._item_type(("MAGIC ITEMS III", "Rings", "Ring Descriptions", "Protection")) == "ring"
    assert kinds._item_type(("MAGIC ITEMS IV", "Staffs", "Staff Descriptions", "Staff of Fire")) == "staff"


def test_armor_rows_have_their_weight_and_items_no_table_fragments(extracted):
    items = by_id(extracted, "items")
    armor = [i for i in items.values() if i["item_type"] == "armor" and i["caster_level"] is None]
    assert armor and all(i["weight"] for i in armor if i["price"]), [i["name"] for i in armor if not i["weight"]][:5]
    assert "|" not in items["bag-of-holding"]["weight"] and "Limit" not in items["bag-of-holding"]["weight"]


def test_domains_have_their_power_and_nine_spells(extracted):
    domains = by_id(extracted, "domains")
    assert set(domains) == {"air", "knowledge", "war"}
    war = domains["war"]
    assert war["spells"]["1"] == "Magic Weapon" and war["spells"]["9"] == "Power Word Kill"
    assert "Martial Weapon Proficiency" in war["granted_power"] and "Granted Power" not in war["granted_power"]
    assert domains["air"]["spells"]["9"] == "Elemental Swarm"  # the conversion garbles its line
    assert domains["knowledge"]["spells"]["7"] == "Legend Lore"  # the list prints it with its component marks


def test_carrying_capacity_is_the_tables_rows(extracted):
    # The fixture's Table: Carrying Capacity: Str 1 is 3 lb. or less, 4–6 lb., 7–10 lb.; Str 29 466/933/1,400 lb.
    carrying = data(extracted, "carrying")
    assert carrying["loads"][0] == {"strength": 1, "light": 3, "medium": 6, "heavy": 10}
    assert carrying["loads"][-1] == {"strength": 29, "light": 466, "medium": 933, "heavy": 1400}
    assert len(carrying["loads"]) == 29 and carrying["tremendous"] == 4


def test_carrying_capacity_has_the_sizes_and_the_reduced_speeds(extracted):  # DEL-399
    # Bigger and Smaller Creatures, for bipeds: "Large x2, Huge x4, Gargantuan x8, Colossal x16" and "Small x3/4, Tiny
    # x1/2, Diminutive x1/4, Fine x1/8"; Armor and Encumbrance for Other Base Speeds: 20 ft. is 15 ft., 100 ft. 70 ft.
    carrying = data(extracted, "carrying")
    assert carrying["sizes"] == {"Large": "2", "Huge": "4", "Gargantuan": "8", "Colossal": "16", "Small": "3/4",
                                 "Tiny": "1/2", "Diminutive": "1/4", "Fine": "1/8"}  # fmt: skip
    assert carrying["reduced_speeds"] == [{"base": 20, "reduced": 15}, {"base": 30, "reduced": 20},
                                          {"base": 40, "reduced": 30}, {"base": 50, "reduced": 35},
                                          {"base": 60, "reduced": 40}, {"base": 70, "reduced": 50},
                                          {"base": 80, "reduced": 55}, {"base": 90, "reduced": 60},
                                          {"base": 100, "reduced": 70}]  # fmt: skip


def test_carrying_capacity_needs_its_table():
    with pytest.raises(ValueError, match="Carrying Capacity"):
        kinds.carrying([("03-01-carrying-capacity.md", '---\ntitle: "Carrying Capacity"\n---\nNo table.\n')])


def test_the_class_lists_are_read_from_the_class_text():
    """The step `extract.py` runs: the adept's, assassin's and blackguard's spell lists into the spells' levels, from
    the shipped classes alone, gives the shipped spells back (deterministic; no class text, no change)."""
    from delve_srd35 import data as shipped

    classes, spells = shipped.load("classes"), json.loads(json.dumps(shipped.load("spells")))
    for row in spells:
        for cls in kinds.CLASS_LISTS:
            row["levels"].pop(cls, None)
    assert kinds.class_list_levels(classes, spells) == ["corrupt weapon"]  # only in the blackguard's text
    assert spells == shipped.load("spells")
    assert kinds.class_list_levels([], spells) == []
    assert {cls for row in spells for cls in row["levels"]} >= {"adept", "assassin", "blackguard"}


def test_the_spells_known_are_read_from_the_class_text():
    """The step `extract.py` runs (DEL-389): each Table: … Spells Known into its class's level rows, from the shipped
    classes alone, gives the shipped classes back (deterministic); "—" is none and a footnote mark goes."""
    from delve_srd35 import data as shipped

    classes = json.loads(json.dumps(shipped.load("classes")))
    for row in classes:
        for level in row["levels"]:
            level.pop("spells_known", None)
    assert kinds.spells_known(classes) == ["assassin", "bard", "sorcerer"]
    assert classes == shipped.load("classes")
    by = {row["id"]: {level["level"]: level for level in row["levels"]} for row in classes}
    # Table: Sorcerer Spells Known, 1st: 4 / 2; 20th: 9 / 5 / 5 / 4 / 4 / 4 / 3 / 3 / 3 / 3. Table: Bard Spells Known,
    # 1st: 4 (— above); 2nd: 5 / 2¹.
    assert by["sorcerer"][1]["spells_known"] == {"0": "4", "1": "2"}
    assert by["sorcerer"][20]["spells_known"] == dict(zip("0123456789", "9554443333", strict=True))
    assert by["bard"][1]["spells_known"] == {"0": "4"} and by["bard"][2]["spells_known"] == {"0": "5", "1": "2"}
    assert "spells_known" not in by["wizard"][1]
    text = "**Table: Test Spells Known**\n\n| Level | 0 | 1st |\n| --- | --- | --- |\n"
    text += "| 1st | 3 | — |\n| 2nd | 4 | 1¹ |\n"
    row = {"id": "test", "text": text, "levels": [{"level": 1}, {"level": 2}, {"level": 3}]}
    assert kinds.spells_known([row]) == ["test"]
    assert row["levels"] == [{"level": 1, "spells_known": {"0": "3"}}, {"level": 2, "spells_known": {"0": "4", "1": "1"}},
                             {"level": 3}]  # fmt: skip
