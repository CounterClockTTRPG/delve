"""A `run … width W` overrides the corridor's width for that run alone."""
from __future__ import annotations

from delve.maps.dsl import parse, render, validate
from delve.maps.dsl.geometry import corridor_polygons, owner_node
from delve.maps.dsl.walls import corridor_outlines

# A 10-foot hall narrowing to a 5-foot passage that turns south.
HALL = """
map "M" { grid { bounds 20 x 20 } }
corridor "c" {
  width 1
  node a at 2,5
  node b at 10,5
  node c at 14,5
  node d at 14,12
  run a to b width 2
  run b to c
  run c to d
}
"""


def test_run_width_lands_on_its_segment_only() -> None:
    c = parse(HALL).corridors["c"]
    assert [c.segment_width(s) for s in c.segments] == [2, 1, 1]
    assert c.max_width == 2


def test_runs_of_different_width_are_not_chained() -> None:
    c = parse(HALL).corridors["c"]
    # the 1-wide pair forms one trail; the wide run stays its own segment
    wide = [s for s in c.segments if s.width == 2]
    assert len(wide) == 1 and {wide[0].start, wide[0].end} == {(2, 5), (10, 5)}


def test_floor_follows_each_runs_width() -> None:
    m = parse(HALL)
    poly = corridor_outlines(m, wall_stroke=0.1)["c"].polygon
    # 2 wide for 8, then 1 wide for 4 + 7, less the bend's overlap, plus its
    # round join: 16 + 11 - 0.25 + pi/16
    assert abs(poly.area - (16 + 11 - 0.25 + 3.14159 / 16)) < 0.01
    assert owner_node(m, (5, 4.2)) == "corridor.c"     # inside the 10' hall
    assert owner_node(m, (12, 4.2)) is None           # beside the 5' passage
    rects = corridor_polygons(m.corridors["c"])
    assert len(rects) == 3


def test_a_run_wider_than_the_corridor_validates_and_renders() -> None:
    m = parse(HALL)
    assert not [d for d in validate(m) if d.severity == "error"]
    assert 'class="corridor-floor"' in render(m)


def test_door_on_the_side_of_a_wide_run_touches_the_corridor() -> None:
    src = HALL + """
room "r" { rect 4,0 4 x 4 }
door at 6,4 { connects room.r, corridor.c }
"""
    diags = validate(parse(src))
    assert not [d for d in diags if "does not touch" in d.message or "far from" in d.message]
