"""Map state: where each character is and what each character has discovered.

Door states and revealed secrets are facts of the world, shared by everyone.
Discovery is what each character knows: characters apart know different rooms,
and characters that share a location share what they know (`merge`).

Pure: every operation takes a `MapState` and returns a new one. Fog itself is
computed by the DSL's `fog_of_war`, through `render_fogged`.
"""

from __future__ import annotations

import threading
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from delve.maps.dsl import (
    DungeonMap,
    SessionView,
    candidates,
    party_start_node,
    render_fogged,
    resolve_node,
    visible_doors,
)
from delve.maps.dsl.graph import Graph
from delve.maps.dsl.secrets import list_secrets
from delve.maps.sources import graph_of
from delve.maps.tokens import Token, entry_points, party_nodes, with_tokens


class UnknownNode(LookupError):
    """`query` names no node of the map, or several (`candidates`)."""

    def __init__(self, query: str, candidates: list[dict]) -> None:
        super().__init__(f"unknown node {query!r}")
        self.query = query
        self.candidates = candidates


class NoPosition(LookupError):
    """None of the given characters has a location on the map."""


@dataclass(frozen=True)
class CharacterView:
    location: str | None = None
    nodes: frozenset[str] = frozenset()
    doors: frozenset[str] = frozenset()
    came_from: str | None = None
    """The node the character stood in before its last move to another, for its fight's side of the room
    (DEL-271); None before a first move, and in a map state from before it."""


@dataclass(frozen=True)
class MapState:
    characters: Mapping[str, CharacterView] = field(default_factory=dict)
    door_states: Mapping[str, str] = field(default_factory=dict)
    revealed: frozenset[str] = frozenset()

    @staticmethod
    def empty() -> MapState:
        return MapState()


def _resolve(dmap: DungeonMap, graph: Graph, query: str) -> str:
    node = resolve_node(dmap, graph, query)
    if node is None:
        raise UnknownNode(query, candidates(dmap, graph, query))
    return node


def _update(state: MapState, character_ids: Iterable[str], **changes: Any) -> MapState:
    characters = dict(state.characters)
    for cid in character_ids:
        characters[cid] = replace(characters.get(cid, CharacterView()), **changes)
    return replace(state, characters=characters)


def _discover(
    state: MapState, graph: Graph, character_ids: Iterable[str], node: str, doors: bool
) -> MapState:
    found = frozenset(visible_doors(graph, node)) if doors else frozenset()
    characters = dict(state.characters)
    for cid in character_ids:
        c = characters.get(cid, CharacterView())
        characters[cid] = replace(c, nodes=c.nodes | {node}, doors=c.doors | found)
    return replace(state, characters=characters)


def merge(state: MapState) -> MapState:
    """Characters that share a location get the union of their knowledge."""
    nodes: dict[str, frozenset[str]] = {}
    doors: dict[str, frozenset[str]] = {}
    for c in state.characters.values():
        if c.location is not None:
            nodes[c.location] = nodes.get(c.location, frozenset()) | c.nodes
            doors[c.location] = doors.get(c.location, frozenset()) | c.doors
    return replace(state, characters={
        cid: c if c.location is None
        else replace(c, nodes=nodes[c.location], doors=doors[c.location])
        for cid, c in state.characters.items()
    })


def place(state: MapState, dmap: DungeonMap, character_ids: Iterable[str], node: str) -> MapState:
    """Put the characters at `node` without discovering anything."""
    to = _resolve(dmap, graph_of(dmap), node)
    return merge(_update(state, character_ids, location=to))


def move(state: MapState, dmap: DungeonMap, character_ids: Iterable[str], to: str) -> MapState:
    """The characters go to `to` (adjacent or not: a chute is a move too) and
    discover it with its visible doors."""
    ids = list(character_ids)
    graph = graph_of(dmap)
    node = _resolve(dmap, graph, to)
    moved = state
    for cid in ids:
        was = state.characters.get(cid, CharacterView())
        came_from = was.location if was.location not in (None, node) else was.came_from
        moved = _update(moved, [cid], location=node, came_from=came_from)
    return merge(_discover(moved, graph, ids, node, doors=True))


