"""Routes by mode: the cheapest way for a mode over a geo map's terrain cells, joined to its roads and rivers.

A mode's `ModeRules` give each terrain class, route kind and kind of water a rate: a share of the mode's base pace, 0
for what it can't cross. `build_graph` builds the graph of one map for one mode (the callers cache it until the map
changes), and `plan` finds the cheapest route on it, in km at the base pace. A ruleset's travel numbers go to
`delve.rules.classic.overland`, which builds the `ModeRules`.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal, get_args

from delve.maps.geo.grid import cell_at, cell_centre, cells_within, neighbours
from delve.maps.geo.model import GeoFeature, GeoMap, Point
from delve.maps.geo.terrain import TERRAIN_OF_LETTER

__all__ = [
    "LARGE_LAKE_CELLS",
    "MODES",
    "MODE_WORDS",
    "GeoRoute",
    "Mode",
    "ModeRules",
    "NoRoute",
    "RouteGraph",
    "Stretch",
    "build_graph",
    "plan",
    "point_along",
    "slowest",
    "stretch_at",
]

Mode = Literal["foot", "horse", "cart", "river", "ship"]
MODES: tuple[Mode, ...] = get_args(Mode)

MODE_WORDS: dict[str, str] = {
    "foot": "on foot",
    "horse": "on horseback",
    "cart": "by cart",
    "river": "by river boat",
    "ship": "by ship",
}
"""How a refusal names the mode."""

LARGE_LAKE_CELLS = 3
"""A ship sails a lake of at least this many connected cells."""

OFF_ROUTE = 1.0001
"""Off-route steps cost this much more, so that a tie goes to the road."""

FORDS = ("ford", "bridge")
"""A place tagged with one of these lets the land modes cross a `barrier` river in its cell."""


@dataclass(frozen=True)
class ModeRules:
    """A mode's rates, each a share of its base pace; 0 can't be crossed. `land` is per terrain class and `routes`
    per route kind, for the land modes. `water` says what a boat keeps to: `river` (rivers, at `downstream` and
    `upstream`, and lakes at `lake`) or `sea` (the sea, lakes of `LARGE_LAKE_CELLS` cells at `lake`, and rivers up to
    their `navigable_km`). A flyer (`flies`) crosses every cell of the map at rate 1."""

    mode: str
    land: Mapping[str, float]
    routes: Mapping[str, float]
    water: Literal["none", "river", "sea"]
    downstream: float = 1.0
    upstream: float = 1.0
    lake: float = 1.0
    flies: bool = False


class NoRoute(Exception):
    """No route: an end doesn't snap to the mode's graph, or nothing joins the two."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Stretch:
    km: float
    rate: float
    what: str
    """A terrain class, a route kind, `"downstream"`, `"upstream"`, `"lake"` or `"sea"`."""
    start_km: float


@dataclass(frozen=True)
class GeoRoute:
    points: tuple[Point, ...]
    km: float
    cost_km: float
    """The km at the base pace: each stretch's km over its rate."""
    stretches: tuple[Stretch, ...]


Piece = tuple[float, float, str]
"""A part of an edge: its km, its rate and what it crosses."""


@dataclass(eq=False)
class RouteGraph:
    """One map's graph for one mode. Nodes `0 … cells - 1` are the cells' centres; the others are the vertices of the
    lines the mode uses. Treat it as read-only."""

    geo: GeoMap
    rules: ModeRules
    points: list[Point]
    adj: list[list[tuple[int, float]]]
    rate: list[float]
    """Each node's own rate: a cell's terrain, a vertex's line."""
    what: list[str]
    edges: dict[tuple[int, int], tuple[Piece, ...]] = field(default_factory=dict)
    """The pieces of every edge but a step between two cells, which `_pieces` works out."""
    vertices_in: dict[int, list[int]] = field(default_factory=dict)
    """The line vertices in each cell, for snapping the ends."""
    fastest: float = 1.0
    _keys: dict[tuple[float, float], int] = field(default_factory=dict, repr=False)

    @property
    def cells(self) -> int:
        return self.geo.grid.cells

    @property
    def on_water(self) -> bool:
        return self.rules.water != "none" and not self.rules.flies

    def _vertex(self, p: Point, rate: float, what: str) -> int:
        key = (round(p[0], 6), round(p[1], 6))
        node = self._keys.get(key)
        if node is None:
            node = len(self.points)
            self._keys[key] = node
            self.points.append((float(p[0]), float(p[1])))
            self.adj.append([])
            self.rate.append(rate)
            self.what.append(what)
            cell = cell_at(self.geo.grid, *p)
            if cell is not None:
                self.vertices_in.setdefault(cell, []).append(node)
        return node

    def _edge(self, u: int, v: int, km: float, rate: float, what: str, factor: float = 1.0) -> None:
        if u == v or rate <= 0:
            return
        cost = km / rate * factor
        known = self.edges.get((u, v))
        if known is not None and sum(k / r for k, r, _ in known) <= km / rate:
            return
        self.adj[u].append((v, cost))
        self.edges[(u, v)] = ((km, rate, what),)
        self.fastest = max(self.fastest, rate)


