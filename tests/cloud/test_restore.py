"""Restore (cloud storage Task 8): what a backup store holds is listed by install, and the owner's choice of its items
comes back under their own ids: a campaign brings its module (and its setting) along, modules go first, and an item
that is here already is left alone unless the owner confirmed replacing it. The store is a local folder; never a real
call."""

import asyncio
import json

import pytest

from delve.cloud.backup import run_backup
from delve.cloud.bundles import pack, unpack_into
from delve.cloud.restore import backed_up_installs, backup_index, restore_items
from delve.cloud.store import LocalStore
from delve.config import Config
from delve.domain.modules import ModuleMap
from delve.play.campaign_maps import played_revision
from delve.storage import open_storage
from tests.cloud.test_backup import CLOCK, INSTALL
from tests.cloud.test_bundles import CRYPT, crypt_module, greyhawk

OTHER = "ins_ba9876543210"


@pytest.fixture
def source(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "source"))
    yield opened
    opened.close()


@pytest.fixture
def target(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "target"))
    yield opened
    opened.close()


@pytest.fixture
def store(tmp_path):
    (tmp_path / "store").mkdir()
    return LocalStore(tmp_path / "store")


@pytest.fixture
def backed_up(source, store):
    """The crypt (two revisions), Tuesday on its first and Greyhawk, backed up from the source install."""
    module = crypt_module(source)
    campaign = source.campaigns.create("Tuesday", module.id, 1, setting="greyhawk", ruleset="osric")
    beat = source.beats.open(campaign.id, [{"player": "owner", "character_ids": [], "kind": "do", "text": "Look"}])
    source.story.append(campaign.id, beat.id, "dm", {"text": "Dust settles."})
    greyhawk(source)
    assert run(run_backup(source, store, INSTALL, now=CLOCK, name="laptop")).status == "ok"
    return module, source.campaigns.get(campaign.id)


def run(coro):
    return asyncio.run(coro)


def restore(target, store, items, *, replace=False, install=INSTALL):
    return run(restore_items(target, store, install, items, replace=replace))


def test_backed_up_installs_lists_each_index(source, store, backed_up):
    run(run_backup(source, store, OTHER, now=CLOCK, name="desktop"))
    (store.root / "stray.json").write_text("{}")
    (store.root / "ins_000000000000").mkdir()
    (store.root / "ins_000000000000" / "index.json").write_text("not json")

    installs = run(backed_up_installs(store))
    assert [(i["install_id"], i["name"]) for i in installs] == [(OTHER, "desktop"), (INSTALL, "laptop")], (
        "the latest first; a damaged index is skipped"
    )
    assert all(set(i) == {"install_id", "name", "updated_at"} and i["updated_at"] for i in installs)


def test_the_index_says_what_exists_here(source, target, store, backed_up):
    module, campaign = backed_up
    items = {(i["kind"], i["item_id"]): i for i in run(backup_index(target, store, INSTALL))}
    assert set(items) == {("module", module.id), ("campaign", campaign.id), ("setting", "greyhawk")}
    assert not any(item["exists_here"] for item in items.values())
    assert items[("campaign", campaign.id)]["module_id"] == module.id
    assert items[("campaign", campaign.id)]["setting_id"] == "greyhawk"
    assert set(items[("module", module.id)]) == {
        "kind", "item_id", "title", "hash", "size", "backed_up_at", "on_install", "exists_here"
    }

    here = {(i["kind"], i["item_id"]): i["exists_here"] for i in run(backup_index(source, store, INSTALL))}
    assert all(here.values())


def test_restore_a_campaign_brings_its_module_along(source, target, store, backed_up):
    module, campaign = backed_up
    results = restore(target, store, [("campaign", campaign.id)])

    assert results == [
        {"kind": "module", "item_id": module.id, "ok": True, "warnings": [], "error": None, "added": True},
        {"kind": "setting", "item_id": "greyhawk", "ok": True, "warnings": [], "error": None, "added": True},
        {"kind": "campaign", "item_id": campaign.id, "ok": True, "warnings": [], "error": None},
    ]
    assert target.snapshots.dump("campaign", campaign.id) == source.snapshots.dump("campaign", campaign.id)
    assert target.snapshots.dump("module", module.id) == source.snapshots.dump("module", module.id)
    restored = target.campaigns.get(campaign.id)
    assert [m.source for m in played_revision(target, restored).maps] == [CRYPT], "it plays on revision 1"


def test_each_copy_is_fetched_and_unpacked_once_off_the_loop(source, target, store, backed_up, monkeypatch):
    """DEL-171: a campaign's copy was unpacked three times on the event loop (its needs, its item, its revision),
    then once more in a thread to restore it."""
    import threading

    import delve.cloud.restore as restore_module

    _, campaign = backed_up
    unpacked: list[bool] = []
    real_unpack = restore_module.unpack

    def counted(data):
        unpacked.append(threading.current_thread() is threading.main_thread())
        return real_unpack(data)

    monkeypatch.setattr(restore_module, "unpack", counted)
    results = restore(target, store, [("campaign", campaign.id)])
    assert all(r["ok"] for r in results) and len(results) == 3
    assert unpacked == [False] * 3, "the campaign, its module and its setting: once each, in a thread"


def test_a_campaign_whose_module_is_here_restores_alone(source, target, store, backed_up):
    module, campaign = backed_up
    restore(target, store, [("module", module.id)])
    results = restore(target, store, [("campaign", campaign.id)])
    assert [(r["kind"], r.get("added", False)) for r in results] == [("setting", True), ("campaign", False)]
    assert all(r["ok"] for r in results)


