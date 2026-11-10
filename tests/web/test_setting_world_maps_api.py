"""A setting's own world maps over HTTP (settings plan Task 9, Review Focus 4): the organisers list, read, put, delete,
import, export, copy from a module, read a picture into one, review and accept it, all under
`/api/settings/{id}/world-maps`, and no change reaches a campaign. A seat at a campaign of the setting lists and views
its ready maps whole, without a hidden feature, and never one in review. The install's old pointer routes are gone."""

import pytest
from fastapi.testclient import TestClient

from delve.domain.world import WorldMapSource
from delve.maps.geo import pictures
from delve.maps.geo.geojson import to_geojson
from delve.maps.geo.model import Frame, GeoMap, Grid, PictureRef
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.settings import GreyhawkSetting
from tests.maps.geo.test_tiles import halves
from tests.play.test_travel import VALE_MAP
from tests.web.conftest import BASE_URL
from tests.web.test_world_api import HAND, HAND_MAPPING, isles_doc, made, vale_module
from tests.web.test_world_import_api import fake_picture_ocr, gridded, png, read_into, registries  # noqa: F401

PATH = "/api/settings/greyhawk/world-maps"
REGION = GreyhawkSetting().world_maps()[0]


def path(rest: str = "") -> str:
    return PATH + rest


def events_since(app, seq: int, kind: str) -> list:
    return [(e.data, e.scope) for e in app.state.events._buffer if e.seq > seq and e.type == kind]


def test_the_crud(local, app, storage):
    assert local.get(path()).json() == []
    assert local.get("/api/settings/atlantis/world-maps").status_code == 404
    seq = app.state.events._seq
    put = local.put(path("/isles"), json={"title": "The Isles", "geo": isles_doc()})
    assert put.status_code == 200, put.text
    isles = put.json()
    assert set(isles) == {"name", "title", "source", "status", "geo", "picture", "knowledge", "reading"}
    assert (isles["source"], isles["status"], isles["knowledge"]) == ("setting", "ready", None)
    assert local.get(path()).json() == [
        {"name": "isles", "title": "The Isles", "status": "ready", "source": "setting", "picture": False}
    ]
    assert local.get(path("/isles")).json() == isles
    retitled = local.put(path("/isles"), json={"title": "", "geo": isles_doc()})
    assert retitled.json()["title"] == "The Isles", "a put without a title keeps it"
    bad = local.put(path("/isles"), json={"title": "x", "geo": {"type": "FeatureCollection", "delve": {}}})
    assert bad.status_code == 422 and bad.json()["problems"]
    assert local.get(path("/nowhere")).status_code == 404
    assert local.request("DELETE", path("/isles"), json={}).status_code == 204
    assert local.request("DELETE", path("/isles"), json={}).status_code == 404
    assert storage.setting_maps.list("greyhawk") == []
    assert events_since(app, seq, "setting") == [({"id": "greyhawk"}, "organisers")] * 3
    assert events_since(app, seq, "world") == [], "no campaign changes"


def test_a_geojson_import(local):
    asked = local.post(path("/geojson"), json={"name": "hand", "document": HAND, "mapping": HAND_MAPPING})
    assert asked.status_code == 422 and asked.json()["needs"] == "scale"
    body = {"name": "hand", "title": "Hand", "document": HAND, "mapping": HAND_MAPPING, "width_km": 200}
    made_ = local.post(path("/geojson"), json=body)
    assert made_.status_code == 201, made_.text
    assert (made_.json()["name"], made_.json()["status"], made_.json()["source"]) == ("hand", "ready", "setting")
    assert local.post(path("/geojson"), json=body).status_code == 409


def test_the_copy_from_a_module(local, storage):
    review = WorldMapSource("draft", "Draft", "", geo=isles_doc(), status="review")
    module = vale_module(storage, [VALE_MAP, review])
    copied = local.post(path("/copy"), json={"module_id": module.id, "name": "vale"})
    assert copied.status_code == 201, copied.text
    assert (copied.json()["name"], copied.json()["source"], copied.json()["status"]) == ("vale", "setting", "ready")
    assert {f["id"] for f in copied.json()["geo"]["features"]} >= {"oakton", "millbrook"}
    taken = local.post(path("/copy"), json={"module_id": module.id, "name": "vale"})
    assert taken.status_code == 409 and taken.json()["error"]
    again = local.post(path("/copy"), json={"module_id": module.id, "name": "vale", "as_name": "vale-2"})
    assert again.status_code == 201 and again.json()["name"] == "vale-2"
    for body in (
        {"module_id": module.id, "name": "draft"},
        {"module_id": module.id, "name": "nowhere"},
        {"module_id": "mod_nope", "name": "vale"},
    ):
        refused = local.post(path("/copy"), json=body)
        assert refused.status_code == 422 and refused.json()["error"], body
    assert [m.name for m in storage.setting_maps.list("greyhawk")] == ["vale", "vale-2"]


def test_the_export_and_the_picture(local, storage):
    local.put(path("/isles"), json={"title": "The Isles", "geo": isles_doc()})
    export = local.get(path("/isles/export.geojson"))
    assert export.status_code == 200 and export.headers["content-disposition"] == 'attachment; filename="isles.geojson"'
    assert local.get(path("/isles/picture")).json() == {"error": "no picture"}
    stored = pictures.store(storage, halves(), "image/png")
    geo = GeoMap(Frame(512.0, 256.0), Grid("square", 32.0, 16, 8), "p" * 128, (), PictureRef(stored.id, 512, 256, 1.0))
    local.put(path("/pictured"), json={"title": "Pictured", "geo": to_geojson(geo)})
    got = local.get(path("/pictured/picture"))
    assert got.status_code == 200 and got.content == halves()


