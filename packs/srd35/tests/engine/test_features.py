"""The class features reader (DEL-389): a sheet's granted features from `features.json` by its class levels, their
bonuses and uses a day, weapon proficiency and the casting classes. The four Phase 2 slice classes read the same
numbers as they did from the engine's constants (`fixtures/phase2_derived.json`, saved from that engine)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from delve_srd35.engine import features, numbers
from delve_srd35.reference import Srd35Reference
from srd35_phase3 import PHASE3_COMBATANT_KEYS, PHASE3_KEYS, without_phase3

from delve.domain.characters import Sheet

REF = Srd35Reference()
TEN = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "phase2_derived.json"


def sheet(cls: str, levels: dict[str, int], race: str = "Human", d20: dict | None = None, **abilities) -> Sheet:
    return Sheet(cls=cls, race=race, levels=levels, ability_scores={**TEN, **abilities}, d20=d20 or {})


def weapon(wid: str, category: str) -> dict:
    return {"id": wid, "category": category}


def test_a_rogue_4_has_uncanny_dodge_and_2d6_sneak():
    got = {f["id"]: f for f in features.granted(sheet("Rogue", {"rogue": 4}))}
    assert got["uncanny-dodge"]["kind"] == "feat" and got["sneak-attack"]["value"] == "2d6"
    assert got["sneak-attack"]["class"] == "rogue" and "special-ability" not in got  # a 10th-level feature


def test_turning_per_day_is_3_plus_cha():
    turn = next(f for f in features.granted(sheet("Cleric", {"cleric": 1}, cha=14)) if f["id"] == "turn-undead")
    assert turn["value"] == 3 and turn["ability"] == "cha"
    assert features.per_day(turn, {"cha": 2}) == 5
    assert features.per_day(turn, {"cha": -5}) == 0  # at least 0


def test_extra_turning_counts_once_in_the_feature_and_the_total():
    # Cleric 1, Cha 14 (+2), Extra Turning: 3 + 2 + 4 = 9, in the feature's per_day and in turning_per_day alike.
    cleric = sheet("Cleric", {"cleric": 1}, d20={"feats": ["extra-turning"]}, cha=14)
    found = numbers.derived(cleric, REF)
    turn = next(f for f in found["features"] if f["id"] == "turn-undead")
    assert turn["per_day"] == found["turning_per_day"] == 9


def test_a_use_without_a_table_has_no_value_and_no_uses():
    # Lay on hands is Cha x paladin level in hit points, not uses: no by_level, so no value.
    got = {f["id"]: f for f in features.granted(sheet("Paladin", {"paladin": 2}))}
    assert got["lay-on-hands"]["value"] is None and features.per_day(got["lay-on-hands"], {"cha": 3}) == 0


def test_bonus_sums_the_rows_whose_condition_holds():
    monk = features.granted(sheet("Monk", {"monk": 6}))
    assert features.bonus(monk, "speed", set()) == 0
    assert features.bonus(monk, "speed", {"unarmoured_unencumbered"}) == 20  # fast movement at 6th
    assert features.bonus(monk, "ac", {"unarmoured_unencumbered"}) == 1  # 5th level's +1
    druid = features.granted(sheet("Druid", {"druid": 1}))
    assert features.bonus(druid, "skill:survival", set()) == 2  # nature sense, a row with `targets`
    assert features.bonus(features.granted(sheet("Barbarian", {"barbarian": 1})), "speed", {"no_heavy_load"}) == 10


def test_proficiency_by_the_class_rows():
    rogue, wizard = sheet("Rogue", {"rogue": 1}), sheet("Wizard", {"wizard": 1})
    assert features.proficient(rogue, weapon("rapier", "martial"), "humans")
    assert not features.proficient(rogue, weapon("longsword", "martial"), "humans")
    assert features.proficient(wizard, weapon("dagger", "simple"), "humans")
    assert not features.proficient(wizard, weapon("mace-light", "simple"), "humans")
    assert features.proficient(wizard, weapon("longsword", "martial"), "elves")  # the elves' weapons
    assert not features.proficient(sheet("Fighter", {"fighter": 1}), weapon("waraxe-dwarven", "exotic"), "humans")
    assert features.proficient(sheet("Fighter", {"fighter": 1}), weapon("waraxe-dwarven", "exotic"), "dwarves")
    assert features.proficient(sheet("Thief", {}), weapon("longsword", "martial"), "humans")  # no class row: the DM's


def test_casters_and_arcane():
    assert features.casters(sheet("Wizard", {"wizard": 1})) == {"wizard": "int"}
    assert features.casters(sheet("Cleric", {"cleric": 3})) == {"cleric": "wis"}
    assert features.casters(sheet("Rogue", {"rogue": 4})) == {}
    assert features.casters(sheet("Paladin", {"paladin": 3})) == {}  # a paladin casts from 4th
    assert features.casters(sheet("Paladin", {"paladin": 4})) == {"paladin": "wis"}
    assert features.arcane(sheet("Wizard", {"wizard": 1})) and features.arcane(sheet("Bard", {"bard": 1}))
    assert not features.arcane(sheet("Cleric", {"cleric": 1})) and not features.arcane(sheet("Fighter", {"fighter": 1}))


def _phase2_sheets() -> list:
    return [pytest.param(Sheet(**saved["sheet"]), saved["derived"], id=saved["name"])
            for saved in json.loads(FIXTURE.read_text("utf-8"))]  # fmt: skip


@pytest.mark.parametrize(("before", "after"), _phase2_sheets())
def test_a_phase_2_build_reads_the_same(before, after):
    # The 3rd-level Bram, Dorna and Elowen as `test_scripted_session_level3` leaves them, and a 1st- and a 4th-level
    # rogue: the derived numbers saved by Phase 2's engine are in the fixture.
    # Phase 3's own keys (`srd35_phase3.PHASE3_KEYS`) postdate the fixture; every other key and number is Phase 2's.
    got = numbers.derived(before, REF)
    # `features` is on every sheet; the other keys (`dr`, `favoured_enemy`) only where a class gives them.
    assert "features" in got
    assert without_phase3({"derived": got})["derived"] == after


def test_the_strip_drops_only_the_listed_keys():
    saved = {"bab": 1, "sneak": ""}
    listed = {"derived": {**saved, **{key: [] for key in PHASE3_KEYS}}}
    assert without_phase3(listed) == {"derived": saved}
    unlisted = {"derived": {**saved, "not_a_phase3_key": 0}}
    assert without_phase3(unlisted) != {"derived": saved}
    # Only under a `derived` key: elsewhere a listed key stays.
    assert without_phase3({"answer": {"features": [1]}}) == {"answer": {"features": [1]}}
    assert without_phase3([{"sheet": {"d20": listed}}]) == [{"sheet": {"d20": {"derived": saved}}}]


def test_the_strip_drops_only_the_listed_combatant_keys():
    # A combatant's `d20` in a fight's `combatants` loses `PHASE3_COMBATANT_KEYS` (the monster's row id), and only
    # those; an unlisted key still differs, and a listed key elsewhere (not a combatant's d20) stays.
    saved = {"ac": 13, "saves": {"fort": 3}}
    listed = {
        "combat": {"combatants": [{"id": "mon_1", "d20": {**saved, **dict.fromkeys(PHASE3_COMBATANT_KEYS, "orc")}}]}
    }
    assert without_phase3(listed) == {"combat": {"combatants": [{"id": "mon_1", "d20": saved}]}}
    unlisted = {"combat": {"combatants": [{"id": "mon_1", "d20": {**saved, "not_a_phase3_key": 0}}]}}
    assert without_phase3(unlisted) != {"combat": {"combatants": [{"id": "mon_1", "d20": saved}]}}
    elsewhere = {"answer": {"d20": {"monster": "orc"}}, "combatants": [{"monster": "orc"}]}
    assert without_phase3(elsewhere) == elsewhere
