"""Combat tokens on a map, as DSL markers anchored in their node with `in <node>`.

Fog-safe by construction: a marker with a location is kept by `fog_of_war` only when its node is discovered (the
plateau 1 invariant), so a token in a room the characters haven't found never reaches their view. The DM view draws
them all.

Where in its node a token stands (DEL-271): a combatant knows only its node, so every token used to stand on one grid
round the node's centre, and the party always looked surrounded at melee range. When both sides are in a node, the
party and its allies stand on the side they came in from (the door from the node they came from, `entries`; else
along the node's longer side), in marching order with the front rank facing the enemies, and the enemies on the far
side. A node with one side only, or a layout that would leave the node's outline, keeps the grid round the centre.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from delve.maps.dsl import DungeonMap, Marker, node_centroid, resolve_node, walk
from delve.maps.dsl.geometry import corridor_polygons, room_polygon
from delve.maps.dsl.graph import door_key
from delve.maps.dsl.model import Room
from delve.maps.sources import graph_of

Vec2 = tuple[float, float]

TOKEN_SIZE = 0.4
"""A token's radius in world units."""
TOKEN_SPACING = 1.05
"""The distance between two tokens in one node: apart enough for the hit-point arcs round them (DEL-10)."""


@dataclass(frozen=True)
class Token:
    id: str
    """The combatant's id, `chr_…` or `mon_<n>`; the marker's name."""
    label: str
    node: str | None
    """The node it stands in, `room.X` or anything `resolve_node` names one node by."""
    side: str
    """party, ally or enemy: the marker's tag, and so its colour."""
    portrait_ref: str | None = None
    rank: int | None = None
    """A PC's place in the marching order, front first: its token stands in the party's front ranks (DEL-271)."""


PARTY_SIDES = frozenset({"party", "ally"})
RANK_WIDTH = 4
"""At most this many tokens side by side in one rank."""
SIDE_DEPTH = 0.55
"""How far from the node's centre towards its edge each side's front rank stands, as a share of the half-length."""


