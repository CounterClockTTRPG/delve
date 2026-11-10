"""Snapshots (cloud storage Task 5): a module, a campaign or a setting as rows, dumped and restored into another
database, and the records of what was backed up."""

from dataclasses import replace

import pytest

from delve.config import Config
from delve.domain.accounts import Profile
from delve.domain.modules import ModuleMap
from delve.domain.setting_content import SettingAddition, SettingFact
from delve.domain.world import CampaignImage, WorldMapSource, WorldPicture
from delve.storage import open_storage
from delve.storage.interfaces import BackupItem, SnapshotRefused
from delve.storage.sqlite.snapshots_repo import TABLES

PNG = b"\x89PNG\r\n\x1a\n" + b"picture"
GEO = {"type": "FeatureCollection", "features": []}


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


def two_revision_module(storage):
    """"The Crypt", with a text, an attachment and two revisions."""
    module = storage.modules.create("The Crypt", {"author": "Raf"})
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    storage.module_texts.put(
        module.id, {"sections": [{"anchor": "s1", "heading_path": ["Crypt"], "markdown": "A gargoyle waits."}]}
    )
    sha = storage.blobs.put(PNG + b"attachment", "image/png")
    storage.blobs.link(module.id, "attachment", sha)
    storage.revisions.snapshot(module.id)
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt { room a }\n", is_default=True))
    storage.revisions.snapshot(module.id)
    return storage.modules.get(module.id)


def played_campaign(storage, module):
    """A campaign on the module's first revision with a character, a beat, story, a translation, a painted image, a
    DM note and house rules."""
    campaign = storage.campaigns.create("Tuesday", module.id, 1, setting="", ruleset="adnd2e")
    storage.characters.create(campaign.id, "Mirela")
    beat = storage.beats.open(campaign.id, [{"player": "owner", "character_ids": [], "kind": "do", "text": "Look"}])
    entry = storage.story.append(campaign.id, beat.id, "dm", {"text": "Dust settles."})
    storage.translations.put(entry.id, "nl", "Stof daalt.", "done")
    storage.events.append(campaign.id, "look", {"at": "door"}, session=1, beat=beat.id)
    storage.dm_log.append(campaign.id, beat.id, {"type": "text", "text": "Dust settles."})
    storage.notes.create(campaign.id, "secret", "The gargoyle is a mimic.")
    sha = storage.blobs.put(PNG + b"portrait", "image/png")
    storage.campaign_images.put(
        CampaignImage(id="img_1", campaign_id=campaign.id, kind="portrait", status="done", blob=sha, mime="image/png")
    )
    rule = storage.house_rules.create(title="Max hit points at first level")
    bundled = storage.house_rules.create(title="Shields shall be splintered")
    bundle = storage.house_rule_bundles.create(title="Gritty", rule_ids=[bundled.id])
    storage.campaign_house_rules.put(campaign.id, [bundle.id], [rule.id])
    return campaign


def copy_blobs(snapshot, source, target):
    """What a bundle does before it restores (Task 6): the bytes go into the target's blob store."""
    mimes = {row["sha256"]: row["mime"] for row in snapshot.rows.get("blobs", [])}
    for sha in snapshot.blobs:
        target.blobs.put(source.blobs.get(sha), mimes[sha])


def restore(snapshot, source, target, *, replace=False):
    copy_blobs(snapshot, source, target)
    return target.snapshots.restore(snapshot, replace=replace)


def test_a_campaign_round_trips_into_an_empty_database(source, target):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    module_snapshot = source.snapshots.dump("module", module.id)
    campaign_snapshot = source.snapshots.dump("campaign", campaign.id)

    assert restore(module_snapshot, source, target) == []
    assert restore(campaign_snapshot, source, target) == []

    assert target.snapshots.dump("module", module.id) == module_snapshot
    assert target.snapshots.dump("campaign", campaign.id) == campaign_snapshot
    restored = target.campaigns.get(campaign.id)
    assert target.revisions.get(restored.module_id, restored.revision) is not None
    assert target.module_texts.search(module.id, 1, "gargoyle")
    assert {"campaigns", "characters", "story", "translations", "beats", "house_rules"} <= set(campaign_snapshot.rows)
    assert "campaign_carries" not in campaign_snapshot.rows


