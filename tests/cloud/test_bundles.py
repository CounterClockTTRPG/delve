"""Bundles (cloud storage Task 6): a module, a campaign or a setting packed into one zip, and unpacked into another
install, where the campaign plays on the revision it pinned."""

import io
import json
import struct
import threading
import zipfile

import pytest
from sqlalchemy import text

from delve.cloud import bundles
from delve.cloud.bundles import EXTENSIONS, FORMAT, BundleRefused, pack, unpack, unpack_into
from delve.cloud.connections import StoreConfig, save_store
from delve.config import Config
from delve.dice import SeededRng
from delve.dm.tools import ToolHost
from delve.domain.modules import ModuleMap
from delve.domain.setting_content import SettingFact
from delve.domain.world import CampaignImage, WorldMapSource, WorldPicture
from delve.play.campaign_maps import played_revision
from delve.play.context import context_for
from delve.storage import open_storage
from delve.storage.interfaces import SnapshotRefused
from tests.fixtures import SAMPLES
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

PNG = b"\x89PNG\r\n\x1a\n" + b"picture"
CRYPT = (SAMPLES / "crypt.dmap").read_text()
HIDDEN = """
room "hidden_crypt" {
  rect 44,14 4 x 6
  label "Hidden Crypt"
}
door at 46,20 { connects room.vestry_alcove, room.hidden_crypt type secret }
"""
SAS = "https://owner.blob.core.windows.net/library?sv=2023-11-03&sp=rl&sig=SAS-XYZZY"
SECRET = "SECRET-ACCESS-XYZZY"


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


def crypt_module(storage):
    """The crypt with an attachment, at revision 1, and with a hidden crypt added at revision 2."""
    module = storage.modules.create("The Crypt", {"author": "Raf"})
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    sha = storage.blobs.put(PNG + b"attachment", "image/png")
    storage.blobs.link(module.id, "attachment", sha)
    storage.revisions.snapshot(module.id)
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT + HIDDEN, is_default=True))
    storage.revisions.snapshot(module.id)
    return storage.modules.get(module.id)


def crypt_campaign(storage, module):
    """A campaign on the crypt's first revision, with Mirela, a story entry and a painted portrait."""
    campaign = storage.campaigns.create("Tuesday", module.id, 1, setting="", ruleset="osric")
    storage.characters.create(campaign.id, "Mirela")
    beat = storage.beats.open(campaign.id, [{"player": "owner", "character_ids": [], "kind": "do", "text": "Look"}])
    storage.story.append(campaign.id, beat.id, "dm", {"text": "Dust settles."})
    sha = storage.blobs.put(PNG + b"portrait", "image/png")
    storage.campaign_images.put(
        CampaignImage(id="img_1", campaign_id=campaign.id, kind="portrait", status="done", blob=sha, mime="image/png")
    )
    return campaign


def greyhawk(storage):
    tile = storage.blobs.put(PNG + b"tile", "image/png")
    original = storage.blobs.put(PNG + b"original", "image/png")
    storage.world_pictures.put(
        WorldPicture(id=original, mime="image/png", width_px=256, height_px=256, max_zoom=0, tiles={"0/0/0": tile})
    )
    storage.setting_facts.add(SettingFact(id=0, setting="greyhawk", text="The Temple fell."))
    geo = {"type": "FeatureCollection", "features": []}
    storage.setting_maps.put("greyhawk", WorldMapSource(name="flanaess", title="Flanaess", dsl="", geo=geo, picture=original))


