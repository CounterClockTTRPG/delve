"""The d20 engine's stored state (DEL-387): written only when present, so every stored OSRIC record is unchanged."""

from delve.config import Config
from delve.domain import data
from delve.domain.characters import CharacterState, Sheet
from delve.play.context import context_for
from delve.rules.classic import combat as cb
from delve.rules.classic.tables import FightRules
from delve.storage import open_storage
from tests.fixtures.rulesets import osric_catalogs
from tests.rules.classic.test_combat import fight_with_goblins


def test_new_fields_are_left_out_while_none():
    assert "d20" not in Sheet().to_dict()
    assert "d20" not in CharacterState().to_dict()
    combat = cb.Combat(combatants={"x": cb.Combatant(id="x", name="X", side="party")})
    assert "d20" not in cb.to_json(combat)["combatants"]["x"]
    rules = data.to_dict(FightRules())
    assert "initiative_once" not in rules and "highest_first" not in rules


def test_a_stored_osric_fight_writes_back_the_same():
    raw = cb.to_json(fight_with_goblins())
    assert cb.to_json(cb.from_json(raw)) == raw
    sheet = Sheet(ac=4, thac0=17).to_dict()
    assert Sheet.from_dict(sheet).to_dict() == sheet


def test_d20_state_round_trips():
    sheet = Sheet(d20={"bab": 1})
    assert sheet.to_dict()["d20"] == {"bab": 1}
    assert Sheet.from_dict(sheet.to_dict()).d20 == {"bab": 1}
    state = CharacterState(d20={"cast": {"1": 2}})
    assert CharacterState.from_dict(state.to_dict()).d20 == {"cast": {"1": 2}}


def test_context_has_no_engine_for_osric(tmp_path):
    storage = open_storage(Config(data_dir=tmp_path / "data"))
    try:
        module = storage.modules.create("The Crypt")
        revision = storage.revisions.snapshot(module.id)
        campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")
        ctx = context_for(storage, campaign.id, "beat-1", catalogs=osric_catalogs())
        assert ctx.ruleset is not None and ctx.d20 is None
    finally:
        storage.close()