def test_a_module_keeps_all_its_revisions(source, target):
    module = two_revision_module(source)
    restore(source.snapshots.dump("module", module.id), source, target)
    assert target.modules.get(module.id).head_revision == 2
    assert [target.revisions.get(module.id, n).number for n in (1, 2)] == [1, 2]
    assert target.module_texts.search(module.id, 2, "gargoyle")


def test_a_module_comment_forgets_its_job(source):
    module = two_revision_module(source)
    source.module_comments.create(module.id, "Make the gargoyle meaner.")
    rows = source.snapshots.dump("module", module.id).rows["module_comments"]
    assert [row["conversion_id"] for row in rows] == [None]


def test_a_setting_round_trips_with_its_world_pictures(source, target):
    tile = source.blobs.put(PNG + b"tile", "image/png")
    original = source.blobs.put(PNG + b"original", "image/png")
    source.world_pictures.put(
        WorldPicture(id=original, mime="image/png", width_px=256, height_px=256, max_zoom=0, tiles={"0/0/0": tile})
    )
    source.setting_pages.put(SettingAddition(setting="greyhawk", title="Hommlet", kind="place", text="A village."))
    source.setting_facts.add(SettingFact(id=0, setting="greyhawk", text="The Temple fell."))
    source.setting_maps.put("greyhawk", WorldMapSource(name="flanaess", title="Flanaess", dsl="", geo=GEO, picture=original))
    source.setting_facts.add(SettingFact(id=0, setting="blackmoor", text="Not this one."))
    snapshot = source.snapshots.dump("setting", "greyhawk")

    restore(snapshot, source, target)

    assert target.snapshots.dump("setting", "greyhawk") == snapshot
    assert target.world_pictures.get(original).tiles == {"0/0/0": tile}
    assert [fact.text for fact in target.setting_facts.list("greyhawk")] == ["The Temple fell."]
    assert target.setting_facts.list("blackmoor") == []
    assert source.snapshots.item_ids("setting") == ["blackmoor", "greyhawk"]


def test_blobs_referenced_anywhere_are_found(source):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    tile = source.blobs.put(PNG + b"tile", "image/png")
    original = source.blobs.put(PNG + b"original", "image/png")
    source.world_pictures.put(
        WorldPicture(id=original, mime="image/png", width_px=256, height_px=256, max_zoom=0, tiles={"0/0/0": tile})
    )
    source.setting_maps.put("greyhawk", WorldMapSource(name="flanaess", title="Flanaess", dsl="", geo=GEO, picture=original))

    attachment = source.blobs.links(module.id)[0][1]
    portrait = source.campaign_images.get("img_1").blob
    assert source.snapshots.dump("module", module.id).blobs == {attachment}
    assert source.snapshots.dump("campaign", campaign.id).blobs == {portrait}
    setting = source.snapshots.dump("setting", "greyhawk")
    assert setting.blobs == {tile, original}
    assert {row["sha256"] for row in setting.rows["blobs"]} == {tile, original}


def test_restore_refuses_an_existing_item_without_replace(source):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    with pytest.raises(SnapshotRefused):
        source.snapshots.restore(source.snapshots.dump("module", module.id), replace=False)
    with pytest.raises(SnapshotRefused):
        source.snapshots.restore(source.snapshots.dump("campaign", campaign.id), replace=False)


def test_replace_removes_rows_the_snapshot_doesnt_have(source):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    snapshot = source.snapshots.dump("campaign", campaign.id)
    source.characters.create(campaign.id, "Tansy")
    source.campaigns.set_status(campaign.id, "paused")

    assert source.snapshots.restore(snapshot, replace=True) == []

    assert [c.name for c in source.characters.list(campaign.id)] == ["Mirela"]
    assert source.campaigns.get(campaign.id).status == "in_progress"
    assert source.snapshots.dump("campaign", campaign.id) == snapshot