def entries(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {info.filename: archive.read(info) for info in archive.infolist()}


def rezip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_pack_then_unpack_into_an_empty_install_restores_the_campaign_and_it_plays_on_its_revision(source, target):
    module = crypt_module(source)
    campaign = crypt_campaign(source, module)
    module_bundle = pack(source, "module", module.id)
    campaign_bundle = pack(source, "campaign", campaign.id)

    assert unpack_into(target, module_bundle.data, replace=False) == []
    assert unpack_into(target, campaign_bundle.data, replace=False) == []

    # Every revision comes back with its number, and the bytes with it.
    assert target.snapshots.dump("module", module.id) == source.snapshots.dump("module", module.id)
    assert target.snapshots.dump("campaign", campaign.id) == source.snapshots.dump("campaign", campaign.id)
    assert [target.revisions.get(module.id, n).number for n in (1, 2)] == [1, 2]
    for sha in source.snapshots.dump("campaign", campaign.id).blobs | source.snapshots.dump("module", module.id).blobs:
        assert target.blobs.get(sha) == source.blobs.get(sha)

    # The campaign plays on revision 1, which has no hidden crypt, though the module's head has.
    restored = target.campaigns.get(campaign.id)
    assert (restored.module_id, restored.revision) == (module.id, 1)
    ctx = context_for(target, campaign.id, "beat-2", catalogs=over(PlayReference()))
    played = played_revision(ctx.storage, restored)
    assert [m.source for m in played.maps] == [CRYPT]
    host = ToolHost(target, lambda: SeededRng(1), catalogs=over(PlayReference()))
    moved = host.call(campaign.id, "beat-2", "move_party", {"to": "entry_hall"})
    assert moved["perceived"]["label"] == "Entry Hall"
    assert "error" not in host.call(campaign.id, "beat-2", "room", {"query": "Vestry"})
    assert "No room 'hidden_crypt'" in host.call(campaign.id, "beat-2", "room", {"query": "hidden_crypt"})["error"]


def test_a_bundle_holds_its_manifest_rows_and_blobs(source):
    module = crypt_module(source)
    campaign = crypt_campaign(source, module)
    packed = pack(source, "campaign", campaign.id)

    files = entries(packed.data)
    manifest = json.loads(files["manifest.json"])
    assert manifest == {
        "format": FORMAT,
        "kind": "campaign",
        "item_id": campaign.id,
        "title": "Tuesday",
        "head": manifest["head"],
        "delve_version": manifest["delve_version"],
        "created_at": manifest["created_at"],
        "module_id": module.id,
        "revision": 1,
        "setting": None,
    }
    assert packed.title == "Tuesday"
    portrait = source.campaign_images.get("img_1").blob
    assert f"blobs/{portrait}" in files
    assert {"rows/campaigns.json", "rows/characters.json", "rows/story.json", "rows/blobs.json"} <= set(files)
    assert list(files) == sorted(files)
    with zipfile.ZipFile(io.BytesIO(packed.data)) as archive:
        assert archive.getinfo(f"blobs/{portrait}").compress_type == zipfile.ZIP_STORED
        assert archive.getinfo("rows/story.json").compress_type == zipfile.ZIP_DEFLATED
        assert {info.date_time for info in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    assert EXTENSIONS == {"module": "dmod", "campaign": "dcmp", "setting": "dset"}


def test_a_setting_bundle_restores_with_its_world_pictures(source, target):
    greyhawk(source)
    packed = pack(source, "setting", "greyhawk")

    assert "module_id" not in json.loads(entries(packed.data)["manifest.json"])
    assert unpack_into(target, packed.data, replace=False) == []
    assert target.snapshots.dump("setting", "greyhawk") == source.snapshots.dump("setting", "greyhawk")
    picture = source.setting_maps.list("greyhawk")[0].picture
    assert target.blobs.get(target.world_pictures.get(picture).tiles["0/0/0"]) == PNG + b"tile"


def test_an_unchanged_item_packs_to_the_same_hash(source):
    module = crypt_module(source)
    campaign = crypt_campaign(source, module)

    first, second = pack(source, "campaign", campaign.id), pack(source, "campaign", campaign.id)
    assert first.hash == second.hash
    assert pack(source, "module", module.id).hash == pack(source, "module", module.id).hash
    greyhawk(source)
    assert pack(source, "setting", "greyhawk").hash == pack(source, "setting", "greyhawk").hash


def test_the_hash_leaves_out_only_the_time_of_packing(source, monkeypatch):
    module = crypt_module(source)
    first = pack(source, "module", module.id)
    monkeypatch.setattr(bundles, "_now", lambda: "2030-01-01T00:00:00+00:00")
    later = pack(source, "module", module.id)

    assert later.hash == first.hash
    assert json.loads(entries(later.data)["manifest.json"])["created_at"] == "2030-01-01T00:00:00+00:00"


def test_a_story_entry_changes_the_campaigns_hash(source):
    module = crypt_module(source)
    campaign = crypt_campaign(source, module)
    before = pack(source, "campaign", campaign.id)

    source.story.append(campaign.id, source.beats.current(campaign.id).id, "dm", {"text": "A door creaks."})

    assert pack(source, "campaign", campaign.id).hash != before.hash


def test_unpack_answers_the_manifest_the_snapshot_and_the_blobs(source):
    module = crypt_module(source)
    packed = pack(source, "module", module.id)

    manifest, snapshot, blobs = unpack(packed.data)

    assert (manifest.format, manifest.kind, manifest.item_id, manifest.title) == (FORMAT, "module", module.id, "The Crypt")
    assert snapshot == source.snapshots.dump("module", module.id)
    (sha,) = snapshot.blobs
    assert blobs == {sha: (PNG + b"attachment", "image/png")}


def test_a_newer_format_is_refused(source):
    module = crypt_module(source)
    files = entries(pack(source, "module", module.id).data)
    files["manifest.json"] = json.dumps(dict(json.loads(files["manifest.json"]), format=FORMAT + 1)).encode()

    with pytest.raises(BundleRefused, match="newer Delve"):
        unpack(rezip(files))


def test_a_tampered_blob_is_refused(source, target):
    module = crypt_module(source)
    files = entries(pack(source, "module", module.id).data)
    (name,) = [name for name in files if name.startswith("blobs/")]
    files[name] = b"something else"

    with pytest.raises(BundleRefused):
        unpack_into(target, rezip(files), replace=False)
    assert target.snapshots.item_ids("module") == []
    assert not target.blobs.exists(name.removeprefix("blobs/"))


@pytest.mark.parametrize("damage", ["no manifest", "not a zip", "bad json", "kind"])
def test_a_damaged_bundle_is_refused(source, damage):
    module = crypt_module(source)
    files = entries(pack(source, "module", module.id).data)
    if damage == "no manifest":
        del files["manifest.json"]
    elif damage == "bad json":
        files["rows/modules.json"] = b"{not json"
    elif damage == "kind":
        files["manifest.json"] = json.dumps(dict(json.loads(files["manifest.json"]), kind="novel")).encode()
    data = b"not a zip at all" if damage == "not a zip" else rezip(files)

    with pytest.raises(BundleRefused):
        unpack(data)


def test_a_refused_restore_puts_no_blobs(source, target):
    module = crypt_module(source)
    campaign = crypt_campaign(source, module)
    packed = pack(source, "campaign", campaign.id)

    with pytest.raises(SnapshotRefused, match="Restore its module first."):
        unpack_into(target, packed.data, replace=False)
    assert not target.blobs.exists(source.campaign_images.get("img_1").blob)


def test_no_credential_is_ever_inside_a_bundle(source, tmp_path):
    """A friend's library credential, or the backup store's, never reaches a bundle (and so never the backups)."""
    data_dir = tmp_path / "source"
    save_store(data_dir, "library", StoreConfig(provider="azure", sas_url=SAS, right="read"), keep_secret=False)
    s3 = StoreConfig(
        provider="s3", endpoint="https://r2.example", bucket="b", access_key_id="AKID-XYZZY", secret_access_key=SECRET
    )
    save_store(data_dir, "backup", s3, keep_secret=False)
    source.settings.save({"backup": {"time": "04:00"}, "note": SECRET})
    module = crypt_module(source)
    campaign = crypt_campaign(source, module)
    greyhawk(source)

    for packed in (
        pack(source, "module", module.id),
        pack(source, "campaign", campaign.id),
        pack(source, "setting", "greyhawk"),
    ):
        files = entries(packed.data)
        assert not {"rows/settings.json", "rows/accounts.json", "rows/login_sessions.json"} & set(files)
        for name, data in files.items():
            for secret in (b"SAS-XYZZY", b"AKID-XYZZY", SECRET.encode(), b"library-store", b"backup-store"):
                assert secret not in data, name


def test_a_campaigns_join_token_is_in_no_entry_and_a_restored_one_gets_a_fresh_token(source, target):
    """The join token is a credential: it stays here, and the restored table gets a link of its own."""
    module = crypt_module(source)
    campaign = crypt_campaign(source, module)
    token = source.campaigns.get(campaign.id).join_token
    assert token
    packed = pack(source, "campaign", campaign.id)

    for name, data in entries(packed.data).items():
        assert token.encode() not in data, name

    unpack_into(target, pack(source, "module", module.id).data, replace=False)
    unpack_into(target, packed.data, replace=False)
    fresh = target.campaigns.get(campaign.id).join_token
    assert fresh and fresh != token
    assert target.campaigns.by_join_token(fresh).id == campaign.id
    assert target.campaigns.by_join_token(token) is None

    # Replacing it gives it a fresh one again.
    unpack_into(target, packed.data, replace=True)
    again = target.campaigns.get(campaign.id).join_token
    assert again and again not in (token, fresh)
    assert target.campaigns.by_join_token(again).id == campaign.id


def test_a_bundle_reads_one_moment_of_the_database_pictures_included(source, monkeypatch):
    """A portrait painted while the campaign is packed is in neither its rows nor its blobs."""
    from delve.storage.sqlite import snapshots_repo

    module = crypt_module(source)
    campaign = crypt_campaign(source, module)
    real = snapshots_repo._rows
    painted = []

    def painted_in_between(connection, table, where):
        rows = real(connection, table, where)
        if table.name == "campaigns" and not painted:
            # In a thread of its own, as a beat's task is: outside the packing's transaction.
            painter = threading.Thread(target=paint)
            painter.start()
            painter.join()
        return rows

    def paint():
        sha = source.blobs.put(PNG + b"second portrait", "image/png")
        image = CampaignImage(id="img_2", campaign_id=campaign.id, kind="portrait", status="done", blob=sha, mime="image/png")
        source.campaign_images.put(image)
        painted.append(sha)

    monkeypatch.setattr(snapshots_repo, "_rows", painted_in_between)
    files = entries(pack(source, "campaign", campaign.id).data)
    assert painted
    assert f"blobs/{painted[0]}" not in files
    assert [row["id"] for row in json.loads(files["rows/campaign_images.json"])] == ["img_1"]


def test_a_forged_setting_bundle_with_an_account_a_login_and_a_setting_is_refused_and_inserts_nothing(source, target):
    """Wei's reproduction (audit finding 1): a `.dset` that also names `accounts`, `login_sessions` and `settings`."""
    greyhawk(source)
    files = entries(pack(source, "setting", "greyhawk").data)
    account = {"id": "acc_evil", "username": "evil", "password_hash": "x", "created_at": "2026", "organiser": True,
               "owner": True, "display_name": "Evil", "language": "en"}
    login = {"id": "ls_evil", "account_id": "acc_evil", "token_hash": "0" * 64, "created_at": "2026",
             "last_used_at": "2026"}
    files["rows/accounts.json"] = json.dumps([account]).encode()
    files["rows/login_sessions.json"] = json.dumps([login]).encode()
    files["rows/settings.json"] = json.dumps([{"key": "evil", "value": {"x": 1}, "updated_at": "2026"}]).encode()

    with pytest.raises(SnapshotRefused, match="This copy holds more than its item."):
        unpack_into(target, rezip(files), replace=False)
    with target.db.connect() as connection:
        for table in ("accounts", "login_sessions", "settings", "setting_facts", "world_pictures"):
            assert connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table


def test_an_entry_over_the_cap_is_refused_before_it_is_read(source, monkeypatch):
    module = crypt_module(source)
    files = entries(pack(source, "module", module.id).data)
    files["rows/module_texts.json"] = b"[" + b" " * 10_000 + b"]"
    monkeypatch.setattr(bundles, "MAX_ENTRY", 5_000)

    with pytest.raises(BundleRefused, match="too large"):
        unpack(rezip(files))


def test_a_bundle_over_the_total_cap_is_refused(source, monkeypatch):
    module = crypt_module(source)
    data = pack(source, "module", module.id).data
    total = sum(len(content) for content in entries(data).values())
    monkeypatch.setattr(bundles, "MAX_TOTAL", total - 1)

    with pytest.raises(BundleRefused, match="too large"):
        unpack(data)


def test_an_entry_that_lies_about_its_size_is_refused(source, monkeypatch):
    """A zip bomb declares a small size: reading stops there, and the entry is refused."""
    module = crypt_module(source)
    files = entries(pack(source, "module", module.id).data)
    name = b"rows/module_texts.json"
    files[name.decode()] = b"[" + b" " * 10_000 + b"]"
    data = bytearray(rezip(files))
    monkeypatch.setattr(bundles, "MAX_ENTRY", 5_000)
    central = data.find(b"PK\x01\x02")
    while data[central + 46 : central + 46 + len(name)] != name:
        central = data.find(b"PK\x01\x02", central + 4)
    struct.pack_into("<I", data, central + 24, 100)  # its uncompressed size, in the central directory

    with pytest.raises(BundleRefused):
        unpack(bytes(data))
