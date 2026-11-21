"""Monsters' special qualities and race data from the SRD's RTFs (DEL-389 part 3): the damage reduction, spell
resistance, regeneration, fast healing, resistances and immunities the Markdown conversion lost with its link text,
the level adjustments it left blank and the "… AS CHARACTERS" traits it dropped. On fixture blocks cut from the RTFs
(the gargoyle, gnoll, ogre, rakshasa, troll and the elf/drow block; OGL text) and on the committed data."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURE = Path(__file__).parent / "fixtures" / "rtf"
QUALITIES = FIXTURE / "qualities"
sys.path.insert(0, str(SCRIPTS))

from delve_srd35 import data
from delve_srd35.engine import numbers
from delve_srd35.reference import Srd35Reference
from srd35_extract import rtf

REF = Srd35Reference()


def monster(key: str) -> dict:
    return next(m for m in data.load("monsters") if m["id"] == key)


def lossy(key: str, **fields) -> dict:
    """A row as the conversion gave it: the fields named, the rest empty."""
    return {"id": key, "name": key.replace("-", " ").title(), "level_adjustment": "", "special_qualities": "",
            "text": "", **fields}  # fmt: skip


# The parser


def test_damage_reduction_forms():
    assert rtf.defences("Damage reduction 10/magic, darkvision 60 ft., freeze")["dr"] == [
        {"value": 10, "bypass": ["magic"]}
    ]
    assert rtf.defences("damage reduction 5/cold iron and good")["dr"] == [
        {"value": 5, "bypass": ["cold iron", "good"]}
    ]
    assert rtf.defences("damage reduction 10/magic or silver")["dr"] == [
        {"value": 10, "bypass_any": ["magic", "silver"]}
    ]
    assert rtf.defences("Damage reduction 5/–")["dr"] == [{"value": 5, "bypass": ["—"]}]
    assert rtf.defences("DR 10/— and 5/good")["dr"] == [
        {"value": 10, "bypass": ["—"]},
        {"value": 5, "bypass": ["good"]},
    ]


def test_spell_resistance_regeneration_fast_healing():
    found = rtf.defences("Change shape, damage reduction 15/good and piercing, darkvision 60 ft., spell resistance 27")
    assert found == {"dr": [{"value": 15, "bypass": ["good", "piercing"]}], "sr": 27}
    assert rtf.defences("SR 11 + class levels") == {"sr": 11, "sr_plus_class_levels": True}
    troll = "Regeneration (Ex): Fire and acid deal normal damage to a troll. If a troll loses a limb…"
    assert rtf.defences("Darkvision 90 ft., regeneration 5, scent", troll) == {
        "regeneration": {"value": 5, "bypass": [["fire"], ["acid"]]}
    }
    assert rtf.defences("fast healing 2") == {"fast_healing": 2}


def test_resistances_and_immunities():
    found = rtf.defences("Darkvision 60 ft., immunity to fire and poison, resistance to acid 10 and cold 10")
    assert found == {"immune": ["fire", "poison"], "resist": {"acid": 10, "cold": 10}}
    assert rtf.defences("immunity to sleep and charm effects")["immune"] == ["sleep", "charm"]
    assert rtf.defences("+2 turn resistance, undead traits") == {}


# The fixture


def completed() -> dict[str, dict]:
    rows = [
        lossy("gargoyle", special_qualities=" freeze", level_adjustment="+5", text="Gargoyles often appear…"),
        lossy("troll", special_qualities=" regeneration 5 scent"),
        lossy("ogre"),
        lossy("gnoll", level_adjustment="+1"),
        lossy("rakshasa", level_adjustment="+7"),
        lossy("drow", text="Spell resistance equal to 11 + class levels.\n\nLevel adjustment +2."),
        lossy("aboleth", special_qualities="Aura, mucus cloud"),
    ]
    return {r["id"]: r for r in rtf.qualities(QUALITIES, rows)}


def test_gargoyle_dr_10_magic():
    gargoyle = completed()["gargoyle"]
    assert gargoyle["dr"] == [{"value": 10, "bypass": ["magic"]}]
    assert gargoyle["special_qualities"] == "Damage reduction 10/magic, darkvision 60 ft., freeze"
    assert gargoyle["text"].startswith("Gargoyles often appear…\n\nGARGOYLES AS CHARACTERS\n\n")
    assert monster("gargoyle")["dr"] == [{"value": 10, "bypass": ["magic"]}]


def test_troll_regeneration_and_la():
    troll = completed()["troll"]
    assert troll["regeneration"] == {"value": 5, "bypass": [["fire"], ["acid"]]}
    assert troll["level_adjustment"] == "+5"
    assert "Favored Class: Fighter." in troll["text"]
    committed = monster("troll")
    assert committed["regeneration"] == {"value": 5, "bypass": [["fire"], ["acid"]]}
    assert committed["level_adjustment"] == "+5"
    race = numbers.monster_race(REF, "troll")
    assert race["level_adjustment"] == 5 and race["favoured_class"] == "fighter"
    # "skill points equal to 9 x (2 + Int modifier…": the RTF's Symbol-font space read as a space, not "?".
    assert race["racial_skill_points"] == {"per_hd": 2, "times": 9}


def test_ogre_la_and_favoured_class():
    ogre = completed()["ogre"]
    assert ogre["level_adjustment"] == "+2"
    assert "Favored Class: Barbarian." in ogre["text"]  # the SRD's ogre: "—Favored Class: Barbarian."
    race = numbers.monster_race(REF, "ogre")
    assert race["level_adjustment"] == 2 and race["favoured_class"] == "barbarian"
    assert race["racial_hd"] == {"levels": 4, "die": "d8"}


def test_gnoll_favoured_class_ranger():
    assert "Favored Class: Ranger." in completed()["gnoll"]["text"]
    assert numbers.monster_race(REF, "gnoll")["favoured_class"] == "ranger"


def test_a_spell_resistance():
    rows = completed()
    assert (rows["rakshasa"]["sr"], rows["rakshasa"]["dr"]) == (27, [{"value": 15, "bypass": ["good", "piercing"]}])
    assert (rows["drow"]["sr"], rows["drow"]["sr_plus_class_levels"]) == (11, True)
    assert rows["drow"]["level_adjustment"] == "+2"
    assert monster("rakshasa")["sr"] == 27
    assert (monster("drow")["sr"], monster("drow")["sr_plus_class_levels"]) == (11, True)
    assert monster("1st-level-warrior-drow")["sr"] == 12


def test_rows_already_right_are_unchanged():
    orc = monster("orc")
    assert rtf.qualities(FIXTURE, [orc]) == [orc]  # the orc's own block changes nothing in its row
    assert not {"dr", "sr", "regeneration", "fast_healing", "resist", "immune"} & set(orc)
    aboleth = lossy("aboleth", special_qualities="Aura, mucus cloud")
    assert completed()["aboleth"] == aboleth  # no block in the fixture: as it was


def run(rtf_dir: Path, out: Path) -> subprocess.CompletedProcess:
    script = str(SCRIPTS / "extract_rtf.py")
    return subprocess.run([sys.executable, "-I", script, str(rtf_dir), str(out)], capture_output=True, text=True,
                          check=False)  # fmt: skip


def test_extract_is_deterministic(tmp_path):
    rows = [lossy("gargoyle", special_qualities=" freeze"), lossy("troll"), lossy("ogre")]
    folder = tmp_path / "rtf"
    folder.mkdir()
    for path in (FIXTURE / "Equipment.rtf", *QUALITIES.glob("*.rtf")):  # the weapons table is needed too
        (folder / path.name).write_bytes(path.read_bytes())
    outputs = []
    for name in ("first", "second"):
        out = tmp_path / name
        out.mkdir()
        (out / "monsters.json").write_text(json.dumps(rows), encoding="utf-8")
        done = run(folder, out)
        assert done.returncode == 0, done.stderr
        first = (out / "monsters.json").read_bytes()
        assert run(folder, out).returncode == 0 and (out / "monsters.json").read_bytes() == first  # nothing more
        outputs.append(first)
    assert outputs[0] == outputs[1]
    made = {r["id"]: r for r in json.loads(outputs[0])}
    assert made["gargoyle"]["dr"] == [{"value": 10, "bypass": ["magic"]}] and made["ogre"]["level_adjustment"] == "+2"


# Fix round 1


def test_regeneration_bypass_is_alternatives_each_all_needed():
    # A pit fiend "takes normal damage from good-aligned silvered weapons, and from spells or effects with the good
    # descriptor": a weapon both good and silver, or a good spell (its alternative has the word "spell", which no
    # weapon has). The tarrasque: nothing.
    assert monster("pit-fiend")["regeneration"] == {"value": 5, "bypass": [["good", "silver"], ["good", "spell"]]}
    assert monster("solar-angel")["regeneration"]["bypass"] == [["epic", "evil"], ["evil", "spell"]]
    # The chain devil's "silvered weapons, good-aligned weapons, and spells or effects with the good descriptor".
    assert monster("chain-devil-kyton")["regeneration"]["bypass"] == [["silver"], ["good"], ["good", "spell"]]
    assert monster("tarrasque")["regeneration"] == {"value": 40, "bypass": []}


def test_spell_resistance_by_class_levels_from_the_race_section():
    section = "—Special Qualities (see above): Change shape, spell resistance equal to 27 + class levels."
    assert rtf.defences("spell resistance 27", traits=section) == {"sr": 27, "sr_plus_class_levels": True}
    assert rtf.defences("spell resistance 12", traits=section) == {"sr": 12}  # another creature's number
    for key, sr in (("azer", 13), ("hound-archon", 16), ("rakshasa", 27), ("pixie", 15), ("drow", 11)):
        assert (monster(key)["sr"], monster(key)["sr_plus_class_levels"]) == (sr, True), key
    assert "sr_plus_class_levels" not in monster("1st-level-warrior-drow")  # its 12 is a 1st-level drow's


def test_a_garbled_rtf_line_takes_the_markdown_copys():
    # The RTF's adult tojanida reads "immunity to acid and cold, electricity 10 and fire 10", the juvenile's ends in
    # "resistance to" and the elder's repeats its resistances; the SRD Markdown copy's line is whole for all three.
    whole = "All-around vision, darkvision 60 ft., immunity to acid and cold, resistance to electricity 10 and fire 10"
    rows = [lossy(f"{age}-tojanida") for age in ("juvenile", "adult", "elder")]
    for row in rtf.qualities(QUALITIES, rows, srd=QUALITIES / "srd"):
        assert row["special_qualities"] == whole, row["id"]
        assert (row["immune"], row["resist"]) == (["acid", "cold"], {"electricity": 10, "fire": 10})
    for row in rtf.qualities(QUALITIES, rows):  # without the copy, the conversion's (empty) line stays
        assert row["special_qualities"] == "" and "resist" not in row
    for age in ("juvenile", "adult", "elder"):
        committed = monster(f"{age}-tojanida")
        assert committed["special_qualities"] == whole and committed["resist"] == {"electricity": 10, "fire": 10}


# Monster races only from base creatures (the engine)


def test_a_classed_column_or_a_lycanthrope_form_is_no_race():
    for name, base in (("4th-Level Barbarian Ogre", "Ogre"), ("6th-Level Ranger Troll Hunter", "Troll Hunter"),
                       ("1st-Level Warrior Dwarf", "Dwarf")):  # fmt: skip
        assert numbers.monster_race(REF, name) is None
        assert numbers.race_refusal(REF, name) == (
            f"{monster_name(name)} can't be a character race: it is a sample character with class levels; play "
            f"the {base} and give it the class instead."
        )
    assert numbers.monster_race(REF, "Human Form Werewolf") is None
    assert numbers.race_refusal(REF, "Human Form Werewolf") == (
        "Human Form Werewolf can't be a character race: it is one form of the Werewolf, a lycanthrope."
    )
    assert numbers.monster_race(REF, "ogre") is not None  # the base creature stays a race


def test_a_subrace_without_a_stat_block_is_no_race_yet():
    for name in ("Drow", "Duergar", "Svirfneblin"):
        assert monster(name.lower())["level_adjustment"]  # the SRD's adjustment stays in the data
        assert numbers.monster_race(REF, name) is None
        assert numbers.race_refusal(REF, name) == (
            f"{name} can't be a character race yet: its entry has no stat block of its own (a subrace)."
        )


def test_race_sections_headed_otherwise_are_read():
    janni = numbers.monster_race(REF, "Janni")  # "Jann as Characters"
    assert janni["favoured_class"] == "rogue"
    assert janni["racial_hd"] == {"levels": 6, "die": "d8"} and janni["racial_bab"] == 6
    assert janni["racial_saves"] == {"fort": 5, "ref": 5, "will": 5}
    assert numbers.monster_race(REF, "Kobold")["favoured_class"] == "sorcerer"  # "KOBOLD CHARACTERS"
    # The hound archon's "9 × (8 + Int modifier)", with a multiplication sign.
    assert numbers.monster_race(REF, "Hound Archon")["racial_skill_points"] == {"per_hd": 8, "times": 9}


def monster_name(name: str) -> str:
    return next(m["name"] for m in data.load("monsters") if m["id"] == name.lower().replace(" ", "-"))
