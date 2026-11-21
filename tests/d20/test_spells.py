"""Spells under a d20 engine (DEL-387): a caster with no slots casts from the engine's pool, and memorizing asks the
engine whether the levels are allowed."""

from dataclasses import replace

import pytest

from delve.play import characters, spells
from delve.play.context import NotFound, PlayError, context_for
from tests.fixtures.d20 import d20_catalogs, fake_engine


@pytest.fixture
def ctx(d20_storage, d20_campaign):
    fake_engine().called.clear()
    return context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())


def _caster(ctx, pool=1):
    made = characters.create(ctx, name="Mira", sheet={"cls": "Mage", "level": 1, "hp_max": 6})
    sheet = replace(made.sheet, d20={**made.sheet.d20, "pool": pool})
    return ctx.storage.characters.save_sheet(replace(made, sheet=sheet))


def test_a_pool_caster_casts_until_the_pool_is_spent(ctx):
    mira = _caster(ctx, pool=1)
    first = spells.cast(ctx, mira.id, "Magic Missile")
    assert first["cast"] is True and first["spell"] == "Magic Missile" and first["name"] == "Mira"
    assert first["character_id"] == mira.id and first["level"] == 1
    assert ctx.storage.characters.get(mira.id).state.d20["used"] == 1
    with pytest.raises(PlayError, match="No spells left to cast."):
        spells.cast(ctx, mira.id, "Magic Missile")
    assert ctx.storage.characters.get(mira.id).state.d20["used"] == 1
    assert "cast" in fake_engine().called


def test_memorize_asks_the_engine(ctx):
    mira = _caster(ctx)
    out = spells.memorize(ctx, mira.id, ["Magic Missile"])
    assert out["memorized"] == ["Magic Missile"]
    assert "can_memorize" in fake_engine().called


def test_memorize_obeys_an_engine_refusal(ctx, monkeypatch):
    mira = _caster(ctx)
    monkeypatch.setattr(type(fake_engine()), "can_memorize", lambda self, sheet, levels, spells=(): "Too many.")
    with pytest.raises(PlayError, match="Too many."):
        spells.memorize(ctx, mira.id, ["Magic Missile"])


def test_a_memorized_spell_is_spent_then_the_engine_casts(ctx):
    mira = _caster(ctx)
    spells.memorize(ctx, mira.id, ["Magic Missile"])
    fake_engine().called.clear()
    out = spells.cast(ctx, mira.id, "Magic Missile")
    assert out["remaining"] == {"1": 0}
    assert fake_engine().called.calls == ["cast"]  # the copy is spent as before; the engine then rolls its own part


def test_a_round_leaves_a_pool_casters_spell_alone(ctx, d20_call):
    mira = _caster(ctx)
    d20_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    out = d20_call(
        "combat_round", beat="beat-2", actions=[{"caster": "Mira", "spell": "Magic Missile", "target": "Goblin"}]
    )
    assert "error" not in out, out
    assert not (ctx.storage.characters.get(mira.id).state.d20 or {}).get("used")


def test_memorize_takes_the_level_the_engine_names(ctx, monkeypatch):
    # R16: under a d20 engine a named spell's level is the engine's for the caster, not the classic reference's.
    mira = _caster(ctx)
    asked = []

    def spell_level(self, sheet, name):
        asked.append((sheet.label, name))
        return 3

    monkeypatch.setattr(type(fake_engine()), "spell_level", spell_level)
    out = spells.memorize(ctx, mira.id, ["magic missile"])
    assert out["by_level"] == {"3": ["Magic Missile"]}
    assert ctx.storage.characters.get(mira.id).state.memorized[0].level == 3
    assert asked == [("Mira", "Magic Missile")]


def test_a_spell_on_none_of_the_casters_lists_is_refused(ctx, monkeypatch):
    mira = _caster(ctx)
    monkeypatch.setattr(type(fake_engine()), "spell_level", lambda self, sheet, name: None)
    with pytest.raises(NotFound, match="Magic Missile is on none of Mira's spell lists."):
        spells.memorize(ctx, mira.id, ["Magic Missile"])
    with pytest.raises(NotFound, match="on none of Mira's spell lists"):
        spells.set_loadout(ctx, mira.id, known={1: ["Magic Missile"]})
    assert ctx.storage.characters.get(mira.id).state.memorized == ()


def test_set_spell_loadout_asks_the_engine_too(ctx):
    mira = _caster(ctx)
    fake_engine().called.clear()
    out = spells.set_loadout(ctx, mira.id, known={1: ["magic missile"]})
    assert out["known"] == {"1": ["Magic Missile"]}
    assert "spell_level" in fake_engine().called


def test_an_unknown_spell_under_a_d20_engine_names_its_near_names(ctx):
    mira = _caster(ctx)
    with pytest.raises(NotFound) as caught:
        spells.memorize(ctx, mira.id, ["magic"])
    assert caught.value.message == "No spell 'magic'."
    # The near names, by name only: a d20 reference's spell has no one level or caster to give.
    assert caught.value.candidates and all(set(c) == {"name"} for c in caught.value.candidates)


def test_a_round_leaves_a_slotted_casters_pool_spell_alone(ctx, d20_call, monkeypatch):
    # DEL-389: a caster with slots whose spell has no uncast copy left, but the engine casts it from its pool (a
    # sorcerer/cleric's sorcerer spell), is skipped as a pool caster is: its pool is spent by `cast_spell`.
    mira = _caster(ctx)
    ctx.storage.characters.save_sheet(replace(mira, sheet=replace(mira.sheet, spell_slots={1: 1})))
    d20_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    action = [{"caster": "Mira", "spell": "Sleep", "target": "Goblin"}]
    refused = d20_call("combat_round", beat="beat-2", actions=action)
    assert "not memorized Sleep" in refused["error"], refused  # the fake says False: core's refusal stands
    monkeypatch.setattr(type(fake_engine()), "casts_unprepared", lambda self, sheet, spell: spell == "Sleep")
    out = d20_call("combat_round", beat="beat-3", actions=action)
    assert "error" not in out and "spells_spent" not in out, out
    assert not (ctx.storage.characters.get(mira.id).state.d20 or {}).get("used")
