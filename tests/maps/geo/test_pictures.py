"""World-map pictures in storage (plan 7 Task 5, Review Focus 1 and 2): the original and its tiles in the blob store,
cut once; the original back for the organiser; and a seat's tile, never sent where nothing is known, fogged where part
is. The pictures are drawn here with Pillow."""

import hashlib
import io

import pytest
from PIL import Image

from delve.config import Config
from delve.maps.geo import pictures, tiles
from delve.maps.geo.model import Frame, GeoMap, Grid, PictureRef
from delve.storage import open_storage
from tests.maps.geo.test_tiles import MAGENTA, halves, picture


@pytest.fixture
def storage(tmp_path):
    opened = open_storage(Config(data_dir=tmp_path / "data"))
    yield opened
    opened.close()


def geo_over(stored, cell_px: int = 32) -> GeoMap:
    cols, rows = stored.width_px // cell_px, stored.height_px // cell_px
    grid = Grid("square", float(cell_px), cols, rows)
    ref = PictureRef(stored.id, stored.width_px, stored.height_px, km_per_px=1.0)
    return GeoMap(Frame(float(stored.width_px), float(stored.height_px)), grid, "p" * (cols * rows), (), ref)


def test_a_picture_is_stored_with_its_tiles(storage):
    data = picture(1000, 700)
    stored = pictures.store(storage, data, "image/png")
    assert stored.id == hashlib.sha256(data).hexdigest()
    assert (stored.mime, stored.width_px, stored.height_px, stored.max_zoom) == ("image/png", 1000, 700, 2)
    assert len(stored.tiles) == 12 + 4 + 1
    assert storage.world_pictures.get(stored.id) == stored
    assert pictures.original(storage, stored.id) == (data, "image/png")
    tile = pictures.tile(storage, stored.id, 2, 3, 2)
    assert tile is not None and Image.open(io.BytesIO(tile)).size == (256, 256)
    assert pictures.tile(storage, stored.id, 2, 4, 0) is None
    assert pictures.tile(storage, stored.id, 3, 0, 0) is None
    assert pictures.tile(storage, "nope", 0, 0, 0) is None
    assert pictures.original(storage, "nope") is None


def test_cutting_an_original_already_stored_is_idempotent(storage):
    data = picture(300, 200, fmt="JPEG")
    sha = storage.blobs.put(data, "image/jpeg")
    first = pictures.store_blob(storage, sha, "image/jpeg")
    assert first.id == sha and first.max_zoom == 1
    assert pictures.store_blob(storage, sha, "image/jpeg") == first
    assert pictures.store(storage, data, "image/jpeg") == first


def test_an_original_missing_from_the_blob_store_is_a_lookup_error(storage):
    with pytest.raises(LookupError):
        pictures.store_blob(storage, "0" * 64, "image/png")


def test_a_picture_over_the_cap_is_refused_before_any_tile_is_put(storage, monkeypatch):
    monkeypatch.setattr(tiles, "MAX_PICTURE_PIXELS", 10_000)
    put: list[str] = []
    original = storage.blobs.put
    monkeypatch.setattr(storage.blobs, "put", lambda data, mime: put.append(mime) or original(data, mime))
    with pytest.raises(tiles.PictureRefused) as refused:
        pictures.store(storage, picture(200, 100), "image/png")
    assert refused.value.status == 422
    assert put == []
    sha = original(picture(200, 100), "image/png")
    with pytest.raises(tiles.PictureRefused):
        pictures.store_blob(storage, sha, "image/png")
    assert put == [] and storage.world_pictures.get(sha) is None


def test_a_seat_gets_no_tile_where_nothing_is_known_and_fog_where_part_is(storage):
    stored = pictures.store(storage, halves(), "image/png")
    geo = geo_over(stored)  # 16 × 8 cells; zoom 1 has two tiles of 8 × 8 cells
    left = frozenset(r * 16 + c for r in range(8) for c in range(8))
    assert pictures.seat_tile(storage, stored.id, geo, left, 1, 1, 0) is None  # all magenta, all unknown
    assert pictures.seat_tile(storage, stored.id, geo, frozenset(), 0, 0, 0) is None
    assert pictures.seat_tile(storage, stored.id, geo, left, 1, 0, 0) == pictures.tile(storage, stored.id, 1, 0, 0)
    assert pictures.seat_tile(storage, stored.id, geo, left, 5, 0, 0) is None  # outside the picture
    fogged = pictures.seat_tile(storage, stored.id, geo, left, 0, 0, 0)
    assert fogged is not None and fogged != pictures.tile(storage, stored.id, 0, 0, 0)
    colours = Image.open(io.BytesIO(fogged)).convert("RGB").getcolors(256 * 256)
    assert not any(r > 200 and b > 200 and g < 120 for _, (r, g, b) in colours), MAGENTA
    everything = frozenset(range(16 * 8))
    assert pictures.seat_tile(storage, stored.id, geo, everything, 0, 0, 0) == pictures.tile(storage, stored.id, 0, 0, 0)
    # Asked again, the same knowledge is the same tile (from the cache), and new knowledge is a new one.
    assert pictures.seat_tile(storage, stored.id, geo, left, 0, 0, 0) == fogged


def test_a_seat_tile_of_a_map_without_its_picture_is_none(storage):
    stored = pictures.store(storage, halves(), "image/png")
    geo = geo_over(stored)
    bare = GeoMap(geo.frame, geo.grid, geo.terrain, ())
    assert pictures.seat_tile(storage, stored.id, bare, frozenset(range(128)), 0, 0, 0) is None
