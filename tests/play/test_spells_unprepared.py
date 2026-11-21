"""The d20 hook `casts_unprepared` (DEL-389): a d20 caster with spell slots that also casts from a per-day pool (a
sorcerer/cleric) reaches the engine's pool for a spell it has no uncast memorized copy of. A classic cast never asks,
and an engine that says False changes nothing."""

from dataclasses import replace

import pytest

from delve.play import characters, spells
from delve.play.context import PlayError, context_for
from tests.fixtures.d20 import FAKE_D20, d20_catalogs, fake_engine
from tests.play.conftest import crypt_campaign

HESH = {"race": "human", "cls": "Cleric", "level": 3, "hp_max": 18, "spell_slots": {1: 2, 2: 1}}


def test_a_classic_cast_is_unchanged(ctx):
    characters.create(ctx, name="Hesh", sheet=HESH)
    spells.memorize(ctx, "Hesh", ["Bless"])
    out = spells.cast(ctx, "Hesh", "bless")
    assert {k: out[k] for k in ("name", "spell", "level", "remaining")} == {
        "name": "Hesh", "spell": "Bless", "level": 1, "remaining": {"1": 0}
    }  # fmt: skip
    assert set(out) == {"character_id", "name", "spell", "level", "remaining"}
    with pytest.raises(PlayError, match="'bless' has already been cast: every memorized copy is spent."):
        spells.cast(ctx, "Hesh", "bless")
    with pytest.raises(PlayError, match="'light' is not memorized by Hesh."):
        spells.cast(ctx, "Hesh", "light")


@pytest.fixture
def d20_ctx(storage):
    fake_engine().called.clear()
    campaign = crypt_campaign(storage, ruleset=FAKE_D20)
    return context_for(storage, campaign.id, "beat-1", catalogs=d20_catalogs())


def _slotted(ctx):
    """A fake d20 caster with spell slots (so core's per-day path is closed to it) and a pool of 1."""
    made = characters.create(ctx, name="Mira", sheet={"cls": "Mage", "level": 1, "hp_max": 6})
    sheet = replace(made.sheet, d20={**made.sheet.d20, "pool": 1}, spell_slots={1: 1})
    return ctx.storage.characters.save_sheet(replace(made, sheet=sheet))


def test_the_fakes_false_changes_nothing(d20_ctx):
    mira = _slotted(d20_ctx)
    spells.memorize(d20_ctx, mira.id, ["Magic Missile"])
    assert spells.cast(d20_ctx, mira.id, "Magic Missile")["remaining"] == {"1": 0}
    assert fake_engine().cast_unprepared is False  # a memorized copy's cast says nothing of a pool
    fake_engine().called.clear()
    with pytest.raises(PlayError, match="has already been cast"):
        spells.cast(d20_ctx, mira.id, "Magic Missile")
    with pytest.raises(PlayError, match="is not memorized by Mira"):
        spells.cast(d20_ctx, mira.id, "Sleep")
    assert fake_engine().called.calls == ["casts_unprepared", "casts_unprepared"]
    assert d20_ctx.storage.characters.get(mira.id).state.d20["used"] == 1  # the memorized copy's cast alone


def test_an_engine_that_casts_unprepared_spends_its_pool(d20_ctx, monkeypatch):
    mira = _slotted(d20_ctx)
    monkeypatch.setattr(type(fake_engine()), "casts_unprepared", lambda self, sheet, spell: spell == "Sleep")
    out = spells.cast(d20_ctx, mira.id, "Sleep")
    assert (out["cast"], out["spell"], out["level"]) == (True, "Sleep", 1)
    assert fake_engine().cast_unprepared is True  # the engine is told the cast is from its pool
    assert d20_ctx.storage.characters.get(mira.id).state.d20["used"] == 1
    # A memorized copy is still spent first, as before: the pool is for a spell with no uncast copy.
    spells.memorize(d20_ctx, mira.id, ["Sleep"])
    assert spells.cast(d20_ctx, mira.id, "Sleep")["remaining"] == {"1": 0}
    assert d20_ctx.storage.characters.get(mira.id).state.d20["used"] == 1
    with pytest.raises(PlayError, match="No spells left to cast."):
        spells.cast(d20_ctx, mira.id, "Sleep")
