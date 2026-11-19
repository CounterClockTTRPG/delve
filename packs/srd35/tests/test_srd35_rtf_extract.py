"""What the SRD's RTFs add to the SRD 3.5 pack (DEL-388): the weapons table and the monsters the Markdown conversion
lost, on a fixture cut from the RTFs (the orc's block and three rows of the weapons table)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURE = Path(__file__).parent / "fixtures" / "rtf"
sys.path.insert(0, str(SCRIPTS))

import extract_rtf
from delve_srd35 import data
from srd35_extract import rtf


def run(rtf_dir: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPTS / "extract_rtf.py"), str(rtf_dir), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_reader_keeps_the_dash():
    assert rtf.text(r"{\rtf1 (2d4+4/18\endash 20) Will \endash 2}").strip() == "(2d4+4/18–20) Will –2"
    assert rtf.text(r"{\rtf1 an orc\rquote s \emdash tusks}").strip() == "an orc’s —tusks"


def test_weapons_from_the_fixture():
    rows = {w["id"]: w for w in extract_rtf.weapons(FIXTURE)}
    sword = rows["longsword"]
    wanted = {"damage_m": "1d8", "threat": 19, "mult": 2, "category": "martial", "kind": "one-handed"}
    assert wanted.items() <= sword.items()
    assert rows["battleaxe"]["mult"] == 3 and rows["battleaxe"]["threat"] == 20
    assert set(sword) == {"id", "name", "category", "kind", "cost", "damage_s", "damage_m", "threat", "mult", "range",
                          "weight", "type"}  # fmt: skip
    assert (sword["cost"], sword["range"], sword["weight"]) == ("15 gp", "", "4 lb.")


def test_the_orc_comes_from_the_rtf():
    orc = next(m for m in extract_rtf.missing_monsters(FIXTURE, have=set()) if m["id"] == "orc")
    assert orc["attack"].startswith("Falchion +4 melee (2d4+4/18–20)")
    assert orc["saves"] == {"fort": "+3", "ref": "+0", "will": "–2"} and orc["touch"] == 10 and orc["cr"] == "1/2"
    assert (orc["name"], orc["size"], orc["type"], orc["subtypes"]) == ("Orc", "Medium", "Humanoid", ["Orc"])
    assert (orc["hit_dice"], orc["hp"], orc["flat_footed"]) == ("1d8+1", 5, "13")
    assert orc["armor_class"] == "13 (+3 studded leather armor)"
    assert orc["text"].startswith("An orc’s hair usually is black.")


def test_a_monster_row_has_the_keys_of_the_rows_already_there():
    (orc,) = extract_rtf.missing_monsters(FIXTURE, have=set())
    assert set(orc) == set(data.load("monsters")[0]) | {"touch"}


def test_monsters_already_extracted_are_not_touched():
    assert not [m for m in extract_rtf.missing_monsters(FIXTURE, have={"orc"}) if m["id"] == "orc"]
    assert not extract_rtf.missing_monsters(FIXTURE, have={"1st level warrior orc"})  # the same words, any order


def test_the_data_has_the_slice_staples():  # against the committed data
    names = {m["name"] for m in data.load("monsters")}
    assert {"Orc", "Wolf", "Goblin", "Kobold"} <= names
    assert data.load("weapons") and all(w["threat"] in range(15, 21) for w in data.load("weapons"))


def test_the_extraction_is_stable(tmp_path):  # two runs on the fixture give the same bytes
    outputs = []
    for name in ("first", "second"):
        out = tmp_path / name
        out.mkdir()
        (out / "monsters.json").write_text("[]\n", encoding="utf-8")
        done = run(FIXTURE, out)
        assert done.returncode == 0, done.stderr
        assert done.stdout.splitlines() == ["weapons: 3", "monsters added: 1", "monsters: 1"]
        outputs.append({p.name: p.read_bytes() for p in sorted(out.iterdir())})
    assert outputs[0] == outputs[1] and set(outputs[0]) == {"monsters.json", "weapons.json"}


def test_rows_already_there_stay_and_the_new_are_sorted_in(tmp_path):
    mine = [{"id": "aboleth", "name": "Aboleth", "cr": "7"}, {"id": "zombie", "name": "Zombie", "cr": "1/2"}]
    (tmp_path / "monsters.json").write_text(json.dumps(mine), encoding="utf-8")
    assert run(FIXTURE, tmp_path).returncode == 0
    rows = json.loads((tmp_path / "monsters.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in rows] == ["aboleth", "orc", "zombie"] and [rows[0], rows[2]] == mine
    again = (tmp_path / "monsters.json").read_bytes()
    assert run(FIXTURE, tmp_path).returncode == 0 and (tmp_path / "monsters.json").read_bytes() == again


def test_a_missing_rtf_exits_2(tmp_path):
    done = run(tmp_path, tmp_path)
    assert done.returncode == 2 and "Equipment.rtf" in done.stderr
