"""A scripted SRD 3.5 session to 3rd level (DEL-388, ruling R22): the fighter, cleric and wizard of the levels 1–2
session take the XP for 3rd level and two level-ups each, through the tool host with seeded dice and the tripwire on.
The fighter takes its 2nd- and 3rd-level feats and its skill ranks through `set_build`; the cleric and the wizard
prepare 2nd-level spells into their new slots (Wis and Int bonus spells and the domain slot counted) and cast one each.

The golden was checked by hand against the SRD and the logged faces (`rolls`; `answers[i]` is the i-th call):

- **XP** (`answers[6]`, `[9]`, `[12]`): 3,000 is 3rd level's (Table 6-13: 0, 1,000, 3,000). `xp_next` is the XP of
  the level after the sheet's, which is still 1st when the XP comes: 1,000.
- **Bram, fighter 2 and 3** (`answers[7]`, `[8]`): d10 [4] + Con 2 = 6, hp_max 12 → 18; d10 [8] + 2 = 10 → 28, the
  hit points following the maximum. BAB 2 then 3; Fort 3 + Con 2 = 5 at both, Ref 0 then 1 + Dex 1 = 1, 2, Will 0
  then 1 + Wis 1 = 1, 2. Hints: 3 skill points a level (2 + Int 0 + 1 human), a fighter bonus feat at 2nd, a feat at
  3rd.
- **Bram's build at 3rd** (`answers[15]`): five feats (1st level's, the human's and the fighter's 1st bonus feat, the
  2nd-level bonus feat Improved Initiative, the 3rd-level feat Great Fortitude); Fort 5 + 2 = 7, initiative Dex 1 + 4 =
  5. Skill points 12 + 3 + 3 = 18, all spent on 6 + 6 + 6 ranks, the most at 3rd (3 + 3): Climb 6 + Str 3 − 4 (scale
  mail) = 5, Jump 5, Intimidate 6 + Cha −1 = 5.
- **Dorna, cleric 2 and 3** (`answers[10]`, `[11]`): d8 [8] + Con 2 = 10 twice, 10 → 20 → 30. BAB 1, 2; Fort 3 + 2 =
  5, Ref 0 then 1, Will 3 + Wis 2 = 5. Slots at 2nd: 0-level 4, 1st 2 + 1 (Wis 15) + 1 domain = 4; at 3rd 2nd-level
  1 + 1 (Wis 15: 1 + (2 − 2) ÷ 4) + 1 domain = 3; the 2nd-level DC 10 + 2 + Wis 2 = 14. Concentration 6 + Con 2 = 8,
  of (2 + 0) × 4 + 2 + 2 = 12 points (`answers[16]`).
- **Elowen, wizard 2 and 3** (`answers[13]`, `[14]`): d4 [1] then [2] + Con 0, 4 → 5 → 7. BAB 1, 1; Fort 0 then 1,
  Ref 0 then 1 + Dex 3 = 3, 4, Will 3 + Wis 1 = 4. Slots at 2nd: 0-level 4, 1st 2 + 1 (Int 17: 1 + (3 − 1) ÷ 4) = 3;
  at 3rd 2nd-level 1 + 1 (1 + (3 − 2) ÷ 4) = 2; the 2nd-level DC 10 + 2 + Int 3 = 15. Skill points (2 + 3) × 4 + 5 +
  5 = 30; Spellcraft 6 + 3 = 9 (`answers[17]`).
- **Spells** (`answers[18..23]`): Dorna's 1st-level slots hold Bless, Cure Light Wounds, Shield of Faith and Magic
  Weapon (war's 1st, the domain slot); her 2nd-level ones Hold Person, Aid and Spiritual Weapon (war's 2nd). Elowen
  fills 3 1st-level and 2 2nd-level slots. Hold Person is cast at DC 14, "Will negates", 2 2nd-level copies left; Web
  at DC 15, "Reflex negates", 1 left.

Every answer is compared with `golden/scripted_session_level3.json`. The test writes the golden when it is missing and
fails; the first one was checked by hand against the working above. It is never regenerated."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parent / "golden" / "scripted_session_level3.json"
SEED = 1
"""The first call's seed; each call after takes the next."""

