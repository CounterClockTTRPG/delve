"""A campaign names its ruleset and its setting (spec §10, plan 3 Task 7): `GET /api/worlds`, and the choice when a
campaign is created."""

from delve.domain.backends import ProviderCapabilities, Registry
from delve.rules.fake import FakeRuleset
from delve.setting.catalog import entry, register_settings
from tests.fixtures.settings import GreyhawkSetting
from tests.web.test_campaigns_api import crypt_module


class Adnd2e(FakeRuleset):
    id = "adnd2e"
    title = "AD&D 2nd edition"


def started(local, module_id: str, **choice) -> dict:
    response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module_id, **choice})
    assert response.status_code == 201, response.json()
    return response.json()


def with_metadata(local, metadata: dict) -> dict:
    module = crypt_module(local)
    response = local.patch(f"/api/modules/{module['id']}", json={"metadata": metadata})
    assert response.status_code == 200, response.json()
    return module


def test_greyhawk_without_a_reference_finds_nothing():
    greyhawk = GreyhawkSetting()
    assert (greyhawk.id, greyhawk.title, greyhawk.kinds()[0]) == ("greyhawk", "Greyhawk", "place")
    assert greyhawk.lookup("place", "Hommlet") == []


def test_worlds_lists_the_registries_without_fakes_beside_real_ones(local):
    # The web fakes: only the fake ruleset, and Greyhawk beside the fake setting.
    assert local.get("/api/worlds").json() == {
        "rulesets": [{"id": "fake-rules", "title": "Fake ruleset"}],
        "settings": [
            {"id": "aun", "title": "Aun"},
            {"id": "forgotten-realms", "title": "Forgotten Realms"},
            {"id": "greyhawk", "title": "Greyhawk", "preferred": True},  # its pack says so
        ],
    }


def test_worlds_lists_only_real_rulesets_when_there_are(local, registries):
    registries.rulesets = Registry()
    registries.rulesets.register(ProviderCapabilities("adnd2e", "AD&D 2nd edition", frozenset()), Adnd2e)
    registries.rulesets.register(ProviderCapabilities("fake-rules", "Fake ruleset", frozenset()), FakeRuleset)
    assert local.get("/api/worlds").json()["rulesets"] == [{"id": "adnd2e", "title": "AD&D 2nd edition"}]


def test_worlds_lists_a_fake_setting_when_it_is_the_only_one(local, registries):
    registries.settings_ = Registry()
    register_settings(registries.settings_, (entry("fake-setting"),))
    assert local.get("/api/worlds").json()["settings"] == [
        {"id": "fake-setting", "title": "Fake setting (development)"}
    ]


def test_worlds_needs_the_owner(lan):
    assert lan.get("/api/worlds").status_code == 401


def test_a_campaign_defaults_to_the_installed_ruleset_in_greyhawk(local):
    """The web tests' install has OSRIC (`make_registries`), the first of the preferred rulesets it has."""
    module = crypt_module(local)
    campaign = started(local, module["id"])
    assert (campaign["ruleset"], campaign["setting"]) == ("osric", "greyhawk")
    detail = local.get(f"/api/campaigns/{campaign['id']}").json()
    assert (detail["ruleset"], detail["setting"]) == ("osric", "greyhawk")


def test_the_defaults_come_from_the_modules_metadata(local, storage):
    module = with_metadata(local, {"system": "fake-rules", "setting": "GREYHAWK"})
    campaign = started(local, module["id"])
    assert (campaign["ruleset"], campaign["setting"]) == ("fake-rules", "greyhawk")
    assert (storage.campaigns.get(campaign["id"]).ruleset, storage.campaigns.get(campaign["id"]).setting) == (
        "fake-rules",
        "greyhawk",
    )


def test_a_setting_matches_by_title_or_id_case_insensitively(local):
    module = with_metadata(local, {"setting": "Greyhawk"})
    assert started(local, module["id"])["setting"] == "greyhawk"
    module = with_metadata(local, {"setting": "greyhawk"})
    assert started(local, module["id"])["setting"] == "greyhawk"


def test_an_unregistered_system_or_setting_in_the_metadata_falls_back(local):
    module = with_metadata(local, {"system": "adnd9", "setting": "Mystara"})
    campaign = started(local, module["id"])
    assert (campaign["ruleset"], campaign["setting"]) == ("osric", "greyhawk")


def test_a_module_set_in_the_forgotten_realms_starts_its_campaigns_there(local):
    module = with_metadata(local, {"setting": "Forgotten Realms"})
    assert started(local, module["id"])["setting"] == "forgotten-realms"


def test_the_choice_wins_over_the_metadata_and_null_means_no_setting(local):
    module = with_metadata(local, {"setting": "Greyhawk"})
    campaign = started(local, module["id"], ruleset="fake-rules", setting=None)
    assert (campaign["ruleset"], campaign["setting"]) == ("fake-rules", "")


def test_unknown_ids_are_refused_and_nothing_is_created(local):
    module = crypt_module(local)
    for choice in ({"ruleset": "osric"}, {"setting": "mystara"}):
        response = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"], **choice})
        assert response.status_code == 422
        assert next(iter(choice.values())) in response.json()["error"]
    assert local.get("/api/campaigns").json() == []
