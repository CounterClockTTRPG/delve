"""Reading a world map's picture in the background (plan 7 Task 12): a `worldmap` job that ends with a world map in
review, of a module, a campaign or a setting, its tiles stored and its doubts listed; a cancelled or failed job leaves no map
and no upload. Claude is `FakeDM` answering from the synthetic picture's truth; the OCR is the fake one."""

import asyncio
import io

import pytest

from delve.config import Config
from delve.conversions import ConversionServices, cancel, wait
from delve.conversions.worldmap import MapNameTaken, check_worldmap, start_worldmap
from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice
from delve.domain.world import WorldMapSource
from delve.maps.geo.geojson import from_geojson
from delve.maps.geo.reading.scale import ScaleKey
from delve.modules.source import ModuleSource, load_source, save_source
from delve.modules.worldmaps import get_world_map
from delve.storage import open_storage
from tests.fixtures.rulesets import osric_catalogs
from tests.maps.geo.pictures import fake_look, fake_ocr, hex_map
from tests.play.conftest import crypt_campaign

THIRTY_MILES = ScaleKey("hex", 30, "miles")


@pytest.fixture(scope="module")
def synthetic():
    return hex_map()


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def picture_file(tmp_path, synthetic):
    out = io.BytesIO()
    synthetic.image.save(out, "PNG")
    path = tmp_path / "worldmap-upload.png"
    path.write_bytes(out.getvalue())
    return path


def services_for(storage, synthetic, look=None):
    """The job's services, with FakeDM's vision calls answered by the fake look, and the fake OCR."""
    look = look or fake_look(synthetic.truth)
    dm = FakeDM([], vision_handler=lambda prompt, image, media_type: _answer(look, prompt, image, media_type))
    return ConversionServices(
        storage=storage,
        conversion=lambda: (dm, BackendChoice("fake", "fake-large")),
        settings=osric_catalogs().settings,  # Greyhawk is a pack's (its double)
        ocr=None,
        picture_ocr=fake_ocr(synthetic.truth),
    ), dm


def _answer(look, prompt, image, media_type):
    """The fake look's answer, run to its end: its coroutine never awaits anything."""
    coroutine = look(prompt, image, media_type)
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    raise AssertionError("the fake look awaited")


def _done(services, start):
    async def scenario():
        started = await start
        return await wait(services, started.id)

    return asyncio.run(scenario())


def test_a_job_reads_the_picture_into_a_module_map_in_review(tmp_path, storage, synthetic):
    module = storage.modules.create("The Flanaess")
    services, dm = services_for(storage, synthetic)
    path = picture_file(tmp_path, synthetic)
    target = {"module_id": module.id, "name": "flanaess", "title": "The Flanaess"}

    done = _done(services, start_worldmap(services, path, "image/png", THIRTY_MILES, target))

    assert (done.kind, done.status, done.module_id) == ("worldmap", "done", None), done.error
    assert done.target == target
    assert done.step == "routes"
    assert not path.exists(), "the job removes its upload"
    world_map = get_world_map(load_source(storage, module.id), "flanaess")
    assert (world_map.title, world_map.status) == ("The Flanaess", "review")
    geo = from_geojson(world_map.geo).geo
    assert geo.picture is not None and geo.picture.id == world_map.picture
    assert (geo.picture.width_px, geo.picture.height_px) == synthetic.image.size
    assert geo.picture.km_per_px == pytest.approx(geo.frame.width_km / synthetic.image.width)
    picture = storage.world_pictures.get(world_map.picture)
    assert picture is not None and picture.tiles and storage.blobs.get(picture.id) is not None
    doubts = world_map.reading["doubts"]
    assert doubts and {d["kind"] for d in doubts} >= {"cell-mixed"}
    assert done.result["picture"] == picture.id and done.result["doubts"] == len(doubts)
    assert dm.vision_prompts, "Claude was asked about the colours"


def test_a_job_reads_the_picture_into_a_campaign_map_in_review_knowing_nothing(tmp_path, storage, synthetic):
    campaign = crypt_campaign(storage, setting=None)
    services, _ = services_for(storage, synthetic)
    target = {"campaign_id": campaign.id, "name": "flanaess", "title": ""}

    done = _done(
        services, start_worldmap(services, picture_file(tmp_path, synthetic), "image/png", THIRTY_MILES, target)
    )

    assert done.status == "done", done.error
    assert done.target == {"campaign_id": campaign.id, "name": "flanaess", "title": "flanaess"}
    world_map = storage.world_maps.get(campaign.id, "flanaess")
    assert (world_map.status, world_map.source, world_map.title) == ("review", "campaign", "flanaess")
    assert world_map.knowledge is not None and not world_map.knowledge.everything and not world_map.knowledge.cells
    assert world_map.reading["clusters"] and world_map.picture


