"""Three additions to the d20 protocol (DEL-388): a cast gets the dice and may lose its spell, memorizing gets the
names, and turning keeps the state the engine returns."""

from dataclasses import replace

import pytest

from delve.dice import Dice
from delve.domain.characters import CharacterState
from delve.play import characters, spells
from delve.play.context import context_for
from tests.dm.tools.conftest import call, campaign, host, storage  # noqa: F401  (the OSRIC fixtures)
from tests.fixtures.d20 import d20_catalogs, fake_engine


@pytest.fixture
def ctx(d20_storage, d20_campaign):
    fake_engine().called.clear()
    return context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())


def _mira(ctx):
    made = characters.create(ctx, name="Mira", sheet={"cls": "Mage", "level": 1, "hp_max": 6})
    return ctx.storage.characters.save_sheet(replace(made, sheet=replace(made.sheet, spell_slots={1: 2})))


def test_cast_hands_the_engine_its_dice(ctx):
    mira = _mira(ctx)
    spells.memorize(ctx, mira.id, ["Magic Missile"])
    fake_engine().cast_dice = fake_engine().cast_actor = None
    out = spells.cast(ctx, mira.id, "Magic Missile")
    assert isinstance(fake_engine().cast_dice, Dice)
    assert fake_engine().cast_actor == mira.id  # the caster's own rolls are keyed by its id (DEL-395)
    assert out["spell"] == "Magic Missile" and "cast" not in out and out["remaining"] == {"1": 0}
    assert "refusal" not in out and "lost" not in out  # the fake cast it: its pool had room
    assert ctx.storage.characters.get(mira.id).state.d20 == {"used": 1}


def test_the_pool_cast_hands_the_engine_its_dice(ctx):
    made = characters.create(ctx, name="Pol", sheet={"cls": "Mage", "level": 1, "hp_max": 6})
    pooled = replace(made.sheet, d20={**made.sheet.d20, "pool": 1})
    ctx.storage.characters.save_sheet(replace(made, sheet=pooled))
    fake_engine().cast_dice = fake_engine().cast_actor = None
    spells.cast(ctx, made.id, "Magic Missile")
    assert isinstance(fake_engine().cast_dice, Dice)
    assert fake_engine().cast_actor == made.id


def test_a_lost_spell_stays_spent_and_does_not_raise(ctx, monkeypatch):
    mira = _mira(ctx)
    spells.memorize(ctx, mira.id, ["Magic Missile"])
    monkeypatch.setattr(
        type(fake_engine()),
        "cast",
        lambda self, sheet, state, spell, level, dice=None, actor=None: (state, {"cast": False, "lost": True, "roll": 3}),
    )
    out = spells.cast(ctx, mira.id, "Magic Missile")
    assert out["lost"] is True and out["roll"] == 3 and "cast" not in out
    stored = ctx.storage.characters.get(mira.id).state
    assert [s.cast for s in stored.memorized] == [True]


def test_the_engines_state_is_saved_over_the_spent_copy(ctx, monkeypatch):
    mira = _mira(ctx)
    spells.memorize(ctx, mira.id, ["Magic Missile"])
    monkeypatch.setattr(
        type(fake_engine()),
        "cast",
        lambda self, sheet, state, spell, level, dice=None, actor=None: (replace(state, d20={"seen": True}), {"cast": True}),
    )
    spells.cast(ctx, mira.id, "Magic Missile")
    stored = ctx.storage.characters.get(mira.id).state
    assert stored.d20 == {"seen": True} and stored.memorized[0].cast is True


def test_can_memorize_gets_the_names(ctx):
    mira = _mira(ctx)
    spells.memorize(ctx, mira.id, ["Bless"])
    assert fake_engine().memorize_spells == ["Bless"]


def test_turning_saves_the_state_it_returns(ctx, d20_call, monkeypatch):
    bram = characters.create(ctx, name="Bram", sheet={"cls": "Cleric", "level": 3, "hp_max": 9})

    def turn(self, sheet, level, undead, hd, dice, *, actor, state=None):
        self.turn_state = state
        return {"turned": True, "state": replace(state, d20={"turning_used": 1})}

    monkeypatch.setattr(type(fake_engine()), "turn_undead", turn)
    out = d20_call("turning_undead", level=3, undead="ghoul", character="Bram")
    assert out == {"turned": True}
    assert isinstance(fake_engine().turn_state, CharacterState)
    assert ctx.storage.characters.get(bram.id).state.d20 == {"turning_used": 1}


