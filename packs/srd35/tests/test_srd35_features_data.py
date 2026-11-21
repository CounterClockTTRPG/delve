"""The class features table (DEL-389): every "Special" entry of the 16 base and NPC classes and the 15 prestige classes
is a row, every prestige entry requirement is a `requirement` row, the rows are well formed, and the numbers the
slice's engine carried as constants are the table's."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from delve_srd35.data import load

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
DATA = Path(__file__).resolve().parents[1] / "src" / "delve_srd35" / "data"
sys.path.insert(0, str(SCRIPTS))

from extract_features import entries, requirement_entries, unaccounted
from srd35_extract import rtf

BASE = ["barbarian", "bard", "cleric", "druid", "fighter", "monk", "paladin", "ranger", "rogue", "sorcerer", "wizard"]
NPC = ["adept", "aristocrat", "commoner", "expert", "warrior"]
PRESTIGE = ["arcane-archer", "arcane-trickster", "archmage", "assassin", "blackguard", "dragon-disciple", "duelist",
            "dwarven-defender", "eldritch-knight", "hierophant", "horizon-walker", "loremaster", "mystic-theurge",
            "shadowdancer", "thaumaturgist"]  # fmt: skip
SHAPES = {"bab", "skill", "skill_any", "feat", "feat_any", "cast", "spell", "alignment", "race", "sneak", "proficient",
          "special"}  # fmt: skip
"""The `requires` kinds: the first key of each row's `requires`."""


def _rows() -> dict[tuple[str, str], dict]:
    return {(c, r["id"]): r for c, rows in load("features").items() for r in rows}


def test_every_special_entry_of_every_class_is_a_row():
    # Each comma-separated entry of each level's "Special" cell (as `classes.json` gives it) is named by one row's
    # `special` list. Nothing dropped.
    missing = unaccounted(load("classes"), load("features"), BASE + NPC)
    assert missing == []


def test_every_row_names_only_entries_its_table_has():
    tables = {c["id"]: {e for lvl in c["levels"] for e in entries(lvl["special"])} for c in load("classes")}
    unknown = [(c, r["id"], s) for c, rows in load("features").items() for r in rows for s in r["special"]
               if s not in tables[c]]  # fmt: skip
    assert unknown == []


def test_every_prestige_special_entry_is_a_row():
    assert unaccounted(load("classes"), load("features"), PRESTIGE) == []


def test_the_table_has_the_31_classes_and_no_others():
    assert sorted(load("features")) == sorted(BASE + NPC + PRESTIGE)


def _requires(cls: str) -> list[dict]:
    return [r for r in load("features")[cls] if r["kind"] == "requirement"]


def test_every_requirement_is_a_row():
    # Each entry of each prestige class's "Requirements" section (its BAB, each skill and feat, its alignment, race,
    # spells and special) is named by a requirement row, of a shape the engine reads or a stated `special`.
    classes = {c["id"]: c for c in load("classes")}
    for cls in PRESTIGE:
        wanted = requirement_entries(classes[cls])
        assert wanted, cls
        rows = _requires(cls)
        assert {(r["section"], r["name"]) for r in rows} == set(wanted), cls
        for row in rows:
            assert row["id"].startswith("req-") and row["level"] == 1, (cls, row)
            assert len(row["requires"]) >= 1 and next(iter(row["requires"])) in SHAPES, (cls, row)
            if "special" in row["requires"]:
                assert isinstance(row["requires"]["special"], str) and row["requires"]["special"], (cls, row)
    # Only the non-prestige classes have none.
    assert not [c for c in BASE + NPC if _requires(c)]


def test_the_requirements_name_known_skills_feats_and_spells():
    skills = {s["id"] for s in load("skills")}
    feats = {f["id"] for f in load("feats")}
    spells = {s["id"] for s in load("spells")}
    for cls in PRESTIGE:
        for row in _requires(cls):
            need = row["requires"]
            for skill in [need.get("skill")] * ("skill" in need) + need.get("skill_any", []):
                assert skill.split("-")[0] in skills or skill in skills, (cls, skill)
            for feat in [need] * ("feat" in need) + need.get("feat_any", []):
                assert feat["feat"] in feats, (cls, feat)
            if "spell" in need:
                assert need["spell"] in spells, (cls, need)


def test_arcane_archer_requirements():
    found = [r["requires"] for r in _requires("arcane-archer")]
    assert {"race": ["elves", "half-elves"]} in found
    assert {"bab": 6} in found
    assert {"feat": "point-blank-shot"} in found and {"feat": "precise-shot"} in found
    bows = next(r["feat_any"] for r in found if "feat_any" in r)
    assert {"feat": "weapon-focus", "choice": "longbow"} in bows
    assert {"feat": "weapon-focus", "choice": "shortbow"} in bows
    assert {b["feat"] for b in bows} == {"weapon-focus"}
    assert {"cast": {"level": 1, "kind": "arcane"}} in found
    assert len(found) == 6


