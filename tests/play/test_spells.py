"""`play.spells`: a spell loadout (known and default spells), memorizing, casting, and rest."""

import pytest

from delve.domain.characters import MemorizedSpell, SpellLoadout
from delve.play import characters, spells
from delve.play.context import NotFound, PlayError

HESH = {"race": "human", "cls": "Cleric", "level": 3, "hp_max": 18, "spell_slots": {1: 2, 2: 1}}
ODO = {"race": "elf", "cls": "Mage", "level": 2, "hp_max": 6, "spell_slots": {"1": 2}}


def memorized(ctx, ref):
    return characters.get(ctx, ref).state.memorized


def test_default_loadout_fits_slots(ctx):
    characters.create(ctx, name="Hesh", sheet=HESH)
    out = spells.set_loadout(
        ctx,
        "Hesh",
        known={1: ["bless", "Cure Light Wounds", "light"], 2: ["Hold Person"]},
        default={1: ["Cure light wounds", "Bless"], 2: ["hold person"]},
    )
    loadout = characters.get(ctx, "Hesh").sheet.spell_loadout
    # names take the reference's spelling
    assert loadout == SpellLoadout(
        known={1: ("Bless", "Cure Light Wounds", "Light"), 2: ("Hold Person",)},
        default={1: ("Cure Light Wounds", "Bless"), 2: ("Hold Person",)},
    )
    assert out["default"] == {"1": ["Cure Light Wounds", "Bless"], "2": ["Hold Person"]}
    with pytest.raises(PlayError) as over:
        spells.set_loadout(ctx, "Hesh", default={1: ["Bless", "Bless", "Light"]})
    assert "level-1" in over.value.message and "2 slots" in over.value.message
    with pytest.raises(PlayError):
        spells.set_loadout(ctx, "Hesh", default={3: ["Bless"]})  # no 3rd-level slots
    # `known` alone leaves the default as it was
    spells.set_loadout(ctx, "Hesh", known={1: ["Bless"]})
    assert characters.get(ctx, "Hesh").sheet.spell_loadout.default == loadout.default


def test_unknown_spell_candidates(ctx):
    characters.create(ctx, name="Hesh", sheet=HESH)
    with pytest.raises(NotFound) as caught:
        spells.set_loadout(ctx, "Hesh", known={1: ["Bles"]})
    assert caught.value.candidates == [
        {"name": "Bless", "level": 1, "caster": "priest"},
        {"name": "Blessed Watchfulness", "level": 1, "caster": "priest"},
    ]
    with pytest.raises(NotFound):
        spells.memorize(ctx, "Hesh", ["Blorp of Doom"])
    assert characters.get(ctx, "Hesh").sheet.spell_loadout == SpellLoadout()


def test_memorize_default(ctx):
    characters.create(ctx, name="Hesh", sheet=HESH)
    with pytest.raises(PlayError):
        spells.memorize(ctx, "Hesh")  # no default yet
    spells.set_loadout(ctx, "Hesh", default={1: ["Bless", "Bless"], 2: ["Hold Person"]})
    out = spells.memorize(ctx, "Hesh")
    assert memorized(ctx, "Hesh") == (
        MemorizedSpell("Bless", 1),
        MemorizedSpell("Bless", 1),
        MemorizedSpell("Hold Person", 2),
    )
    assert out["by_level"] == {"1": ["Bless", "Bless"], "2": ["Hold Person"]}


def test_memorize_named_spells_resolves_levels_by_caster(ctx):
    """ttrpg2 `test_bare_names_get_levels_resolved`: a priest's Hold Person is 2nd level, a wizard's 3rd."""
    characters.create(ctx, name="Hesh", sheet=HESH)
    characters.create(ctx, name="Odo", sheet=ODO)
    spells.memorize(ctx, "Hesh", ["cure light wounds", "Hold Person"])
    assert memorized(ctx, "Hesh") == (MemorizedSpell("Cure Light Wounds", 1), MemorizedSpell("Hold Person", 2))
    spells.memorize(ctx, "Odo", ["sleep", "magic missile"])
    assert [s.level for s in memorized(ctx, "Odo")] == [1, 1]
    with pytest.raises(PlayError) as over:
        spells.memorize(ctx, "Odo", ["Sleep", "Sleep", "Light"])
    assert "level-1" in over.value.message
    with pytest.raises(PlayError):
        spells.memorize(ctx, "Odo", ["Web"])  # a 2nd-level spell, and Odo has no 2nd-level slots
    assert [s.name for s in memorized(ctx, "Odo")] == ["Sleep", "Magic Missile"]


def test_cast_marks_once(ctx):
    characters.create(ctx, name="Hesh", sheet=HESH)
    spells.memorize(ctx, "Hesh", ["Bless", "Bless", "Hold Person"])
    out = spells.cast(ctx, "Hesh", "bless")
    assert out == {
        "character_id": out["character_id"],
        "name": "Hesh",
        "spell": "Bless",
        "level": 1,
        "remaining": {"1": 1, "2": 1},
    }
    spells.cast(ctx, "Hesh", "Bless")
    with pytest.raises(PlayError) as spent:
        spells.cast(ctx, "Hesh", "Bless")
    assert "already been cast" in spent.value.message
    with pytest.raises(PlayError) as missing:
        spells.cast(ctx, "Hesh", "Light")
    assert "not memorized" in missing.value.message
    assert [s.cast for s in memorized(ctx, "Hesh")] == [True, True, False]
    cast_events = [e for e in ctx.storage.events.list(ctx.campaign_id) if e.type == "spell_cast"]
    assert [e.data["spell"] for e in cast_events] == ["Bless", "Bless"]

    status = spells.spell_status(ctx, "Hesh")
    assert status["available"] == ["Hold Person"] and status["spent"] == ["Bless", "Bless"]
    assert status["slots"] == {
        "1": {"max": 2, "memorized": 2, "remaining": 0},
        "2": {"max": 1, "memorized": 1, "remaining": 1},
    }


def test_rest_clears_cast_and_rememorizes(ctx):
    """ttrpg2's `rest`: any rest of a day or more makes memorized spells uncast again; with `rememorize` the
    character memorizes their default loadout instead (PHB ch. 7: spells are memorized after rest)."""
    characters.create(ctx, name="Hesh", sheet=HESH)
    spells.set_loadout(ctx, "Hesh", default={1: ["Bless", "Cure Light Wounds"]})
    spells.memorize(ctx, "Hesh", ["Bless", "Hold Person"])
    spells.cast(ctx, "Hesh", "Bless")
    spells.cast(ctx, "Hesh", "Hold Person")

    characters.rest(ctx, "Hesh", days=0)
    assert [s.cast for s in memorized(ctx, "Hesh")] == [True, True]  # no rest of a day: nothing comes back

    out = characters.rest(ctx, "Hesh", days=1)
    assert memorized(ctx, "Hesh") == (MemorizedSpell("Bless", 1), MemorizedSpell("Hold Person", 2))
    assert "memorize" in out["reminder"]

    spells.cast(ctx, "Hesh", "Bless")
    out = characters.rest(ctx, "Hesh", days=1, rememorize=True)
    assert memorized(ctx, "Hesh") == (MemorizedSpell("Bless", 1), MemorizedSpell("Cure Light Wounds", 1))
    assert out["memorized"] == {"Hesh": ["Bless", "Cure Light Wounds"]} and "reminder" not in out
