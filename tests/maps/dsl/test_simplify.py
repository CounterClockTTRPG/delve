"""Geometry-preserving simplification (dungml.simplify).

Besides case-by-case checks, the footprint tests sample a grid and assert
every corridor's and room's floor covers exactly the same points before and
after — the "the drawing doesn't change" promise, checked numerically.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from delve.maps.dsl import parse
from delve.maps.dsl.geometry import corridor_polygons, room_polygon
from delve.maps.dsl.model import LineSegment
from delve.maps.dsl.simplify import simplify
from tests.fixtures import SAMPLES


C97 = """map "M" { grid { bounds 20 x 30 } }
corridor "c97" {
  width 1
  node n1 at 7,19.5
  node n2 at 7.5,19.5
  node n3 at 8,19.5
  node n4 at 7.5,22.5
  node n5 at 7,22.5
  node n6 at 7.5,24.5
  node n7 at 8,24.5
  node n8 at 7.5,25.5
  node n9 at 7,25.5
  run n1 to n2
  run n2 to n3
  run n2 to n4
  run n4 to n5
  run n4 to n6
  run n6 to n7
  run n6 to n8
  run n8 to n9
}
"""
DOORS = """
room "w" { rect 2,18 5 x 9 }
room "e" { rect 8,18 5 x 9 }
door at 7,22.5 { connects room.w, corridor.c97 }
door at 8,24.5 { connects room.e, corridor.c97 }
"""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _inside(pt, poly) -> bool:
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def _all_corridors(m):
    out = dict(m.corridors)
    for layer in m.layers:
        out.update({c.name: c for c in layer.corridors})
    return out


def _all_rooms(m):
    out = dict(m.rooms)
    for layer in m.layers:
        out.update({r.name: r for r in layer.rooms})
    return out


def _grid(m, step=0.23):
    g = m.map.grid
    W, H = (getattr(g, "bounds_w", None) or 60), (getattr(g, "bounds_h", None) or 60)
    # An odd step keeps sample points off the integer/half-integer edges.
    return [(0.07 + i * step, 0.11 + j * step)
            for i in range(int(W / step) + 1) for j in range(int(H / step) + 1)]


def _footprints(src: str) -> dict:
    m = parse(src)
    grid = _grid(m)
    out = {}
    for name, c in _all_corridors(m).items():
        polys = corridor_polygons(c)
        out[f"corridor.{name}"] = frozenset(p for p in grid if any(_inside(p, q) for q in polys))
    for name, r in _all_rooms(m).items():
        poly = room_polygon(r)
        out[f"room.{name}"] = frozenset(p for p in grid if _inside(p, poly))
    return out


def _dead_ends(src: str, name: str) -> set:
    c = _all_corridors(parse(src))[name]
    ends = [p for s in c.segments if isinstance(s, LineSegment) for p in (s.start, s.end)]
    return {p for p in ends if sum(1 for q in ends if math.dist(p, q) < 1e-6) == 1}


def _nodes(src: str, name: str) -> dict:
    return _all_corridors(parse(src))[name].nodes


# ---------------------------------------------------------------------------
# the c97 example
# ---------------------------------------------------------------------------

def test_c97_without_doors_drops_covered_spurs_and_merges_the_spine():
    r = simplify(C97)
    assert r.stats == {"corridor.c97": {"nodes": {"before": 9, "after": 5},
                                         "segments": {"before": 8, "after": 4}}}
    assert set(_nodes(r.source, "c97")) == {"n1", "n2", "n3", "n8", "n9"}
    assert "run n2 to n8" in r.source
    assert [c.kind for c in r.changes] == ["covered-spur", "covered-spur",
                                           "collinear-node", "collinear-node"]
    assert _footprints(r.source) == _footprints(C97)
    # Only the two removed spurs' (blemish) caps go; every real end stays.
    assert _dead_ends(C97, "c97") - _dead_ends(r.source, "c97") == {(7.0, 22.5), (8.0, 24.5)}


def test_c97_keeps_spurs_a_door_uses_and_says_why():
    r = simplify(C97 + DOORS)
    assert not r.changed and r.source == C97 + DOORS
    kept = [c for c in r.changes if not c.applied]
    assert len(kept) == 2 and all("door" in c.message for c in kept)


def test_c97_door_spurs_opt_in():
    r = simplify(C97 + DOORS, door_spurs=True)
    assert r.stats["corridor.c97"]["nodes"] == {"before": 9, "after": 5}
    assert _footprints(r.source) == _footprints(C97 + DOORS)


# ---------------------------------------------------------------------------
# corridor rules
# ---------------------------------------------------------------------------

def _corr(body: str, extra: str = "") -> str:
    return f'map "M" {{ grid {{ bounds 30 x 30 }} }}\ncorridor "c" {{\n{body}}}\n{extra}'


def test_collinear_chain_merges_but_a_bend_does_not():
    src = _corr("  width 2\n  node a at 2,5\n  node m at 8,5\n  node b at 14,5\n"
                "  node c at 14,12\n  run a to m\n  run m to b\n  run b to c\n")
    r = simplify(src)
    assert set(_nodes(r.source, "c")) == {"a", "b", "c"}
    assert "run a to b" in r.source and "node m" not in r.source
    assert _footprints(r.source) == _footprints(src)


def test_door_beside_a_node_keeps_it():
    """The fog fade starts at the corridor endpoint nearest the door."""
    src = _corr("  width 1\n  node a at 0,5\n  node m at 5,5\n  node b at 10,5\n"
                "  run a to m\n  run m to b\n",
                'room "r" { rect 3,6 4 x 4 }\ndoor at 5,5.5 { connects room.r, corridor.c }\n')
    assert not simplify(src).changed
    assert simplify(src, door_spurs=True).changed


def test_duplicates_zero_runs_and_unused_nodes():
    # An L (a-b-c) plus a branch b-d; the repeated run and the zero run sit
    # at the junction b, where dropping them changes no cap.
    src = _corr("  width 1\n  node a at 1,1\n  node b at 6,1\n  node b2 at 6,1\n"
                "  node c at 6,6\n  node e at 12,6\n  node d at 11,1\n  node lone at 20,20\n"
                "  run a to b\n  run b2 to c\n  run c to b\n  run c to e\n  run b to d\n"
                "  run b to b\n")
    r = simplify(src)
    kinds = sorted(c.kind for c in r.changes)
    assert kinds == ["duplicate-node", "duplicate-run", "unused-node", "zero-run"]
    assert set(_nodes(r.source, "c")) == {"a", "b", "c", "d", "e"}
    assert _footprints(r.source) == _footprints(src)


def test_runs_that_hide_a_dead_end_cap_stay():
    """A duplicate or zero-length run at a dead end suppresses its wall cap;
    removing it would draw one, so it's left alone."""
    src = _corr("  width 1\n  node a at 1,1\n  node b at 6,1\n"
                "  run a to b\n  run b to a\n  run a to a\n")
    r = simplify(src)
    # The zero run can go (a still has two ends, still no cap); the
    # repeated run can't (a and b would each become a capped dead end).
    assert [c.kind for c in r.changes] == ["zero-run"]
    assert _dead_ends(r.source, "c") == _dead_ends(src, "c") == set()


