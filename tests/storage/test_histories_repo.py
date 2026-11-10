"""Histories and carries in the database (carry-the-party-on plan Task 1): a campaign's history, one row with the DM's
and the table's texts, gone with its campaign; and the link from the campaign a party was carried on from to the one
it was carried into, which outlives the old campaign."""

from dataclasses import replace

import pytest

from delve.config import Config
from delve.domain.histories import Carry, History
from delve.storage import open_storage


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path))
    yield opened
    opened.close()


def _campaign(storage, name: str) -> str:
    module = storage.modules.create(f"The module of {name}")
    return storage.campaigns.create(
        name, module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
    ).id


def test_put_then_get_round_trips_a_history(storage):
    campaign_id = _campaign(storage, "Barrowmaze")
    stored = storage.histories.put(
        History(
            campaign_id,
            dm_md="## The party\n\nMira and Anselm.\n\n## Loose ends\n\nThe abbot lied.",
            table_md="## The party\n\nMira and Anselm.",
            status="done",
            edited=True,
            conversion_id="cnv_1",
            cost_usd=0.25,
        )
    )
    assert stored.created_at and stored.updated_at
    assert storage.histories.get(campaign_id) == stored
    assert stored.dm_md.endswith("The abbot lied.") and stored.edited and stored.cost_usd == 0.25
    assert storage.histories.get(_campaign(storage, "Other")) is None


def test_put_replaces_and_keeps_created_at(storage):
    campaign_id = _campaign(storage, "Barrowmaze")
    first = storage.histories.put(History(campaign_id))
    assert first.status == "writing" and first.dm_md == "" and first.error is None and not first.edited
    second = storage.histories.put(replace(first, status="failed", error="It broke.", created_at="", updated_at=""))
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at
    assert storage.histories.get(campaign_id) == second
    assert (second.status, second.error) == ("failed", "It broke.")


def test_put_for_unknown_campaign_raises_key_error(storage):
    with pytest.raises(KeyError):
        storage.histories.put(History("cmp_nobody"))


def test_writing_lists_only_writing_histories(storage):
    writing, done, failed = (_campaign(storage, name) for name in ("A", "B", "C"))
    storage.histories.put(History(writing))
    storage.histories.put(History(done, status="done"))
    storage.histories.put(History(failed, status="failed", error="no"))
    assert [h.campaign_id for h in storage.histories.writing()] == [writing]


def test_deleting_the_campaign_deletes_its_history(storage):
    campaign_id = _campaign(storage, "Barrowmaze")
    storage.histories.put(History(campaign_id, status="done"))
    storage.campaigns.delete(campaign_id)
    assert storage.histories.get(campaign_id) is None


def test_carry_add_origin_onward(storage):
    a, b, c = (_campaign(storage, name) for name in ("A", "B", "C"))
    first = storage.carries.add(a, b, ["chr_1", "chr_2"])
    second = storage.carries.add(a, c, ["chr_2"])
    assert isinstance(first, Carry) and first.id and first.carried_at
    assert (first.from_campaign_id, first.to_campaign_id, first.character_ids) == (a, b, ("chr_1", "chr_2"))
    assert storage.carries.onward(a) == [first, second]
    assert storage.carries.origin(b) == first and storage.carries.origin(b).from_campaign_id == a
    assert storage.carries.origin(a) is None and storage.carries.onward(b) == []


def test_a_campaign_is_carried_into_once(storage):
    a, b = _campaign(storage, "A"), _campaign(storage, "B")
    storage.carries.add(a, b, ["chr_1"])
    with pytest.raises(ValueError):
        storage.carries.add(a, b, ["chr_1"])


def test_carry_add_for_unknown_campaign_raises_key_error(storage):
    a = _campaign(storage, "A")
    with pytest.raises(KeyError):
        storage.carries.add(a, "cmp_nobody", [])
    with pytest.raises(KeyError):
        storage.carries.add("cmp_nobody", a, [])


def test_deleting_the_old_campaign_keeps_the_carry_with_from_none(storage):
    a, b = _campaign(storage, "A"), _campaign(storage, "B")
    storage.carries.add(a, b, ["chr_1"])
    storage.histories.put(History(b, status="done", dm_md="Past."))
    storage.campaigns.delete(a)
    origin = storage.carries.origin(b)
    assert origin is not None and origin.from_campaign_id is None and origin.character_ids == ("chr_1",)
    assert storage.histories.get(b).dm_md == "Past."
    assert storage.carries.onward(a) == []


def test_deleting_the_new_campaign_deletes_the_carry(storage):
    a, b = _campaign(storage, "A"), _campaign(storage, "B")
    storage.carries.add(a, b, ["chr_1"])
    storage.campaigns.delete(b)
    assert storage.carries.origin(b) is None and storage.carries.onward(a) == []
