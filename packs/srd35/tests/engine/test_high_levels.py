"""Levels 6 to 20 under 3.5 (DEL-389 part 2): the live party at 6th level reads as it did, the XP and the hints past
5th level, and the weekly uses.

`fixtures/live_party_level6.json` is the owner's live party as Phase 2's builds make it: a 6th-level fighter, cleric,
wizard and rogue, each built through `create_character`, `set_build` and `update_character` with seeded dice (`build`),
with the derived numbers the engine gave them before part 2 changed it. It was written once, by the engine of part 1,
before part 2's first change; it is never regenerated. A missing fixture is written and the test fails."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from delve_srd35.engine import Srd35Engine, numbers, progress
from delve_srd35.reference import Srd35Reference
from srd35_phase3 import without_phase3

from delve.domain.characters import CharacterState, Sheet

REF = Srd35Reference()
ENGINE = Srd35Engine(REF)
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "live_party_level6.json"

FIGHTER = {"str": 16, "dex": 13, "con": 14, "int": 10, "wis": 12, "cha": 8}
CLERIC = {"str": 14, "dex": 10, "con": 14, "int": 10, "wis": 15, "cha": 12}
WIZARD = {"str": 8, "dex": 16, "con": 10, "int": 17, "wis": 12, "cha": 10}
ROGUE = {"str": 12, "dex": 16, "con": 12, "int": 14, "wis": 10, "cha": 13}


def build(call) -> list[dict]:
    """The party at 1st level, the XP for 6th (15,000) and five level-ups each, then the builds the levels allow:
    the fighter's feats (1st, human, fighter 1st, 2nd, 4th and 6th bonus, 3rd and 6th), the ability increase at 4th,
    skill ranks to 9 (6 + 3). Each character: its sheet as stored and its derived numbers."""

    def run(tool, **args):
        out = call(tool, **args)
        assert "error" not in out, (tool, out)
        return out

    party = (
        ("Bram", "Fighter", "Human", 12, FIGHTER),
        ("Dorna", "Cleric", "Dwarf", 10, CLERIC),
        ("Elowen", "Wizard", "Elf", 4, WIZARD),
        ("Pip", "Rogue", "Halfling", 7, ROGUE),
    )
    for name, cls, race, hp, scores in party:
        run("create_character", name=name, sheet={"cls": cls, "level": 1, "race": race, "hp_max": hp,
                                                   "ability_scores": scores})  # fmt: skip
    run("set_build", character="Bram", skills={"climb": 4, "jump": 4, "intimidate": 4},
        feats=["power attack", "cleave", {"id": "weapon focus", "choice": "longsword"}], weapon="longsword",
        armor="banded mail", shield="heavy steel shield")  # fmt: skip
    run("set_build", character="Dorna", skills={"concentration": 4}, domains=["war", "good"], weapon="warhammer",
        armor="scale mail", shield="heavy steel shield")  # fmt: skip
    run("set_build", character="Elowen", skills={"concentration": 4, "spellcraft": 4, "knowledge (arcana)": 4},
        feats=["improved initiative"], weapon="dagger")  # fmt: skip
    run("set_build", character="Pip", skills={"hide": 4, "move silently": 4, "open lock": 4, "disable device": 4,
                                              "search": 4, "spot": 4, "listen": 4, "tumble": 4},
        feats=["improved initiative"], weapon="short sword", armor="leather")  # fmt: skip
    for name, *_ in party:
        run("award_xp", character=name, amount=15000)
        for level in range(2, 7):
            run("update_character", ref=name, patch={"level": level}, reason=f"level {level}")
    run("update_character", ref="Bram", patch={"ability_scores": {**FIGHTER, "str": 17}}, reason="4th level")
    run("update_character", ref="Dorna", patch={"ability_scores": {**CLERIC, "wis": 16}}, reason="4th level")
    run("update_character", ref="Elowen", patch={"ability_scores": {**WIZARD, "int": 18}}, reason="4th level")
    run("update_character", ref="Pip", patch={"ability_scores": {**ROGUE, "dex": 17}}, reason="4th level")
    run("set_build", character="Bram", skills={"climb": 9, "jump": 9, "intimidate": 9},
        feats=["power attack", "cleave", {"id": "weapon focus", "choice": "longsword"}, "improved initiative",
               "great fortitude", {"id": "weapon specialization", "choice": "longsword"}, "great cleave",
               "iron will"])  # fmt: skip
    run("set_build", character="Dorna", skills={"concentration": 9}, feats=["toughness", "combat casting"])
    run("set_build", character="Elowen", skills={"concentration": 9, "spellcraft": 9, "knowledge (arcana)": 9},
        feats=["improved initiative", {"id": "spell focus", "choice": "evocation"}, "lightning reflexes"])  # fmt: skip
    run("set_build", character="Pip", skills={"hide": 9, "move silently": 9, "open lock": 9, "disable device": 9,
                                              "search": 9, "spot": 9, "listen": 9, "tumble": 9},
        feats=["improved initiative", "weapon finesse", "dodge"])  # fmt: skip
    out = []
    for name, *_ in party:
        sheet = run("get_character", ref=name)["sheet"]
        out.append({"name": name, "sheet": sheet, "derived": sheet["d20"]["derived"]})
    return out


@pytest.fixture
def live_party(srd35_storage, srd35_campaign):
    """[(the stored sheet, its derived numbers before part 2)] for the four, from the fixture."""
    if not FIXTURE.exists():
        from delve.dice import SeededRng
        from delve.dm.tools import ToolHost
        from tests.fixtures.rulesets import srd35_catalogs

        seeds, beats = itertools.count(1), itertools.count(1)
        host = ToolHost(srd35_storage, lambda: SeededRng(next(seeds)), catalogs=srd35_catalogs())
        party = build(lambda tool, /, **args: host.call(srd35_campaign.id, f"beat-{next(beats)}", tool, args))
        FIXTURE.write_text(json.dumps(party, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        pytest.fail("fixture written: check it")
    return [(Sheet.from_dict(c["sheet"]), c["derived"]) for c in json.loads(FIXTURE.read_text())]


def test_the_live_party_reads_the_same(live_party):
    assert [s.levels for s, _ in live_party] == [{"fighter": 6}, {"cleric": 6}, {"wizard": 6}, {"rogue": 6}]
    for before, after in live_party:
        assert without_phase3({"derived": numbers.derived(before, REF)}) == without_phase3({"derived": after})


def _phase2(sheet: Sheet, derived: dict) -> Sheet:
    """The sheet as the live party's are stored: derived numbers from before part 1, without `PHASE3_KEYS`."""
    from dataclasses import replace

    from srd35_phase3 import PHASE3_KEYS

    old = {key: value for key, value in derived.items() if key not in PHASE3_KEYS}
    return replace(sheet, d20={**(sheet.d20 or {}), "derived": old})


