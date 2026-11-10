"""Reading a world map's picture, the review and the accept (plan 7 Task 12, Review Focus 2 and 5): the picture's
upload refused before any tile is cut (413, 422, 400, 415), the key checked before the body is read, a map in review
no seat's until it is accepted, and the accept refused while a colour has no terrain. Claude is `FakeDM` answering
from the synthetic picture's truth; the OCR is the fake one."""

import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.maps.geo import tiles
from delve.web.routes import world_import
from delve.web.routes.conversions import conversions
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.conversions.test_worldmap_job import _answer
from tests.maps.geo.pictures import fake_look, fake_ocr, hex_map
from tests.web.conftest import BASE_URL, make_registries
from tests.web.test_conversions_api import ended, uploads
from tests.web.test_world_api import made, vale_module

WORLDMAP = "/api/conversions/worldmap"
THIRTY_MILES = {"cell": "hex", "distance": "30", "units": "miles"}


@pytest.fixture(scope="module")
def gridded():
    return hex_map()


@pytest.fixture(scope="module")
def plain():
    return hex_map(lines=False)


@pytest.fixture
def registries(gridded):
    """A DM whose vision calls the fake look answers. Both pictures share one truth: they differ only in the grid."""
    look = fake_look(gridded.truth)
    dm = Registry()
    dm.register(
        FAKE_DM_CAPABILITIES,
        lambda: FakeDM([], vision_handler=lambda prompt, image, media_type: _answer(look, prompt, image, media_type)),
    )
    return replace(make_registries(), dm=dm)


@pytest.fixture(autouse=True)
def fake_picture_ocr(app, gridded):
    conversions(app).picture_ocr = fake_ocr(gridded.truth)


def png(synthetic) -> bytes:
    out = io.BytesIO()
    synthetic.image.save(out, "PNG")
    return out.getvalue()


def send(local, data: bytes, *, media_type="image/png", **query):
    return local.post(WORLDMAP, params=query, content=data, headers={"Content-Type": media_type})


def read_into(local, data: bytes, **query) -> dict:
    """The job reading `data` with `query`, once it has ended."""
    response = send(local, data, **{**THIRTY_MILES, **query})
    assert response.status_code == 202, response.json()
    started = response.json()
    assert (started["kind"], started["target"]["name"]) == ("worldmap", query["name"])
    done = ended(local, started["id"])
    assert done["status"] == "done", done["error"]
    return done


@pytest.fixture
def module_id(storage):
    return storage.modules.create("The Flanaess").id


def module_map(module_id: str, name: str = "flanaess") -> str:
    return f"/api/modules/{module_id}/world-maps/{name}"


def test_a_picture_is_read_into_a_module_map_in_review(local, storage, config, gridded, module_id):
    done = read_into(local, png(gridded), module_id=module_id, name="flanaess", title="The Flanaess")

    assert uploads(config) == [], "the job removes its upload"
    [row] = local.get(f"/api/modules/{module_id}/world-maps").json()
    assert row == {"name": "flanaess", "title": "The Flanaess", "status": "review", "source": "module", "picture": True}
    doc = local.get(module_map(module_id)).json()
    assert doc["status"] == "review" and doc["picture"] == done["result"]["picture"]
    assert doc["geo"]["delve"]["picture"]["id"] == doc["picture"]
    assert [d["kind"] for d in doc["reading"]["doubts"]][:4] == ["cluster-unmapped"] * 4
    assert local.get(f"/api/world-pictures/{doc['picture']}/tiles/0/0/0").status_code == 200
    assert local.get(f"{module_map(module_id)}/export.geojson").status_code == 409, "a map in review isn't exported"


def test_the_accept_is_refused_while_a_colour_is_unmapped_and_kinds_decide_them_all(local, gridded, module_id):
    read_into(local, png(gridded), module_id=module_id, name="flanaess")
    before = local.get(module_map(module_id)).json()

    refused = local.post(f"{module_map(module_id)}/accept", json={})

    assert refused.status_code == 422 and refused.json() == {"error": "Give every colour a terrain first."}
    assert local.get(module_map(module_id)).json() == before, "nothing changes"

    reviewed = local.post(f"{module_map(module_id)}/review", json={"kinds": {"cluster-unmapped": "keep"}})

    assert reviewed.status_code == 200, reviewed.json()
    clusters = reviewed.json()["reading"]["clusters"]
    assert all(c["terrain"] == (c["suggestion"] or "sea") for c in clusters)
    accepted = local.post(f"{module_map(module_id)}/accept", json={})
    assert accepted.status_code == 200, accepted.json()
    assert accepted.json()["status"] == "ready"
    assert local.get(f"/api/modules/{module_id}/world-maps").json()[0]["status"] == "ready"