def reveal(
    state: MapState,
    dmap: DungeonMap,
    character_ids: Iterable[str],
    node: str,
    reveal_doors: bool = True,
) -> MapState:
    """The characters discover `node` (and its visible doors) without moving."""
    graph = graph_of(dmap)
    found = _resolve(dmap, graph, node)
    return merge(_discover(state, graph, character_ids, found, doors=reveal_doors))


def leave(state: MapState, character_ids: Iterable[str]) -> MapState:
    """The characters are no longer on this map (they went to another): their
    locations clear, what they know of it stays."""
    return _update(state, [cid for cid in character_ids if cid in state.characters], location=None)


def discover_door(state: MapState, character_ids: Iterable[str], door_key: str) -> MapState:
    """The characters find a door, a secret one say; those who share their
    location learn it too (`merge`)."""
    characters = dict(state.characters)
    for cid in character_ids:
        c = characters.get(cid, CharacterView())
        characters[cid] = replace(c, doors=c.doors | {door_key})
    return merge(replace(state, characters=characters))


def set_door(state: MapState, door_key: str, door_state: str) -> MapState:
    return replace(state, door_states={**state.door_states, door_key: door_state})


def reveal_secret(state: MapState, secret_key: str) -> MapState:
    return replace(state, revealed=state.revealed | {secret_key})


def start(state: MapState, dmap: DungeonMap, character_ids: Iterable[str]) -> MapState:
    """Move the characters to the map's party start. A map without one places
    nobody, as in dungml."""
    node = party_start_node(dmap)
    return state if node is None else move(state, dmap, character_ids, node)


def view(state: MapState, character_ids: Iterable[str]) -> SessionView:
    """What these characters know together. `party_location` is set only when
    they all stand in one location."""
    known = [state.characters[cid] for cid in character_ids if cid in state.characters]
    locations = {c.location for c in known}
    return SessionView(
        discovered_nodes=frozenset().union(*(c.nodes for c in known)),
        discovered_doors=frozenset().union(*(c.doors for c in known)),
        door_states=dict(state.door_states),
        party_location=locations.pop() if len(locations) == 1 else None,
        revealed=state.revealed,
    )


def groups(state: MapState, character_ids: Iterable[str]) -> list[tuple[str, frozenset[str]]]:
    """(location, character ids) per occupied location, sorted by location."""
    at: dict[str, set[str]] = {}
    for cid in character_ids:
        c = state.characters.get(cid)
        if c is not None and c.location is not None:
            at.setdefault(c.location, set()).add(cid)
    return [(loc, frozenset(at[loc])) for loc in sorted(at)]


VIEW_CACHE_SIZE = 32
"""How many drawn views are kept, the least recently used going first (DEL-166)."""

_views_lock = threading.Lock()
_views: OrderedDict[tuple, tuple[DungeonMap, str]] = OrderedDict()
"""Drawn views by what they show: the map (by `id`; the entry holds the map, so the id can't be reused while it is
kept), the fight's tokens, whether it is the full map, what is discovered and revealed, and the party discs. Every seat
redraws the same map after every map event, so a view drawn once serves them all (DEL-166): the Tomb of Horrors' DM
view takes over a second to draw."""


def _drawn(key: tuple, dmap: DungeonMap, draw: Callable[[], str]) -> str:
    with _views_lock:
        hit = _views.get(key)
        if hit is not None and hit[0] is dmap:
            _views.move_to_end(key)
            return hit[1]
    svg = draw()
    with _views_lock:
        _views[key] = (dmap, svg)
        _views.move_to_end(key)
        while len(_views) > VIEW_CACHE_SIZE:
            _views.popitem(last=False)
    return svg


def clear_views() -> None:
    with _views_lock:
        _views.clear()


def _came_from(state: MapState) -> tuple[tuple[str, str], ...]:
    """Each node's way in for a fight's sides (DEL-271): the node most of the characters standing in it came from."""
    counts: dict[str, Counter[str]] = {}
    for c in state.characters.values():
        if c.location is not None and c.came_from is not None:
            counts.setdefault(c.location, Counter())[c.came_from] += 1
    return tuple(sorted((node, came.most_common(1)[0][0]) for node, came in counts.items()))