def test_stale_stored_numbers_are_worked_again(live_party, srd35_call, srd35_storage, srd35_campaign):  # DEL-389
    # The live party's stored derived numbers have no features (Phase 2's engine gave none): the sheet's numbers and
    # use_feature work them again, so the rogue's sneak attack, uncanny dodge and trap sense show, and the cleric
    # turns.
    sheets = [_phase2(sheet, derived) for sheet, derived in live_party]
    assert all("features" not in (s.d20 or {})["derived"] for s in sheets)
    ids = [[f["id"] for f in ENGINE.sheet_numbers(s)["features"]] for s in sheets]
    assert {"sneak-attack", "uncanny-dodge", "trap-sense"} <= set(ids[3])
    assert "turn-undead" in ids[1]
    rogue = ENGINE.sheet_numbers(sheets[3])
    assert rogue["bab"] == 4 and [f["value"] for f in rogue["features"] if f["id"] == "sneak-attack"] == ["3d6"]
    # use_feature reads the features the same way: a barbarian 6 stored as Phase 2 stored its sheets rages.
    barbarian = Sheet(label="Krug", cls="Barbarian", race="Human", levels={"barbarian": 6}, hp_max=60,
                      ability_scores=TEN)  # fmt: skip
    filled = ENGINE.fill_derived(barbarian, REF)
    stale = _phase2(filled, filled.d20["derived"])
    srd35_storage.characters.create(srd35_campaign.id, "Krug", kind="pc", sheet=stale, state=CharacterState(hp=60))
    out = srd35_call("use_feature", character="Krug", feature="rage")
    assert "error" not in out and out["effect"]["name"] == "Rage", out


# --- XP and levels past 5th ---------------------------------------------------------------------------------------


def test_level_6_has_a_next_level():
    # Unearthed Arcana's Table 6-13 (`data/xp.json`): 6th level is 16,000 XP, 7th 24,000; 19th 1,800,000, 20th
    # 2,600,000. A fighter 6 with 17,000 XP is 6th, and 7th is next; with 24,000 it is ready for 7th.
    fighter = Sheet(cls="Fighter", race="Human", levels={"fighter": 6}, ability_scores=TEN)
    found = progress.progress(fighter, CharacterState(xp=17000), REF)
    assert (found.level, found.xp, found.xp_next, found.ready) == (6, 17000, 24000, ())
    assert progress.progress(fighter, CharacterState(xp=24000), REF).ready == ("fighter",)
    nineteen = Sheet(cls="Fighter", race="Human", levels={"fighter": 19}, ability_scores=TEN)
    found = progress.progress(nineteen, CharacterState(xp=1900000), REF)
    assert (found.level, found.xp_next, found.ready) == (19, 2600000, ())