FIGHTER = {"str": 16, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8}
CLERIC = {"str": 14, "dex": 10, "con": 14, "int": 10, "wis": 15, "cha": 12}
WIZARD = {"str": 8, "dex": 16, "con": 10, "int": 17, "wis": 12, "cha": 10}
FIRST_FEATS = ["power attack", "cleave", {"id": "weapon focus", "choice": "falchion"}]


def play(call) -> list[tuple[str, dict, dict]]:
    """The session: each call as (tool, args, answer). `call(tool, **args)` runs one tool call in a beat of its own."""
    said: list[tuple[str, dict, dict]] = []

    def run(tool, **args):
        out = call(tool, **args)
        assert "error" not in out, (tool, out)
        said.append((tool, args, out))
        return out

    # 1. The party at 1st level, as the levels 1–2 session makes it.
    run("create_character", name="Bram", sheet={"cls": "Fighter", "level": 1, "race": "Human", "hp_max": 12,
                                                 "ability_scores": FIGHTER})  # fmt: skip
    run("create_character", name="Dorna", sheet={"cls": "Cleric", "level": 1, "race": "Dwarf", "hp_max": 10,
                                                  "ability_scores": CLERIC})  # fmt: skip
    run("create_character", name="Elowen", sheet={"cls": "Wizard", "level": 1, "race": "Elf", "hp_max": 4,
                                                   "ability_scores": WIZARD})  # fmt: skip
    run("set_build", character="Bram", skills={"climb": 4, "jump": 4, "intimidate": 4}, feats=FIRST_FEATS,
        weapon="falchion", armor="scale mail")  # fmt: skip
    run("set_build", character="Dorna", skills={"concentration": 4}, domains=["war", "good"], weapon="warhammer",
        armor="scale mail", shield="heavy steel shield")  # fmt: skip
    run("set_build", character="Elowen", skills={"concentration": 4, "spellcraft": 4, "knowledge (arcana)": 4},
        feats=["improved initiative"], weapon="dagger")  # fmt: skip

    # 2. The XP for 3rd level, and two level-ups each.
    for name in ("Bram", "Dorna", "Elowen"):
        run("award_xp", character=name, amount=3000)
        run("update_character", ref=name, patch={"level": 2}, reason="2nd level")
        run("update_character", ref=name, patch={"level": 3}, reason="3rd level")

    # 3. What the levels gave: Bram's fighter bonus feat at 2nd and his feat at 3rd, and everyone's skill points.
    run("set_build", character="Bram", skills={"climb": 6, "jump": 6, "intimidate": 6},
        feats=[*FIRST_FEATS, "improved initiative", "great fortitude"])  # fmt: skip
    run("set_build", character="Dorna", skills={"concentration": 6})
    run("set_build", character="Elowen", skills={"concentration": 6, "spellcraft": 6, "knowledge (arcana)": 6})

    # 4. Spells: 2nd-level ones into the new slots, Spiritual Weapon in Dorna's 2nd-level domain slot (war's 2nd).
    run("memorize_spells", character="Dorna", spells=["Bless", "Cure Light Wounds", "Shield of Faith", "Magic Weapon",
                                                        "Hold Person", "Aid", "Spiritual Weapon"])  # fmt: skip
    run("memorize_spells", character="Elowen", spells=["Sleep", "Magic Missile", "Shield", "Web", "Glitterdust"])
    run("cast_spell", character="Dorna", spell_name="Hold Person")
    run("cast_spell", character="Elowen", spell_name="Web")
    run("spell_status", character="Dorna")
    run("spell_status", character="Elowen")
    run("get_character", ref="Bram")
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
    """`value` with ids by name: characters by theirs, roll ids and times as placeholders."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    for c in storage.characters.list(campaign_id):
        text = text.replace(c.id, c.name)
    text = re.sub(r'"(roll|note|hr)_[0-9a-f]{12}"', r'"<\1 id>"', text)
    text = re.sub(r'"\d{4}-\d\d-\d\dT[^"]+"', '"<time>"', text)
    return json.loads(text)


def test_the_level_3_session_matches_its_golden(seeded_call, srd35_storage, srd35_campaign):
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
