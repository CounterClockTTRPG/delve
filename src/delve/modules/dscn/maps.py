"""Map handling inside a bundle — includes resolve *only* within the bundle
(spec §4.2), so a scenario renders the same wherever it is opened."""
from __future__ import annotations

from dataclasses import dataclass, field

import delve.maps.dsl as dungml
from delve.maps.dsl import DmapParseError, DungeonMap, Graph, build_graph

from .container import Bundle


@dataclass
class MapInfo:
    name: str
    model: DungeonMap | None = None
    graph: Graph | None = None
    error: str | None = None
    missing_includes: list[str] = field(default_factory=list)

    @property
    def nodes(self) -> set[str]:
        return set(self.graph.nodes) if self.graph else set()


def missing_includes(source: str, libs: dict[str, str]) -> list[str]:
    """Every include reachable from `source` that the bundle doesn't carry."""
    missing: list[str] = []
    seen: set[str] = set()
    stack = [source]
    while stack:
        try:
            names = dungml.include_names(stack.pop())
        except DmapParseError:
            continue
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            if n in libs:
                stack.append(libs[n])
            else:
                missing.append(n)
    return missing


def analyse_map(bundle: Bundle, name: str, libs: dict[str, str] | None = None) -> MapInfo:
    libs = bundle.library_sources() if libs is None else libs
    info = MapInfo(name=name)
    try:
        source = bundle.map_source(name)
    except Exception as e:  # missing file / bad utf-8 — reported elsewhere
        info.error = str(e)
        return info
    info.missing_includes = missing_includes(source, libs)
    if info.missing_includes:
        info.error = "missing include(s): " + ", ".join(info.missing_includes)
        return info
    try:
        info.model = dungml.parse(source, include_sources=libs)
    except DmapParseError as e:
        info.error = str(e)
        return info
    info.graph = build_graph(info.model)
    return info


def analyse_maps(bundle: Bundle) -> dict[str, MapInfo]:
    libs = bundle.library_sources()
    return {
        m["name"]: analyse_map(bundle, m["name"], libs)
        for m in bundle.maps("map") if isinstance(m.get("name"), str)
    }


def vendor(bundle: Bundle) -> list[str]:
    """Copy every include the bundle's maps need but don't carry from
    dungml's bundled library into `maps/lib/`. Returns the names added;
    names dungml doesn't ship either are left for the validator to report."""
    added: list[str] = []
    while True:
        libs = bundle.library_sources()
        wanted: list[str] = []
        for m in bundle.maps():
            try:
                src = bundle.read_text(m["file"])
            except Exception:
                continue
            for n in missing_includes(src, libs):
                if n not in wanted and n not in added:
                    wanted.append(n)
        new = [n for n in wanted if dungml.library_source(n) is not None]
        if not new:
            return added
        for n in new:
            bundle.add_map(n, dungml.library_source(n) or "", role="library")
            added.append(n)