def test_the_rulings_on_alignment_and_the_special_requirements():
    def found(cls):
        return [r["requires"] for r in _requires(cls)]

    assert {"alignment": {"not": ["lawful"]}} in found("arcane-trickster")
    assert {"sneak": "2d6"} in found("arcane-trickster")
    assert {"alignment": ["evil"]} in found("assassin") and {"alignment": ["evil"]} in found("blackguard")
    assert {"alignment": ["lawful"]} in found("dwarven-defender") and {"race": ["dwarves"]} in found("dwarven-defender")
    assert {"special": "kill someone for no other reason than to join"} in found("assassin")
    assert {"skill": "knowledge-religion", "ranks": 2} in found("blackguard")
    assert [r for r in found("blackguard") if "special" in r]
    assert {"proficient": "martial"} in found("eldritch-knight")
    assert {"cast": {"level": 3, "kind": "arcane"}} in found("eldritch-knight")
    assert {"feat": "spell-focus", "choice": "conjuration"} in found("thaumaturgist")
    assert {"spell": "planar-ally-lesser"} in found("thaumaturgist")
    assert {"skill": "perform-dance", "ranks": 5} in found("shadowdancer")


def test_mystic_theurge_table_from_the_rtf():
    theurge = next(c for c in load("classes") if c["id"] == "mystic-theurge")
    levels = theurge["levels"]
    assert [lvl["level"] for lvl in levels] == list(range(1, 11))
    assert [lvl["bab"] for lvl in levels] == ["+0", "+1", "+1", "+2", "+2", "+3", "+3", "+4", "+4", "+5"]
    assert [lvl["will"] for lvl in levels] == ["+2", "+3", "+3", "+4", "+4", "+5", "+5", "+6", "+6", "+7"]
    assert [lvl["fort"] for lvl in levels] == [lvl["ref"] for lvl in levels] == ["+0", "+0", "+1", "+1", "+1", "+2",
                                                                                 "+2", "+2", "+3", "+3"]  # fmt: skip
    assert all(lvl["special"] == "" and lvl["spells_per_day"] == {} for lvl in levels)
    # The text's table (the cells the conversion joined again) says the same.
    rows = [line for line in theurge["text"].splitlines() if re.match(r"\| \d+(st|nd|rd|th) \|", line)]
    assert [[c.strip() for c in row.strip("|").split("|")][1:5] for row in rows] == [
        [lvl["bab"], lvl["fort"], lvl["ref"], lvl["will"]] for lvl in levels
    ]
    casting = _rows()["mystic-theurge", "casting"]
    assert casting["advances"] == ["arcane", "divine"] and casting["count"] == 2
    assert casting["by_level"] == {str(level): True for level in range(1, 11)}


def test_the_rtf_reader_gives_a_class_table(tmp_path):
    raw = (r"{\rtf1 MYSTIC THEURGE\par Table: The Mystic Theurge\par Level\tab Base\par Attack\par Bonus\tab Fort\par "
           r"Save\tab Ref\par Save\tab Will\par Save\tab Spells per Day\par "
           r"1st\tab +0\tab +0\tab +0\tab +2\tab +1 level "
           r"of existing arcane spellcasting class/\par +1 level of existing divine spellcasting class\par 2nd\tab +1"
           r"\tab +0\tab +0\tab +3\tab +1 level of existing arcane spellcasting class/\par +1 level of existing divine "
           r"spellcasting class\par Class Features\par}")  # fmt: skip
    (tmp_path / "PrestigeClasses.rtf").write_text(raw, encoding="latin-1")
    levels = rtf.class_levels(tmp_path, "Mystic Theurge")
    assert levels == [
        {"bab": "+0", "fort": "+0", "level": 1, "ref": "+0", "special": "", "spells_per_day": {}, "will": "+2"},
        {"bab": "+1", "fort": "+0", "level": 2, "ref": "+0", "special": "", "spells_per_day": {}, "will": "+3"},
    ]


def test_eldritch_knight_casting_from_2nd():
    casting = _rows()["eldritch-knight", "casting"]
    assert (casting["kind"], casting["advances"], casting["count"], casting["level"]) == ("casting", "arcane", 1, 2)
    assert casting["by_level"] == {str(level): True for level in range(2, 11)}
    assert casting["special"] == ["+1 level of existing arcane spellcasting class"]


