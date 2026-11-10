"""Geometry-preserving simplification of corridor and room outlines.

`simplify(source)` returns a rewritten source plus a list of the changes it
made. Every applied change leaves what the renderer draws unchanged — the
floor footprint, the walls, the dead-end caps, and where doors attach — so
the button is safe to press on any map:

Corridors (`node` / `run` form, and explicit `segment line`s)
  collinear-node      a node joining exactly two runs that continue in a
                      straight line → one run (`a–m–b` → `a–b`)
  duplicate-node      two nodes at the same point → one
  duplicate-run       the same run twice → once
  zero-run            a run from a point to itself
  covered-spur        a dead-end stub no longer than half the width, lying
                      inside a straight stretch of the same corridor (its
                      floor is already drawn by that stretch); often freeing
                      the junction it hung off for a collinear-node merge
  unused-node         a node no run uses
  collinear-segment   two `segment line`s continuing in a straight line

Rooms
  collinear-point     a polygon vertex on the straight line between its
                      neighbours (the classic "points on the same line")
  duplicate-point     a polygon vertex repeating the previous one
  collinear-edge      a boundary `line to` whose next straight edge carries
                      on in the same direction

What is deliberately *not* touched, because it would change the drawing:

- a covered spur whose free end has a door or exit at it — the door uses
  that end as the corridor's mouth (and the fog-of-war fade starts there).
  Reported as a suggestion. `door_spurs=True` removes it anyway and lets
  doors re-anchor: their fog fade then starts at the nearest remaining
  corridor end instead (the map itself still draws the same);
- any node whose removal would change which corridor endpoint a connected
  door is nearest to (the fog fade stub is anchored there);
- rooms and zero-width corridors drawn dashed/dotted/ruined/trail — their
  dash pattern restarts per wall/segment, so merging would shift it;
- arcs, rect and circle rooms.

Nodes are self-contained within their corridor, so renaming or dropping
one can't break a reference elsewhere. One visible side effect remains:
a room's or corridor's *vertex-average* centre (where an unpositioned
label or the party marker goes) can shift when vertices are dropped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from lark import Token, Tree

from .errors import DmapParseError
from .model import ArcSegment, DungeonMap, LineSegment
from .parser import _get_parser, _strip_string, parse

Vec2 = tuple[float, float]
_EPS = 1e-6
# Wall styles whose dash pattern restarts per wall piece / segment.
_PATTERNED = {"ruined", "dotted", "dashed", "trail"}


@dataclass
class Change:
    kind: str
    target: str          # "corridor.c97" / "room.hall"
    message: str
    line: int
    applied: bool = True  # False: a suggestion that was left alone

    def as_dict(self) -> dict:
        return {"kind": self.kind, "target": self.target, "message": self.message,
                "line": self.line, "applied": self.applied}


@dataclass
class SimplifyResult:
    source: str
    changes: list[Change] = field(default_factory=list)
    # target -> {"nodes"|"segments"|"points": {"before": n, "after": m}}
    stats: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return any(c.applied for c in self.changes)

    def as_dict(self) -> dict:
        return {"source": self.source, "changed": self.changed,
                "changes": [c.as_dict() for c in self.changes], "stats": self.stats}


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------

def _same(p: Vec2, q: Vec2) -> bool:
    return abs(p[0] - q[0]) <= _EPS and abs(p[1] - q[1]) <= _EPS


def _straight_through(a: Vec2, m: Vec2, b: Vec2) -> bool:
    """`m` lies strictly between `a` and `b` on the segment a–b."""
    ax, ay = a[0] - m[0], a[1] - m[1]
    bx, by = b[0] - m[0], b[1] - m[1]
    la, lb = math.hypot(ax, ay), math.hypot(bx, by)
    if la <= _EPS or lb <= _EPS:
        return False
    cross = abs(ax * by - ay * bx) / (la * lb)
    dot = (ax * bx + ay * by) / (la * lb)
    return cross <= 1e-9 and dot < 0


def _arc_end(s: ArcSegment, deg: float) -> Vec2:
    a = math.radians(deg)
    return (s.center[0] + s.radius * math.cos(a), s.center[1] + s.radius * math.sin(a))


def _fmt(v: float) -> str:
    i = int(v)
    return str(i) if v == i else repr(v)


# ---------------------------------------------------------------------------
# source edits
# ---------------------------------------------------------------------------

class _Edits:
    def __init__(self, text: str):
        self.text = text
        self.ops: list[tuple[int, int, str]] = []

    def replace(self, start: int, end: int, new: str) -> None:
        self.ops.append((start, end, new))

    def delete_stmt(self, start: int, end: int) -> None:
        """Remove a statement; take its whole line when it's alone on it
        (a trailing `# comment` belongs to the statement and goes too)."""
        t = self.text
        ls = t.rfind("\n", 0, start) + 1
        le = t.find("\n", end)
        le = len(t) if le < 0 else le
        rest = t[end:le].strip()
        if t[ls:start].strip() == "" and (rest == "" or rest.startswith("#")):
            self.ops.append((ls, min(le + 1, len(t)), ""))
            return
        # Shared line: eat the whitespace after (or, at a line end, before).
        e = end
        while e < len(t) and t[e] in " \t":
            e += 1
        if e < len(t) and t[e] not in "\n}":
            self.ops.append((start, e, ""))
            return
        s = start
        while s > ls and t[s - 1] in " \t":
            s -= 1
        self.ops.append((s, end, ""))

    def delete_inline(self, start: int, end: int) -> None:
        """Remove an inline item (a polygon point) and one adjoining run of
        spaces, keeping its neighbours separated."""
        t = self.text
        s = start
        while s > 0 and t[s - 1] in " \t":
            s -= 1
        if s < start and t[s - 1:s] not in ("", "\n"):
            self.ops.append((s, end, ""))
            return
        e = end
        while e < len(t) and t[e] in " \t":
            e += 1
        self.ops.append((start, e, ""))

    def apply(self) -> str:
        out = self.text
        for start, end, new in sorted(self.ops, key=lambda o: o[0], reverse=True):
            out = out[:start] + new + out[end:]
        return out


# ---------------------------------------------------------------------------
# model lookups
# ---------------------------------------------------------------------------

def _all_corridors(dmap: DungeonMap) -> dict:
    out = dict(dmap.corridors)
    for layer in dmap.layers:
        for c in layer.corridors:
            out.setdefault(c.name, c)
    return out


def _all_rooms(dmap: DungeonMap) -> dict:
    out = dict(dmap.rooms)
    for layer in dmap.layers:
        for r in layer.rooms:
            out.setdefault(r.name, r)
    return out


def _connectors(dmap: DungeonMap) -> tuple[list[Vec2], list[tuple[Vec2, list[str]]]]:
    """(every door + exit position, [(door position, connects)])."""
    doors = list(dmap.doors)
    exits = list(dmap.exits)
    for layer in dmap.layers:
        doors += list(layer.doors)
        exits += list(getattr(layer, "exits", []) or [])
    for r in _all_rooms(dmap).values():
        exits += list(getattr(r, "exits", []) or [])
    for c in _all_corridors(dmap).values():
        exits += list(c.exits)
    pts = [d.position for d in doors] + [e.position for e in exits]
    return pts, [(d.position, list(d.connects)) for d in doors]


# ---------------------------------------------------------------------------
# corridors
# ---------------------------------------------------------------------------

@dataclass
class _Run:
    a: str
    b: str
    meta: Any | None      # None for a run created by a merge
    origin: int           # source order, for placing merged runs
    dirty: bool = False


class _CorridorJob:
    def __init__(self, tree: Tree, model, connectors, doors, edits: _Edits,
                 changes: list[Change], door_spurs: bool):
        self.tree, self.model, self.edits, self.changes = tree, model, edits, changes
        self.name = _strip_string(tree.children[0])
        self.target = f"corridor.{self.name}"
        self.half = (model.width if model else 1.0) / 2.0
        self.connectors = connectors
        self.my_doors = [p for p, refs in doors if self.target in refs]
        self.door_spurs = door_spurs
        self.nodes: dict[str, Vec2] = {}
        self.node_meta: dict[str, Any] = {}
        self.runs: list[_Run] = []
        self.segs: list[dict] = []   # explicit `segment line`s
        self.arc_ends: list[Vec2] = []
        for i, ch in enumerate(tree.children):
            if not isinstance(ch, Tree):
                continue
            if ch.data == "corridor_node":
                nm, x, y = ch.children
                self.nodes[str(nm)] = (float(x), float(y))
                self.node_meta[str(nm)] = ch.meta
            elif ch.data == "corridor_run":
                self.runs.append(_Run(str(ch.children[0]), str(ch.children[1]), ch.meta, i))
            elif ch.data == "segment_decl":
                seg = ch.children[0]
                if isinstance(seg, Tree) and seg.data == "line_segment":
                    t = [str(v) for v in seg.children]
                    self.segs.append({"a": (float(t[0]), float(t[1])), "b": (float(t[2]), float(t[3])),
                                      "at": t[0:2], "bt": t[2:4], "meta": ch.meta, "origin": i,
                                      "dirty": False, "alive": True})
        if model is not None:
            for s in model.segments:
                if isinstance(s, ArcSegment):
                    self.arc_ends += [_arc_end(s, s.from_angle), _arc_end(s, s.to_angle)]
        self.removed_nodes: list[str] = []
        self.removed_runs: list[_Run] = []
        self.before = (len(self.nodes), len(self.runs) + len(self.segs))

    # -- state queries ----------------------------------------------------

    def line_ends(self) -> list[tuple[Vec2, Vec2]]:
        out = [(self.nodes[r.a], self.nodes[r.b]) for r in self.runs]
        out += [(s["a"], s["b"]) for s in self.segs if s["alive"]]
        return out

    def degree(self, p: Vec2) -> int:
        n = sum(1 for q in self.arc_ends if _same(p, q))
        for a, b in self.line_ends():
            n += _same(a, p) + _same(b, p)
        return n

    def anchors(self) -> tuple:
        """Per connected door: the endpoints nearest to it (what the fog
        fade stub and the door-mouth logic anchor on)."""
        pts = [p for ab in self.line_ends() for p in ab]
        sig = []
        for d in self.my_doors:
            if not pts:
                sig.append(())
                continue
            best = min(math.hypot(p[0] - d[0], p[1] - d[1]) for p in pts)
            near = {(round(p[0], 6), round(p[1], 6)) for p in pts
                    if math.hypot(p[0] - d[0], p[1] - d[1]) <= best + 1e-9}
            sig.append(tuple(sorted(near)))
        return tuple(sig)

    def connector_near(self, p: Vec2) -> bool:
        tol = max(self.half, 0.5) + 0.25
        return any(math.hypot(c[0] - p[0], c[1] - p[1]) <= tol for c in self.connectors)

    def runs_at(self, name: str) -> list[_Run]:
        return [r for r in self.runs if r.a == name or r.b == name]

    def line(self, meta) -> int:
        return getattr(meta, "line", 0) or 0

    def note(self, kind: str, msg: str, meta, applied: bool = True) -> None:
        self.changes.append(Change(kind, self.target, msg, self.line(meta), applied))

    # -- passes -----------------------------------------------------------

    def patterned(self) -> bool:
        m = self.model
        return bool(m and m.width <= 0 and (m.line_style or "") in _PATTERNED | {"organic"})

    def pass_duplicate_nodes(self) -> bool:
        seen: dict[tuple, str] = {}
        changed = False
        for nm in list(self.nodes):
            key = (round(self.nodes[nm][0], 6), round(self.nodes[nm][1], 6))
            keep = seen.get(key)
            if keep is None:
                seen[key] = nm
                continue
            for r in self.runs:
                if r.a == nm:
                    r.a, r.dirty = keep, True
                if r.b == nm:
                    r.b, r.dirty = keep, True
            self._drop_node(nm)
            self.note("duplicate-node", f"node {nm} sits on {keep}; merged into it",
                      self.node_meta.get(nm))
            changed = True
        return changed

    def _keeps_caps(self, p: Vec2, removed_ends: int) -> bool:
        before = self.degree(p)
        after = before - removed_ends
        return (before == 1) == (after == 1)

    def pass_zero_and_duplicate_runs(self) -> bool:
        changed = False
        seen: set[frozenset] = set()
        for r in list(self.runs):
            pa, pb = self.nodes[r.a], self.nodes[r.b]
            if _same(pa, pb):
                if self._keeps_caps(pa, 2) and self._try(lambda r=r: self._remove_run(r)):
                    self.note("zero-run", f"run {r.a} to {r.b} has no length", r.meta)
                    changed = True
                continue
            key = frozenset((r.a, r.b))
            if key in seen:
                if (self._keeps_caps(pa, 1) and self._keeps_caps(pb, 1)
                        and self._try(lambda r=r: self._remove_run(r))):
                    self.note("duplicate-run", f"run {r.a} to {r.b} is repeated", r.meta)
                    changed = True
                continue
            seen.add(key)
        return changed

    def pass_covered_spurs(self) -> bool:
        if self.half <= 0:
            return False
        changed = False
        for leaf in list(self.nodes):
            rs = self.runs_at(leaf)
            lp = self.nodes.get(leaf)
            if lp is None or len(rs) != 1 or self.degree(lp) != 1:
                continue
            spur = rs[0]
            j = spur.b if spur.a == leaf else spur.a
            jp = self.nodes[j]
            L = math.hypot(lp[0] - jp[0], lp[1] - jp[1])
            if L <= _EPS or L > self.half + _EPS:
                continue
            if not self._covered_at(j, spur, (lp[0] - jp[0]) / L, (lp[1] - jp[1]) / L, L):
                continue
            if self.connector_near(lp):
                if not self.door_spurs:
                    if not any(c.kind == "covered-spur" and c.target == self.target
                               and leaf in c.message and not c.applied for c in self.changes):
                        self.note("covered-spur",
                                  f"spur {j} to {leaf} lies inside the corridor, but a door/exit "
                                  f"at {_fmt(lp[0])},{_fmt(lp[1])} uses it as the corridor's "
                                  f"end — kept (door_spurs removes it)", spur.meta, applied=False)
                    continue
                self._remove_run(spur)
                self._drop_node(leaf)
            elif not self._try(lambda: (self._remove_run(spur), self._drop_node(leaf))):
                continue
            self.note("covered-spur",
                      f"spur {j} to {leaf} lies inside the corridor's straight stretch; removed",
                      spur.meta)
            changed = True
        return changed

    def _covered_at(self, j: str, spur: _Run, ux: float, uy: float, L: float) -> bool:
        """Is the spur's band inside a straight stretch passing through j?"""
        jp = self.nodes[j]
        others = [r for r in self.runs_at(j) if r is not spur]
        for i in range(len(others)):
            for k in range(i + 1, len(others)):
                p = self.nodes[others[i].b if others[i].a == j else others[i].a]
                q = self.nodes[others[k].b if others[k].a == j else others[k].a]
                if not _straight_through(p, jp, q):
                    continue
                dx, dy = p[0] - jp[0], p[1] - jp[1]
                lp = math.hypot(dx, dy)
                dx, dy = dx / lp, dy / lp
                lq = math.hypot(q[0] - jp[0], q[1] - jp[1])
                along = abs(ux * dx + uy * dy) * L
                need = self.half + along
                if lp + _EPS >= need and lq + _EPS >= need:
                    return True
        return False

    def pass_collinear_nodes(self) -> bool:
        if self.patterned():
            return False
        changed = False
        for m in list(self.nodes):
            if m not in self.nodes:
                continue
            rs = self.runs_at(m)
            mp = self.nodes[m]
            if len(rs) != 2 or self.degree(mp) != 2:
                continue
            r1, r2 = rs
            a = r1.b if r1.a == m else r1.a
            b = r2.b if r2.a == m else r2.a
            if a == b or not _straight_through(self.nodes[a], mp, self.nodes[b]):
                continue
            first, second = (r1, r2) if r1.origin <= r2.origin else (r2, r1)
            start = (first.a if first.b == m else first.b)
            end = (second.b if second.a == m else second.a)

            def merge(first=first, second=second, start=start, end=end, m=m):
                self._remove_run(second)
                first.a, first.b, first.dirty = start, end, True
                self._drop_node(m)

            snapshot = (first.a, first.b, first.dirty)
            if self._try(merge, undo=lambda f=first, s=snapshot: self._undo_merge(f, s)):
                self.note("collinear-node",
                          f"node {m} is on the straight line {start}–{end}; runs merged",
                          self.node_meta.get(m))
                changed = True
        return changed

    def pass_collinear_segments(self) -> bool:
        if self.patterned():
            return False
        changed = False
        for s1 in [s for s in self.segs if s["alive"]]:
            for s2 in [s for s in self.segs if s["alive"] and s is not s1]:
                if not (s1["alive"] and s2["alive"]):
                    continue
                if _same(s1["b"], s2["a"]):
                    mid, a, b, at, bt = s1["b"], s1["a"], s2["b"], s1["at"], s2["bt"]
                elif _same(s1["b"], s2["b"]):
                    mid, a, b, at, bt = s1["b"], s1["a"], s2["a"], s1["at"], s2["at"]
                else:
                    continue
                if self.degree(mid) != 2 or not _straight_through(a, mid, b):
                    continue
                first, second = (s1, s2) if s1["origin"] <= s2["origin"] else (s2, s1)
                saved = (dict(first), dict(second))

                def merge(first=first, second=second, a=a, b=b, at=at, bt=bt):
                    second["alive"] = False
                    first.update(a=a, b=b, at=at, bt=bt, dirty=True)

                def undo(first=first, second=second, saved=saved):
                    first.clear(); first.update(saved[0])
                    second.clear(); second.update(saved[1])

                if self._try(merge, undo=undo):
                    self.note("collinear-segment",
                              f"segments meeting at {_fmt(mid[0])},{_fmt(mid[1])} continue "
                              f"straight; merged", first["meta"])
                    changed = True
        return changed

    def pass_unused_nodes(self) -> None:
        used = {r.a for r in self.runs} | {r.b for r in self.runs}
        for nm in list(self.nodes):
            if nm not in used:
                self._drop_node(nm)
                self.note("unused-node", f"node {nm} is not used by any run",
                          self.node_meta.get(nm))

    # -- mutation with an anchor guard ------------------------------------

    def _remove_run(self, r: _Run) -> None:
        self.runs.remove(r)
        self.removed_runs.append(r)

    def _drop_node(self, nm: str) -> None:
        self.nodes.pop(nm, None)
        self.removed_nodes.append(nm)

    def _undo_merge(self, first: _Run, snapshot) -> None:
        first.a, first.b, first.dirty = snapshot

    def _try(self, fn, undo=None) -> bool:
        """Apply `fn`; keep it only if every connected door still anchors
        on the same corridor endpoints. `door_spurs` is the caller's opt-in
        to doors re-anchoring, so the guard steps aside then."""
        if self.door_spurs:
            fn()
            return True
        before = self.anchors()
        state = (dict(self.nodes), list(self.runs), list(self.removed_runs),
                 list(self.removed_nodes))
        fn()
        if self.anchors() == before:
            return True
        if undo is not None:
            undo()
        self.nodes, self.runs, self.removed_runs, self.removed_nodes = (
            state[0], state[1], state[2], state[3])
        return False

    # -- driver -----------------------------------------------------------

    def run(self) -> dict[str, dict[str, int]]:
        while True:
            progressed = False
            progressed |= self.pass_duplicate_nodes()
            progressed |= self.pass_zero_and_duplicate_runs()
            progressed |= self.pass_covered_spurs()
            progressed |= self.pass_collinear_nodes()
            progressed |= self.pass_collinear_segments()
            if not progressed:
                break
        if self.runs or self.removed_runs:
            self.pass_unused_nodes()
        self.write()
        after = (len(self.nodes), len(self.runs) + sum(s["alive"] for s in self.segs))
        return {"nodes": {"before": self.before[0], "after": after[0]},
                "segments": {"before": self.before[1], "after": after[1]}}

    def write(self) -> None:
        live = {id(r) for r in self.runs}
        for nm in set(self.removed_nodes):
            meta = self.node_meta.get(nm)
            if meta is not None:
                self.edits.delete_stmt(meta.start_pos, meta.end_pos)
        for r in self.removed_runs:
            if r.meta is not None and id(r) not in live:
                self.edits.delete_stmt(r.meta.start_pos, r.meta.end_pos)
        for r in self.runs:
            if r.dirty and r.meta is not None:
                self.edits.replace(r.meta.start_pos, r.meta.end_pos, f"run {r.a} to {r.b}")
        for s in self.segs:
            if not s["alive"]:
                self.edits.delete_stmt(s["meta"].start_pos, s["meta"].end_pos)
            elif s["dirty"]:
                self.edits.replace(
                    s["meta"].start_pos, s["meta"].end_pos,
                    f"segment line from {s['at'][0]},{s['at'][1]} to {s['bt'][0]},{s['bt'][1]}")