def _offsets(n: int) -> list[tuple[float, float]]:
    """`n` points around (0, 0) in a near-square grid, `TOKEN_SPACING` apart, row by row."""
    columns = math.ceil(math.sqrt(n))
    rows = math.ceil(n / columns)
    return [
        ((i % columns - (columns - 1) / 2) * TOKEN_SPACING, ((rows - 1) / 2 - i // columns) * TOKEN_SPACING)
        for i in range(n)
    ]


def with_tokens(dmap: DungeonMap, tokens: Iterable[Token], entries: Mapping[str, Vec2] | None = None) -> DungeonMap:
    """A copy of the map with a marker per token, in its node: the sides apart when both are there, the party on the
    side of its way in (`entries`, a node's entry point), else a grid round the node's centre (DEL-271).

    A token whose node is missing or names no single node of the map isn't drawn."""
    graph = graph_of(dmap)
    by_node: dict[str, list[Token]] = {}
    for token in tokens:
        node = resolve_node(dmap, graph, token.node) if token.node else None
        if node is not None and node_centroid(dmap, node) is not None:
            by_node.setdefault(node, []).append(token)
    markers = list(dmap.markers)
    for node, here in by_node.items():
        centre = node_centroid(dmap, node)
        placed = _sides(dmap, node, centre, here, (entries or {}).get(node)) or _grid(centre, here)
        for token, position in placed:
            markers.append(
                Marker(
                    name=token.id,
                    position=position,
                    tag=token.side,
                    label=token.label,
                    initial=token.label[:1] or None,
                    size=TOKEN_SIZE,
                    location=node,
                    image=token.portrait_ref,
                )
            )
    return dmap.model_copy(update={"markers": markers})


def party_nodes(dmap: DungeonMap, tokens: Iterable[Token]) -> frozenset[str]:
    """The nodes where a party token is drawn (`with_tokens`): there the characters stand as tokens of their own, so
    the party's disc is left out (DEL-128)."""
    graph = graph_of(dmap)
    nodes = (resolve_node(dmap, graph, t.node) for t in tokens if t.side == "party" and t.node)
    return frozenset(n for n in nodes if n is not None and node_centroid(dmap, n) is not None)

def entry_points(dmap: DungeonMap, came_from: Mapping[str, str]) -> dict[str, Vec2]:
    """Each node's way in, from the node the party came from (`came_from`, node → node): the door between them, else
    the centre of the node it came from. A node with no known way in has none."""
    graph = graph_of(dmap)
    doors = {door_key(placed.item): placed.item.position for placed in walk.members(dmap, "doors")}
    out: dict[str, Vec2] = {}
    for node, before in came_from.items():
        edge = next((e for neighbour, e in graph.neighbors(node) if neighbour == before), None)
        door = doors.get(edge.key.split("#", 1)[0]) if edge is not None else None
        point = door if door is not None else node_centroid(dmap, before)
        if point is not None:
            out[node] = (float(point[0]), float(point[1]))
    return out


def _grid(centre: Vec2, here: list[Token]) -> list[tuple[Token, Vec2]]:
    cx, cy = centre
    return [(token, (cx + dx, cy + dy)) for token, (dx, dy) in zip(here, _offsets(len(here)), strict=True)]


def _sides(
    dmap: DungeonMap, node: str, centre: Vec2, here: list[Token], entry: Vec2 | None
) -> list[tuple[Token, Vec2]] | None:
    """Both sides apart in the node, or None when it has one side only or the layout would leave its outline."""
    party = sorted((t for t in here if t.side in PARTY_SIDES), key=lambda t: (t.rank is None, t.rank or 0))
    enemies = [t for t in here if t.side not in PARTY_SIDES]
    outline = _outline(dmap, node)
    if not party or not enemies or not outline:
        return None
    toward = _toward_entry(centre, entry, outline)
    half = max(_extent(centre, toward, polygon) for polygon in outline)
    if half <= TOKEN_SPACING:
        return None
    reach = half * SIDE_DEPTH
    front = max(reach - TOKEN_SPACING * (_ranks(len(party)) - 1) / 2, TOKEN_SPACING / 2)
    placed = _ranked(party, centre, toward, front) + _ranked(enemies, centre, (-toward[0], -toward[1]), front)
    if not all(any(_inside(point, polygon) for polygon in outline) for _, point in placed):
        return None
    return placed


def _ranked(side: list[Token], centre: Vec2, toward: Vec2, front: float) -> list[tuple[Token, Vec2]]:
    """A side in ranks of `RANK_WIDTH`, the first rank `front` from the centre towards `toward`, the others behind it."""
    across = (-toward[1], toward[0])
    width = min(RANK_WIDTH, len(side))
    out = []
    for i, token in enumerate(side):
        rank, place = divmod(i, width)
        in_rank = min(width, len(side) - rank * width)
        depth = front + rank * TOKEN_SPACING
        offset = (place - (in_rank - 1) / 2) * TOKEN_SPACING
        out.append((token, (centre[0] + toward[0] * depth + across[0] * offset,
                            centre[1] + toward[1] * depth + across[1] * offset)))
    return out


def _ranks(count: int) -> int:
    return math.ceil(count / RANK_WIDTH)


def _outline(dmap: DungeonMap, node: str) -> list[list[Vec2]]:
    """The node's polygons: a room's one, a corridor's segments."""
    found = walk.nodes(dmap).get(node)
    if found is None:
        return []
    polygons = [room_polygon(found)] if isinstance(found, Room) else corridor_polygons(found)
    return [p for p in polygons if len(p) >= 3]


def _toward_entry(centre: Vec2, entry: Vec2 | None, outline: list[list[Vec2]]) -> Vec2:
    """A unit vector from the centre towards the way in; without one, towards the node's longer side's start."""
    if entry is not None:
        dx, dy = entry[0] - centre[0], entry[1] - centre[1]
        length = math.hypot(dx, dy)
        if length > 1e-6:
            return (dx / length, dy / length)
    xs = [x for polygon in outline for x, _ in polygon]
    ys = [y for polygon in outline for _, y in polygon]
    return (-1.0, 0.0) if max(xs) - min(xs) >= max(ys) - min(ys) else (0.0, 1.0)


def _extent(centre: Vec2, toward: Vec2, polygon: list[Vec2]) -> float:
    """How far the polygon reaches from the centre along `toward` (or against it, whichever is shorter)."""
    along = [(x - centre[0]) * toward[0] + (y - centre[1]) * toward[1] for x, y in polygon]
    return min(max(along), -min(along))


def _inside(point: Vec2, polygon: list[Vec2]) -> bool:
    """Ray casting: whether the point is inside the polygon."""
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside
