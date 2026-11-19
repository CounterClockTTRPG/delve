"""The DEL-387 leftovers in core (DEL-388): under a d20 engine every sheet patch fills the derived numbers again (R19a),
a patch to what the combatant is made from rebuilds a live combatant (R19b), and a spell declared in a round is spent
through the engine with its report in the round's answer (R15). OSRIC runs the code it ran before."""

from dataclasses import replace

import pytest

from delve.play import characters, spells
from delve.play.context import PlayError, context_for
from delve.rules.classic import combat as rules
from tests.dm.tools.conftest import GARREK, call, campaign, host, storage  # noqa: F401  (the OSRIC fixtures)
from tests.fixtures.d20 import d20_catalogs, fake_engine
from tests.fixtures.rulesets import osric_catalogs


@pytest.fixture
def ctx(d20_storage, d20_campaign):
    fake_engine().called.clear()
    return context_for(d20_storage, d20_campaign.id, "beat-1", catalogs=d20_catalogs())


@pytest.fixture
def fighter(ctx):
    return characters.create(ctx, name="Bram", sheet={"cls": "Fighter", "level": 2, "hp_max": 12})


def _mira(ctx):
    made = characters.create(ctx, name="Mira", sheet={"cls": "Mage", "level": 1, "hp_max": 6})
    return ctx.storage.characters.save_sheet(replace(made, sheet=replace(made.sheet, spell_slots={1: 2})))


def _fight(ctx):
    return rules.from_json(ctx.storage.combats.live(ctx.campaign_id)[1])


def _goblin(d20_call):
    out = d20_call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 50}], surprise=False)
    assert "error" not in out, out
    return out


def test_a_same_levels_patch_refills(ctx, fighter):
    fake_engine().called.clear()
    saved = characters.update(ctx, fighter.id, {"levels": dict(fighter.sheet.levels), "alignment": "LG"})
    assert "fill_derived" in fake_engine().called and "level_up" not in fake_engine().called
    assert saved.sheet.alignment == "LG" and saved.sheet.levels == fighter.sheet.levels


def test_a_same_cls_patch_refills(ctx, fighter):
    fake_engine().called.clear()
    characters.update(ctx, fighter.id, {"cls": fighter.sheet.cls, "alignment": "LG"})
    assert "fill_derived" in fake_engine().called


def test_a_raised_level_still_levels_up(ctx, fighter):
    fake_engine().called.clear()
    saved = characters.update(ctx, fighter.id, {"level": 3})
    assert fake_engine().called.calls.count("level_up") == 1 and saved.sheet.d20["attack"] == 3


def test_an_ability_patch_rearms_the_live_combatant(ctx, fighter, d20_call):
    _goblin(d20_call)
    characters.apply_damage(ctx, fighter.id, 4)
    before = _fight(ctx).combatants[fighter.id]
    fake_engine().called.clear()
    characters.update(ctx, fighter.id, {"ability_scores": {**fighter.sheet.ability_scores, "str": 18}})
    c = _fight(ctx).combatants[fighter.id]
    assert "combatant_from_sheet" in fake_engine().called
    assert c.hp == before.hp == 8 and c.hp_max == before.hp_max
    assert (c.conditions, c.effects, c.init, c.node) == (before.conditions, before.effects, before.init, before.node)
    assert c.d20 == characters.get(ctx, fighter.id).sheet.d20


def test_a_state_patch_does_not_rearm(ctx, fighter, d20_call):
    _goblin(d20_call)
    fake_engine().called.clear()
    characters.update(ctx, fighter.id, {"hp": 5})
    assert "combatant_from_sheet" not in fake_engine().called


def test_a_declared_spell_is_spent_through_the_engine(ctx, d20_call):
    mira = _mira(ctx)
    spells.memorize(ctx, mira.id, ["Magic Missile"])
    _goblin(d20_call)
    fake_engine().called.clear()
    out = d20_call(
        "combat_round", beat="beat-2", actions=[{"caster": "Mira", "spell": "Magic Missile", "target": "Goblin"}]
    )
    assert "error" not in out, out
    assert fake_engine().called.calls.count("cast") == 1
    assert out["spells_spent"] == [{"caster": "Mira", "spell": "Magic Missile", "remaining": {"1": 0}}]
    assert (ctx.storage.characters.get(mira.id).state.d20 or {}).get("used") == 1