def test_a_picture_read_into_a_setting(tmp_path, storage, synthetic):
    services, _ = services_for(storage, synthetic)
    published = []
    services.publish = lambda kind, data: published.append((kind, data))
    target = {"setting_id": "greyhawk", "name": "flanaess", "title": "The Flanaess"}

    done = _done(
        services, start_worldmap(services, picture_file(tmp_path, synthetic), "image/png", THIRTY_MILES, target)
    )

    assert done.status == "done", done.error
    assert done.target == target
    world_map = storage.setting_maps.get("greyhawk", "flanaess")
    assert (world_map.status, world_map.title, world_map.dsl) == ("review", "The Flanaess", "")
    assert world_map.reading["clusters"] and world_map.picture == done.result["picture"]
    assert ("setting", {"id": "greyhawk"}) in published
    with pytest.raises(KeyError):
        check_worldmap(storage, THIRTY_MILES, {"setting_id": "atlantis", "name": "x"})
    with pytest.raises(MapNameTaken):
        check_worldmap(storage, THIRTY_MILES, {"setting_id": "greyhawk", "name": "flanaess"}, services.settings)
    with pytest.raises(ValueError, match="not two"):
        check_worldmap(storage, THIRTY_MILES, {"setting_id": "greyhawk", "module_id": "mod_x", "name": "x"})


def test_cancel_leaves_no_map_and_no_upload(tmp_path, storage, synthetic):
    module = storage.modules.create("The Flanaess")
    gate = asyncio.Event()
    look = fake_look(synthetic.truth)

    async def held(prompt, image, media_type):
        await gate.wait()
        return await look(prompt, image, media_type)

    services, dm = services_for(storage, synthetic)

    async def vision_call(prompt, image, media_type, choice, *, timeout=None, on_usage=None):
        return await held(prompt, image, media_type)

    dm.vision_call = vision_call
    path = picture_file(tmp_path, synthetic)
    target = {"module_id": module.id, "name": "flanaess"}

    async def scenario():
        started = await start_worldmap(services, path, "image/png", THIRTY_MILES, target)
        while services.storage.conversions.get(started.id).step != "terrain":
            await asyncio.sleep(0.01)
        return await cancel(services, started.id)

    cancelled = asyncio.run(scenario())

    assert cancelled.status == "cancelled"
    assert get_world_map(load_source(storage, module.id), "flanaess") is None
    assert not path.exists()


def test_a_picture_that_cant_be_read_fails_the_job_and_leaves_no_map(tmp_path, storage, synthetic):
    module = storage.modules.create("The Flanaess")
    services, _ = services_for(storage, hex_map(lines=False))
    path = tmp_path / "worldmap-plain.png"
    out = io.BytesIO()
    hex_map(lines=False).image.save(out, "PNG")
    path.write_bytes(out.getvalue())

    done = _done(
        services, start_worldmap(services, path, "image/png", THIRTY_MILES, {"module_id": module.id, "name": "x"})
    )

    assert done.status == "failed" and "No hex grid" in done.error
    assert load_source(storage, module.id).worldmaps == ()
    assert not path.exists()


def test_the_target_and_key_are_checked_before_the_job_starts(tmp_path, storage, synthetic):
    module = storage.modules.create("The Flanaess")
    save_source(storage, module.id, ModuleSource(worldmaps=(WorldMapSource("taken", "Taken", "", geo=None),)))
    campaign = crypt_campaign(storage, setting=None)
    with pytest.raises(ValueError):
        check_worldmap(storage, ScaleKey(None, 30, "miles"), {"module_id": module.id, "name": "x"})
    with pytest.raises(ValueError):
        check_worldmap(storage, THIRTY_MILES, {"module_id": module.id, "campaign_id": campaign.id, "name": "x"})
    with pytest.raises(ValueError):
        check_worldmap(storage, THIRTY_MILES, {"module_id": module.id, "name": " "})
    with pytest.raises(KeyError):
        check_worldmap(storage, THIRTY_MILES, {"campaign_id": "cmp_nope", "name": "x"})
    with pytest.raises(MapNameTaken):
        check_worldmap(storage, THIRTY_MILES, {"module_id": module.id, "name": "taken"})

    services, _ = services_for(storage, synthetic)
    path = picture_file(tmp_path, synthetic)
    with pytest.raises(MapNameTaken):
        asyncio.run(
            start_worldmap(services, path, "image/png", THIRTY_MILES, {"module_id": module.id, "name": "taken"})
        )
    assert not path.exists(), "a refused start removes the upload"
    assert storage.conversions.list(limit=5) == []
