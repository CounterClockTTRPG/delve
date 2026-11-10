"""What converting real modules (Arden Vul) found the DSL couldn't say:

- false doors (a door drawn on a wall that leads nowhere),
- wall segments inside a space (a half-wall, a partition, a chamfer),
- rope bridges, ziplines and marked paths,
- raised / sunken floors, magical darkness and floor inlays as area kinds,
- exits with several destinations (a teleporter that rolls where it sends you),
- library glyphs the maps needed.
"""
from __future__ import annotations

from delve.maps.dsl import build_graph, fog_of_war, parse, render, render_fogged, validate
from delve.maps.dsl.room_context import SessionView, room_context

INC = 'include "core.dmap"\ninclude "dungeon.dmap"\n'


def _map(body: str) -> str:
    return (
        INC + 'map "M" { grid { bounds 12 x 9 } renderer "classic-bw" }\n'
        'room "a" { rect 1,1 4 x 4 }\n'
        'room "b" { rect 5,1 4 x 4 }\n'
        'door at 5,2 { connects room.a, room.b }\n' + body + "\n"
    )


def _warnings(src: str) -> list[str]:
    return [d.message for d in validate(parse(src))]


# ----- false doors ---------------------------------------------------------

FALSE = 'door at 1,3 { connects room.a  type false }'


def test_false_door_is_known_and_clean():
    assert _warnings(_map(FALSE)) == []


def test_false_door_aliases():
    for t in ("false-door", "false_door"):
        assert _warnings(_map(f'door at 1,3 {{ connects room.a  type {t} }}')) == []


def test_false_door_is_no_edge_but_a_boundary_exit():
    g = build_graph(parse(_map(FALSE)))
    assert len(g.edges) == 1  # only a <-> b
    assert [b.type for b in g.boundary] == ["false"]


def test_false_door_draws_its_marker_for_the_gm():
    svg = render(parse(_map(FALSE)))
    assert "door-false" in svg


def test_false_door_looks_like_a_door_to_the_players():
    m = parse(_map(FALSE))
    fogged = fog_of_war(m, {"room.a"}, {"1,3", "5,2"})
    d = next(d for d in fogged.doors if d.position == (1.0, 3.0))
    assert d.type == "wooden"
    svg = render_fogged(m, {"room.a"}, {"1,3", "5,2"})
    assert "door-false" not in svg and 'data-door="false"' not in svg


def test_false_door_room_context_perceived_as_a_door_dm_knows():
    m = parse(_map(FALSE))
    ctx = room_context(m, build_graph(m), "room.a",
                       SessionView(discovered_nodes=frozenset({"room.a"}),
                                   discovered_doors=frozenset({"1,3", "5,2"})))
    seen = {e["door"]: e for e in ctx["perceived"]["exits"]}
    assert seen["1,3"]["type"] == "wooden"
    assert "false" not in str(ctx["perceived"])
    assert ctx["dm_only"]["false_doors"] == ["1,3"]


# ----- wall segments, bridges, paths ---------------------------------------

def test_wall_line_feature_is_known_and_drawn_as_wall():
    src = _map('line_feature "half" kind wall { point 2,3 point 4,3 }')
    assert _warnings(src) == []
    svg = render(parse(src))
    assert 'data-kind="wall"' in svg
    assert 'class="wall-segment"' in svg


def test_wall_segment_does_not_change_the_graph():
    a = build_graph(parse(_map("")))
    b = build_graph(parse(_map('line_feature "half" kind wall { point 2,3 point 4,3 }')))
    assert a.edges == b.edges and set(a.nodes) == set(b.nodes)


def test_rope_bridge_zipline_path_kinds():
    for kind in ("rope-bridge", "zipline", "path"):
        src = _map(f'line_feature "x" kind {kind} {{ point 1,4 point 8,4 }}')
        assert _warnings(src) == [], kind
        assert f'data-kind="{kind}"' in render(parse(src))


def test_rope_bridge_has_planks_and_two_ropes():
    svg = render(parse(_map('line_feature "x" kind rope-bridge { point 1,4 point 8,4 width 1 }')))
    assert svg.count('class="rope"') == 2
    assert svg.count('class="plank"') >= 5


# ----- area kinds ----------------------------------------------------------