def test_a_spell_lost_in_a_round_shows_the_engines_report(ctx, d20_call, monkeypatch):
    mira = _mira(ctx)
    spells.memorize(ctx, mira.id, ["Magic Missile"])
    _goblin(d20_call)
    report = {"cast": False, "lost": True, "spell_failure": 20, "roll": 7, "remaining": "the engine's", "caster": "x"}
    monkeypatch.setattr(
        type(fake_engine()), "cast", lambda self, sheet, state, spell, level, dice=None, actor=None: (state, dict(report))
    )
    out = d20_call(
        "combat_round", beat="beat-2", actions=[{"caster": "Mira", "spell": "Magic Missile", "target": "Goblin"}]
    )
    assert "error" not in out, out
    assert out["spells_spent"] == [
        {
            "caster": "Mira",
            "spell": "Magic Missile",
            "remaining": {"1": 0},
            "lost": True,
            "spell_failure": 20,
            "roll": 7,
        }
    ]


@pytest.mark.parametrize("cast", [{"cast": False}, {}])
def test_a_refusal_without_lost_says_lost(ctx, monkeypatch, cast):
    mira = _mira(ctx)
    spells.memorize(ctx, mira.id, ["Magic Missile"])
    said = {**cast, "refusal": "Too heavy.", "name": "Nobody", "level": 9, "spell": "Wish", "character_id": "x"}
    monkeypatch.setattr(
        type(fake_engine()), "cast", lambda self, sheet, state, spell, level, dice=None, actor=None: (state, dict(said))
    )
    out = spells.cast(ctx, mira.id, "Magic Missile")
    assert out == {
        "character_id": mira.id,
        "name": "Mira",
        "spell": "Magic Missile",
        "level": 1,
        "remaining": {"1": 0},
        "refusal": "Too heavy.",
        "lost": True,
    }


def test_osric_patch_path_unchanged(call):  # noqa: F811
    made = call("create_character", name="Garrek", sheet=GARREK)
    fake_engine().called.clear()
    out = call("update_character", ref="Garrek", patch={"levels": made["sheet"]["levels"], "alignment": "LG"})
    assert "error" not in out, out
    assert not fake_engine().called
    assert "d20" not in out["sheet"]
    assert {**made["sheet"], "alignment": "LG"} == out["sheet"]


def test_an_engine_build_writes_d20_and_fills_again(ctx, fighter):
    fake_engine().called.clear()
    saved = characters.update(ctx, fighter.id, {}, d20_build={"feats": ["dodge"], "attack": 99})
    assert saved.sheet.d20["feats"] == ["dodge"]
    assert saved.sheet.d20["attack"] == 2  # fill_derived ran after the build went in
    assert "fill_derived" in fake_engine().called
    assert characters.get(ctx, fighter.id).sheet.d20["feats"] == ["dodge"]


def test_an_engine_build_rearms_the_live_combatant(ctx, fighter, d20_call):
    _goblin(d20_call)
    fake_engine().called.clear()
    characters.update(ctx, fighter.id, {}, d20_build={"feats": ["dodge"]})
    assert "combatant_from_sheet" in fake_engine().called
    assert _fight(ctx).combatants[fighter.id].d20["feats"] == ["dodge"]


def test_the_dms_patch_still_cannot_name_d20(ctx, fighter):
    with pytest.raises(PlayError, match="Can't change 'd20'"):
        characters.update(ctx, fighter.id, {"d20": {"feats": ["dodge"]}})


def test_an_engine_build_is_refused_without_an_engine(storage, campaign):  # noqa: F811
    osric_ctx = context_for(storage, campaign.id, "beat-1", catalogs=osric_catalogs())
    made = characters.create(osric_ctx, name="Garrek", sheet=GARREK)
    with pytest.raises(PlayError, match="d20"):
        characters.update(osric_ctx, made.id, {}, d20_build={"feats": ["dodge"]})