def test_an_existing_item_needs_replace(source, target, store, backed_up):
    module, campaign = backed_up
    restore(target, store, [("campaign", campaign.id)])
    target.campaigns.set_status(campaign.id, "finished")

    refused = restore(target, store, [("campaign", campaign.id), ("module", module.id)])
    assert refused == [
        {"kind": "module", "item_id": module.id, "ok": False, "warnings": [], "error": "exists"},
        {"kind": "campaign", "item_id": campaign.id, "ok": False, "warnings": [], "error": "exists"},
    ]
    assert target.campaigns.get(campaign.id).status == "finished", "left alone"

    replaced = restore(target, store, [("campaign", campaign.id)], replace=True)
    assert replaced == [{"kind": "campaign", "item_id": campaign.id, "ok": True, "warnings": [], "error": None}]
    assert target.campaigns.get(campaign.id).status == "in_progress"


def test_restore_from_another_installs_backups(source, target, store, backed_up):
    """A new machine has a new install id; it restores from the old one's backups in the same store."""
    module, _ = backed_up
    assert run(run_backup(target, store, OTHER, now=CLOCK)).status == "ok"

    results = restore(target, store, [("module", module.id)], install=INSTALL)
    assert results == [{"kind": "module", "item_id": module.id, "ok": True, "warnings": [], "error": None}]
    assert target.modules.get(module.id).title == "The Crypt"
    assert json.loads(run(store.get(f"{OTHER}/index.json")))["items"] == [], "the other install's index is its own"


def test_several_items_restore_in_dependency_order(source, target, store, backed_up):
    module, campaign = backed_up
    results = restore(target, store, [("campaign", campaign.id), ("setting", "greyhawk"), ("module", module.id)])
    assert [(r["kind"], r["ok"], "added" in r) for r in results] == [
        ("module", True, False),
        ("setting", True, False),
        ("campaign", True, False),
    ]


def test_an_item_asked_twice_restores_once(source, target, store, backed_up):
    module, _ = backed_up
    results = restore(target, store, [("module", module.id), ("module", module.id)])
    assert len(results) == 1 and results[0]["ok"]


def test_an_item_not_in_the_backup_says_so(target, store, backed_up):
    results = restore(target, store, [("module", "mod_nothere")])
    assert results == [
        {"kind": "module", "item_id": "mod_nothere", "ok": False, "warnings": [],
         "error": "This backup has no copy of it."}
    ]


def test_a_campaign_whose_module_isnt_in_the_backup_is_refused(source, target, store, backed_up):
    module, campaign = backed_up
    (store.root / INSTALL / "modules" / f"{module.id}.dmod").unlink()
    results = restore(target, store, [("campaign", campaign.id)])
    by_kind = {r["kind"]: r for r in results}
    assert by_kind["module"] == {
        "kind": "module", "item_id": module.id, "ok": False, "warnings": [],
        "error": "This backup has no copy of it.", "added": True,
    }
    assert by_kind["campaign"]["ok"] is False and by_kind["campaign"]["error"] == "Restore its module first."
    assert campaign.id not in target.snapshots.item_ids("campaign")


def test_a_campaign_whose_module_here_lacks_its_revision_says_to_replace_the_module(source, target, store, backed_up):
    module, campaign = backed_up
    unpack_into(target, pack(source, "module", module.id).data, replace=False)  # the crypt here at revision 2
    source.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT + "\n", is_default=True))
    source.revisions.snapshot(module.id)
    source.campaigns.set_revision(campaign.id, 3)
    assert run(run_backup(source, store, INSTALL, now=CLOCK)).status == "ok"

    results = restore(target, store, [("campaign", campaign.id)])
    assert [r["kind"] for r in results] == ["setting", "campaign"]
    assert results[1]["ok"] is False
    assert results[1]["error"] == (
        "The Crypt here doesn't have the revision this campaign plays. Tick the module and replace it."
    )
    assert campaign.id not in target.snapshots.item_ids("campaign")

    ticked = restore(target, store, [("campaign", campaign.id), ("module", module.id)], replace=True)
    assert [(r["kind"], r["ok"]) for r in ticked] == [("module", True), ("campaign", True)]


def test_a_damaged_copy_is_refused_and_the_rest_restore(source, target, store, backed_up):
    _, campaign = backed_up
    (store.root / INSTALL / "settings" / "greyhawk.dset").write_bytes(b"not a zip")
    results = restore(target, store, [("campaign", campaign.id)])
    by_kind = {r["kind"]: r for r in results}
    assert by_kind["setting"]["error"] == "This copy isn't a Delve bundle."
    assert by_kind["module"]["ok"] and by_kind["campaign"]["ok"]


def test_a_missing_store_folder_is_one_error_per_item(target, tmp_path, backed_up):
    module, _ = backed_up
    gone = LocalStore(tmp_path / "gone")
    results = restore(target, gone, [("module", module.id)])
    assert results == [
        {"kind": "module", "item_id": module.id, "ok": False, "warnings": [], "error": "This backup has no copy of it."}
    ]


def test_a_copy_of_another_item_under_an_items_name_is_refused(source, target, store, backed_up):
    module, _ = backed_up
    other = source.modules.create("The Other", {})
    (store.root / INSTALL / "modules" / f"{module.id}.dmod").write_bytes(pack(source, "module", other.id).data)

    (result,) = restore(target, store, [("module", module.id)])

    assert result["error"] == "This copy is of another item."
    assert target.snapshots.item_ids("module") == []
