"""A module's world maps, in its source (`ModuleSource.worldmaps`): found, put and removed by name, and read as a geo
document (`geo_of`).

A world map is a Delve GeoJSON document (`geo`), or plateau 6's `.map` text (`dsl`), converted on read. A `.map` that
isn't a workspace is an include fragment: it is no world map of its own, never listed, and read only through the map
that includes it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from delve.domain.world import WorldMapSource
from delve.maps import world
from delve.maps.geo.from_dsl import from_view
from delve.maps.geo.geojson import to_geojson
from delve.modules.source import ModuleSource


def is_fragment(world_map: WorldMapSource) -> bool:
    """A `.map` include fragment: no world map of its own."""
    return world_map.geo is None and not world.is_workspace(world_map.dsl)


def world_maps(source: ModuleSource) -> list[WorldMapSource]:
    """The module's world maps, in order, without the include fragments."""
    return [w for w in source.worldmaps if not is_fragment(w)]


def get_world_map(source: ModuleSource, name: str) -> WorldMapSource | None:
    return next((w for w in world_maps(source) if w.name == name), None)


def put_world_map(source: ModuleSource, world_map: WorldMapSource) -> ModuleSource:
    """The source with `world_map` in place of the one of its name, else added last."""
    if any(w.name == world_map.name for w in source.worldmaps):
        maps = tuple(world_map if w.name == world_map.name else w for w in source.worldmaps)
    else:
        maps = (*source.worldmaps, world_map)
    return replace(source, worldmaps=maps)


def remove_world_map(source: ModuleSource, name: str) -> ModuleSource:
    return replace(source, worldmaps=tuple(w for w in source.worldmaps if w.name != name))


def geo_of(world_map: WorldMapSource, includes: dict[str, str]) -> dict[str, Any]:
    """The map's Delve GeoJSON document: the stored one, else its `.map` text's first view converted, its includes
    (`source.world_includes`) compiled in. Raises `world.WorldMapError` for a `.map` that doesn't read."""
    if world_map.geo is not None:
        return world_map.geo
    view = world.compile_view(world.parse(world_map.dsl, includes))
    return to_geojson(from_view(view).geo)