def test_explicit_line_segments_merge():
    src = _corr("  width 1\n  segment line from 1,1 to 4,1\n  segment line from 4,1 to 9,1\n"
                "  segment line from 9,1 to 9,5\n")
    r = simplify(src)
    assert [c.kind for c in r.changes] == ["collinear-segment"]
    assert "segment line from 1,1 to 9,1" in r.source
    assert r.stats["corridor.c"] == {"nodes": {"before": 0, "after": 0},
                                     "segments": {"before": 3, "after": 2}}
    assert _footprints(r.source) == _footprints(src)


def test_long_or_uncovered_spurs_stay():
    # Spur longer than half the width, and a spur off a corner.
    src = _corr("  width 1\n  node a at 2,2\n  node j at 8,2\n  node b at 14,2\n"
                "  node s at 8,4\n  node k at 14,8\n  node t at 14.5,8\n"
                "  run a to j\n  run j to b\n  run j to s\n  run b to k\n  run k to t\n")
    assert not simplify(src).changed


def test_patterned_zero_width_corridor_untouched():
    src = _corr("  width 0\n  line_style dashed\n  node a at 1,1\n  node m at 5,1\n"
                "  node b at 9,1\n  run a to m\n  run m to b\n")
    assert not simplify(src).changed


# ---------------------------------------------------------------------------
# rooms
# ---------------------------------------------------------------------------

