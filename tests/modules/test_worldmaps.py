"""A module's world maps (plan 6 Task 7, Review Focus 5): a `.dscn`'s `worldmaps` come into the module's source, go
back out with the export, and a broken one imports with a `worldmap-unreadable` warning instead of failing."""

import json

import pytest

from delve.config import Config
from delve.domain.world import WorldMapSource
from delve.modules.dscn import Bundle, check
from delve.modules.exporter import export_module
from delve.modules.importer import import_bundle
from delve.modules.source import ModuleSource, derive, from_bundle, load_source, world_includes
from delve.storage import open_storage
from tests.fixtures import SAMPLES
from tests.maps.world import read

CRYPT = SAMPLES / "scenarios" / "crypt-of-saint-vellis"
BROKEN = "workspace broken {\n  model {\n    road r { from nowhere }\n  }\n}\n"


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def with_worldmaps() -> Bundle:
    bundle = Bundle.load(CRYPT)
    bundle.add_worldmap("greyhawk-region", read("greyhawk-region.map"), title="The Greyhawk region")
    bundle.add_worldmap("wastes-of-cynidicea", read("wastes-of-cynidicea.map"))
    bundle.add_worldmap("sulm-akar-buildings", read("sulm-akar-buildings.map"))
    bundle.add_worldmap("broken", BROKEN)
    return bundle


def test_worldmaps_come_into_the_source():
    source = from_bundle(with_worldmaps())
    assert [(w.name, w.title) for w in source.worldmaps] == [
        ("greyhawk-region", "The Greyhawk region"),
        ("wastes-of-cynidicea", "wastes-of-cynidicea"),
        ("sulm-akar-buildings", "sulm-akar-buildings"),
        ("broken", "broken"),
    ]
    assert source.worldmaps[0].dsl == read("greyhawk-region.map")
    assert set(world_includes(source.worldmaps)) >= {"sulm-akar-buildings.map", "sulm-akar-buildings"}


def test_a_worldmap_of_another_type_is_not_read():
    bundle = Bundle.new("Other")
    bundle.add_worldmap("elsewhere", "{}", type="azgaar-map")
    assert from_bundle(bundle).worldmaps == ()


def test_a_broken_worldmap_imports_with_a_warning(storage):
    result = import_bundle(storage, with_worldmaps().to_zip())
    source = load_source(storage, result.module.id)
    assert [w.name for w in source.worldmaps] == [
        "greyhawk-region", "wastes-of-cynidicea", "sulm-akar-buildings", "broken"
    ]  # fmt: skip
    assert source.worldmaps[3].dsl == BROKEN  # kept as it is
    unreadable = [w for w in derive(source, result.module.maps).warnings if w.code == "worldmap-unreadable"]
    assert [(w.ref, w.message) for w in unreadable] == [
        ("worldmap:broken", "The world map broken doesn't read: line 3: unresolved reference 'nowhere'.")
    ]  # the fragment reads through the map that includes it, and gets no warning
    assert unreadable[0].message in result.warnings


def test_worldmaps_survive_the_round_trip(storage):
    first = import_bundle(storage, with_worldmaps().to_zip()).module
    source = load_source(storage, first.id)
    once = export_module(storage, first.id)
    assert [str(d) for d in check(once).diagnostics if d.severity == "error"] == []
    assert [(w["name"], w["file"], w["type"], w.get("title")) for w in once.entries("worldmaps")] == [
        ("greyhawk-region", "worldmaps/greyhawk-region.map", "ttrpg2-worldmap", "The Greyhawk region"),
        ("wastes-of-cynidicea", "worldmaps/wastes-of-cynidicea.map", "ttrpg2-worldmap", None),
        ("sulm-akar-buildings", "worldmaps/sulm-akar-buildings.map", "ttrpg2-worldmap", None),
        ("broken", "worldmaps/broken.map", "ttrpg2-worldmap", None),
    ]
    assert from_bundle(Bundle.load(once.to_zip())).worldmaps == source.worldmaps

    second = import_bundle(storage, once.to_zip()).module
    assert load_source(storage, second.id).worldmaps == source.worldmaps
    assert export_module(storage, second.id).to_zip() == once.to_zip()


def test_the_source_json_keeps_its_worldmaps():
    region = WorldMapSource("region", "The region", "workspace region { }\n")
    source = ModuleSource(worldmaps=(region,))
    assert source.to_json()["worldmaps"] == [
        {
            "name": "region",
            "title": "The region",
            "dsl": "workspace region { }\n",
            "geo": None,
            "picture": None,
            "status": "ready",
            "reading": None,
        }
    ]
    assert ModuleSource.from_json(source.to_json()) == source
    assert ModuleSource.from_json({"texts": []}).worldmaps == ()
    assert WorldMapSource.from_dict(region.to_dict()) == region


# --- plateau 7: geojson world maps and their pictures (plan 7 Task 5) -----------------------------------------------


def geojson_map(picture_id: str | None, *, status: str = "ready") -> WorldMapSource:
    from delve.maps.geo.geojson import to_geojson
    from delve.maps.geo.model import Frame, GeoFeature, GeoMap, Grid, PictureRef

    ref = None if picture_id is None else PictureRef(picture_id, 64, 32, km_per_px=0.5)
    town = GeoFeature("hommlet", "places", "village", "Hommlet", {"type": "Point", "coordinates": [3.0, 4.0]})
    geo = GeoMap(Frame(32.0, 16.0), Grid("square", 4.0, 8, 4), "p" * 32, (town,), ref)
    return WorldMapSource("flanaess", "The Flanaess", "", geo=to_geojson(geo), picture=picture_id, status=status)