def test_turning_without_a_character_has_no_state(ctx, d20_call, monkeypatch):
    def turn(self, sheet, level, undead, hd, dice, *, actor, state=None):
        self.turn_state = state
        return {"turned": True, "state": CharacterState()}

    monkeypatch.setattr(type(fake_engine()), "turn_undead", turn)
    out = d20_call("turning_undead", level=3, undead="ghoul")
    assert out == {"turned": True} and fake_engine().turn_state is None


def test_classic_cast_is_unchanged(call):  # noqa: F811
    call("create_character", name="Merrin", sheet={"cls": "Magic-User", "level": 1, "hp_max": 4, "spell_slots": {1: 1}})
    call("memorize_spells", character="Merrin", spells=["Sleep"])
    out = call("cast_spell", beat="beat-2", character="Merrin", spell_name="Sleep")
    assert "error" not in out, out
    assert set(out) == {"character_id", "name", "spell", "level", "remaining"}
    assert out["remaining"] == {"1": 0}


def test_a_load_is_weighed_against_the_engines_multiplier(ctx, d20_call):  # DEL-399
    # The fake engine's halfling carries half: each of OSRIC's bands for its Strength, halved and rounded down.
    for name, race in (("Bram", "Human"), ("Pip", "Halfling")):
        sheet = {"cls": "Fighter", "level": 1, "race": race, "hp_max": 8, "ability_scores": {"str": 12}}
        assert "error" not in d20_call("create_character", name=name, sheet=sheet)
    human = d20_call("encumbrance", character="Bram")["thresholds"]
    halfling = d20_call("encumbrance", character="Pip")["thresholds"]
    assert halfling == {band: lb // 2 for band, lb in human.items()}
    assert "load_multiplier" in fake_engine().called


def test_a_classic_load_has_no_multiplier(call):  # noqa: F811  DEL-399
    sheet = {"cls": "Fighter", "level": 1, "race": "Halfling", "hp_max": 8, "ability_scores": {"str": 12}}
    call("create_character", name="Pip", sheet=sheet)
    call("create_character", name="Bram", sheet={**sheet, "race": "Human"})
    assert call("encumbrance", character="Pip")["thresholds"] == call("encumbrance", character="Bram")["thresholds"]


def test_a_load_moves_at_the_engines_loaded_speed(ctx, d20_call):  # DEL-404
    # The fake engine's dwarf isn't slowed by a load it can still carry; a human is, by OSRIC's band penalty.
    for name, race in (("Bram", "Human"), ("Thorin", "Dwarf")):
        sheet = {"cls": "Fighter", "level": 1, "race": race, "hp_max": 8, "ability_scores": {"str": 12}}
        assert "error" not in d20_call("create_character", name=name, sheet=sheet)
        for _ in range(3):
            assert "error" not in d20_call("add_item", character=name, item="Plate mail")
    human = d20_call("encumbrance", character="Bram")
    dwarf = d20_call("encumbrance", character="Thorin")
    assert human["band"] == dwarf["band"] != "light"
    assert human["movement"] < 12 and human["penalty"] < 0
    assert (dwarf["movement"], dwarf["penalty"]) == (12, 0)
    assert "loaded_speed" in fake_engine().called


def test_a_classic_dwarf_is_slowed_as_anyone(call):  # noqa: F811  DEL-404
    for name, race in (("Bram", "Human"), ("Thorin", "Dwarf")):
        sheet = {"cls": "Fighter", "level": 1, "race": race, "hp_max": 8, "ability_scores": {"str": 12}}
        call("create_character", name=name, sheet=sheet)
        for _ in range(3):
            call("add_item", character=name, item="Plate mail")
    human, dwarf = call("encumbrance", character="Bram"), call("encumbrance", character="Thorin")
    assert human["movement"] == dwarf["movement"] < 12
