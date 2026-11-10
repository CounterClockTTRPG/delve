"""World-map pictures in storage: the original and its tiles in the blob store, and the `world_pictures` row that lists
them (`WorldPicture`, by the original's sha256). A picture is cut once and shared by every map that uses it.

Storage is injected (`PictureStore`; `delve.storage.Storage` is one), as `delve.modules.source` takes it. A seat's tile
(`seat_tile`) is cut from the party's known cells: None where nothing is known, the tile as printed where all is, and
fogged on the server where part is; the fogged ones are kept in a small LRU.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Collection
from typing import Protocol

from delve.domain.world import WorldPicture
from delve.maps.geo import tiles
from delve.maps.geo.model import GeoMap

FOGGED_CACHE = 512
"""How many seats' tiles are kept."""


class _Blobs(Protocol):
    def put(self, data: bytes, mime: str) -> str: ...

    def get(self, sha: str) -> bytes | None: ...


class _Pictures(Protocol):
    def get(self, id: str) -> WorldPicture | None: ...

    def put(self, picture: WorldPicture) -> WorldPicture: ...


class PictureStore(Protocol):
    """What the pictures need of storage."""

    blobs: _Blobs
    world_pictures: _Pictures


def _cut(store: PictureStore, sha: str, data: bytes, mime: str) -> WorldPicture:
    image = tiles.open_picture(data, mime)
    try:
        cut = {f"{z}/{x}/{y}": store.blobs.put(tile, "image/jpeg") for z, x, y, tile in tiles.cut_tiles(image)}
    except (OSError, SyntaxError, ValueError):
        raise tiles.PictureRefused(400, f"The picture isn't the {mime} it claims to be.") from None
    picture = WorldPicture(sha, mime, image.width, image.height, tiles.max_zoom(image.width, image.height), cut)
    return store.world_pictures.put(picture)


def store_blob(store: PictureStore, sha: str, mime: str) -> WorldPicture:
    """The picture whose original is the blob `sha`, cut into its tiles unless it already is. `LookupError` when the
    blob store hasn't the original; `tiles.PictureRefused` for a picture Delve won't take, before any tile is put."""
    stored = store.world_pictures.get(sha)
    if stored is not None:
        return stored
    data = store.blobs.get(sha)
    if data is None:
        raise LookupError(f"the picture {sha} isn't in the blob store")
    return _cut(store, sha, data, mime)


def store(store: PictureStore, data: bytes, mime: str) -> WorldPicture:
    """The picture `data`: its original put in the blob store, then cut. A refused one puts nothing."""
    tiles.open_picture(data, mime)
    sha = store.blobs.put(data, mime)
    return store_blob(store, sha, mime)


def tile(store: PictureStore, picture_id: str, z: int, x: int, y: int) -> bytes | None:
    """The tile as printed; None for a tile or a picture there isn't."""
    picture = store.world_pictures.get(picture_id)
    sha = None if picture is None else picture.tiles.get(f"{z}/{x}/{y}")
    return None if sha is None else store.blobs.get(sha)


def original(store: PictureStore, picture_id: str) -> tuple[bytes, str] | None:
    """The original's bytes and mime, for the organiser; None for a picture there isn't."""
    picture = store.world_pictures.get(picture_id)
    data = None if picture is None else store.blobs.get(picture.id)
    return None if picture is None or data is None else (data, picture.mime)


_FOGGED: OrderedDict[tuple[str, int, int, int, str], bytes | None] = OrderedDict()
_LOCK = threading.Lock()


def _digest(geo: GeoMap, cells: Collection[int]) -> str:
    """What a seat's tile depends on besides its place: the grid, the picture's scale and the known cells."""
    h = hashlib.sha256(repr((geo.grid, geo.picture)).encode())
    h.update(",".join(map(str, sorted(cells))).encode())
    return h.hexdigest()


def seat_tile(
    store: PictureStore, picture_id: str, geo: GeoMap, cells: frozenset[int], z: int, x: int, y: int
) -> bytes | None:
    """The tile `z/x/y` as a seat that knows `cells` may see it: None when nothing there is known or the tile isn't
    there, the tile as printed when all of it is, and else the tile fogged where nothing is known."""
    picture = store.world_pictures.get(picture_id)
    if picture is None or geo.picture is None or f"{z}/{x}/{y}" not in picture.tiles:
        return None
    key = (picture_id, z, x, y, _digest(geo, cells))
    with _LOCK:
        if key in _FOGGED:
            _FOGGED.move_to_end(key)
            return _FOGGED[key]
    mask = tiles.tile_mask(geo, cells, z, x, y, picture.max_zoom)
    if mask == "none":
        answer = None
    else:
        raw = tile(store, picture_id, z, x, y)
        answer = raw if raw is None or mask == "all" else tiles.fog_tile(raw, mask)
    with _LOCK:
        _FOGGED[key] = answer
        while len(_FOGGED) > FOGGED_CACHE:
            _FOGGED.popitem(last=False)
    return answer