def _with_fight(dmap: DungeonMap, tokens: Sequence[Token], came_from: tuple[tuple[str, str], ...]) -> DungeonMap:
    return with_tokens(dmap, tokens, entry_points(dmap, dict(came_from))) if tokens else dmap


def _discs(dmap: DungeonMap, locations: tuple[str, ...], tokens: Sequence[Token]) -> tuple[str, ...]:
    """The groups' nodes that get a party disc: not where the fight draws the characters themselves (DEL-128)."""
    if not tokens:
        return locations
    fought = party_nodes(dmap, tokens)
    return tuple(loc for loc in locations if loc not in fought)

def render_view(
    state: MapState, dmap: DungeonMap, character_ids: Iterable[str], tokens: Sequence[Token] = ()
) -> str:
    """The characters' fog view, with one party disc per group and the fight's `tokens` (`with_tokens`). Drawn once
    for what it shows: treat `dmap` as read-only, as every parsed map from `delve.maps.sources` is."""
    ids = list(character_ids)
    locations = tuple(loc for loc, _ in groups(state, ids))
    if not locations:
        raise NoPosition("none of the characters has a position")
    v = view(state, ids)
    locations = _discs(dmap, locations, tokens)
    came = _came_from(state) if tokens else ()
    key = (id(dmap), tuple(tokens), came, False, v.discovered_nodes, v.discovered_doors, v.revealed, locations)
    return _drawn(key, dmap, lambda: render_fogged(
        _with_fight(dmap, tokens, came), v.discovered_nodes, v.discovered_doors,
        party_locations=locations, revealed=v.revealed,
    ))


def render_dm(state: MapState, dmap: DungeonMap, tokens: Sequence[Token] = ()) -> str:
    """The full map with every group's party disc and the fight's `tokens`; drawn once for what it shows, as
    `render_view`."""
    locations = _discs(dmap, tuple(loc for loc, _ in groups(state, state.characters)), tokens)
    came = _came_from(state) if tokens else ()
    key = (id(dmap), tuple(tokens), came, True, locations)
    return _drawn(key, dmap, lambda: render_fogged(
        _with_fight(dmap, tokens, came), (), (), party_locations=locations, full=True,
    ))


def upgrade(state: MapState, new_dmap: DungeonMap) -> MapState:
    """The state against a new version of the map: node ids, door keys and
    secret keys that no longer exist are dropped, everything else is kept."""
    graph = graph_of(new_dmap)
    nodes = set(graph.nodes)
    doors = {e.key for e in graph.edges} | {b.key for b in graph.boundary}
    secrets = {s.key for s in list_secrets(new_dmap)}
    return MapState(
        characters={
            cid: CharacterView(
                location=c.location if c.location in nodes else None,
                nodes=c.nodes & nodes,
                doors=c.doors & doors,
            )
            for cid, c in state.characters.items()
        },
        door_states={k: v for k, v in state.door_states.items() if k in doors},
        revealed=state.revealed & secrets,
    )


def to_json(state: MapState) -> dict:
    return {
        "characters": {
            cid: {
                "location": c.location,
                "nodes": sorted(c.nodes),
                "doors": sorted(c.doors),
                **({"came_from": c.came_from} if c.came_from else {}),
            }
            for cid, c in state.characters.items()
        },
        "door_states": dict(state.door_states),
        "revealed": sorted(state.revealed),
    }


def from_json(raw: Mapping[str, Any]) -> MapState:
    return MapState(
        characters={
            cid: CharacterView(
                location=c.get("location"),
                nodes=frozenset(c.get("nodes", ())),
                doors=frozenset(c.get("doors", ())),
                came_from=c.get("came_from"),
            )
            for cid, c in raw.get("characters", {}).items()
        },
        door_states=dict(raw.get("door_states", {})),
        revealed=frozenset(raw.get("revealed", ())),
    )