def _lines(geo: GeoMap, layer: str, kinds: Iterable[str] | None = None) -> list[GeoFeature]:
    wanted = set(kinds) if kinds is not None else None
    return [
        f
        for f in geo.features
        if f.layer == layer
        and (wanted is None or f.kind in wanted)
        and f.geometry.get("type") == "LineString"
        and len(f.geometry.get("coordinates") or ()) >= 2
    ]


def _coords(f: GeoFeature) -> list[Point]:
    return [(float(p[0]), float(p[1])) for p in f.geometry["coordinates"]]


def _large_lakes(geo: GeoMap) -> set[int]:
    """The cells of the lakes of at least `LARGE_LAKE_CELLS` connected cells."""
    grid, terrain = geo.grid, geo.terrain
    seen: set[int] = set()
    large: set[int] = set()
    for i, letter in enumerate(terrain[: grid.cells]):
        if letter != "l" or i in seen:
            continue
        lake, todo = [i], [i]
        seen.add(i)
        while todo:
            for j in neighbours(grid, todo.pop()):
                if j < len(terrain) and terrain[j] == "l" and j not in seen:
                    seen.add(j)
                    lake.append(j)
                    todo.append(j)
        if len(lake) >= LARGE_LAKE_CELLS:
            large.update(lake)
    return large


