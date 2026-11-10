"""One catalog of settings (settings plan Task 1): the web registry and the DM's context are both made from it, and a
setting leaves out the lore facts another setting claims."""

import shutil
from pathlib import Path

import pytest

from delve.__main__ import build_registries
from delve.config import Config
from delve.domain.backends import Registry
from delve.domain.campaigns import MissingPack
from delve.domain.modules import ModuleMap
from delve.domain.world import PLAIN_CALENDAR
from delve.packs import loader
from delve.play.context import context_for
from delve.setting.aun import AunSetting
from delve.setting.catalog import (
    CATALOG,
    SettingEntry,
    catalog,
    claimed_elsewhere,
    entry,
    make_setting,
    register_settings,
)
from delve.setting.fake import FakeSetting
from delve.setting.named import NamedSetting
from delve.storage import open_storage
from tests.fixtures.rulesets import osric_catalogs, setting


def test_the_in_tree_settings_are_aun_and_the_fake():
    registry = Registry()
    register_settings(registry)
    assert [(caps.id, caps.title) for caps in registry.capabilities()] == [
        ("aun", "Aun"),
        ("fake-setting", "Fake setting (development)"),
    ]
    assert isinstance(registry.get("aun"), AunSetting)
    assert isinstance(registry.get("fake-setting"), FakeSetting)


def test_the_packs_settings_join_them_by_title_the_fake_last():
    registry = Registry()
    register_settings(registry, osric_catalogs().settings)
    assert [(caps.id, caps.title) for caps in registry.capabilities()] == [
        ("aun", "Aun"),
        ("forgotten-realms", "Forgotten Realms"),
        ("greyhawk", "Greyhawk"),
        ("fake-setting", "Fake setting (development)"),
    ]
    # By name: a test here resets the loader, after which the packs' classes are imported anew.
    assert type(registry.get("greyhawk")).__name__ == "GreyhawkSetting"
    assert type(registry.get("forgotten-realms")).__name__ == "RealmsSetting"


def test_make_setting_of_no_setting_is_none_and_of_an_unknown_id_is_missing():
    assert make_setting(None) is None
    assert make_setting("") is None
    with pytest.raises(MissingPack) as raised:
        make_setting("nowhere")
    assert (raised.value.kind, raised.value.id) == ("setting", "nowhere")
    assert entry("nowhere") is None
    assert make_setting("aun").id == "aun"
    with pytest.raises(MissingPack):
        make_setting("greyhawk")  # a pack's, not Delve's
    assert make_setting("greyhawk", osric_catalogs().settings).id == "greyhawk"


def test_a_named_setting_is_a_name_and_nothing_else():
    blackmoor = NamedSetting("blackmoor", "Blackmoor")
    assert (blackmoor.id, blackmoor.title, blackmoor.kinds(), blackmoor.world_maps()) == (
        "blackmoor",
        "Blackmoor",
        (),
        (),
    )
    assert blackmoor.calendar() == PLAIN_CALENDAR
    assert blackmoor.search("Glenwood") == [] and blackmoor.page("Glenwood") is None and blackmoor.lore_facts(5) == []
    with pytest.raises(ValueError, match="no kinds"):
        blackmoor.lookup("place", "Glenwood")


def test_the_realms_claim_their_lore_facts():
    assert claimed_elsewhere("forgotten-realms", osric_catalogs().settings) == {"greyhawk", "history", "fake"}


def test_claimed_elsewhere():
    catalog = (
        SettingEntry("greyhawk", "Greyhawk", lambda exclude: FakeSetting(), frozenset({"greyhawk", "history"})),
        SettingEntry("elsewhere", "Elsewhere", lambda exclude: FakeSetting(), frozenset({"history"})),
    )
    assert claimed_elsewhere("greyhawk", catalog) == {"history"}
    assert claimed_elsewhere("elsewhere", catalog) == {"greyhawk", "history"}
    assert claimed_elsewhere("greyhawk", osric_catalogs().settings) == {"forgotten-realms", "fake"}


def test_greyhawk_leaves_out_facts_another_setting_claims():
    assert "history" in {fact.category for fact in setting("greyhawk", frozenset()).lore_facts(100)}
    left = setting("greyhawk", frozenset({"history"})).lore_facts(100)
    assert left and "history" not in {fact.category for fact in left}


def test_context_and_registry_agree(tmp_path):
    storage = open_storage(Config(data_dir=tmp_path / "data"))
    try:
        module = storage.modules.create("The Crypt")
        storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
        revision = storage.revisions.snapshot(module.id)
        registries = build_registries(Config(data_dir=tmp_path / "data"))
        for setting in CATALOG:
            campaign = storage.campaigns.create(
                "Tuesday", module.id, revision.number, setting=setting.id, ruleset="osric"
            )
            assert context_for(storage, campaign.id, "b1", catalogs=osric_catalogs()).setting.id == setting.id
            assert registries.settings_.get(setting.id).id == setting.id
    finally:
        storage.close()


def test_a_pack_setting_is_in_the_catalog_with_its_manifests_fact_categories(tmp_path):
    shutil.copytree(Path(__file__).parent.parent / "fixtures" / "packs" / "test-setting", tmp_path / "test-setting")
    loader.reset()
    try:
        packs, _ = loader.load_packs(tmp_path)
        cat = catalog(packs)
        found = entry("test-setting", cat)
        assert found is not None and found.fact_categories == frozenset({"place"})
        assert make_setting("test-setting", cat).id == "test-setting"
        assert "place" in claimed_elsewhere("aun", cat)
        assert entry("aun", cat) is not None
    finally:
        loader.reset()
