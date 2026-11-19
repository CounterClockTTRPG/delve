"""A scripted SRD 3.5 session, levels 1–2 (DEL-388): four characters, a fight with four orcs, a climb, a turning and
the XP to 2nd level, through the tool host with seeded dice and the tripwire on (a classic table read raises).

Seed 19 is the first start seed (a search over 1–200) whose round 1 gives Bram a confirmed critical and Pip a sneak
attack on a flat-footed orc. The golden was checked by hand against the SRD and the logged faces (`rolls`; `answers[i]`
is the i-th call):

- **The party** (`answers[4..7]`): Bram AC 10 + scale mail 4 + Dex 1 = 15, Climb 4 ranks + Str 3 − 4 (scale mail's
  armour check penalty) = +3; falchion BAB 1 + Str 3 + Weapon Focus 1 = +5, 2d4 + 1.5 × Str 3 = 2d4+4, 18–20/×2.
  Dorna AC 10 + 4 + heavy shield 2 = 16, level-1 slots 1 + 1 (Wis 15) + 1 domain = 3, turning 3 + Cha 1 = 4 a day.
  Pip short sword (Small) 1d4, +1 (BAB 0, Str 0, size +1), sneak 1d6. Elowen slots {0: 3, 1: 2}, level-1 DC 14.
- **The orcs** (`answers[10]`, rolls `hp`): the row's 1d8+1 each, faces 2, 6, 5, 2, so 3, 7, 6, 3 hp.
- **Initiative**, highest first and rolled once: Elowen 14 + 7 (Dex 3, Improved Initiative 4) = 21, Bram 17 + 1 = 18,
  Pip 13 + 3 = 16, Orc 4 15, Dorna 12, Orcs 3, 2, 1 at 4, 2, 1.
- **The critical** (`answers[11].actions[1]`): d20 18 is a threat; Orc 1 hasn't acted, so it is flat-footed at AC 13.
  The confirmation, 10 + 5 = 15 ≥ 13, gives ×2: (1 + 2 + 4) + (3 + 1 + 4) = 15 damage, Orc 1 at 3 − 15, dead at −10.
- **The sneak attack** (`actions[2]`): 13 + 1 = 14 ≥ flat-footed 13; 1d4 [4] + sneak 1d6 [6] = 10, Orc 2 at 7 − 10 = −3.
- Orc 4 swings at Dorna, who hasn't acted (12 < 15) and is flat-footed at 16: 5 + 4 = 9, a miss.
- **Sleep** (`answers[11].spells_spent[0]`): DC 10 + 1 + Int 17's +3 = 14, "Will negates". Orc 3's Will save
  (`answers[13]`): 3 − 2 = 1 < 14, it sleeps (the face needed is 14 + 2 = 16). Bless (`spells_spent[1]`): DC 10 + 1 +
  Wis 15's +2 = 13, one of three level-1 copies spent.
- **The provoke** (`answers[14]`): Orc 4 runs in round 2, when Bram isn't flat-footed. 19 + 5 + Bless 1 = 25 hits and
  threatens; the confirmation 6 + 6 = 12 < 13 fails. 2d4+4 = 2 + 3 + 4 = 9, Orc 4 at 3 − 9 = −6.
- **Climb** (`answers[16]`): 18 + 3 = 21 ≥ DC 10.
- **Turning** (`answers[17]`): 11 + Cha 1 = 12, Table: Turning Undead's row 10–12 (+0): up to 1 + 0 = 1 HD. The human
  warrior skeleton's row gives 1d12, so 1 HD (its CR 1/3 is the template's 1-HD row) and it is turned; turning damage
  2d6 [1, 1] + level 1 + Cha 1 = 4 HD; not destroyed (level 1 < 2 × 1 HD); 3 of 4 attempts left.
- **XP** (`answers[15]`, `[18..22]`): a CR 1/2 orc is half CR 1's 300, 150. The DM awards all four, 4 × 150 = 600,
  150 each (`end_combat` counts the three slain: 450). Bram's 150 + 850 = 1,000 reaches 2nd level (Table 6-13).
- **2nd level** (`answers[23]`): d10 [2] + Con 2 = 4 hit points, hp_max 12 → 16 and hp 12 → 16; BAB 2, Fort 3 + 2 = 5;
  3 skill points (2 + Int 0 + 1 human) and a fighter bonus feat.

Every answer is compared with `golden/scripted_session.json`. The test writes the golden when it is missing and fails;
the first one was checked by hand against the working above. It is never regenerated."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden" / "scripted_session.json"
SEED = 19
"""The first call's seed; each call after takes the next."""

FIGHTER = {"str": 16, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8}
CLERIC = {"str": 14, "dex": 10, "con": 14, "int": 10, "wis": 15, "cha": 12}
ROGUE = {"str": 10, "dex": 17, "con": 12, "int": 12, "wis": 10, "cha": 12}
WIZARD = {"str": 8, "dex": 16, "con": 10, "int": 17, "wis": 12, "cha": 10}