def test_replace_keeps_a_module_its_campaigns_play(source):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    snapshot = source.snapshots.dump("module", module.id)
    source.modules.rename(module.id, "The Crypt, edited")
    source.modules.put_map(module.id, ModuleMap("annex", "map", "map annex {}\n", is_default=False))

    assert source.snapshots.restore(snapshot, replace=True) == []

    assert source.modules.get(module.id).title == "The Crypt"
    assert [m.name for m in source.modules.get(module.id).maps] == ["crypt"]
    assert source.campaigns.get(campaign.id) is not None
    assert source.snapshots.dump("module", module.id) == snapshot


def test_a_newer_head_is_refused(source, target):
    module = two_revision_module(source)
    snapshot = replace(source.snapshots.dump("module", module.id), head="9999_future")
    with pytest.raises(SnapshotRefused):
        target.snapshots.restore(snapshot, replace=False)
    assert target.modules.get(module.id) is None


def test_an_unknown_account_is_unlinked_with_a_warning(source, target):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    account = source.accounts.create("mira", Profile(display_name="Mira"))
    seat = source.seats.create(campaign.id, "Mira", "en", "player", account_id=account.id)
    restore(source.snapshots.dump("module", module.id), source, target)

    warnings = restore(source.snapshots.dump("campaign", campaign.id), source, target)

    assert target.seats.get(seat.id).account_id is None
    assert len(warnings) == 1 and "Mira" in warnings[0]


def test_house_rules_present_are_kept(source, target):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    snapshot = source.snapshots.dump("campaign", campaign.id)
    restore(source.snapshots.dump("module", module.id), source, target)
    restore(snapshot, source, target)
    rule_id = snapshot.rows["house_rules"][0]["id"]
    target.house_rules.save(replace(target.house_rules.get(rule_id), title="Mine now"))
    target.campaigns.delete(campaign.id)

    assert target.snapshots.restore(snapshot, replace=False) == []

    assert target.house_rules.get(rule_id).title == "Mine now"
    assert target.campaign_house_rules.get(campaign.id) == source.campaign_house_rules.get(campaign.id)


def test_a_campaign_without_its_module_is_refused(source, target):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    with pytest.raises(SnapshotRefused, match="Restore its module first."):
        target.snapshots.restore(source.snapshots.dump("campaign", campaign.id), replace=False)
    assert target.campaigns.get(campaign.id) is None


def test_counter_ids_in_use_here_are_given_new_ones(source, target):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    restore(source.snapshots.dump("module", module.id), source, target)
    other = target.campaigns.create("Here", module.id, 1, setting="", ruleset="adnd2e")
    target.events.append(other.id, "mine", {}, session=1, beat="b")

    restore(source.snapshots.dump("campaign", campaign.id), source, target)

    assert [e.type for e in target.events.list(campaign.id)] == ["look"]
    assert [e.type for e in target.events.list(other.id)] == ["mine"]


def test_dump_is_deterministic(source):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    assert source.snapshots.dump("module", module.id) == source.snapshots.dump("module", module.id)
    assert source.snapshots.dump("campaign", campaign.id) == source.snapshots.dump("campaign", campaign.id)


def test_item_ids_and_titles(source):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    assert source.snapshots.item_ids("module") == [module.id]
    assert source.snapshots.item_ids("campaign") == [campaign.id]
    assert source.snapshots.title("module", module.id) == "The Crypt"
    assert source.snapshots.title("campaign", campaign.id) == "Tuesday"
    assert source.snapshots.title("setting", "greyhawk") == "greyhawk"
    with pytest.raises(KeyError):
        source.snapshots.dump("module", "mod_missing")


