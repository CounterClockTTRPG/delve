"""Characters under a d20 engine (DEL-387): derived numbers, XP, level-ups, drain and rest come from the engine."""

from dataclasses import replace

import pytest

from delve.domain.characters import CharacterState
from delve.play import characters
from delve.play.context import context_for
from tests.fixtures.d20 import d20_catalogs, fake_engine
from tests.fixtures.rulesets import osric_catalogs


@pytest.fixture
def ctx(d20_storage, d20_campaign):
    fake_engine().called.clear()
    return context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())


def _fighter(ctx, level=1):
    return characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": level, "hp_max": 12})


def test_create_fills_from_the_engine(ctx):
    character = _fighter(ctx, 2)
    assert character.sheet.d20 == {"attack": 2, "defence": 12, "save": 3, "pool": 2}
    assert character.sheet.thac0 == 20
    assert character.sheet.saves == {}
    assert "fill_derived" in fake_engine().called


def test_raising_a_level_levels_up_once_per_level(ctx):
    character = _fighter(ctx, 2)
    fake_engine().called.clear()
    saved = characters.update(ctx, character.id, {"level": 4})
    assert saved.sheet.levels == {"fighter": 4}
    assert saved.sheet.d20["attack"] == 4
    assert "level_up" in fake_engine().called


def test_a_lower_level_fills_again(ctx):
    character = _fighter(ctx, 3)
    fake_engine().called.clear()
    saved = characters.update(ctx, character.id, {"level": 1})
    assert saved.sheet.d20["attack"] == 1
    assert "fill_derived" in fake_engine().called and "level_up" not in fake_engine().called


def test_award_xp_is_one_total(ctx):
    character = _fighter(ctx)
    out = characters.award_xp(ctx, character.id, 1500)
    assert out["xp_total"] == 1500 and out["xp_gained"] == 1500
    assert out["level"] == 2 and out["xp_next"] == 2000
    assert out["level_up_hints"] == ["fighter"]
    assert "per_class" not in out and "xp_bonus" not in out
    assert {"award_xp", "progress"} <= fake_engine().called


def test_drain_takes_a_level(ctx):
    character = _fighter(ctx, 2)
    out = characters.drain_level(ctx, character.id, 1)
    assert out["levels_after"] == {"fighter": 1}
    assert "thac0" not in out and "saves" not in out
    assert out["d20"] == {"slain": False, "levels": 1, "class": "fighter"}
    assert "drain" in fake_engine().called


def test_a_slaying_drain_kills(ctx):
    character = _fighter(ctx, 1)
    out = characters.drain_level(ctx, character.id, 1)
    assert out["slain"] is True and out["hp"] == -10
    # In d20 terms: no "below 1st level" (a d20 drain gives negative levels).
    assert out["note"] == (
        "Slain by the drain: its negative levels reached the character's level, or its hit points went past dead. "
        "The monster's entry says whether and when the victim rises."
    )


def test_rest_restores_the_pool(ctx):
    character = _fighter(ctx)
    ctx.storage.characters.save_state(
        character.__class__(**{**character.__dict__, "state": CharacterState(hp=5, d20={"used": 2})})
    )
    out = characters.rest(ctx, character.id, days=1)
    assert out["healing"]["Bram"]["d20"] == {"healed": 1, "basis": "fake rest, 1 hp a day"}
    assert characters.get(ctx, character.id).state.d20 == {"used": 0}
    assert "rest" in fake_engine().called
    assert "rate_per_day" not in out and out["basis"] == "fake rest, 1 hp a day"


def test_bed_rest_reaches_the_engine(ctx):
    character = _fighter(ctx)
    ctx.storage.characters.save_state(character.__class__(**{**character.__dict__, "state": CharacterState(hp=5)}))
    out = characters.rest(ctx, character.id, days=2, bed_rest=True)
    assert out["healing"]["Bram"]["hp_after"] == 9
    assert out["basis"] == "fake rest, 2 hp a day" and "rate_per_day" not in out


def test_full_rest_still_restores_after_the_engine(ctx):
    character = _fighter(ctx)
    ctx.storage.characters.save_state(character.__class__(**{**character.__dict__, "state": CharacterState(hp=5)}))
    out = characters.rest(ctx, character.id, days=1, full=True)
    assert out["healing"]["Bram"]["hp_after"] == 12 and "rest" in fake_engine().called
    assert out["basis"].startswith("DM override")


