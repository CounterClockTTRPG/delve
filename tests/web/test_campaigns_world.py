"""A new campaign's ruleset and setting come from what this install has (DEL-307): no setting where none is
installed, else the preferred ones."""

from dataclasses import replace

from delve.domain.backends import Registry
from delve.packs.catalogs import IN_TREE
from tests.web.test_campaigns_api import crypt_module


def started(local, module_id: str, **choice) -> dict:
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module_id, **choice})
    assert response.status_code == 201, response.json()
    return response.json()


def test_new_campaign_without_setting_packs_has_no_setting(local, registries, storage):
    registries.settings_ = Registry()
    registries.catalogs = replace(IN_TREE, settings=())
    module = crypt_module(local)
    campaign = started(local, module["id"])
    assert campaign["setting"] == ""
    assert storage.campaigns.get(campaign["id"]).setting == ""
    assert local.get(f"/api/campaigns/{campaign['id']}").json()["setting"] == ""


def test_a_campaign_without_a_setting_shows_none_and_has_no_setting_tab(local, registries):
    registries.settings_ = Registry()
    registries.catalogs = replace(IN_TREE, settings=())
    campaign = started(local, crypt_module(local)["id"])
    response = local.get(f"/api/campaigns/{campaign['id']}/setting")
    assert response.status_code == 404
    assert local.get(f"/api/campaigns/{campaign['id']}/lore/random").json() == {"facts": []}


def test_the_ruleset_default_asks_the_servers_catalogs(local, registries, osric_catalogs):
    registries.catalogs = replace(osric_catalogs, rulesets=tuple(e for e in osric_catalogs.rulesets if e.id != "adnd2e"))
    campaign = started(local, crypt_module(local)["id"])
    assert campaign["ruleset"] == "osric"