def test_level_20_is_the_top(srd35_call):
    # Fighter 20 with 2,600,000 XP (Table 6-13's 20th): 50,000 more XP is added (the SRD has no cap on XP), but there
    # is no 21st level: no next XP, no class ready, and the answer says so.
    out = srd35_call("create_character", name="Vorn", sheet={"cls": "Fighter", "level": 20, "race": "Human",
                                                             "hp_max": 150, "ability_scores": TEN})  # fmt: skip
    assert "error" not in out, out
    srd35_call("update_character", ref="Vorn", patch={"xp": 2600000}, reason="20th level's XP")
    out = srd35_call("award_xp", character="Vorn", amount=50000)
    assert (out["xp_total"], out["level"], out["xp_next"], out["level_up_hints"]) == (2650000, 20, None, [])
    assert "20th level is the top" in out["xp_note"]


def test_fighter_6_gets_a_feat_and_a_bonus_feat():
    # Fighter 6: 2 + Int 0 + 1 (human) = 3 skill points; a feat (6 is a multiple of 3); the fighter's bonus feat at
    # 6th; no ability increase (4th and 8th).
    fighter = Sheet(cls="Fighter", race="Human", levels={"fighter": 6}, ability_scores=TEN)
    assert progress.hints(fighter, "fighter", REF) == ["3 skill points", "a feat", "a fighter bonus feat"]
    # Fighter 12: a feat, a bonus feat and an ability increase; wizard 10: its bonus feat, no feat (10 % 3).
    twelve = Sheet(cls="Fighter", race="Human", levels={"fighter": 12}, ability_scores=TEN)
    assert progress.hints(twelve, "fighter", REF) == ["3 skill points", "a feat", "a fighter bonus feat",
                                                      "an ability increase"]  # fmt: skip
    wizard = Sheet(cls="Wizard", race="Elf", levels={"wizard": 10}, ability_scores=TEN)
    assert progress.hints(wizard, "wizard", REF) == ["2 skill points", "a wizard bonus feat"]


# --- weekly uses ---------------------------------------------------------------------------------------------------


def test_remove_disease_is_weekly_on_the_sheet():
    paladin = ENGINE.fill_derived(Sheet(cls="Paladin", race="Human", levels={"paladin": 6}, ability_scores=TEN), REF)
    found = next(f for f in paladin.d20["derived"]["features"] if f["id"] == "remove-disease")
    assert (found["per_day"], found["per"]) == (1, "week")
    shown = next(f for f in ENGINE.sheet_numbers(paladin)["features"] if f["id"] == "remove-disease")
    assert shown["per"] == "week"
    # Paladin 9: 2 a week.
    nine = numbers.derived(Sheet(cls="Paladin", race="Human", levels={"paladin": 9}, ability_scores=TEN), REF)
    assert next(f["per_day"] for f in nine["features"] if f["id"] == "remove-disease") == 2


def test_a_rest_under_a_week_leaves_weekly_uses():
    paladin = Sheet(cls="Paladin", race="Human", levels={"paladin": 6}, hp_max=40, ability_scores=TEN)
    spent = CharacterState(hp=40, d20={"used": {"remove-disease": 1, "lay-on-hands": 2}})
    rested, _ = ENGINE.rest(paladin, spent, 6)
    assert rested.d20["used"] == {"remove-disease": 1}
    rested, _ = ENGINE.rest(paladin, spent, 7)
    assert rested.d20["used"] == {}
    rested, _ = ENGINE.rest(paladin, spent, 0)
    assert rested.d20["used"] == {"remove-disease": 1, "lay-on-hands": 2}


def test_remove_disease_is_weekly(srd35_call):
    # Paladin 6: remove disease 1 a week. Used, it is refused until a rest of 7 days; a rest of 1 day doesn't give it
    # back.
    out = srd35_call("create_character", name="Aldra", sheet={"cls": "Paladin", "level": 6, "race": "Human",
                                                              "hp_max": 45, "ability_scores": {**TEN, "cha": 14}})  # fmt: skip
    assert "error" not in out, out
    out = srd35_call("use_feature", character="Aldra", feature="remove disease", target="Aldra")
    assert "error" not in out, out
    assert out["uses_left"] == 0
    refused = srd35_call("use_feature", character="Aldra", feature="remove disease")
    assert refused["error"] == "Remove disease: 1 a week at this level, used 1."
    srd35_call("rest", character="Aldra", days=1)
    assert "error" in srd35_call("use_feature", character="Aldra", feature="remove disease")
    srd35_call("rest", character="Aldra", days=7)
    assert "error" not in srd35_call("use_feature", character="Aldra", feature="remove disease")
