"""The browser checks' server (`tests/e2e/fake_play_server.py`) prepares what the specs expect."""

from delve.config import Config
from delve.storage import open_storage
from tests.e2e import fake_play_server
from tests.e2e.test_play_with_fake_claude import SECRET
from tests.fixtures import rulesets


def test_the_crypts_campaign_waits_for_its_banner_and_delve_starting_paints_it(tmp_path):
    """The campaign is made in storage, not through the API, so it asks for its banner here; the fake images are
    free, so `delve serve` paints it at its start (`banners.wake`), for the empty story's banner in the browser."""
    fake_play_server.prepare(tmp_path, rulesets.osric_packs_dir())
    storage = open_storage(Config(data_dir=tmp_path / "data"))
    try:
        [campaign] = storage.campaigns.list()
        [banner] = storage.campaign_images.list(campaign.id, kind="banner")
        assert banner.status == "waiting"
        assert "Crypt of Saint Vellis" in banner.prompt and "Greyhawk" in banner.prompt
        assert SECRET not in banner.prompt
    finally:
        storage.close()


def test_the_fake_images_paint_a_picture_that_shows():
    """The banner the browser checks screenshot fills its frame with the fake's pixel, so it must be opaque."""
    import io

    from PIL import Image

    from delve.images.fake import PIXEL_PNG

    pixel = Image.open(io.BytesIO(PIXEL_PNG)).convert("RGBA").getpixel((0, 0))
    assert pixel[3] == 255


def test_the_stores_folders_open_as_a_backup_store_that_fails_in_part_and_a_library_read_and_managed(tmp_path, monkeypatch):
    """`zzz-storage.spec.ts` sets folders as the stores: the backups' refuses the settings' objects, so a run fails in
    part, and the library's read-only view probes as `read` while the library itself probes as `manage`."""
    import asyncio

    import pytest

    from delve.cloud import connections
    from delve.cloud.store import Refused, probe

    root = tmp_path / f"{fake_play_server.STORES_PREFIX}1"
    (root / "stale").mkdir(parents=True)
    fake_play_server.make_stores(root)
    assert sorted(path.name for path in root.iterdir()) == ["backups", "library", "library-read"]
    monkeypatch.setattr(connections.Stores, "open", connections.Stores.open)
    fake_play_server.fake_stores(root)
    stores = connections.Stores(tmp_path)

    def opened(name: str):
        return stores.open(connections.StoreConfig(provider="local", root=str(root / name)))

    async def run() -> None:
        backups = opened("backups")
        await backups.put("ins_000000000000/modules/mod_1.dscn", b"module")
        with pytest.raises(Refused):
            await backups.put("ins_000000000000/settings/greyhawk.json", b"setting")
        assert await probe(opened("library")) == "manage"
        assert await probe(opened("library-read")) == "read"

    asyncio.run(run())
    (tmp_path / "mine").mkdir()
    with pytest.raises(SystemExit):
        fake_play_server.make_stores(tmp_path / "mine")  # a folder of another name is never emptied
    assert (tmp_path / "mine").is_dir()
