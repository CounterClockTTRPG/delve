"""Exhausted (DEL-435): the engine reads it wherever it reads fatigued, at 6 off Str and Dex instead of 2, and halves
speed. Each number is worked by hand in its comment."""

from __future__ import annotations

import pytest
from delve_srd35.engine import class_features, numbers
from test_class_features import REF, Fight


@pytest.fixture
def fight(srd35_call, srd35_storage, srd35_campaign):
    return Fight(srd35_call, srd35_storage, srd35_campaign)


def _rogue(fight, name, **conditions):
    # Rogue 1, Dex 18 (+4), Str 10; Escape Artist: 4 ranks + Dex 4 = +8.
    fight.character(name, "Rogue", 1, scores={"dex": 18, "str": 10}, skills={"escape-artist": 4})
    if conditions:
        fight.call("update_character", ref=name, patch=conditions, reason="a captive")


def test_exhausted_takes_six_from_str_and_dex(fight):
    # Dex 18 less 6 is 12 (+1), not 18 (+4): Escape Artist +8 becomes +5, initiative +4 becomes +1, Reflex 3 lower.
    _rogue(fight, "Elsse")
    rested = fight.call("skill_check", character="Elsse", skill="escape artist", dc=10)["bonus"]
    rested_ref = fight.call("saving_throw", character="Elsse", save_type="ref", dc=10)["base"]
    fight.call("update_character", ref="Elsse", patch={"conditions": ["exhausted"]}, reason="a captive")
    assert fight.call("skill_check", character="Elsse", skill="escape artist", dc=10)["bonus"] == rested - 3
    assert fight.call("saving_throw", character="Elsse", save_type="ref", dc=10)["base"] == rested_ref - 3
    _rogue(fight, "Bree")
    fight.enemies("orc")
    elsse, bree = fight.combatant("Elsse"), fight.combatant("Bree")
    assert elsse.d20["init_bonus"] == bree.d20["init_bonus"] - 3
    assert elsse.d20["saves"]["ref"] == bree.d20["saves"]["ref"] - 3
    assert elsse.d20["ac"] == bree.d20["ac"] - 3


def test_exhausted_halves_speed(fight):
    fight.character("Tor", "Fighter", 1)
    sheet = fight.state("Tor").sheet
    assert sheet.movement_rate == 30
    tired = class_features.tired(sheet, class_features.EXHAUSTION)
    assert tired.movement_rate == 15
    assert numbers.derived(tired, REF)["speed"] == 15
    assert class_features.tired(sheet).movement_rate == 30  # fatigued keeps it


def test_exhausted_replaces_fatigued(fight):
    # Both on one character: -6, not -8.
    _rogue(fight, "Elsse")
    fight.call("update_character", ref="Elsse", patch={"conditions": ["exhausted"]}, reason="a captive")
    exhausted = fight.call("skill_check", character="Elsse", skill="escape artist", dc=10)["bonus"]
    fight.call("update_character", ref="Elsse", patch={"conditions": ["fatigued", "exhausted"]}, reason="both")
    assert fight.call("skill_check", character="Elsse", skill="escape artist", dc=10)["bonus"] == exhausted
    assert class_features.penalty_of(["fatigued", "exhausted"]) == 6


def test_an_exhausted_barbarian_cant_rage(fight):
    fight.character("Krug", "Barbarian", 1)
    fight.call("update_character", ref="Krug", patch={"conditions": ["exhausted"]}, reason="a march")
    assert "error" in fight.call("use_feature", character="Krug", feature="rage")


def test_a_rest_clears_exhaustion(fight):
    fight.character("Krug", "Barbarian", 1)
    fight.call("update_character", ref="Krug", patch={"conditions": ["exhausted", "fatigued"]}, reason="a march")
    out = fight.call("rest", character="Krug", days=1)
    assert out["fatigue_cleared"] == ["Krug"]
    assert not {"exhausted", "fatigued"} & set(fight.state("Krug").state.conditions)