def test_a_review_decision_drop_removes_the_place(local, gridded, module_id):
    read_into(local, png(gridded), module_id=module_id, name="flanaess")
    doubts = local.get(module_map(module_id)).json()["reading"]["doubts"]
    guessed = next(d for d in doubts if d["kind"] == "kind-guessed")

    reviewed = local.post(f"{module_map(module_id)}/review", json={"decisions": {guessed["id"]: "drop"}}).json()

    assert guessed["ref"] not in {f["id"] for f in reviewed["geo"]["features"]}
    assert next(d for d in reviewed["reading"]["doubts"] if d["id"] == guessed["id"])["resolved"]


def test_a_decision_that_doesnt_fit_is_422_and_changes_nothing(local, gridded, module_id):
    read_into(local, png(gridded), module_id=module_id, name="flanaess")
    before = local.get(module_map(module_id)).json()
    for body in ({"decisions": {"no-such-doubt": "keep"}}, {"clusters": {"0": "lava"}}, {"kinds": {"nonsense": "x"}}):
        assert local.post(f"{module_map(module_id)}/review", json=body).status_code == 422
    assert local.get(module_map(module_id)).json() == before


def test_the_accept_passes_once_the_frames_colour_is_outside_the_map(local, plain, module_id):
    read_into(
        local,
        png(plain),
        module_id=module_id,
        name="plain",
        cell="none",
        distance="100",
        units="km",
        points="40,40,140,40",
    )
    path = module_map(module_id, "plain")
    clusters = local.get(path).json()["reading"]["clusters"]
    frame = next(c for c in clusters if c["suggestion"] == "outside")
    land = {str(c["id"]): c["suggestion"] for c in clusters if c["terrain"] is None and c is not frame}
    assert local.post(f"{path}/review", json={"clusters": land}).status_code == 200

    assert local.post(f"{path}/accept", json={}).status_code == 422, "the frame's colour is still unmapped"

    assert local.post(f"{path}/review", json={"clusters": {str(frame["id"]): "outside"}}).status_code == 200
    accepted = local.post(f"{path}/accept", json={})
    assert accepted.status_code == 200 and accepted.json()["status"] == "ready"