def png(width: int = 64, height: int = 32) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (10, 90, 30)).save(out, "PNG")
    return out.getvalue()


def module_with(storage, *worldmaps: WorldMapSource) -> str:
    module = import_bundle(storage, Bundle.load(CRYPT).to_zip()).module
    source = load_source(storage, module.id)
    from dataclasses import replace

    from delve.modules.source import save_source

    save_source(storage, module.id, replace(source, worldmaps=source.worldmaps + worldmaps))
    return module.id


def test_a_geojson_map_and_its_picture_survive_the_round_trip(storage):
    data = png()
    sha = storage.blobs.put(data, "image/png")
    module_id = module_with(storage, geojson_map(sha))
    attachments = load_source(storage, module_id).attachments

    bundle = export_module(storage, module_id)
    assert [str(d) for d in check(bundle).diagnostics if d.severity == "error"] == []
    (entry,) = [w for w in bundle.entries("worldmaps") if w["name"] == "flanaess"]
    assert (entry["type"], entry["file"], entry["title"]) == ("geojson", "worldmaps/flanaess.geojson", "The Flanaess")
    document = json.loads(bundle.read_text(entry["file"]))
    assert document["delve"]["picture"]["asset"] == "worldmap-flanaess"
    (asset,) = [a for a in bundle.entries("assets") if a["id"] == "worldmap-flanaess"]
    assert (asset["type"], asset["audience"], asset["role"]) == ("image/png", "gm", "attachment")
    assert asset["description"] == "The picture of the world map The Flanaess"
    assert bundle.files[asset["file"]] == data

    result = import_bundle(storage, bundle.to_zip())
    assert result.pictures == [(sha, "image/png")]
    again = load_source(storage, result.module.id)
    (flanaess,) = [w for w in again.worldmaps if w.name == "flanaess"]
    assert flanaess == geojson_map(sha)  # the same document, the same picture id
    assert again.attachments == attachments  # the picture is no attachment: `show_image` can't offer it
    assert "worldmap-flanaess" not in {a.id for a in again.attachments}
    assert export_module(storage, result.module.id).to_zip() == bundle.to_zip()


def test_a_geojson_map_without_a_picture_round_trips(storage):
    module_id = module_with(storage, geojson_map(None))
    bundle = export_module(storage, module_id)
    assert "worldmap-flanaess" not in {a["id"] for a in bundle.entries("assets")}
    result = import_bundle(storage, bundle.to_zip())
    assert result.pictures == []
    (flanaess,) = [w for w in load_source(storage, result.module.id).worldmaps if w.name == "flanaess"]
    assert flanaess == geojson_map(None)


def test_a_map_in_review_is_not_exported(storage):
    sha = storage.blobs.put(png(), "image/png")
    module_id = module_with(storage, geojson_map(sha, status="review"))
    source = load_source(storage, module_id)
    module = storage.modules.get(module_id)
    warnings = [(w.code, w.ref) for w in derive(source, module.maps).warnings if w.code.startswith("worldmap")]
    assert warnings == [("worldmap-in-review", "worldmap:flanaess")]
    bundle = export_module(storage, module_id)
    assert bundle.entries("worldmaps") == []
    assert "worldmap-flanaess" not in {a["id"] for a in bundle.entries("assets")}


def test_the_world_maps_of_a_source():
    from delve.modules import worldmaps

    source = from_bundle(with_worldmaps())
    names = [w.name for w in worldmaps.world_maps(source)]
    assert names == ["greyhawk-region", "wastes-of-cynidicea", "broken"]  # the include fragment is no map of its own
    assert worldmaps.get_world_map(source, "sulm-akar-buildings") is None
    assert worldmaps.get_world_map(source, "greyhawk-region") == source.worldmaps[0]

    flanaess = geojson_map(None)
    added = worldmaps.put_world_map(source, flanaess)
    assert worldmaps.get_world_map(added, "flanaess") == flanaess
    renamed = WorldMapSource("flanaess", "Oerik's east", "", geo=flanaess.geo)
    replaced = worldmaps.put_world_map(added, renamed)
    assert [w.name for w in replaced.worldmaps].count("flanaess") == 1
    assert worldmaps.get_world_map(replaced, "flanaess") == renamed
    assert worldmaps.get_world_map(worldmaps.remove_world_map(replaced, "flanaess"), "flanaess") is None
    assert worldmaps.remove_world_map(source, "nowhere") == source

    includes = world_includes(source.worldmaps)
    assert worldmaps.geo_of(flanaess, includes) == flanaess.geo
    region = worldmaps.geo_of(source.worldmaps[0], includes)
    assert region["type"] == "FeatureCollection" and region["delve"]["grid"]["kind"] == "square"
    assert any(f["properties"]["name"] == "Greyhawk" for f in region["features"])
    cynidicea = worldmaps.geo_of(source.worldmaps[1], includes)  # compiled with its include
    assert cynidicea["features"]


def test_a_geojson_map_is_never_unreadable_as_a_dsl():
    source = ModuleSource(worldmaps=(geojson_map(None),))
    assert [w for w in derive(source, []).warnings if w.code.startswith("worldmap")] == []