def _cell_rates(geo: GeoMap, rules: ModeRules) -> tuple[list[float], list[str]]:
    large = _large_lakes(geo) if rules.water == "sea" and not rules.flies else set()
    rates, whats = [], []
    terrain = geo.terrain.ljust(geo.grid.cells, ".")
    for i in range(geo.grid.cells):
        cls = TERRAIN_OF_LETTER.get(terrain[i])
        if cls is None:
            rate = 0.0
        elif rules.flies:
            rate = 1.0
        elif rules.water == "river":
            rate = rules.lake if cls == "lake" else 0.0
        elif rules.water == "sea":
            rate = 1.0 if cls == "sea" else rules.lake if cls == "lake" and i in large else 0.0
        else:
            rate = float(rules.land.get(cls, 0.0))
        rates.append(rate)
        whats.append(cls or "")
    return rates, whats


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _crosses(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Whether segments ab and cd meet (touching counts)."""
    if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
        return False
    return _orient(a, b, c) * _orient(a, b, d) <= 0 and _orient(c, d, a) * _orient(c, d, b) <= 0


def _barrier_steps(geo: GeoMap, centres: list[Point]) -> set[tuple[int, int]]:
    """The steps between cells that cross a `barrier` river, but for those from or into a cell with a ford or a
    bridge."""
    grid = geo.grid
    fords = set()
    for f in geo.features:
        if f.layer == "places" and f.geometry.get("type") == "Point" and any(t in FORDS for t in f.tags):
            cell = cell_at(grid, *f.geometry["coordinates"][:2])
            if cell is not None:
                fords.add(cell)
    blocked: set[tuple[int, int]] = set()
    for river in _lines(geo, "water", ("river",)):
        if not river.props.get("barrier"):
            continue
        pts = _coords(river)
        for c, d in pairwise(pts):
            mid = ((c[0] + d[0]) / 2, (c[1] + d[1]) / 2)
            for i in cells_within(grid, mid, math.dist(c, d) / 2 + grid.size_km * 1.5):
                if i in fords:
                    continue
                for j in neighbours(grid, i):
                    if j not in fords and _crosses(centres[i], centres[j], c, d):
                        blocked.add((min(i, j), max(i, j)))
    return blocked


def _add_cell_steps(graph: RouteGraph, centres: list[Point], blocked: set[tuple[int, int]]) -> None:
    grid, rate, adj = graph.geo.grid, graph.rate, graph.adj
    cols, square = grid.cols, grid.kind == "square"
    for i in range(grid.cells):
        ri = rate[i]
        if ri <= 0:
            continue
        ci = centres[i]
        for j in neighbours(grid, i):
            if j < i:
                continue
            rj = rate[j]
            if rj <= 0 or (i, j) in blocked:
                continue
            # A diagonal step doesn't slip between two cells that can't be crossed.
            if (
                square
                and i % cols != j % cols
                and i // cols != j // cols
                and rate[(i // cols) * cols + j % cols] <= 0
                and rate[(j // cols) * cols + i % cols] <= 0
            ):
                continue
            d = math.dist(ci, centres[j])
            cost = (d / 2 / ri + d / 2 / rj) * OFF_ROUTE
            adj[i].append((j, cost))
            adj[j].append((i, cost))
    graph.fastest = max([graph.fastest, *rate[: grid.cells]])


def _densified(pts: list[Point], step: float) -> list[Point]:
    """The line with a vertex at least every `step` km, so that a route is joined to every cell it passes."""
    out = [pts[0]]
    for a, b in pairwise(pts):
        n = max(1, math.ceil(math.dist(a, b) / step))
        out.extend((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1))
    return out


def _add_line(
    graph: RouteGraph, pts: list[Point], forward: tuple[float, str], backward: tuple[float, str], *, join: bool
) -> list[int]:
    """The line's vertices, joined forward and backward at their rates; with `join`, each joins the cell it is in."""
    nodes = [graph._vertex(p, *forward) for p in _densified(pts, graph.geo.grid.size_km / 2)]
    for u, v in pairwise(nodes):
        km = math.dist(graph.points[u], graph.points[v])
        graph._edge(u, v, km, *forward)
        graph._edge(v, u, km, *backward)
    if join:
        for u in nodes:
            cell = cell_at(graph.geo.grid, *graph.points[u])
            if cell is not None and graph.rate[cell] > 0:
                km = math.dist(graph.points[u], graph.points[cell])
                graph._edge(u, cell, km, graph.rate[cell], graph.what[cell], OFF_ROUTE)
                graph._edge(cell, u, km, graph.rate[cell], graph.what[cell], OFF_ROUTE)
    return nodes


def _join_water(graph: RouteGraph, node: int) -> None:
    """A river's end joins the lake or sea cell it reaches: its own, else the nearest within a cell."""
    p, grid = graph.points[node], graph.geo.grid
    cell = cell_at(grid, *p)
    if cell is None or graph.rate[cell] <= 0:
        near = [i for i in cells_within(grid, p, grid.size_km) if graph.rate[i] > 0]
        if not near:
            return
        cell = min(near, key=lambda i: math.dist(p, graph.points[i]))
    km = math.dist(p, graph.points[cell])
    graph._edge(node, cell, km, graph.rate[cell], graph.what[cell], OFF_ROUTE)
    graph._edge(cell, node, km, graph.rate[cell], graph.what[cell], OFF_ROUTE)


def _navigable(pts: list[Point], navigable_km: float) -> list[Point]:
    """The part of a river (source to mouth) within `navigable_km` of its mouth."""
    out = [pts[-1]]
    left = navigable_km
    for b, a in pairwise(reversed(pts)):
        d = math.dist(a, b)
        if d >= left:
            t = left / d if d else 0.0
            out.append((b[0] + (a[0] - b[0]) * t, b[1] + (a[1] - b[1]) * t))
            break
        out.append(a)
        left -= d
    return list(reversed(out))


def _join_confluences(graph: RouteGraph, rivers: list[list[int]]) -> None:
    """Two rivers join where a vertex of one is within half a cell of a vertex of the other."""
    grid = graph.geo.grid
    line_of: dict[int, int] = {}
    for k, nodes in enumerate(rivers):
        for u in nodes:
            line_of.setdefault(u, k)
    reach = grid.size_km / 2
    for k, nodes in enumerate(rivers):
        for u in nodes:
            p = graph.points[u]
            for cell in cells_within(grid, p, grid.size_km * 1.5):
                for v in graph.vertices_in.get(cell, ()):
                    if line_of.get(v, k) != k and math.dist(p, graph.points[v]) <= reach:
                        km = math.dist(p, graph.points[v])
                        graph._edge(u, v, km, graph.rules.downstream, "downstream")
                        graph._edge(v, u, km, graph.rules.downstream, "downstream")


def build_graph(geo: GeoMap, rules: ModeRules) -> RouteGraph:
    """The graph of `geo` for one mode. The callers cache it until the map changes."""
    grid = geo.grid
    centres = [cell_centre(grid, i) for i in range(grid.cells)]
    rates, whats = _cell_rates(geo, rules)
    graph = RouteGraph(geo, rules, list(centres), [[] for _ in centres], rates, whats)
    on_land = not graph.on_water
    blocked = _barrier_steps(geo, centres) if on_land and not rules.flies else set()
    _add_cell_steps(graph, centres, blocked)
    if on_land:
        for f in _lines(geo, "routes"):
            rate = float(rules.routes.get(f.kind, 0.0))
            if rate > 0:
                _add_line(graph, _coords(f), (rate, f.kind), (rate, f.kind), join=True)
        return graph
    rivers = []
    for f in _lines(geo, "water", ("river",)):
        pts = _coords(f)
        if rules.water == "sea":
            navigable = float(f.props.get("navigable_km") or 0.0)
            if navigable <= 0:
                continue
            pts = _navigable(pts, navigable)
            if len(pts) < 2:
                continue
        nodes = _add_line(graph, pts, (rules.downstream, "downstream"), (rules.upstream, "upstream"), join=False)
        _join_water(graph, nodes[0])
        _join_water(graph, nodes[-1])
        rivers.append(nodes)
    _join_confluences(graph, rivers)
    return graph


def _ends(graph: RouteGraph, p: Point, label: str) -> dict[int, Piece]:
    """The nodes an end snaps to, each with the piece that reaches it. On land, in a cell the mode crosses: that cell
    and its line vertices, at the cell's rate. Else (on water, or in a cell the mode can't cross): the nearest cell it
    may cross or line vertex, within a cell."""
    grid = graph.geo.grid
    size = grid.size_km
    cell = cell_at(grid, *p)
    if not graph.on_water and cell is not None and graph.rate[cell] > 0:
        rate, what = graph.rate[cell], graph.what[cell]
        return {
            node: (math.dist(p, graph.points[node]), rate, what) for node in (cell, *graph.vertices_in.get(cell, ()))
        }
    near = [i for i in cells_within(grid, p, size) if graph.rate[i] > 0]
    near += [
        v
        for i in cells_within(grid, p, size * 2)
        for v in graph.vertices_in.get(i, ())
        if math.dist(p, graph.points[v]) <= size
    ]
    if not near:
        raise NoRoute(_unsnapped(graph.rules, label))
    node = min(near, key=lambda n: (math.dist(p, graph.points[n]), n))
    return {node: (math.dist(p, graph.points[node]), graph.rate[node], graph.what[node])}


def _sentence(label: str) -> str:
    return label[:1].upper() + label[1:]


def _unsnapped(rules: ModeRules, label: str) -> str:
    if rules.water == "river" and not rules.flies:
        return f"{_sentence(label)} isn't on a river or a lake."
    if rules.water == "sea" and not rules.flies:
        return f"{_sentence(label)} isn't on the sea, a large lake or a navigable river."
    words = MODE_WORDS.get(rules.mode, rules.mode)
    return f"{_sentence(label)} lies in water or land that can't be crossed {words}."


def _pieces(graph: RouteGraph, u: int, v: int) -> tuple[Piece, ...]:
    known = graph.edges.get((u, v))
    if known is not None:
        return known
    d = math.dist(graph.points[u], graph.points[v]) / 2
    return ((d, graph.rate[u], graph.what[u]), (d, graph.rate[v], graph.what[v]))


def _route(points: list[Point], pieces: list[Piece]) -> GeoRoute:
    kept = [points[0]]
    for p in points[1:]:
        if p != kept[-1]:
            kept.append(p)
    stretches: list[Stretch] = []
    at = 0.0
    for km, rate, what in pieces:
        if km <= 1e-12:
            continue
        last = stretches[-1] if stretches else None
        if last is not None and last.rate == rate and last.what == what:
            stretches[-1] = Stretch(last.km + km, rate, what, last.start_km)
        else:
            stretches.append(Stretch(km, rate, what, at))
        at += km
    if not stretches and pieces:
        stretches.append(Stretch(0.0, pieces[0][1], pieces[0][2], 0.0))
    return GeoRoute(tuple(kept), at, sum(s.km / s.rate for s in stretches if s.km), tuple(stretches))


def plan(
    graph: RouteGraph,
    start: Point,
    goal: Point,
    *,
    start_label: str = "the start",
    goal_label: str = "the destination",
) -> GeoRoute:
    """The cheapest route from `start` to `goal`, A* over the graph with the straight line at the fastest rate.

    Both ends snap to the graph within a cell (`_ends`). `NoRoute` names the end that doesn't snap, or the mode when
    nothing joins them; the labels name the ends in its reason."""
    start, goal = (float(start[0]), float(start[1])), (float(goal[0]), float(goal[1]))
    grid = graph.geo.grid
    cell = cell_at(grid, *start)
    if not graph.on_water and cell is not None and graph.rate[cell] > 0 and cell == cell_at(grid, *goal):
        km = math.dist(start, goal)
        return _route([start, goal], [(km, graph.rate[cell], graph.what[cell])])
    starts = _ends(graph, start, start_label)
    goals = _ends(graph, goal, goal_label)
    points, adj, fastest = graph.points, graph.adj, graph.fastest
    gx, gy = goal
    best = [math.inf] * len(points)
    prev = [-1] * len(points)
    heap: list[tuple[float, float, int]] = []
    for node, (km, rate, _) in starts.items():
        best[node] = km / rate * OFF_ROUTE
        x, y = points[node]
        heapq.heappush(heap, (best[node] + math.hypot(x - gx, y - gy) / fastest, best[node], node))
    arrived, last = math.inf, -1
    while heap:
        f, d, u = heapq.heappop(heap)
        if f >= arrived:
            break
        if d > best[u]:
            continue
        end = goals.get(u)
        if end is not None and d + end[0] / end[1] * OFF_ROUTE < arrived:
            arrived, last = d + end[0] / end[1] * OFF_ROUTE, u
        for v, w in adj[u]:
            nd = d + w
            if nd < best[v]:
                best[v] = nd
                prev[v] = u
                x, y = points[v]
                heapq.heappush(heap, (nd + math.hypot(x - gx, y - gy) / fastest, nd, v))
    if last < 0:
        words = MODE_WORDS.get(graph.rules.mode, graph.rules.mode)
        raise NoRoute(f"No way leads from {start_label} to {goal_label} {words}.")
    path = [last]
    while prev[path[-1]] >= 0:
        path.append(prev[path[-1]])
    path.reverse()
    pieces = [starts[path[0]]]
    for u, v in pairwise(path):
        pieces.extend(_pieces(graph, u, v))
    pieces.append(goals[last])
    return _route([start, *(points[n] for n in path), goal], pieces)


def point_along(route: GeoRoute, km: float) -> Point:
    """The point `km` along the route's line, its ends beyond them."""
    pts = route.points
    if km <= 0 or len(pts) == 1:
        return pts[0]
    for a, b in pairwise(pts):
        d = math.dist(a, b)
        if km <= d:
            t = km / d if d else 0.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        km -= d
    return pts[-1]


def stretch_at(route: GeoRoute, km: float) -> Stretch:
    """The stretch `km` along the route lies in; the last one beyond its end."""
    for s in route.stretches:
        if km < s.start_km + s.km:
            return s
    return route.stretches[-1]


def slowest(route: GeoRoute, n: int = 3) -> list[Stretch]:
    """The route's `n` slowest stretches, the longest first among equals."""
    return sorted(route.stretches, key=lambda s: (s.rate, -s.km))[:n]