def test_polygon_collinear_and_duplicate_points():
    src = ('map "M" { grid { bounds 20 x 20 } }\n'
           'room "r" {\n  polygon (0,0) (5,0) (5,0) (10,0) (10,5) (10,10) (0,10) (0,5)\n}\n')
    r = simplify(src)
    assert "polygon (0,0) (10,0) (10,10) (0,10)" in r.source
    assert r.stats["room.r"] == {"points": {"before": 8, "after": 4}}
    assert sorted(c.kind for c in r.changes).count("collinear-point") == 3
    assert _footprints(r.source) == _footprints(src)


def test_polygon_keeps_spikes_and_three_points():
    # (10,0)->(5,0) doubles back: not "between", so it stays.
    src = ('map "M" { grid { bounds 20 x 20 } }\n'
           'room "r" { polygon (0,0) (10,0) (5,0) (5,5) }\n')
    assert not simplify(src).changed


def test_boundary_collinear_edges_and_arcs():
    src = ('map "M" { grid { bounds 30 x 30 } }\n'
           'room "b" {\n  boundary {\n    start 0,0\n    line to 5,0\n    line to 10,0\n'
           '    arc to 10,10 via 13,5\n    line to 0,10\n    line to 0,5\n  }\n}\n')
    r = simplify(src)
    assert "line to 5,0" not in r.source and "line to 0,5" not in r.source
    assert "arc to 10,10 via 13,5" in r.source
    assert _footprints(r.source) == _footprints(src)


def test_ruined_room_untouched():
    src = ('map "M" { grid { bounds 20 x 20 } }\n'
           'room "r" { polygon (0,0) (5,0) (10,0) (10,10) (0,10)\n  line_style ruined }\n')
    assert not simplify(src).changed


# ---------------------------------------------------------------------------
# rewriting
# ---------------------------------------------------------------------------

def test_comments_and_layout_survive():
    src = _corr("  width 2  # wide\n  # the spine\n  node a at 2,5\n  node m at 8,5  # mid\n"
                "  node b at 14,5\n  run a to m\n  run m to b\n  description \"x\"\n")
    out = simplify(src).source
    assert "width 2  # wide" in out and "# the spine" in out and 'description "x"' in out
    assert "# mid" not in out   # the removed node's own line goes with it


def test_one_line_corridor():
    src = ('map "M" { grid { bounds 20 x 20 } }\n'
           'corridor "c" { node a at 1,1 node m at 4,1 node b at 9,1 run a to m run m to b }\n')
    out = simplify(src).source
    assert parse(out).corridors["c"].nodes == {"a": (1, 1), "b": (9, 1)}
    assert "run a to b" in out


def test_layer_blocks_are_simplified():
    src = ('map "M" { grid { bounds 20 x 20 } }\nlayer "L" {\n  corridor "c" {\n'
           '    node a at 1,1\n    node m at 4,1\n    node b at 9,1\n    run a to m\n    run m to b\n'
           '  }\n}\n')
    r = simplify(src)
    assert r.stats["corridor.c"]["nodes"] == {"before": 3, "after": 2}


@pytest.mark.parametrize("path", sorted(SAMPLES.glob("*.dmap")), ids=lambda p: p.name)
def test_samples_keep_their_footprint_and_are_idempotent(path):
    src = path.read_text(encoding="utf-8")
    r = simplify(src)
    assert _footprints(r.source) == _footprints(src)
    again = simplify(r.source)
    assert not again.changed and again.source == r.source


def test_cli_check_in_place_and_json(tmp_path, capsys):
    import json

    from delve.maps.dsl.cli import main

    f = tmp_path / "c97.dmap"
    f.write_text(C97)
    assert main(["simplify", str(f), "--check"]) == 1           # something to do
    capsys.readouterr()
    assert main(["simplify", str(f), "--json", "--check"]) == 1
    rep = json.loads(capsys.readouterr().out)
    assert rep["changed"] and rep["stats"]["corridor.c97"]["nodes"]["after"] == 5
    assert main(["simplify", str(f), "-i"]) == 0
    assert "node n4" not in f.read_text()
    assert main(["simplify", str(f), "--check"]) == 0           # idempotent