def test_new_area_kinds_are_known_and_distinct():
    fills = set()
    for kind in ("dais", "sunken", "darkness", "inlay"):
        src = _map(f'area "z" kind {kind} {{ rect 2,2 2 x 2 }}')
        assert _warnings(src) == [], kind
        svg = render(parse(src))
        assert f'data-kind="{kind}"' in svg
        style = svg.split(f'data-kind="{kind}"')[1].split('style="')[1].split('"')[0]
        fills.add(style)
    assert len(fills) == 4


def test_inlay_is_an_outline_only():
    svg = render(parse(_map('area "lapis" kind inlay { circle at 3,3 radius 1 }')))
    style = svg.split('data-kind="inlay"')[1].split('style="')[1].split('"')[0]
    assert "fill:none" in style


# ----- exits with several destinations ------------------------------------

MULTI = ('exit at 3,3 {\n'
         '  to "Level 3" at 10,20 roll "1"\n'
         '  to "Level 2" at 81,19 roll "2"\n'
         '  to "Sub-Level 7" at 84,24 roll "3-6"\n'
         '  label "teleporter"\n'
         '}')


def test_exit_with_several_targets():
    ex = parse(_map(MULTI)).exits[0]
    assert [t.map for t in ex.targets] == ["Level 3", "Level 2", "Sub-Level 7"]
    assert [t.roll for t in ex.targets] == ["1", "2", "3-6"]
    # the first stays the exit's target, for every caller that reads one
    assert ex.target_map == "Level 3" and ex.target_position == (10.0, 20.0)
    assert _warnings(_map(MULTI)) == []


def test_single_target_exit_has_one_target():
    ex = parse(_map('exit at 3,3 { to "cellar" at 1,2 }')).exits[0]
    assert len(ex.targets) == 1 and ex.targets[0].roll is None


def test_multi_target_exit_renders_every_target():
    svg = render(parse(_map(MULTI)))
    assert 'data-exit-to="Level 3"' in svg
    assert "data-exit-targets=" in svg and "Sub-Level 7" in svg


def test_empty_roll_target_map_is_an_error():
    src = _map('exit at 3,3 { to "a" at 1,1  to "" at 2,2 }')
    assert any(d.severity == "error" for d in validate(parse(src)))


# ----- library glyphs ------------------------------------------------------

NEW_GLYPHS = ("anvil", "pentagram", "chalkboard", "monolith", "bust", "font", "mosaic",
              "light-prism", "mausoleum", "cylinder", "false-door", "window-slot")


def test_new_library_glyphs_parse_and_render():
    body = "\n".join(f'feature "{g}" at {1 + i % 8 + .5},{1 + i // 8 + .5}'
                     for i, g in enumerate(NEW_GLYPHS))
    src = (INC + 'map "M" { grid { bounds 12 x 9 } renderer "classic-bw" }\n'
           'room "a" { rect 0,0 12 x 9\n' + body + "\n}\n")
    assert [m for m in _warnings(src) if "sits on" not in m] == []
    svg = render(parse(src))
    for g in NEW_GLYPHS:
        assert f'data-feature="{g}"' in svg or g in svg, g


# ----- town and outdoor scale (Azure Keep): roads, cliffs, fences, towers -----

def test_road_cliff_fence_kinds():
    for kind in ("road", "cliff", "fence"):
        src = _map(f'line_feature "x" kind {kind} {{ point 1,4 point 8,4 point 8,7 }}')
        assert _warnings(src) == [], kind
        assert f'data-kind="{kind}"' in render(parse(src))


def test_road_is_a_band_with_edges():
    svg = render(parse(_map('line_feature "x" kind road { point 1,4 point 8,4 width 1.2 }')))
    assert svg.count('class="road-edge"') == 2


def test_cliff_has_ticks_on_one_side():
    svg = render(parse(_map('line_feature "x" kind cliff { point 1,4 point 8,4 }')))
    assert svg.count('class="cliff-tick"') >= 6


def test_tower_and_gatehouse_glyphs():
    src = ('include "city.dmap"\nmap "M" { grid { bounds 12 x 9 } }\n'
           'room "a" { rect 0,0 12 x 9\n feature tower at 3,3\n feature gatehouse at 7,3\n}\n')
    assert _warnings(src) == []