def play(call) -> list[tuple[str, dict, dict]]:
    """The session: each call as (tool, args, answer). `call(tool, **args)` runs one tool call in a beat of its own."""
    said: list[tuple[str, dict, dict]] = []

    def run(tool, **args):
        out = call(tool, **args)
        assert "error" not in out, (tool, out)
        said.append((tool, args, out))
        return out

    # 1. The party, each at its hit die's maximum + Con (the DM gives it at 1st level).
    run("create_character", name="Bram", sheet={"cls": "Fighter", "level": 1, "race": "Human", "hp_max": 12,
                                                 "ability_scores": FIGHTER})  # fmt: skip
    run("create_character", name="Dorna", sheet={"cls": "Cleric", "level": 1, "race": "Dwarf", "hp_max": 10,
                                                  "ability_scores": CLERIC})  # fmt: skip
    run("create_character", name="Pip", sheet={"cls": "Rogue", "level": 1, "race": "Halfling", "hp_max": 7,
                                                "ability_scores": ROGUE})  # fmt: skip
    run("create_character", name="Elowen", sheet={"cls": "Wizard", "level": 1, "race": "Elf", "hp_max": 4,
                                                   "ability_scores": WIZARD})  # fmt: skip
    run("set_build", character="Bram", skills={"climb": 4, "jump": 4, "intimidate": 4},
        feats=["power attack", "cleave", {"id": "weapon focus", "choice": "falchion"}], weapon="falchion",
        armor="scale mail")  # fmt: skip
    run("set_build", character="Dorna", skills={"concentration": 4}, domains=["war", "good"], weapon="warhammer",
        armor="scale mail", shield="heavy steel shield")  # fmt: skip
    run("set_build", character="Pip", skills={"hide": 4, "move silently": 4, "open lock": 4, "climb": 4, "tumble": 4,
        "spot": 4, "listen": 4, "search": 4}, feats=["dodge"], weapon="short sword", armor="leather")  # fmt: skip
    run("set_build", character="Elowen", skills={"concentration": 4, "spellcraft": 4, "knowledge (arcana)": 4},
        feats=["improved initiative"], weapon="dagger")  # fmt: skip

    # 2. Spells: Magic Weapon in Dorna's domain slot (war's 1st).
    run("memorize_spells", character="Elowen", spells=["Sleep", "Magic Missile"])
    run("memorize_spells", character="Dorna", spells=["Bless", "Cure Light Wounds", "Magic Weapon"])

    # 3. The fight.
    run("setup_combat", enemies=[{"name": "orc", "count": 4}], surprise=False)
    run("combat_round", actions=[
        {"attacker": "Bram", "target": "Orc 1"},
        {"attacker": "Pip", "target": "Orc 2"},
        {"caster": "Elowen", "spell": "Sleep", "target": "Orc 3"},
        {"caster": "Dorna", "spell": "Bless"},
        {"attacker": "Orc 4", "target": "Dorna"},
    ])  # fmt: skip
    # Bless: +1 on attack rolls for 1 minute a level (10 rounds); the DM applies it, here to Bram, who swings again.
    run("apply_effect", target="Bram", name="bless", duration=10, to_hit=1, source="Dorna")
    run("saving_throw", character="Orc 3", save_type="will", dc=14)
    run("provoke", provoker="Orc 4", threatened_by=["Bram"])
    run("end_combat")

    # 4. A climb.
    run("skill_check", character="Bram", skill="climb", dc=10, occasion="the gully wall")

    # 5. Turning.
    run("turning_undead", level=1, undead="human warrior skeleton", character="Dorna")

    # 6. XP and 2nd level.
    for name in ("Bram", "Dorna", "Pip", "Elowen"):
        run("award_xp", character=name, amount=4 * 150 // 4)
    run("award_xp", character="Bram", amount=850)
    run("update_character", ref="Bram", patch={"level": 2}, reason="2nd level")
    return said


@pytest.fixture
def seeded_call(srd35_tripwire, srd35_storage, srd35_campaign):
    """`call(tool, **args)` on the srd35 campaign, each call in a beat of its own with the next seed."""
    from delve.dice import SeededRng
    from delve.dm.tools import ToolHost
    from tests.fixtures.rulesets import srd35_catalogs

    seeds = itertools.count(SEED)
    host = ToolHost(srd35_storage, lambda: SeededRng(next(seeds)), catalogs=srd35_catalogs())
    beats = itertools.count(1)

    def run(tool, /, **args):
        return host.call(srd35_campaign.id, f"beat-{next(beats)}", tool, args)

    return run


def _normalised(value, storage, campaign_id):
    """`value` with ids by name: characters by theirs, the fight as <fight>, roll ids and times as placeholders."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    for c in storage.characters.list(campaign_id):
        text = text.replace(c.id, c.name)
    for event in storage.events.list(campaign_id, types=["combat_started"]):
        text = text.replace(event.data["combat_id"], "<fight>")
    text = re.sub(r'"(roll|note|hr)_[0-9a-f]{12}"', r'"<\1 id>"', text)
    text = re.sub(r'"\d{4}-\d\d-\d\dT[^"]+"', '"<time>"', text)
    return json.loads(text)


def test_the_scripted_session_matches_its_golden(seeded_call, srd35_storage, srd35_campaign):
    said = play(seeded_call)
    rolls = [
        {"beat": r.key.beat, "purpose": r.key.purpose, "actor": r.key.actor, "target": r.key.target,
         "round": r.key.combat_round, "notation": r.notation, "faces": list(r.faces), "total": r.total}
        for r in srd35_storage.rolls.list(srd35_campaign.id)
    ]  # fmt: skip
    session = {"answers": [{"tool": t, "args": a, "answer": o} for t, a, o in said], "rolls": rolls}
    answers = _normalised(session, srd35_storage, srd35_campaign.id)
    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(answers, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        pytest.fail("golden written: check it by hand")
    assert answers == json.loads(GOLDEN.read_text())