def test_backup_items_are_recorded_by_kind_and_id(source):
    assert source.backup_items.get("module", "mod_1") is None
    first = BackupItem("module", "mod_1", "a" * 64, 10, "2026-10-26T04:00:00+00:00")
    source.backup_items.put(first)
    source.backup_items.put(replace(first, hash="b" * 64, size=12))
    source.backup_items.put(BackupItem("campaign", "cmp_1", "c" * 64, 5, "2026-10-26T04:00:00+00:00"))
    assert source.backup_items.get("module", "mod_1") == replace(first, hash="b" * 64, size=12)
    assert [(i.kind, i.item_id) for i in source.backup_items.list()] == [("campaign", "cmp_1"), ("module", "mod_1")]


def test_a_module_has_no_library_fields_until_published(source):
    module = source.modules.create("The Crypt")
    assert (module.library_key, module.library_version, module.library_hash) == (None, None, None)
    assert (module.library_origin, module.library_author) == (None, None)


def test_a_dump_reads_one_moment_of_the_database(source, monkeypatch):
    """A beat that commits while a backup reads the campaign doesn't reach the copy halfway: it reads as one."""
    from delve.storage.sqlite import snapshots_repo

    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    real = snapshots_repo._rows
    written = []

    def a_beat_commits_in_between(connection, table, where):
        rows = real(connection, table, where)
        if table.name == "campaigns" and not written:
            written.append(source.characters.create(campaign.id, "Tansy"))
            beat = source.story.list(campaign.id)[0].beat_id
            source.story.append(campaign.id, beat, "dm", {"text": "A door opens."})
        return rows

    monkeypatch.setattr(snapshots_repo, "_rows", a_beat_commits_in_between)
    snapshot = source.snapshots.dump("campaign", campaign.id)
    monkeypatch.setattr(snapshots_repo, "_rows", real)

    assert written
    assert [row["name"] for row in snapshot.rows["characters"]] == ["Mirela"]
    assert len(snapshot.rows["story"]) == 1
    later = source.snapshots.dump("campaign", campaign.id)
    assert [row["name"] for row in later.rows["characters"]] == ["Mirela", "Tansy"]
    assert len(later.rows["story"]) == 2


def test_a_dump_inside_a_transaction_sees_its_writes(source):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    with source.transaction():
        source.characters.create(campaign.id, "Tansy")
        snapshot = source.snapshots.dump("campaign", campaign.id)
    assert [row["name"] for row in snapshot.rows["characters"]] == ["Mirela", "Tansy"]


@pytest.mark.parametrize("kind", ["module", "campaign", "setting"])
def test_a_dump_names_only_its_kinds_tables(source, kind):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    source.setting_facts.add(SettingFact(id=0, setting="greyhawk", text="The Temple fell."))
    item_id = {"module": module.id, "campaign": campaign.id, "setting": "greyhawk"}[kind]
    assert set(source.snapshots.dump(kind, item_id).rows) <= {table.name for table in TABLES[kind]}


def test_a_snapshot_naming_another_table_is_refused_and_inserts_nothing(source, target):
    source.setting_facts.add(SettingFact(id=0, setting="greyhawk", text="The Temple fell."))
    snapshot = source.snapshots.dump("setting", "greyhawk")
    account = {"id": "acc_evil", "username": "evil", "password_hash": "x", "created_at": "2026", "owner": True}
    forged = replace(snapshot, rows={**snapshot.rows, "accounts": [account]})

    with pytest.raises(SnapshotRefused, match="This copy holds more than its item."):
        target.snapshots.restore(forged, replace=False)
    assert target.accounts.get("acc_evil") is None
    assert target.setting_facts.list("greyhawk") == []


def forge(snapshot, table, change):
    """The snapshot with the first row of `table` changed."""
    rows = [dict(snapshot.rows[table][0], **change), *snapshot.rows[table][1:]]
    return replace(snapshot, rows={**snapshot.rows, table: rows})


