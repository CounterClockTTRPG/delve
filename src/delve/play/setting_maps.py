"""A setting's own world maps on this install (settings plan Task 9): a third owner kind beside a module and a campaign,
in `storage.setting_maps`, always a Delve GeoJSON document.

A module's ready map is copied into the setting as a document (`copy_module_map`). A new campaign copies the setting's ready maps (`world_maps.seed`, through the setting
layer); a campaign made before keeps its own copies.

A seat reads a setting's map whole (`seat_view`): the shipped setting's lore is public, but a hidden feature, a feature's
`dm_notes` and its `hidden` tag never go in.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from delve.domain.world import WorldKnowledge, WorldMapSource
from delve.maps.geo import knowledge
from delve.maps.geo.geojson import from_geojson
from delve.maps.geo.model import GeoMapError
from delve.modules.source import load_source, world_includes
from delve.modules.worldmaps import geo_of, get_world_map
from delve.setting.catalog import CATALOG, SettingEntry, entry
from delve.storage.interfaces import Storage

__all__ = ["SettingMapTaken", "copy_module_map", "seat_view"]


class SettingMapTaken(ValueError):
    """The setting has a world map of that name already."""


def copy_module_map(
    storage: Storage,
    setting_id: str,
    module_id: str,
    name: str,
    *,
    as_name: str | None = None,
    settings: Sequence[SettingEntry] = CATALOG,
) -> WorldMapSource:
    """The module's ready map `name` as the setting's, under `as_name` when given: a Delve document, its `.map` includes
    compiled in, its picture kept. `KeyError` for a setting, a module or a map there isn't, `ValueError` for a map in
    review, `SettingMapTaken` for a name the setting has, and `WorldMapError` for a `.map` that doesn't read."""
    if entry(setting_id, settings) is None:  # the install's settings: `settings`, its catalogs'
        raise KeyError(setting_id)
    if storage.modules.get(module_id) is None:
        raise KeyError(module_id)
    source = load_source(storage, module_id)
    found = get_world_map(source, name)
    if found is None:
        raise KeyError(name)
    if found.status != "ready":
        raise ValueError(f"The world map {found.title} is still in review.")
    new_name = (as_name or "").strip() or found.name
    if storage.setting_maps.get(setting_id, new_name) is not None:
        raise SettingMapTaken(f"There is a world map named '{new_name}' already.")
    geo = geo_of(found, world_includes(source.worldmaps))
    copied = WorldMapSource(new_name, found.title or found.name, "", geo=geo, picture=found.picture, status="ready")
    return storage.setting_maps.put(setting_id, copied)


def _picture(storage: Storage, ref: Any) -> dict[str, Any] | None:
    """The map's picture as the views give it, once it is cut into tiles; None without one."""
    stored = storage.world_pictures.get(ref.id) if ref is not None else None
    if ref is None or stored is None:
        return None
    return {
        "id": ref.id,
        "width_px": ref.width_px,
        "height_px": ref.height_px,
        "km_per_px": ref.km_per_px,
        "max_zoom": stored.max_zoom,
    }


def seat_view(storage: Storage, world_map: WorldMapSource, maps: Sequence[WorldMapSource]) -> dict[str, Any]:
    """The setting's map whole, as a seat sees it (`knowledge.seat_view` knowing everything): no party, no journey,
    never a hidden feature or the DM's notes. `maps` are the setting's maps, which a `.map` one may include.
    `WorldMapError` or `GeoMapError` for a map that doesn't read."""
    geo_map = from_geojson(geo_of(world_map, world_includes(maps))).geo
    if geo_map is None:
        raise GeoMapError("A world map needs its scale", ["the document isn't a Delve world map"])
    picture = _picture(storage, geo_map.picture)
    return knowledge.seat_view(
        geo_map,
        WorldKnowledge(everything=True),
        name=world_map.name,
        title=world_map.title or world_map.name,
        party=None,
        journey=None,
        picture=picture,
        tiles_version=picture["id"] if picture else "",
    )