def test_a_picture_is_read_reviewed_and_accepted(local, app, storage, gridded):  # noqa: F811
    seq = app.state.events._seq
    done = read_into(local, png(gridded), setting_id="greyhawk", name="flanaess", title="The Flanaess")
    assert done["target"] == {"setting_id": "greyhawk", "name": "flanaess", "title": "The Flanaess"}
    [row] = local.get(path()).json()
    assert row == {
        "name": "flanaess",
        "title": "The Flanaess",
        "status": "review",
        "source": "setting",
        "picture": True,
    }
    assert local.get(path("/flanaess/export.geojson")).status_code == 409, "a map in review isn't exported"
    taken = local.post(
        "/api/conversions/worldmap",
        params={"setting_id": "greyhawk", "name": "flanaess", "cell": "hex", "distance": "30", "units": "miles"},
        content=b"x",
        headers={"Content-Type": "image/png"},
    )
    assert taken.status_code == 409
    unknown = local.post(
        "/api/conversions/worldmap",
        params={"setting_id": "atlantis", "name": "x", "cell": "hex", "distance": "30", "units": "miles"},
        content=b"x",
        headers={"Content-Type": "image/png"},
    )
    assert unknown.status_code == 404

    refused = local.post(path("/flanaess/accept"), json={})
    assert refused.status_code == 422 and refused.json() == {"error": "Give every colour a terrain first."}
    reviewed = local.post(path("/flanaess/review"), json={"kinds": {"cluster-unmapped": "keep"}})
    assert reviewed.status_code == 200 and reviewed.json()["status"] == "review", reviewed.text
    accepted = local.post(path("/flanaess/accept"), json={})
    assert accepted.status_code == 200 and accepted.json()["status"] == "ready"
    assert storage.setting_maps.get("greyhawk", "flanaess").status == "ready"
    assert local.post(path("/flanaess/review"), json={}).status_code == 409
    assert local.post(path("/nowhere/accept"), json={}).status_code == 404
    assert ({"id": "greyhawk"}, "organisers") in events_since(app, seq, "setting")
    assert events_since(app, seq, "world") == [], "the accept changes no campaign"


def test_the_pointer_routes_are_gone(local):
    assert local.get("/api/settings/world-maps").status_code == 404
    assert local.put("/api/settings/world-maps/greyhawk", json={"module_id": "m", "name": "n"}).status_code in (
        404,
        405,
    )


# ----- the seats -----


@pytest.fixture
def table(app, local, storage):
    """A campaign of Greyhawk, and Ana's browser on the LAN, seated at it."""
    cid = made(local, vale_module(storage).id, setting="greyhawk")
    token = new_seat_token()
    storage.seats.create(cid, "Ana", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as client:
        client.cookies.set(SEAT_COOKIE, token)
        yield cid, client


def test_a_seat_sees_the_built_in_map_until_the_install_has_a_ready_one(table, storage):
    cid, ana = table
    base = f"/api/campaigns/{cid}/setting/maps"
    assert ana.get(base).json() == [{"name": REGION.name, "title": REGION.title}]
    built_in = ana.get(f"{base}/{REGION.name}/view")
    assert built_in.status_code == 200 and built_in.json()["known"]["all"] is True
    assert "Ambush Site" not in {f["name"] for f in built_in.json()["features"]}, "a hidden place stays hidden"

    stored = pictures.store(storage, halves(), "image/png")
    geo = GeoMap(Frame(512.0, 256.0), Grid("square", 32.0, 16, 8), "p" * 128, (), PictureRef(stored.id, 512, 256, 1.0))
    storage.setting_maps.put(
        "greyhawk", WorldMapSource("pictured", "Pictured", "", geo=to_geojson(geo), picture=stored.id)
    )
    storage.setting_maps.put("greyhawk", WorldMapSource("draft", "Draft", "", geo=isles_doc(), status="review"))
    assert ana.get(base).json() == [{"name": "pictured", "title": "Pictured"}], "never a map in review"
    assert ana.get(f"{base}/draft/view").status_code == 404
    assert ana.get(f"{base}/{REGION.name}/view").status_code == 404, "the built-in map is no longer the setting's"
    view = ana.get(f"{base}/pictured/view").json()
    assert view["tiles_version"] == stored.id and "id" not in view["picture"]
    tile = ana.get(f"{base}/pictured/tiles/0/0/0")
    assert tile.status_code == 200 and tile.headers["content-type"] == "image/jpeg"
    assert tile.headers["x-content-type-options"] == "nosniff"
    assert ana.get(f"{base}/pictured/tiles/9/0/0").status_code == 404
    assert ana.get(f"{base}/draft/tiles/0/0/0").status_code == 404
    assert ana.get(f"{base}/{REGION.name}/tiles/0/0/0").status_code == 404


def test_a_campaign_without_a_setting_has_no_setting_maps(local, storage):
    cid = made(local, vale_module(storage).id, setting=None)
    assert local.get(f"/api/campaigns/{cid}/setting/maps").status_code == 404


@pytest.mark.parametrize(
    ("method", "rest"),
    [
        ("GET", ""),
        ("GET", "/isles"),
        ("PUT", "/isles"),
        ("DELETE", "/isles"),
        ("POST", "/geojson"),
        ("POST", "/copy"),
        ("GET", "/isles/export.geojson"),
        ("GET", "/isles/picture"),
        ("POST", "/isles/review"),
        ("POST", "/isles/accept"),
    ],
)
def test_a_seat_is_refused_the_organisers_routes(table, method, rest):
    _, ana = table
    body = {"json": {}} if method != "GET" else {}
    assert ana.request(method, path(rest), **body).status_code == 403