def test_a_sheet_patch_fills_again(ctx):
    character = _fighter(ctx)
    fake_engine().called.clear()
    characters.update(ctx, character.id, {"ability_scores": {"str": 16}})
    assert "fill_derived" in fake_engine().called and "level_up" not in fake_engine().called


def test_a_state_patch_alone_fills_nothing(ctx):
    character = _fighter(ctx)
    fake_engine().called.clear()
    characters.update(ctx, character.id, {"hp": 3})
    assert "fill_derived" not in fake_engine().called


def test_osric_is_unchanged(d20_storage, d20_campaign):
    module = d20_storage.modules.create("Other")
    revision = d20_storage.revisions.snapshot(module.id)
    campaign = d20_storage.campaigns.create("Old", module.id, revision.number, ruleset="osric", setting="greyhawk")
    ctx = context_for(d20_storage, campaign.id, "beat-1", catalogs=osric_catalogs())
    character = characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": 1, "hp_max": 12})
    assert character.sheet.d20 is None and character.sheet.saves
    out = characters.award_xp(ctx, character.id, 100)
    assert set(out) == {"character_id", "name", "xp_gained", "xp_total", "per_class", "level_up_hints"}
    rested = characters.rest(ctx, character.id, days=1)
    assert "rate_per_day" in rested and "hp/day" in rested["basis"]


def test_a_level_up_gains_its_hit_points(ctx, monkeypatch):  # R19
    # The engine's level-up gives 4 hit points (as srd35's: a d10 face 2 + Con 2): Bram, at 12 of 12, is at 16 of 16.
    engine = type(fake_engine())
    level_up = engine.level_up
    monkeypatch.setattr(engine, "level_up", lambda self, sheet, cls, ref, dice: replace(
        level_up(self, sheet, cls, ref, dice), hp_max=sheet.hp_max + 4))  # fmt: skip
    character = _fighter(ctx)
    saved = characters.update(ctx, character.id, {"level": 2})
    assert (saved.sheet.hp_max, saved.state.hp) == (16, 16)
    # Wounded, the gain is on top of what is left; a hit point patch given with the level is the DM's.
    characters.update(ctx, character.id, {"hp": 5})
    assert characters.update(ctx, character.id, {"level": 3}).state.hp == 9
    assert characters.update(ctx, character.id, {"level": 4, "hp": 7}).state.hp == 7
    # A dead character stays dead.
    characters.update(ctx, character.id, {"hp": -10})
    assert characters.update(ctx, character.id, {"level": 5}).state.hp == -10


def test_an_osric_level_patch_leaves_hp_alone(d20_storage, d20_campaign):  # R19
    module = d20_storage.modules.create("Other")
    revision = d20_storage.revisions.snapshot(module.id)
    campaign = d20_storage.campaigns.create("Old", module.id, revision.number, ruleset="osric", setting="greyhawk")
    ctx = context_for(d20_storage, campaign.id, "beat-1", catalogs=osric_catalogs())
    character = characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": 1, "hp_max": 12})
    saved = characters.update(ctx, character.id, {"level": 2, "hp_max": 20})
    assert (saved.sheet.hp_max, saved.state.hp) == (20, 12)


def test_a_seat_never_sees_the_build_warnings(ctx):  # DEL-398
    # The engine's build warnings (an unknown race, armour or skill, a feat without its prerequisites) are the DM's
    # to fix: the organiser's view keeps them, a player seat's JSON has none, at any depth of the sheet's d20.
    from delve.web.routes.characters import character_json, player_character_json

    made = _fighter(ctx)
    d20 = {**made.sheet.d20, "warnings": ["top"], "derived": {"ac": 12, "warnings": ["Unknown race 'Elfish'."]}}
    bram = ctx.storage.characters.save_sheet(replace(made, sheet=replace(made.sheet, d20=d20)))
    dm = character_json(bram, ctx, ctx.storage)
    assert dm["sheet"]["d20"]["derived"]["warnings"] == ["Unknown race 'Elfish'."]
    assert dm["sheet"]["d20"]["warnings"] == ["top"]
    seat = player_character_json(bram, ctx, ctx.storage)
    assert seat["sheet"]["d20"] == {**made.sheet.d20, "derived": {"ac": 12}}
