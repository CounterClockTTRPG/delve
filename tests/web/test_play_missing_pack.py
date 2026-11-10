"""A campaign whose ruleset or setting isn't installed says so and doesn't play (DEL-307)."""

import pytest

from delve.domain.modules import ModuleMap
from tests.web.conftest import make_registries


@pytest.fixture
def registries():
    return make_registries()


def campaign_of(storage, **kinds):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create(
        "Tuesday", module.id, revision.number, **{"ruleset": "osric", "setting": "greyhawk", **kinds}
    )


@pytest.mark.parametrize(
    ("kinds", "kind", "id"),
    [({"ruleset": "adnd9"}, "ruleset", "adnd9"), ({"setting": "eberron"}, "setting", "eberron")],
)
def test_a_campaign_without_its_pack_refuses_to_act_and_says_so(local, storage, kinds, kind, id):
    campaign = campaign_of(storage, **kinds)
    answer = local.post(f"/api/campaigns/{campaign.id}/act", json={"text": "I look."})
    assert (answer.status_code, answer.json()) == (409, {"error": f"This campaign's {kind}, {id}, isn't installed."})
    assert storage.beats.current(campaign.id) is None
    state = local.get(f"/api/campaigns/{campaign.id}/play/state").json()
    assert state["missing_pack"] == {"kind": kind, "id": id}


def test_a_campaign_with_its_pack_has_no_missing_pack(local, storage, registries, osric_catalogs):
    registries.catalogs = osric_catalogs
    campaign = campaign_of(storage, ruleset="osric", setting="greyhawk")
    state = local.get(f"/api/campaigns/{campaign.id}/play/state").json()
    assert state["missing_pack"] is None
