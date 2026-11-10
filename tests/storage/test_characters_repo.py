"""A character's sheet and its state are saved apart: a fight's hit points and a painter's portrait, each from its own
read, never undo the other (whole-row saves were last-writer-wins)."""

from dataclasses import replace

import pytest

from delve.config import Config
from delve.domain.characters import CharacterState, Sheet
from delve.storage import open_storage


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


@pytest.fixture
def garrek(storage):
    module = storage.modules.create("The Crypt")
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="")
    return storage.characters.create(campaign.id, "Garrek", sheet=Sheet(hp_max=20), state=CharacterState(hp=20))


def test_a_state_save_keeps_a_sheet_saved_since(storage, garrek):
    stale = storage.characters.get(garrek.id)
    storage.characters.save_sheet(replace(garrek, sheet=replace(garrek.sheet, background="A smith's son.")))
    saved = storage.characters.save_state(replace(stale, state=replace(stale.state, hp=7)))
    stored = storage.characters.get(garrek.id)
    assert (stored.state.hp, stored.sheet.background) == (7, "A smith's son.")
    assert saved == stored


def test_a_sheet_save_keeps_a_state_saved_since(storage, garrek):
    stale = storage.characters.get(garrek.id)
    storage.characters.save_state(replace(garrek, state=replace(garrek.state, hp=7, conditions=("prone",))))
    saved = storage.characters.save_sheet(replace(stale, name="Garrek the Red", sheet=replace(stale.sheet, ac=4)))
    stored = storage.characters.get(garrek.id)
    assert (stored.state.hp, stored.state.conditions) == (7, ("prone",))
    assert (stored.name, stored.sheet.label, stored.sheet.ac) == ("Garrek the Red", "Garrek the Red", 4)
    assert saved == stored


def test_a_part_save_of_a_character_not_in_its_campaign_is_refused(storage, garrek):
    with pytest.raises(KeyError):
        storage.characters.save_state(replace(garrek, id="chr_000000000000"))
    with pytest.raises(KeyError):
        storage.characters.save_sheet(replace(garrek, campaign_id="cmp_000000000000"))
