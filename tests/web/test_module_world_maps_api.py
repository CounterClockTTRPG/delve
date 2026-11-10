"""A module's world maps over HTTP (plan 7 Task 11): the organisers list, read, put, delete, import, export and
download them on the module's working source, the shapes of the campaign's routes. A `.map` one reads converted, its
includes compiled in; an include fragment is no map of its own. A seat is refused every one of them."""

import pytest
from fastapi.testclient import TestClient

from delve.domain.modules import ModuleMap
from delve.domain.world import WorldMapSource
from delve.maps.geo import pictures
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.model import Frame, GeoMap, Grid, PictureRef
from delve.modules.source import ModuleSource, load_source
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.maps.geo.test_tiles import halves
from tests.play.test_world_maps import TOWNS, WITH_TOWNS
from tests.web.conftest import BASE_URL
from tests.web.test_world_api import HAND, HAND_MAPPING, isles_doc


@pytest.fixture
def module_id(storage):
    """A module with the vale (`.map`, including the towns), the towns fragment, and the isles in review."""
    module = storage.modules.create("The Vale")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    worldmaps = (
        WorldMapSource("vale", "The Vale", WITH_TOWNS),
        WorldMapSource("towns", "towns", TOWNS),
        WorldMapSource("isles", "The Isles", "", geo=isles_doc(), status="review"),
    )
    storage.module_sources.put(module.id, ModuleSource(worldmaps=worldmaps))
    return module.id


def path(module_id: str, rest: str = "") -> str:
    return f"/api/modules/{module_id}/world-maps{rest}"


def test_the_list_has_the_maps_but_no_fragment(local, module_id):
    listed = local.get(path(module_id))
    assert listed.status_code == 200, listed.text
    assert listed.json() == [
        {"name": "vale", "title": "The Vale", "status": "ready", "source": "module", "picture": False},
        {"name": "isles", "title": "The Isles", "status": "review", "source": "module", "picture": False},
    ]
    assert local.get("/api/modules/mod_nope/world-maps").status_code == 404


def test_a_map_reads_converted_with_its_includes(local, module_id):
    read = local.get(path(module_id, "/vale"))
    assert read.status_code == 200, read.text
    vale = read.json()
    assert set(vale) == {"name", "title", "source", "status", "geo", "picture", "knowledge", "reading"}
    assert (vale["source"], vale["status"], vale["knowledge"], vale["picture"]) == ("module", "ready", None, None)
    ids = {f["id"] for f in vale["geo"]["features"]}
    assert {"oakton", "northby"} <= ids  # northby is the fragment's
    assert local.get(path(module_id, "/towns")).status_code == 404
    assert local.get(path(module_id, "/nowhere")).status_code == 404


def test_a_put_writes_the_document_and_keeps_the_status(local, storage, module_id):
    vale = local.get(path(module_id, "/vale")).json()
    put = local.put(path(module_id, "/vale"), json={"title": "The Green Vale", "geo": vale["geo"]})
    assert put.status_code == 200, put.text
    assert put.json()["title"] == "The Green Vale" and put.json()["status"] == "ready"
    stored = next(w for w in load_source(storage, module_id).worldmaps if w.name == "vale")
    assert stored.geo is not None and stored.title == "The Green Vale"
    review = local.put(path(module_id, "/isles"), json={"title": "The Isles", "geo": isles_doc()})
    assert review.status_code == 200 and review.json()["status"] == "review"
    new = local.put(path(module_id, "/reef"), json={"title": "", "geo": isles_doc()})
    assert new.status_code == 200 and (new.json()["title"], new.json()["status"]) == ("reef", "ready")
    bad = local.put(path(module_id, "/vale"), json={"title": "x", "geo": {"type": "FeatureCollection", "delve": {}}})
    assert bad.status_code == 422 and bad.json()["problems"]


def test_a_delete(local, storage, module_id):
    assert local.request("DELETE", path(module_id, "/isles"), json={}).status_code == 204
    assert [w.name for w in load_source(storage, module_id).worldmaps] == ["vale", "towns"]
    assert local.request("DELETE", path(module_id, "/isles"), json={}).status_code == 404


def test_a_geojson_import(local, module_id):
    asked = local.post(path(module_id, "/geojson"), json={"name": "hand", "document": HAND, "mapping": HAND_MAPPING})
    assert asked.status_code == 422 and asked.json()["needs"] == "scale"
    body = {"name": "hand", "title": "Hand", "document": HAND, "mapping": HAND_MAPPING, "width_km": 200}
    made = local.post(path(module_id, "/geojson"), json=body)
    assert made.status_code == 201, made.text
    assert (made.json()["name"], made.json()["status"]) == ("hand", "ready")
    assert local.post(path(module_id, "/geojson"), json=body).status_code == 409
    assert "hand" in {m["name"] for m in local.get(path(module_id)).json()}


def test_the_export_and_the_picture(local, storage, module_id):
    export = local.get(path(module_id, "/vale/export.geojson"))
    assert export.status_code == 200, export.text
    assert export.headers["content-disposition"] == 'attachment; filename="vale.geojson"'
    assert any(f["properties"]["layer"] == "terrain" for f in export.json()["features"])
    assert local.get(path(module_id, "/isles/export.geojson")).status_code == 409  # in review: never exported

    stored = pictures.store(storage, halves(), "image/png")
    geo = GeoMap(Frame(512.0, 256.0), Grid("square", 32.0, 16, 8), "p" * 128, (), PictureRef(stored.id, 512, 256, 1.0))
    local.put(path(module_id, "/pictured"), json={"title": "Pictured", "geo": to_geojson(geo)})
    assert {m["name"]: m["picture"] for m in local.get(path(module_id)).json()}["pictured"] is True
    got = local.get(path(module_id, "/pictured/picture"))
    assert got.status_code == 200 and got.content == halves() and got.headers["content-type"] == "image/png"
    assert got.headers["content-disposition"] == 'attachment; filename="pictured.png"'
    assert local.get(path(module_id, "/vale/picture")).json() == {"error": "no picture"}


@pytest.fixture
def ana(app, storage):
    """A player's browser on the LAN, seated at a campaign of another module."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    token = new_seat_token()
    storage.seats.create(campaign.id, "Ana", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as client:
        client.cookies.set(SEAT_COOKIE, token)
        yield client


@pytest.mark.parametrize(
    ("method", "rest"),
    [
        ("GET", ""),
        ("GET", "/vale"),
        ("PUT", "/vale"),
        ("DELETE", "/vale"),
        ("POST", "/geojson"),
        ("GET", "/vale/export.geojson"),
        ("GET", "/vale/picture"),
    ],
)
def test_a_seat_is_refused(ana, module_id, method, rest):
    body = {"json": {}} if method != "GET" else {}
    assert ana.request(method, path(module_id, rest), **body).status_code == 403
