"""A whole character's life on the fake d20 engine (DEL-387): every hook runs through the tool host, as the DM calls
it, and the tripwire tables raise on any read of the classic maths."""

import inspect
from dataclasses import replace

import pytest

from delve.dm.tools import dice
from delve.play import spells
from delve.play.context import PlayError, context_for
from delve.rules.d20 import D20Engine
from tests.fixtures.d20 import d20_catalogs, fake_engine


def _engine_methods() -> set[str]:
    return {name for name, member in inspect.getmembers(D20Engine) if not name.startswith("_") and callable(member)}


def test_a_whole_life_on_the_engine(d20_call, d20_storage, d20_campaign):
    engine = fake_engine()
    engine.called.clear()
    answers = []
    beats = iter(f"beat-{n}" for n in range(1, 100))

    def ran(expected, tool, **args):
        """The tool call, with the hooks it ran: each of `expected` ran in this call."""
        before = len(engine.called.calls)
        out = d20_call(tool, beat=next(beats), **args)
        answers.append((tool, out))
        assert set(expected) <= set(engine.called.calls[before:]), (tool, engine.called.calls[before:])
        return out

    ran(["fill_derived"], "create_character", name="Bram", sheet={"cls": "Fighter", "level": 1, "hp_max": 12})
    ran(["fill_derived"], "create_character", name="Mira", sheet={"cls": "Cleric", "level": 1, "hp_max": 8})
    ran(
        ["combatant_from_sheet", "combatant_from_monster", "read_hit_dice", "initiative"],
        "setup_combat",
        enemies=[{"name": "goblin", "count": 2, "hp": 1}],
        surprise=False,
    )
    for _ in range(10):
        out = ran(
            ["swing"],
            "combat_round",
            actions=[
                {"attacker": "Bram", "target": "Goblin 1", "targets": ["Goblin 2"]},
                {"attacker": "Mira", "target": "Goblin 1", "targets": ["Goblin 2"]},
            ],
        )
        if all(c["hp"] <= 0 for c in out["status"]["combatants"] if c["side"] == "enemy"):
            break
    else:
        raise AssertionError("the goblins never went down")
    fighting = ran([], "combat_status")
    for entry in fighting["combatants"]:
        assert "thac0" not in entry and "ac" not in entry and "d20" in entry
    fought = ran(["save"], "saving_throw", character="Bram", save_type="spells")
    assert fought["basis"] == "faked20" and fought["needed"] == 15 - 2
    ended = ran(["xp_for_defeated"], "end_combat")
    assert ended["groups"][0]["xp_earned"] == 100 * 2
    ctx = context_for(d20_storage, d20_campaign.id, next(beats), catalogs=d20_catalogs())
    before = len(engine.called.calls)
    core = dice.saving_throw(ctx, "Bram", "spells")
    assert "save" in engine.called.calls[before:]
    assert core["basis"] == "faked20" and core["needed"] == 15 - 2
    scoped = ran(["save"], "saving_throw", character="Bram", save_type="spells", dc=12)
    assert scoped["basis"] == "faked20" and scoped["needed"] == 12 - 2
    ran(["skill_check"], "skill_check", character="Bram", skill="climb")
    ran(["ability_check"], "ability_check", character="Bram", ability="str")
    ran(["turn_undead"], "turning_undead", level=1, undead="skeleton", hd=1)
    ran(["can_memorize"], "memorize_spells", character="Mira", spells=["Cure Light Wounds"])
    cast = ran(["cast"], "cast_spell", character="Mira", spell_name="Bless")
    assert cast["cast"] is True
    # A caster with slots and no uncast copy asks whether the engine casts the spell from a pool; the fake says no.
    mira = d20_storage.characters.get(cast["character_id"])
    d20_storage.characters.save_sheet(replace(mira, sheet=replace(mira.sheet, spell_slots={1: 1})))
    before = len(engine.called.calls)
    with pytest.raises(PlayError, match="is not memorized"):
        spells.cast(context_for(d20_storage, d20_campaign.id, next(beats), catalogs=d20_catalogs()), "Mira", "Bless")
    assert "casts_unprepared" in engine.called.calls[before:]
    awarded = ran(["award_xp", "progress"], "award_xp", character="Bram", amount=1000)
    assert awarded["level"] == 2 and awarded["xp_next"] == 2000 and "per_class" not in awarded
    ran(["level_up"], "update_character", ref="Bram", patch={"level": 2})
    ran(["fill_derived"], "update_character", ref="Bram", patch={"ability_scores": {"str": 16}})
    drained = ran(["drain"], "drain_level", character="Bram", levels=1)
    assert drained["d20"]["slain"] is False and "thac0" not in drained and "saves" not in drained
    rested = ran(["rest"], "rest", days=1, bed_rest=True)
    assert "rate_per_day" not in rested and rested["basis"] == "fake rest, 2 hp a day"
    status = ran(["sheet_numbers"], "party_status")
    for entry in status["party"]:
        assert entry["d20"]["defence"] == 10 + 1 and "ac" not in entry and "thac0" not in entry
    ran(["load_multiplier", "loaded_speed"], "encumbrance", character="Bram")
    ran([], "fake_flourish")

    assert [tool for tool, out in answers if "error" in out] == []
    # prompt_terms and tools run at prompt and host build, not in a tool call, so they are not asserted.
    assert engine.called - {"prompt_terms", "tools"} == _engine_methods() - {"prompt_terms", "tools"}
