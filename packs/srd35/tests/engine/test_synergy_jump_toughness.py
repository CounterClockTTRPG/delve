"""DEL-456: Toughness's hit points, Jump's speed modifier and the skill synergies, by the SRD's words. Each worked
example is checked by hand in its comment."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from delve_srd35.data import load
from delve_srd35.engine import Srd35Engine, numbers
from delve_srd35.reference import Srd35Reference

from delve.dice import Dice, MemoryRollLog, ScriptedRng
from delve.domain.characters import Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
PACK = Path(__file__).resolve().parents[2]


def sheet(cls: str, race: str, levels: dict[str, int], skills: dict[str, float], **d20) -> Sheet:
    return Sheet(cls=cls, race=race, levels=levels, ability_scores=TEN, d20={"skills": skills, **d20})


def skills(cls: str, race: str, levels: dict[str, int], ranks: dict[str, float], **d20) -> dict[str, int]:
    return numbers.derived(sheet(cls, race, levels, ranks, **d20), REF)["skills"]


# --- Jump's speed ----------------------------------------------------------------------------------------------------


def test_jump_takes_6_off_for_each_10_feet_below_30():
    # "If your speed is less than 30 feet, you take a -6 penalty for every 10 feet of speed less than 30 feet." A human
    # (30 ft.) with 4 ranks and Str 10: 4. A dwarf (20 ft., kept in armour): 4 - 6 = -2; a halfling (20 ft.), with its
    # "+2 racial bonus on Climb, Jump, and Move Silently checks": 4 + 2 - 6 = 0.
    assert skills("Fighter", "Human", {"fighter": 3}, {"jump": 4})["jump"] == 4
    assert skills("Fighter", "Dwarf", {"fighter": 3}, {"jump": 4})["jump"] == -2
    assert skills("Fighter", "Halfling", {"fighter": 3}, {"jump": 4})["jump"] == 0


def test_jump_follows_the_speed_in_armour():
    # A human in full plate moves 20 ft. (Table: Armor and Shields): 4 - 6 for the speed - 6 armour check = -8. A
    # halfling in scale mail moves 15 ft.: one full 10 ft. below 30 is -6, the check penalty -4 and its racial +2:
    # 4 + 2 - 6 - 4 = -4.
    assert skills("Fighter", "Human", {"fighter": 3}, {"jump": 4}, armor="full plate")["jump"] == -8
    assert skills("Fighter", "Halfling", {"fighter": 3}, {"jump": 4}, armor="scale mail")["jump"] == -4


def test_jump_adds_4_for_each_10_feet_above_30():
    # "If your speed is greater than 30 feet, you gain a +4 bonus for every 10 feet beyond 30 feet." A human barbarian 1
    # (fast movement +10 ft.: 40) with 4 ranks: 4 + 4 = 8; a human monk 6 (+20 ft.: 50): 4 + 8 = 12.
    assert skills("Barbarian", "Human", {"barbarian": 1}, {"jump": 4})["jump"] == 8
    assert skills("Monk", "Human", {"monk": 6}, {"jump": 4})["jump"] == 12
    assert [numbers.jump_speed_modifier(s) for s in (None, 15, 20, 30, 35, 40, 60)] == [0, -6, -6, 0, 0, 4, 12]


# --- Synergies -------------------------------------------------------------------------------------------------------


def test_five_ranks_of_tumble_add_2_to_balance_and_jump():
    # Tumble: "If you have 5 or more ranks in Tumble, you get a +2 bonus on Balance and Jump checks." A human rogue 3,
    # Dex and Str 10, 1 rank each in Balance and Jump: 1 + 2 = 3 each with Tumble 5 (Tumble 5 itself: 5); with Tumble 4
    # nothing: 1 each. Jump: "If you have 5 or more ranks in Jump, you get a +2 bonus on Tumble checks": Tumble 5 + 2.
    five = skills("Rogue", "Human", {"rogue": 3}, {"tumble": 5, "balance": 1, "jump": 1})
    assert (five["balance"], five["jump"], five["tumble"]) == (3, 3, 5)
    four = skills("Rogue", "Human", {"rogue": 3}, {"tumble": 4, "balance": 1, "jump": 1})
    assert (four["balance"], four["jump"], four["tumble"]) == (1, 1, 4)
    both = skills("Rogue", "Human", {"rogue": 3}, {"tumble": 5, "jump": 5})
    assert (both["jump"], both["tumble"]) == (7, 7)


def test_synergies_from_several_skills_add_up():
    # Diplomacy: "If you have 5 or more ranks in Bluff, Knowledge (nobility and royalty), or Sense Motive, you get a +2
    # bonus on Diplomacy checks", one row each: Bluff 5 and Sense Motive 5 give Diplomacy 1 + 2 + 2 = 5 at Cha 10.
    # Bluff's "+2 bonus on Diplomacy, Intimidate, and Sleight of Hand checks": Intimidate and Sleight of Hand 1 + 2.
    found = skills("Rogue", "Human", {"rogue": 3}, {"bluff": 5, "sense-motive": 5, "diplomacy": 1, "intimidate": 1,
                                                    "sleight-of-hand": 1, "disguise": 1})  # fmt: skip
    assert (found["diplomacy"], found["intimidate"], found["sleight-of-hand"]) == (5, 3, 3)
    # "... as well as on Disguise checks made when you know you're being observed": conditional, noted, not added.
    assert found["disguise"] == 1


def test_a_conditional_synergy_is_noted_not_added():
    # Use Rope: "+2 bonus on Escape Artist checks when escaping from rope bonds" and on "Climb checks made to climb a
    # rope": a rogue with Use Rope 5, Escape Artist and Climb 1 each keeps 1 and 1, the two in `skill_notes`; so are a
    # check that is no skill (Knowledge (history)'s on bardic knowledge) and one with no ranks of its own.
    ranks = {"use-rope": 5, "escape-artist": 1, "climb": 1, "knowledge-history": 5}
    found = numbers.derived(sheet("Rogue", "Human", {"rogue": 3}, ranks), REF)
    assert (found["skills"]["escape-artist"], found["skills"]["climb"]) == (1, 1)
    assert found["skill_notes"] == {
        "climb": [("+2 on Climb checks made to climb a rope, a knotted rope, or a rope-and-wall combination "
                   "(Use Rope 5+ ranks)")],
        "escape-artist": ["+2 on Escape Artist checks when escaping from rope bonds (Use Rope 5+ ranks)"],
        "bardic-knowledge": ["+2 on bardic knowledge checks (Knowledge (history) 5+ ranks)"],
    }  # fmt: skip
    assert numbers.derived(sheet("Rogue", "Human", {"rogue": 3}, {"use-rope": 4}), REF)["skill_notes"] == {}


def test_the_turning_synergy_is_the_engines_not_a_note():
    # Knowledge (religion) 5 ranks: "+2 bonus on turning checks against undead", added by turn_undead (64b62f94).
    found = numbers.derived(sheet("Cleric", "Human", {"cleric": 3}, {"knowledge-religion": 5}), REF)
    assert found["skill_notes"] == {}
    assert numbers.synergies({"knowledge-religion": 5}, "turning")[0]["from"] == "knowledge-religion"


def test_an_untrained_check_takes_the_synergy():
    # A rogue with Tumble 5 and no Jump ranks jumps untrained: Str 10's 0 + Tumble's 2 = 2, [10] + 2 = 12.
    rogue = sheet("Rogue", "Human", {"rogue": 3}, {"tumble": 5})
    out = ENGINE.skill_check(rogue, "jump", None, 0, Dice(ScriptedRng([10]), MemoryRollLog(), "c", "b"), actor="pc_1",
                             occasion="")  # fmt: skip
    assert (out.bonus, out.total) == (2, 12)


def test_the_synergy_table_is_the_srds():
    # The 29 rows of the skills' Synergy sections, each pair once; a few by their words.
    rows = {(r["from"], r["to"]): r for r in load("synergies")}
    assert len(rows) == len(load("synergies")) == 29
    assert rows["tumble", "jump"] == {"from": "tumble", "to": "jump", "ranks": 5, "bonus": 2, "condition": None}
    assert rows["handle-animal", "wild-empathy"]["condition"] is None
    assert rows["use-rope", "escape-artist"]["condition"] == "when escaping from rope bonds"
    assert rows["knowledge-religion", "turning"]["condition"] == "against undead"
    unconditional = sorted(f"{a}>{b}" for (a, b), r in rows.items() if r["condition"] is None)
    assert unconditional == ["bluff>diplomacy", "bluff>intimidate", "bluff>sleight-of-hand",
                             "handle-animal>ride", "handle-animal>wild-empathy", "jump>tumble",
                             "knowledge-arcana>spellcraft", "knowledge-history>bardic-knowledge",
                             "knowledge-local>gather-information", "knowledge-nobility-and-royalty>diplomacy",
                             "sense-motive>diplomacy", "survival>knowledge-nature", "tumble>balance",
                             "tumble>jump"]  # fmt: skip


def test_the_synergy_script_makes_the_same_bytes(tmp_path):
    data = PACK / "src" / "delve_srd35" / "data"
    shutil.copy(data / "skills.json", tmp_path / "skills.json")
    done = subprocess.run([sys.executable, "-I", str(PACK / "scripts" / "extract_synergies.py"), str(tmp_path)],
                          capture_output=True, text=True, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert (tmp_path / "synergies.json").read_bytes() == (data / "synergies.json").read_bytes()
    assert json.loads((tmp_path / "synergies.json").read_text()) == load("synergies")


# --- Toughness -------------------------------------------------------------------------------------------------------


def _fighter(srd35_call, hp_max=12):
    made = srd35_call("create_character", name="Bram", sheet={"cls": "Fighter", "level": 1, "race": "Human",
                                                             "hp_max": hp_max, "ability_scores": TEN})  # fmt: skip
    assert "error" not in made, made


def test_toughness_gives_3_hit_points(srd35_call):
    # Toughness: "You gain +3 hit points." Taken through set_build, the maximum and current hit points rise by 3: 12 →
    # 15. "A character may gain this feat multiple times. Its effects stack": twice, 18; given up, back to 12.
    _fighter(srd35_call)
    out = srd35_call("set_build", character="Bram", feats=["toughness"])
    assert "error" not in out, out
    bram = srd35_call("get_character", ref="Bram")
    assert (bram["sheet"]["hp_max"], bram["state"]["hp"]) == (15, 15)
    assert "error" not in srd35_call("set_build", character="Bram", feats=["toughness", "toughness"])
    bram = srd35_call("get_character", ref="Bram")
    assert (bram["sheet"]["hp_max"], bram["state"]["hp"]) == (18, 18)
    assert "error" not in srd35_call("set_build", character="Bram", feats=[])
    bram = srd35_call("get_character", ref="Bram")
    assert (bram["sheet"]["hp_max"], bram["state"]["hp"]) == (12, 12)


def test_toughness_on_a_wounded_character_and_kept_feats(srd35_call):
    # Wounded at 5 of 12, Toughness: 8 of 15. A build that keeps its feats (only skills given) moves nothing.
    _fighter(srd35_call)
    srd35_call("update_character", ref="Bram", patch={"hp": 5})
    srd35_call("set_build", character="Bram", feats=["toughness", "alertness"])
    bram = srd35_call("get_character", ref="Bram")
    assert (bram["sheet"]["hp_max"], bram["state"]["hp"]) == (15, 8)
    srd35_call("set_build", character="Bram", skills={"climb": 4})
    srd35_call("set_build", character="Bram", feats=["alertness", "toughness"])
    bram = srd35_call("get_character", ref="Bram")
    assert (bram["sheet"]["hp_max"], bram["state"]["hp"]) == (15, 8)


def test_toughness_counts_in_the_feat_hit_points():
    with_two = Sheet(d20={"feats": [{"id": "toughness"}, {"id": "toughness"}, {"id": "dodge"}]})
    from delve_srd35.engine.tools import feat_hp

    assert feat_hp(REF, with_two) == 6 and feat_hp(REF, Sheet()) == 0
