"""A module's maps as parsed `DungeonMap`s: a map's source with its includes resolved.

Includes resolve against a module's (or a revision's) `library` maps first, then the built-in libraries, and nothing
else: never a file on disk. The web routes and the play services both parse maps through here.

`cached_source` parses each map text once, with the texts of its includes, whatever module, revision or campaign it
comes from (DEL-166): play (`parsed_map`), the editor's `derive`, the ref repair and the module list share that one
cache. `graph_of` is the graph of a parsed map, built once per map object, so the map state and the tokens reuse it.
Parsed maps are shared: treat them as read-only (`with_tokens` copies). `parse_source` and `parse_map` parse afresh,
for a caller that changes what it gets.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from functools import lru_cache

from delve.domain.modules import ModuleMap
from delve.maps.dsl import (
    DmapParseError,
    DungeonMap,
    build_graph,
    include_names,
    library_source,
    list_libraries,
    parse,
)
from delve.maps.dsl.graph import Graph

__all__ = [
    "CACHE_SIZE",
    "cached_map",
    "cached_source",
    "clear_cache",
    "graph_of",
    "library_sources",
    "parse_map",
    "parse_source",
    "parsed_map",
    "resolve_includes",
]

CACHE_SIZE = 128
"""How many parsed maps (with their graphs), and how many graphs of other maps, are kept: the least recently used go
first. A parsed map with its graph takes about 0.7 MB (the 336 maps of the live modules: 229 MB, 2026-10-28), and the
module list alone puts a map of each module in (DEL-166)."""


def library_sources(maps: Sequence[ModuleMap], exclude: str | None = None) -> dict[str, str]:
    """The `library` maps of a module or revision by name, without the map named `exclude`."""
    return {m.name: m.source for m in maps if m.role == "library" and m.name != exclude}


@lru_cache(maxsize=4 * CACHE_SIZE)
def _include_names(text: str) -> tuple[str, ...]:
    """The includes `text` names: a parse of its own, so kept for more texts than the parsed maps (DEL-166), as every
    lookup of `cached_source` resolves them."""
    return tuple(include_names(text))


@lru_cache(maxsize=1)
def _builtin() -> frozenset[str]:
    """The built-in libraries' names: they ship with Delve, so they don't change while it runs."""
    return frozenset(list_libraries())


@lru_cache(maxsize=64)
def _library_source(name: str) -> str | None:
    return library_source(name)


def resolve_includes(source: str, libraries: Mapping[str, str]) -> dict[str, str]:
    """Every include `source` needs, directly or through another include, by name: from `libraries`, else built in.

    Raises `DmapParseError` for a source that doesn't parse, and for an include that is neither, at its line when
    `source` names it itself.
    """
    resolved: dict[str, str] = {}
    builtin = _builtin()
    pending = list(_include_names(source))
    while pending:
        name = pending.pop(0)
        if name in resolved:
            continue
        text = libraries.get(name)
        if text is None and name in builtin:
            text = _library_source(name)
        if text is None:
            raise DmapParseError(f'include not found: "{name}"', *_include_position(source, name))
        resolved[name] = text
        pending.extend(_include_names(text))
    return resolved


def _include_position(source: str, name: str) -> tuple[int, int]:
    pattern = re.compile(r'^([ \t]*)include\s+"' + re.escape(name) + '"', re.MULTILINE)
    found = pattern.search(source)
    if found is None:
        return 0, 0
    line = source.count("\n", 0, found.start()) + 1
    return line, len(found.group(1)) + 1


def parse_source(source: str, libraries: Mapping[str, str] | None = None) -> DungeonMap:
    """`source` parsed, its includes resolved from `libraries` and then the built-ins."""
    return parse(source, include_sources=resolve_includes(source, libraries or {}))


def parse_map(maps: Sequence[ModuleMap], name: str, source: str | None = None) -> DungeonMap:
    """The map `name` of a module's or a revision's `maps`, parsed with their libraries.

    `source` replaces the stored one (an editor's unsaved buffer). Raises `KeyError` for an unknown name and
    `DmapParseError` when it doesn't parse.
    """
    stored = next((m for m in maps if m.name == name), None)
    if stored is None:
        raise KeyError(name)
    return parse_source(stored.source if source is None else source, library_sources(maps, exclude=name))


# --- the cache ---------------------------------------------------------------------------------------------------

_lock = threading.Lock()


class _Entry:
    """A parsed map with its graph, built on first use: they come and go together, so the graphs of the maps `derive`
    reads never push out those play uses (DEL-166)."""

    __slots__ = ("dmap", "graph")

    def __init__(self, dmap: DungeonMap) -> None:
        self.dmap = dmap
        self.graph: Graph | None = None


_parsed: OrderedDict[tuple[str, tuple[tuple[str, str], ...]], _Entry] = OrderedDict()
"""By the map's text and the texts of the includes it resolves to (DEL-166): one cache for every reader, play, the
editor's derive, the ref repair and the module list, whatever module, revision or campaign the text comes from."""
_by_id: dict[int, _Entry] = {}
"""The entries of `_parsed` by `id(dmap)`, for `graph_of`; an entry leaves both at once."""
_graphs: OrderedDict[int, tuple[DungeonMap, Graph]] = OrderedDict()
"""The graphs of maps that aren't in `_parsed` (a copy, a map parsed elsewhere), by `id(dmap)`; the entry holds the map
itself, so its id can't be reused while it is cached."""


def cached_source(source: str, libraries: Mapping[str, str] | None = None) -> DungeonMap:
    """`source` parsed as `parse_source` parses it, once per text and includes: the least recently used of
    `CACHE_SIZE` go first. The map is shared: treat it as read-only. Raises as `parse_source`; a map that doesn't
    parse isn't cached."""
    includes = resolve_includes(source, libraries or {})
    key = (source, tuple(sorted(includes.items())))
    with _lock:
        entry = _parsed.get(key)
        if entry is not None:
            _parsed.move_to_end(key)
            return entry.dmap
    dmap = parse(source, include_sources=includes)
    with _lock:
        entry = _parsed.get(key)
        if entry is not None:  # another thread parsed it meanwhile: keep the one already handed out
            return entry.dmap
        entry = _parsed[key] = _by_id[id(dmap)] = _Entry(dmap)
        while len(_parsed) > CACHE_SIZE:
            _, old = _parsed.popitem(last=False)
            _by_id.pop(id(old.dmap), None)
    return dmap


def cached_map(maps: Sequence[ModuleMap], name: str) -> DungeonMap:
    """The map `name` of a module's or a revision's `maps`, parsed with their libraries, through the cache. Raises
    as `parse_map`."""
    stored = next((m for m in maps if m.name == name), None)
    if stored is None:
        raise KeyError(name)
    return cached_source(stored.source, library_sources(maps, exclude=name))


def graph_of(dmap: DungeonMap) -> Graph:
    """The map's graph, built once for this map object."""
    with _lock:
        entry = _by_id.get(id(dmap))
        if entry is not None and entry.dmap is dmap and entry.graph is not None:
            return entry.graph
        hit = _graphs.get(id(dmap))
        if hit is not None and hit[0] is dmap:
            _graphs.move_to_end(id(dmap))
            return hit[1]
    graph = build_graph(dmap)
    with _lock:
        entry = _by_id.get(id(dmap))
        if entry is not None and entry.dmap is dmap:
            if entry.graph is None:
                entry.graph = graph
            return entry.graph
        _graphs[id(dmap)] = (dmap, graph)
        _graphs.move_to_end(id(dmap))
        while len(_graphs) > CACHE_SIZE:
            _graphs.popitem(last=False)
    return graph


def parsed_map(module_id: str, revision: int, maps: Sequence[ModuleMap], name: str) -> tuple[DungeonMap, Graph]:
    """The map `name` of the revision `revision` of a module, whose maps are `maps`, parsed, with its graph, through
    the cache (`cached_source`). A campaign's own map (campaign maps, 2026-10-23), which can change under the same
    revision and name, is parsed again when its text changes. Raises as `parse_map`."""
    dmap = cached_map(maps, name)
    return dmap, graph_of(dmap)


def clear_cache() -> None:
    with _lock:
        _parsed.clear()
        _by_id.clear()
        _graphs.clear()
