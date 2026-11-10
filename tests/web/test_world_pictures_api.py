"""The raw tiles of a world-map picture over HTTP (plan 7 Task 5): the organisers' editors and the DM view read them; a
seat is refused. A module import cuts its world maps' pictures."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from delve.domain.modules import ModuleMap
from delve.maps.geo import pictures
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.modules.test_worldmaps import geojson_map, module_with, png
from tests.web.conftest import BASE_URL


@pytest.fixture
def stored(storage):
    out = io.BytesIO()
    Image.new("RGB", (600, 300), (20, 80, 160)).save(out, "PNG")
    return pictures.store(storage, out.getvalue(), "image/png")


@pytest.fixture
def ana(app, storage):
    """A player's browser on the LAN, seated at a campaign."""
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


def test_the_organiser_reads_a_raw_tile(local, stored):
    response = local.get(f"/api/world-pictures/{stored.id}/tiles/2/2/1")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, max-age=86400"
    assert response.content == pictures.tile(local.app.state.storage, stored.id, 2, 2, 1)


def test_a_tile_that_isnt_there_is_404(local, stored):
    for path in [f"{stored.id}/tiles/2/3/0", f"{stored.id}/tiles/4/0/0", "nope/tiles/0/0/0"]:
        response = local.get(f"/api/world-pictures/{path}")
        assert (response.status_code, response.json()) == (404, {"error": "no such tile"})


def test_a_seat_is_refused_the_raw_tiles(ana, stored):
    response = ana.get(f"/api/world-pictures/{stored.id}/tiles/0/0/0")
    assert response.status_code == 403


def test_the_module_import_cuts_its_world_maps_pictures(local, storage):
    from delve.modules.exporter import export_module

    data = png(300, 200)
    sha = storage.blobs.put(data, "image/png")
    zipped = export_module(storage, module_with(storage, geojson_map(sha))).to_zip()
    assert storage.world_pictures.get(sha) is None
    response = local.post(
        "/api/modules/import", content=zipped, headers={"Content-Type": "application/vnd.dscn+zip"}
    )
    assert response.status_code == 201, response.text
    cut = storage.world_pictures.get(sha)
    assert cut is not None and cut.max_zoom == 1 and len(cut.tiles) == 2 + 1