# ---------------------------------------------------------------------------
# rooms
# ---------------------------------------------------------------------------

def _simplify_polygon(shape: Tree, target: str, edits: _Edits, changes: list[Change]) -> tuple[int, int]:
    pts = [c for c in shape.children if isinstance(c, Tree) and c.data == "point"]
    coords = [(float(p.children[0]), float(p.children[1])) for p in pts]
    alive = list(range(len(pts)))
    before = len(pts)

    def note(kind, msg, i):
        changes.append(Change(kind, target, msg, pts[i].meta.line or 0))

    i = 0
    while i < len(alive) and len(alive) > 3:   # consecutive duplicates, cyclic
        cur, nxt = alive[i], alive[(i + 1) % len(alive)]
        if _same(coords[cur], coords[nxt]):
            alive.remove(nxt)
            note("duplicate-point", f"point {_fmt(coords[nxt][0])},{_fmt(coords[nxt][1])} "
                 f"repeats the previous one", nxt)
            continue
        i += 1
    progressed = True
    while progressed and len(alive) > 3:
        progressed = False
        for k in range(len(alive)):
            if len(alive) <= 3:
                break
            p, m, n = alive[k - 1], alive[k], alive[(k + 1) % len(alive)]
            if _straight_through(coords[p], coords[m], coords[n]):
                alive.remove(m)
                note("collinear-point", f"point {_fmt(coords[m][0])},{_fmt(coords[m][1])} "
                     f"is on the straight wall between its neighbours", m)
                progressed = True
                break
    for idx in range(len(pts)):
        if idx not in alive:
            edits.delete_inline(pts[idx].meta.start_pos, pts[idx].meta.end_pos)
    return before, len(alive)