def test_a_campaign_map_in_review_is_no_seats_until_it_is_accepted(app, local, storage, gridded):
    cid = made(local, vale_module(storage).id, setting=None)
    done = read_into(local, png(gridded), campaign_id=cid, name="flanaess", title="The Flanaess")
    assert done["target"] == {"campaign_id": cid, "name": "flanaess", "title": "The Flanaess"}
    path = f"/api/campaigns/{cid}/world-maps/flanaess"
    rows = local.get(f"/api/campaigns/{cid}/organiser/world-maps").json()
    assert {
        "name": "flanaess",
        "title": "The Flanaess",
        "status": "review",
        "source": "campaign",
        "picture": True,
    } in rows
    assert local.put(f"{path}/knowledge", json={"how": "everything"}).status_code == 200
    token = new_seat_token()
    storage.seats.create(cid, "Ana", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as ana:
        ana.cookies.set(SEAT_COOKIE, token)
        assert "flanaess" not in {m["name"] for m in ana.get(f"/api/campaigns/{cid}/world-maps").json()}
        assert ana.get(f"{path}/view").status_code == 404
        assert ana.post(f"{path}/review", json={}).status_code == 403
        assert ana.post(f"{path}/accept", json={}).status_code == 403

        assert local.post(f"{path}/accept", json={}).status_code == 422
        assert local.post(f"{path}/review", json={"kinds": {"cluster-unmapped": "keep"}}).status_code == 200
        accepted = local.post(f"{path}/accept", json={})
        assert accepted.status_code == 200 and accepted.json()["status"] == "ready"
        assert "flanaess" in {m["name"] for m in ana.get(f"/api/campaigns/{cid}/world-maps").json()}


def test_a_ready_map_has_no_review(local, storage):
    cid = made(local, vale_module(storage).id, setting=None)
    response = local.post(f"/api/campaigns/{cid}/world-maps/vale/review", json={})
    assert response.status_code == 409 and response.json() == {"error": "The world map isn't in review."}
    assert local.post(f"/api/campaigns/{cid}/world-maps/nowhere/review", json={}).status_code == 404


# ----- the upload's refusals (Review Focus 2) -----


def test_a_body_over_the_cap_is_413_and_leaves_no_upload(local, config, gridded, module_id, monkeypatch):
    monkeypatch.setattr(world_import, "PICTURE_LIMIT", 1000)
    response = send(local, png(gridded), module_id=module_id, name="flanaess", **THIRTY_MILES)
    assert response.status_code == 413
    assert uploads(config) == []


def test_a_picture_over_the_pixel_cap_is_422_before_any_tile_is_cut(
    local, storage, config, gridded, module_id, monkeypatch
):
    monkeypatch.setattr(tiles, "MAX_PICTURE_PIXELS", 1000)
    response = send(local, png(gridded), module_id=module_id, name="flanaess", **THIRTY_MILES)
    assert response.status_code == 422 and "pixels" in response.json()["error"]
    assert uploads(config) == [] and local.get("/api/conversions").json() == []


def test_bytes_that_arent_the_type_are_400(local, config, gridded, module_id):
    response = send(local, png(gridded), media_type="image/jpeg", module_id=module_id, name="flanaess", **THIRTY_MILES)
    assert response.status_code == 400
    assert send(local, b"not a picture", module_id=module_id, name="x", **THIRTY_MILES).status_code == 400
    assert uploads(config) == []


def test_another_type_is_415_and_the_picture_types_are_taken_on_that_path_only(local, gridded, module_id):
    assert (
        send(local, b"GIF89a", media_type="image/gif", module_id=module_id, name="x", **THIRTY_MILES).status_code == 415
    )
    other = local.post("/api/conversions/generate", content=png(gridded), headers={"Content-Type": "image/png"})
    assert other.status_code == 415
    review = local.post(f"{module_map(module_id)}/review", content=png(gridded), headers={"Content-Type": "image/png"})
    assert review.status_code == 415


def test_a_key_or_target_that_doesnt_check_is_refused_before_the_body(local, config, module_id, storage):
    body = b"not even a picture"
    assert send(local, body, module_id=module_id, name="x", cell="none", distance="30", units="km").status_code == 422
    assert send(local, body, module_id=module_id, name="x", cell="hex", distance="0", units="km").status_code == 422
    assert (
        send(local, body, module_id=module_id, name="x", cell="hex", distance="30", units="leagues").status_code == 422
    )
    assert send(local, body, module_id=module_id, name="", **THIRTY_MILES).status_code == 422
    assert send(local, body, name="x", **THIRTY_MILES).status_code == 422
    assert send(local, body, module_id="mod_nope", name="x", **THIRTY_MILES).status_code == 404
    assert send(local, body, campaign_id="cmp_nope", name="x", **THIRTY_MILES).status_code == 404
    cid = made(local, vale_module(storage).id, setting=None)
    taken = send(local, body, campaign_id=cid, name="vale", **THIRTY_MILES)
    assert taken.status_code == 409, "the campaign's own copy of its module's map"
    assert uploads(config) == [] and local.get("/api/conversions").json() == []


def test_a_second_reading_is_409_while_one_runs(local, app, gridded, module_id):
    from delve.conversions.runner import _Live

    running = app.state.storage.conversions.create("worldmap", "held", "ready")
    conversions(app).live[running.id] = _Live(running)
    try:
        response = send(local, png(gridded), module_id=module_id, name="flanaess", **THIRTY_MILES)
    finally:
        conversions(app).live.pop(running.id)
    assert response.status_code == 409 and response.json()["conversion"]["id"] == running.id


def test_seats_cant_read_a_picture(app, local, storage, gridded):
    cid = made(local, vale_module(storage).id, setting=None)
    token = new_seat_token()
    storage.seats.create(cid, "Bo", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as bo:
        bo.cookies.set(SEAT_COOKIE, token)
        response = send(bo, png(gridded), campaign_id=cid, name="flanaess", **THIRTY_MILES)
    assert response.status_code == 403


def test_leftover_pictures_are_removed_at_startup(config, storage, registries, static_dir):
    from delve.web.app import create_app

    folder = config.data_dir / "uploads"
    folder.mkdir(parents=True)
    left = folder / "worldmap-abc123.png"
    left.write_bytes(b"left")
    other = folder / "notes.txt"
    other.write_text("not an upload")
    with TestClient(create_app(config, storage, registries, static_dir=static_dir), base_url=BASE_URL):
        assert not left.exists() and other.exists()
