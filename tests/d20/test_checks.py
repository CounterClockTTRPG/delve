"""Saves, checks and turning undead under a d20 engine (DEL-387): each asks the engine, not the classic tables."""

from dataclasses import replace

import pytest

from delve.dice import Dice, SeededRng
from delve.domain.characters import Effect
from delve.play import characters
from delve.play.context import context_for
from delve.rules.classic import combat as rules
from tests.fixtures.d20 import d20_catalogs, fake_engine


@pytest.fixture
def ctx(d20_storage, d20_campaign):
    fake_engine().called.clear()
    return context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())


@pytest.fixture
def fighter(ctx):
    return characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": 2, "hp_max": 12})


def test_a_save_out_of_combat_uses_the_engine(ctx, fighter, d20_call):
    out = d20_call("saving_throw", character="Bram", save_type="whatever")
    assert out["needed"] == 15 - fighter.sheet.d20["save"]
    assert "save" in fake_engine().called


def test_a_save_in_combat_uses_the_engine(ctx, fighter):
    fight, _ = rules.start([fighter], rules=ctx.rules)
    member = fight.combatants[fighter.id]
    fight = replace(fight, combatants={**fight.combatants, member.id: replace(member, d20={"save": 4})})
    dice = Dice(SeededRng(1), ctx.storage.rolls, ctx.campaign_id, "beat-1/cmb")
    _, out = rules.saving_throw(fight, dice, ctx.lookups, member.id, "x", d20=fake_engine(), rules=ctx.rules)
    assert out["needed"] == 11 and out["save_type"] == "x" and out["round"] == fight.round
    assert "save" in fake_engine().called


def test_skill_and_ability_checks_use_the_engine(ctx, fighter, d20_call):
    skill = d20_call("skill_check", character="Bram", skill="climb")
    assert skill["skill"] == "climb" and "needed" in skill and "skill_check" in fake_engine().called
    ability = d20_call("ability_check", character="Bram", ability="str", modifier=1)
    assert ability["ability"] == "str" and "ability_check" in fake_engine().called


def test_turning_uses_the_engine(ctx, fighter, d20_call):
    out = d20_call("turning_undead", level=3, undead="ghoul", character="Bram")
    assert out["undead"] == "ghoul" and "turned" in out
    assert "turn_undead" in fake_engine().called


def test_effects_save_modifiers_count_out_of_combat(ctx, fighter, d20_call):
    plain = d20_call("saving_throw", character="Bram", save_type="x")
    stored = characters.get(ctx, fighter.id)
    ctx.storage.characters.save_state(
        replace(stored, state=replace(stored.state, effects=(Effect("bless", 3, save=2),)))
    )
    blessed = d20_call("saving_throw", character="Bram", save_type="x", beat="beat-2")
    assert blessed["modifier"] == plain["modifier"] + 2


def _fight(ctx, fighter, effects=()):
    fight, _ = rules.start([fighter], rules=ctx.rules)
    member = fight.combatants[fighter.id]
    member = replace(member, d20={"save": 4}, effects=tuple(effects))
    return replace(fight, combatants={**fight.combatants, member.id: member}), member


def _dice(ctx):
    return Dice(SeededRng(1), ctx.storage.rolls, ctx.campaign_id, "beat-1/cmb")


def test_effects_save_modifiers_count_in_combat(ctx, fighter):
    fight, member = _fight(ctx, fighter, [Effect("bless", 3, save=2)])
    _, out = rules.saving_throw(fight, _dice(ctx), ctx.lookups, member.id, "x", d20=fake_engine(), rules=ctx.rules)
    assert out["modifier"] == 2 and out["needed"] == 15 - 4 - 2


def test_a_sheet_subject_uses_the_sheets_d20_save(ctx, fighter):
    fight, member = _fight(ctx, fighter)
    sheet = replace(fighter.sheet, d20={"save": 9})
    _, out = rules.saving_throw(
        fight, _dice(ctx), ctx.lookups, member.id, "x", sheet=sheet, d20=fake_engine(), rules=ctx.rules
    )
    assert out["base"] == 9 and out["needed"] == 6