def test_the_prestige_casting_rows():
    f = _rows()
    advances = {c: f[c, "casting"].get("advances") for c in PRESTIGE if (c, "casting") in f}
    assert advances == {"arcane-trickster": "any", "archmage": "arcane", "assassin": None, "blackguard": None,
                        "eldritch-knight": "arcane", "hierophant": "divine", "loremaster": "any",
                        "mystic-theurge": ["arcane", "divine"], "thaumaturgist": "any"}  # fmt: skip
    assert f["archmage", "casting"]["by_level"] == {str(level): True for level in range(1, 6)}
    assert f["arcane-trickster", "casting"]["by_level"] == {str(level): True for level in range(1, 11)}
    # No caster level from the arcane archer or the dragon disciple (whose bonus spells are slots); the hierophant's
    # levels "do not advance spell progression … still stack with the character's base spellcasting levels to
    # determine caster level": a caster level only, each level.
    assert not [c for c in ("arcane-archer", "dragon-disciple") if (c, "casting") in f]
    assert f["hierophant", "casting"]["caster_level_only"] is True
    assert f["hierophant", "casting"]["by_level"] == {str(level): True for level in range(1, 6)}
    assert f["dragon-disciple", "bonus-spells"]["by_level"] == {"1": 1, "2": 2, "4": 3, "5": 4, "6": 5, "8": 6,
                                                                "9": 7}  # fmt: skip


def test_the_assassin_and_the_blackguard_cast_their_own_lists():
    f = _rows()
    assert {k: f["assassin", "casting"][k] for k in ("ability", "list", "prepared", "type")} == {
        "ability": "int", "list": "assassin", "prepared": False, "type": "arcane"}  # fmt: skip
    assert {k: f["blackguard", "casting"][k] for k in ("ability", "list", "prepared", "type")} == {
        "ability": "wis", "list": "blackguard", "prepared": True, "type": "divine"}  # fmt: skip
    spells = {s["id"]: s["levels"] for s in load("spells")}
    assert spells["sleep"]["assassin"] == 1 and spells["modify-memory"]["assassin"] == 4
    assert spells["doom"]["blackguard"] == 1 and spells["summon-monster-iv"]["blackguard"] == 4
    assert spells["invisibility-greater"]["assassin"] == 4 and spells["protection-from-energy"]["blackguard"] == 3
    assert sum("assassin" in lv for lv in spells.values()) == 31
    assert sum("blackguard" in lv for lv in spells.values()) == 25  # 26 listed; corrupt weapon has no entry


def test_the_dwarven_defenders_ac_bonus_matches_his_table():
    table = _column("dwarven-defender", "AC Bonus")
    ac = _rows()["dwarven-defender", "ac-bonus"]
    for level in range(1, 11):
        assert f"+{_at(ac['by_level'], level)}" == table[str(level)], level


def test_live_party_unchanged():
    # The owner's live party (four 6th-level single-class characters) reads as before (`engine/test_high_levels.py`).
    from delve_srd35.engine import numbers
    from delve_srd35.reference import Srd35Reference
    from srd35_phase3 import without_phase3

    from delve.domain.characters import Sheet

    party = json.loads((Path(__file__).parent / "fixtures" / "live_party_level6.json").read_text(encoding="utf-8"))
    for character in party:
        sheet = Sheet.from_dict(character["sheet"])
        now = numbers.derived(sheet, Srd35Reference())
        assert without_phase3({"derived": now}) == without_phase3({"derived": character["derived"]})


def test_rows_are_well_formed():
    for cls, rows in load("features").items():
        assert len({r["id"] for r in rows}) == len(rows), cls
        for row in rows:
            assert row["kind"] in {"bonus", "uses", "dice", "reduction", "feat", "proficiency", "casting", "note",
                                   "requirement"}  # fmt: skip
            assert row["id"] and row["name"] and 1 <= row["level"] <= 20
            assert all(1 <= int(level) <= 20 for level in row.get("by_level", {}))
            if row["kind"] == "feat" and "feat" in row:
                assert row["feat"] == "uncanny-dodge" or row["feat"] in {f["id"] for f in load("feats")}


def test_every_class_has_a_proficiency_row_and_every_caster_a_casting_row():
    f = _rows()
    assert all((c, "proficiency") in f for c in BASE + NPC + PRESTIGE)
    casters = {c["id"] for c in load("classes") if any(lvl["spells_per_day"] for lvl in c["levels"])}
    # A class's own casting (the assassin's and blackguard's too); a prestige "+1 level of existing class" row aside.
    assert {c for c, i in f if i == "casting" and "advances" not in f[c, i]} == casters
    weapons = {w["id"] for w in load("weapons")}
    for c in BASE + NPC + PRESTIGE:
        assert set(f[c, "proficiency"]["weapon_ids"]) <= weapons, c