def _simplify_boundary(shape: Tree, target: str, edits: _Edits, changes: list[Change]) -> tuple[int, int]:
    items = [c for c in shape.children if isinstance(c, Tree)]
    starts = [c for c in items if c.data == "boundary_start"]
    if len(starts) != 1 or items[0] is not starts[0]:
        return 0, 0
    start = (float(starts[0].children[0]), float(starts[0].children[1]))
    edges = [{"tree": c, "kind": "line" if c.data == "boundary_line" else "arc",
              "end": (float(c.children[0]), float(c.children[1])), "alive": True}
             for c in items[1:] if c.data in ("boundary_line", "boundary_arc")]
    before = len(edges) + 1
    progressed = True
    while progressed:
        progressed = False
        live = [e for e in edges if e["alive"]]
        for k, e in enumerate(live):
            if e["kind"] != "line" or len(live) <= 2:
                continue
            prev = live[k - 1]["end"] if k > 0 else start
            if k + 1 < len(live):
                nxt = live[k + 1]
                if nxt["kind"] != "line":
                    continue
                nxt_pt = nxt["end"]
            else:
                nxt_pt = start     # the implicit closing line
                if _same(e["end"], start):
                    continue
            if _straight_through(prev, e["end"], nxt_pt):
                e["alive"] = False
                changes.append(Change(
                    "collinear-edge", target,
                    f"line to {_fmt(e['end'][0])},{_fmt(e['end'][1])} continues straight; "
                    f"merged with the next edge", e["tree"].meta.line or 0))
                progressed = True
                break
    for e in edges:
        if not e["alive"]:
            edits.delete_stmt(e["tree"].meta.start_pos, e["tree"].meta.end_pos)
    return before, sum(e["alive"] for e in edges) + 1


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def simplify(
    text: str,
    *,
    include_sources: Mapping[str, str] | None = None,
    path: str | None = None,
    include_root: str | Path | None = None,
    door_spurs: bool = False,
) -> SimplifyResult:
    """Simplify every corridor and room declared in `text` (not in its
    includes). `path`, `include_sources` and `include_root` resolve includes
    as in `parse()`.
    Raises DmapParseError if the source doesn't parse."""
    dmap = parse(text, include_sources=include_sources, path=path, include_root=include_root)
    tree = _get_parser().parse(text)
    corridors, rooms = _all_corridors(dmap), _all_rooms(dmap)
    connectors, doors = _connectors(dmap)
    edits = _Edits(text)
    result = SimplifyResult(source=text)

    blocks = sorted(
        (t for t in tree.iter_subtrees() if t.data in ("corridor", "room")),
        key=lambda t: t.meta.start_pos,
    )
    for t in blocks:
        name = _strip_string(t.children[0])
        if t.data == "corridor":
            job = _CorridorJob(t, corridors.get(name), connectors, doors, edits,
                               result.changes, door_spurs)
            if not (job.nodes or job.segs):
                continue
            counts = job.run()
            if any(v["before"] != v["after"] for v in counts.values()):
                result.stats[job.target] = counts
            continue
        room = rooms.get(name)
        if room is not None and (room.line_style or "") in _PATTERNED:
            continue
        target = f"room.{name}"
        for shape in t.children:
            if not isinstance(shape, Tree):
                continue
            if shape.data == "polygon_room":
                before, after = _simplify_polygon(shape, target, edits, result.changes)
            elif shape.data == "boundary_room":
                before, after = _simplify_boundary(shape, target, edits, result.changes)
            else:
                continue
            if before != after:
                result.stats[target] = {"points": {"before": before, "after": after}}

    result.source = edits.apply()
    if result.changed:
        # The rewrite must still parse — a bug here must never hand back a
        # broken map.
        try:
            parse(result.source, include_sources=include_sources, path=path,
                  include_root=include_root)
        except DmapParseError as e:  # pragma: no cover - defensive
            raise DmapParseError(f"simplify produced an unparsable map: {e}") from e
    return result


__all__ = ["Change", "SimplifyResult", "simplify"]