def test_a_campaign_snapshot_carrying_another_campaigns_rows_is_refused(source, target):
    module = two_revision_module(source)
    campaign = played_campaign(source, module)
    other = source.campaigns.create("Wednesday", module.id, 1, setting="", ruleset="adnd2e")
    restore(source.snapshots.dump("module", module.id), source, target)
    restore(source.snapshots.dump("campaign", other.id), source, target)
    snapshot = source.snapshots.dump("campaign", campaign.id)

    for forged in (
        forge(snapshot, "characters", {"campaign_id": other.id, "id": "chr_forged"}),
        forge(snapshot, "campaigns", {"id": other.id}),
        replace(snapshot, rows={**snapshot.rows, "campaigns": snapshot.rows["campaigns"] * 2}),
        forge(snapshot, "translations", {"entry_id": "ent_elsewhere"}),
        forge(snapshot, "house_rules_bundle_rules", {"bundle_id": "hrb_elsewhere"}),
    ):
        with pytest.raises(SnapshotRefused, match="This copy holds more than its item."):
            target.snapshots.restore(forged, replace=False)
    assert target.campaigns.get(campaign.id) is None
    assert target.characters.get("chr_forged") is None
    assert target.campaigns.get(other.id).name == "Wednesday"


def test_a_module_or_setting_snapshot_carrying_another_items_rows_is_refused(source, target):
    module = two_revision_module(source)
    source.setting_facts.add(SettingFact(id=0, setting="greyhawk", text="The Temple fell."))
    snapshot = source.snapshots.dump("module", module.id)
    setting = source.snapshots.dump("setting", "greyhawk")

    for forged in (
        forge(snapshot, "modules", {"id": "mod_elsewhere"}),
        forge(snapshot, "module_maps", {"module_id": "mod_elsewhere"}),
        forge(setting, "setting_facts", {"setting": "blackmoor"}),
    ):
        with pytest.raises(SnapshotRefused, match="This copy holds more than its item."):
            target.snapshots.restore(forged, replace=False)
    assert target.snapshots.item_ids("module") == []
    assert target.snapshots.item_ids("setting") == []


def test_shared_rows_here_are_never_replaced(source, target):
    tile = source.blobs.put(PNG + b"tile", "image/png")
    original = source.blobs.put(PNG + b"original", "image/png")
    picture = WorldPicture(id=original, mime="image/png", width_px=256, height_px=256, max_zoom=0, tiles={"0/0/0": tile})
    source.world_pictures.put(picture)
    source.setting_maps.put("greyhawk", WorldMapSource(name="flanaess", title="Flanaess", dsl="", geo=GEO, picture=original))
    target.world_pictures.put(replace(picture, width_px=512))

    restore(source.snapshots.dump("setting", "greyhawk"), source, target)

    assert target.world_pictures.get(original).width_px == 512


def test_a_module_brings_its_category_and_banner(source, target):
    """DEL-114 and DEL-123: a module's copy carries its category (matched by name where this install has one) and its
    banner picture."""
    module = source.modules.create("Crypt")
    mega = source.module_categories.create("Megadungeons")
    source.modules.set_category(module.id, mega.id)
    sha = source.blobs.put(b"banner bytes", "image/webp")
    source.modules.set_banner(module.id, sha, "image/webp", "uploaded")
    snapshot = source.snapshots.dump("module", module.id)
    assert [row["name"] for row in snapshot.rows["module_categories"]] == ["Megadungeons"]
    assert sha in snapshot.blobs

    target.blobs.put(b"banner bytes", "image/webp")
    target.module_categories.create("One-shots")
    target.snapshots.restore(snapshot, replace=False)
    restored = target.modules.get(module.id)
    assert restored.banner.blob == sha and restored.banner.source == "uploaded"
    assert [c.name for c in target.module_categories.list()] == ["One-shots", "Megadungeons"], "added last"
    assert restored.category_id == mega.id


def test_a_restored_module_takes_the_category_of_the_same_name(source, target):
    module = source.modules.create("Crypt")
    source.modules.set_category(module.id, source.module_categories.create("Megadungeons").id)
    here = target.module_categories.create("megadungeons")
    target.snapshots.restore(source.snapshots.dump("module", module.id), replace=False)
    assert target.modules.get(module.id).category_id == here.id
    assert len(target.module_categories.list()) == 1, "no second one of that name"
