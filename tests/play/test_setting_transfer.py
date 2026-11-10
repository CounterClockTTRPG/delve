"""A setting's additions as a file (DEL-366): exported from one install and imported into another, pages, facts and
maps with their pictures, DM-only marks kept; what the other install has already is kept or replaced as asked."""

import io
import json
import zipfile

import pytest

from delve.config import Config
from delve.domain.setting_content import SettingAddition, SettingFact
from delve.domain.world import WorldMapSource
from delve.maps.geo import pictures
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.model import Frame, GeoMap, Grid, PictureRef
from delve.play.context import PlayError
from delve.play.setting_transfer import FORMAT, export_additions, import_additions
from delve.storage import open_storage
from tests.maps.geo.test_tiles import halves
from tests.web.test_world_api import isles_doc


@pytest.fixture
def other(tmp_path):
    """Another install's storage."""
    opened = open_storage(Config(data_dir=tmp_path / "other"))
    yield opened
    opened.close()


def with_additions(storage):
    storage.setting_pages.put(SettingAddition("greyhawk", "Hommlet", "settlements", {"ruler": "Burne"}, "A village."))
    storage.setting_pages.put(SettingAddition("greyhawk", "The Secret Cult", text="Shh.", dm_only=True))
    storage.setting_facts.add(SettingFact(0, "greyhawk", "The Wild Coast is wild.", "geography"))
    storage.setting_facts.add(SettingFact(0, "greyhawk", "Lareth serves the Temple.", dm_only=True))
    stored = pictures.store(storage, halves(), "image/png")
    geo = GeoMap(Frame(512.0, 256.0), Grid("square", 32.0, 16, 8), "p" * 128, (), PictureRef(stored.id, 512, 256, 1.0))
    storage.setting_maps.put("greyhawk", WorldMapSource("pictured", "Pictured", "", geo=to_geojson(geo), picture=stored.id))
    storage.setting_maps.put("greyhawk", WorldMapSource("isles", "The Isles", "", geo=isles_doc(), status="review"))
    storage.setting_pages.put(SettingAddition("realms", "Waterdeep", text="Not Greyhawk's."))
    return stored


def test_the_additions_travel_whole_to_another_install(storage, other):
    stored = with_additions(storage)
    data = export_additions(storage, "greyhawk")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        document = json.loads(archive.read("additions.json"))
        assert sorted(archive.namelist()) == ["additions.json", f"pictures/{stored.id}"]
    assert document["format"] == FORMAT and document["setting"] == "greyhawk"
    assert [p["title"] for p in document["pages"]] == ["Hommlet", "The Secret Cult"], "never another setting's"

    done = import_additions(other, "greyhawk", data)
    assert done.to_dict() == {
        "pages_added": 2, "pages_replaced": 0, "pages_kept": 0,
        "facts_added": 2, "facts_kept": 0,
        "maps_added": 2, "maps_replaced": 0, "maps_kept": 0,
    }
    secret = other.setting_pages.get("greyhawk", "The Secret Cult")
    assert secret is not None and secret.dm_only and secret.text == "Shh.", "DM-only travels with its mark"
    assert other.setting_pages.get("greyhawk", "Hommlet").fields == {"ruler": "Burne"}
    facts = [(f.text, f.category, f.dm_only) for f in other.setting_facts.list("greyhawk")]
    assert facts == [("The Wild Coast is wild.", "geography", False), ("Lareth serves the Temple.", "", True)]
    maps = {m.name: m for m in other.setting_maps.list("greyhawk")}
    assert maps["pictured"].picture == stored.id and pictures.original(other, stored.id) == (halves(), "image/png")
    assert pictures.tile(other, stored.id, 0, 0, 0) is not None, "the picture is cut into its tiles again"
    assert maps["isles"].status == "review" and maps["isles"].picture is None


def test_what_the_install_has_is_kept_or_replaced_as_asked(storage, other):
    with_additions(storage)
    data = export_additions(storage, "greyhawk")
    other.setting_pages.put(SettingAddition("greyhawk", "hommlet", text="Ours."))
    other.setting_facts.add(SettingFact(0, "greyhawk", "the wild  coast is WILD."))
    other.setting_maps.put("greyhawk", WorldMapSource("isles", "Our Isles", "", geo=isles_doc()))

    kept = import_additions(other, "greyhawk", data)
    assert (kept.pages_added, kept.pages_kept, kept.facts_added, kept.facts_kept) == (1, 1, 1, 1)
    assert (kept.maps_added, kept.maps_kept) == (1, 1)
    assert other.setting_pages.get("greyhawk", "Hommlet").text == "Ours."
    assert other.setting_maps.get("greyhawk", "isles").title == "Our Isles"

    replaced = import_additions(other, "greyhawk", data, keep=False)
    assert (replaced.pages_replaced, replaced.maps_replaced, replaced.facts_added) == (2, 2, 0)
    assert other.setting_pages.get("greyhawk", "Hommlet").text == "A village."
    assert other.setting_maps.get("greyhawk", "isles").title == "The Isles"
    assert len(other.setting_facts.list("greyhawk")) == 2, "a fact is never added twice"


def zipped(files: dict[str, bytes | str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def test_a_file_that_isnt_one_stores_nothing(storage, other):
    with_additions(storage)
    good = json.loads(zipfile.ZipFile(io.BytesIO(export_additions(storage, "greyhawk"))).read("additions.json"))
    refused = [
        (b"not a zip", "isn't a file of a setting's additions"),
        (zipped({"other.json": "{}"}), "isn't a file"),
        (zipped({"additions.json": json.dumps({"format": "x"})}), "isn't a file"),
        (zipped({"additions.json": json.dumps({**good, "version": 9})}), "version 9"),
        (zipped({"additions.json": json.dumps({**good, "setting": "realms"})}), "of 'realms', not of 'greyhawk'"),
        (zipped({"additions.json": json.dumps({**good, "pages": [{"title": ""}]})}), "no title"),
        (zipped({"additions.json": json.dumps({**good, "facts": [{"text": "x", "dm_only": "yes"}]})}), "true or false"),
        (zipped({"additions.json": json.dumps(good)}), "picture isn't in the file"),
        (zipped({"additions.json": json.dumps(good), "../evil": "x"}), "outside the file"),
    ]
    for data, message in refused:
        with pytest.raises(PlayError, match=message):
            import_additions(other, "greyhawk", data)
    assert other.setting_pages.list("greyhawk") == [] and other.setting_facts.list("greyhawk") == []
    assert other.setting_maps.list("greyhawk") == []


def test_an_install_without_additions_exports_an_empty_file(storage, other):
    data = export_additions(storage, "greyhawk")
    assert import_additions(other, "greyhawk", data).to_dict() == dict.fromkeys(
        ["pages_added", "pages_replaced", "pages_kept", "facts_added", "facts_kept", "maps_added", "maps_replaced", "maps_kept"],
        0,
    )