def test_known_values():
    f = _rows()
    assert f["barbarian", "rage"]["by_level"]["1"] == 1 and f["barbarian", "rage"]["by_level"]["20"] == 6
    assert f["monk", "ac-bonus"]["ability"] == "wis"
    # No armour, no shield and a light load (the monk's Weapon and Armor Proficiency).
    for rid in ("ac-bonus", "fast-movement", "flurry-of-blows"):
        assert f["monk", rid]["condition"] == "unarmoured_unencumbered", rid
    assert (
        f["monk", "unarmed-strike"]["by_level"]["1"] == "1d6" and f["monk", "unarmed-strike"]["by_level"]["4"] == "1d8"
    )
    assert f["rogue", "sneak-attack"]["by_level"]["1"] == "1d6" and f["rogue", "sneak-attack"]["by_level"]["3"] == "2d6"
    assert f["barbarian", "fast-movement"]["by_level"]["1"] == 10
    assert f["barbarian", "fast-movement"]["condition"] == "no_heavy_load"
    assert f["paladin", "smite-evil"]["by_level"]["1"] == 1 and f["paladin", "smite-evil"]["by_level"]["5"] == 2
    assert f["fighter", "proficiency"]["weapons"] == ["simple", "martial"]


def test_four_slice_classes_carry_their_phase_2_constants():
    # The rows replace numbers.CASTERS, UNCANNY_DODGE, the sneak and turning lines and combat.PROFICIENT.
    f = _rows()
    assert f["rogue", "uncanny-dodge"]["level"] == 4
    assert f["cleric", "turn-undead"]["ability"] == "cha" and f["cleric", "turn-undead"]["by_level"]["1"] == 3
    assert f["wizard", "casting"]["ability"] == "int" and f["cleric", "casting"]["ability"] == "wis"
    assert set(f["rogue", "proficiency"]["weapon_ids"]) == {"crossbow-hand", "rapier", "sap", "shortbow", "sword-short"}
    # numbers.derived: a rogue's sneak dice are (level + 1) // 2 d6, at every level.
    sneak = f["rogue", "sneak-attack"]["by_level"]
    for level in range(1, 21):
        assert _at(sneak, level) == f"{(level + 1) // 2}d6", level
    # combat.PROFICIENT, class by class.
    assert f["cleric", "proficiency"]["weapons"] == ["simple"] and f["cleric", "proficiency"]["weapon_ids"] == []
    assert f["wizard", "proficiency"]["weapons"] == []
    assert set(f["wizard", "proficiency"]["weapon_ids"]) == {"club", "dagger", "crossbow-heavy", "crossbow-light",
                                                             "quarterstaff"}  # fmt: skip


def _monk_column(header: str) -> dict[str, str]:
    """A column of the monk's table in its class text, by level ("1": "1d6")."""
    return _column("monk", header)


def _column(cls: str, header: str) -> dict[str, str]:
    """A column of a class's table in its class text, by level ("1": "1d6")."""
    row = next(c for c in load("classes") if c["id"] == cls)
    lines = [line for line in row["text"].splitlines() if line.startswith("| ")]
    heads = [h.strip() for h in lines[0].strip("|").split("|")]
    at = heads.index(header)
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines[2:22]]
    rows = [row for row in rows if re.match(r"\d+(st|nd|rd|th)$", row[0])]
    return {re.match(r"\d+", row[0]).group(): row[at] for row in rows}


def _at(by_level: dict, level: int):
    return by_level[max((k for k in by_level if int(k) <= level), key=int)]


def test_the_monks_hand_written_rows_match_her_table():
    f = _rows()
    damage, ac, speed = _monk_column("Unarmed Damage¹"), _monk_column("AC Bonus"), _monk_column("Unarmored Speed Bonus")
    for level in range(1, 21):
        assert _at(f["monk", "unarmed-strike"]["by_level"], level) == damage[str(level)], level
        assert f"+{_at(f['monk', 'ac-bonus']['by_level'], level)}" == ac[str(level)], level
        moves = f["monk", "fast-movement"]["by_level"]
        bonus = _at(moves, level) if level >= f["monk", "fast-movement"]["level"] else 0
        assert f"+{bonus} ft." == speed[str(level)], level


def test_the_script_makes_the_same_bytes(tmp_path):
    for name in ("classes", "skills", "feats"):
        shutil.copy(DATA / f"{name}.json", tmp_path / f"{name}.json")
    done = subprocess.run([sys.executable, "-I", str(SCRIPTS / "extract_features.py"), str(tmp_path)],
                          capture_output=True, text=True, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "features.json").read_bytes() == (DATA / "features.json").read_bytes()
