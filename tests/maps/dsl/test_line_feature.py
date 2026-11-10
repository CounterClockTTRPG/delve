"""`line_feature` — bars (dotted), curtain (wavy), barred (+ marks)."""
from __future__ import annotations

from delve.maps.dsl import parse, render, render_fogged, validate


def _map(body: str) -> str:
    return (
        'map "M" { grid { bounds 12 x 9 } renderer "classic-bw" }\n'
        'room "r" { rect 0,0 12 x 9 }\n' + body + "\n"
    )


def test_parses_points_and_kind():
    m = parse(_map('line_feature "f" { kind curtain point 1,2 point 8,2 point 8,6 }'))
    lf = m.line_features[0]
    assert lf.kind == "curtain"
    assert lf.points == [(1.0, 2.0), (8.0, 2.0), (8.0, 6.0)]


def test_inline_kind_form():
    m = parse(_map('line_feature "f" kind bars { point 1,2 point 8,2 }'))
    assert m.line_features[0].kind == "bars"


def test_bars_render_dotted():
    svg = render(parse(_map('line_feature "f" { kind bars point 1,2 point 10,2 }')))
    assert 'data-kind="bars"' in svg
    assert "stroke-dasharray" in svg


def test_curtain_render_is_a_wavy_path():
    svg = render(parse(_map('line_feature "f" { kind curtain point 1,2 point 10,2 }')))
    # A single multi-vertex path (the sine wiggle) tagged as a curtain.
    assert 'data-kind="curtain"' in svg
    assert svg.count('class="line-feature"') == 1


def test_barred_render_plus_marks():
    svg = render(parse(_map('line_feature "f" { kind barred point 1,2 point 9,2 }')))
    # Several `+` marks (each a class="line-feature" path with two strokes).
    assert svg.count('class="line-feature"') > 4


def test_step_render_two_parallel_lines():
    svg = render(parse(_map('line_feature "f" { kind step point 1,2 point 10,2 }')))
    # Two thin parallel polylines tagged as a step.
    assert 'data-kind="step"' in svg
    assert svg.count('class="line-feature"') == 2


def test_step_kind_is_known():
    diags = validate(parse(_map('line_feature "f" { kind step point 1,2 point 8,2 }')))
    assert not any("unknown kind" in d.message for d in diags)


def test_single_point_is_an_error():
    diags = validate(parse(_map('line_feature "f" { kind bars point 3,3 }')))
    assert any(
        d.severity == "error" and "at least 2" in d.message for d in diags
    )


def test_unknown_kind_warns():
    diags = validate(
        parse(_map('line_feature "f" { kind squiggle point 1,2 point 8,2 }'))
    )
    assert any(
        d.severity == "warning" and "unknown kind" in d.message for d in diags
    )


def test_valid_line_feature_clean():
    diags = validate(
        parse(_map('line_feature "f" { kind barred point 1,2 point 8,2 }'))
    )
    assert not any(d.severity == "error" for d in diags)


def test_nested_in_room_stays_on_room_not_hoisted():
    m = parse(_map(
        'room "b" { rect 0,0 6 x 6 '
        '  line_feature "f" { kind bars point 1,1 point 5,1 } }'
    ))
    # Bound to the room, not lifted to the map-level list.
    assert m.line_features == []
    assert len(m.rooms["b"].line_features) == 1
    # Still rendered in the normal (GM) view.
    assert "line-feature" in render(m)


def test_nested_line_feature_hidden_until_room_discovered():
    body = (
        'room "b" { rect 0,0 6 x 6 '
        '  line_feature "f" { kind curtain point 1,1 point 5,1 } }'
    )
    m = parse(_map(body))
    hidden = render_fogged(m, {"room.r"}, set(), party_location="room.r")
    assert 'class="line-features"' not in hidden
    shown = render_fogged(m, {"room.r", "room.b"}, set(), party_location="room.r")
    assert 'class="line-features"' in shown


def test_nested_in_corridor():
    m = parse(_map(
        'corridor "c" { width 2 segment line from 0,8 to 12,8 '
        '  line_feature "f" { kind barred point 4,7 point 4,9 } }'
    ))
    assert len(m.corridors["c"].line_features) == 1
    assert not any(d.severity == "error" for d in validate(m))


def test_stream_is_one_water_line_and_canal_two_banks():
    from delve.maps.dsl.render.classic_bw import AREA_KINDS
    water = AREA_KINDS["water"][1]
    m = parse(_map('line_feature "s" kind stream { point 1,2 point 10,2 }\n'
                   'line_feature "c" kind canal { point 1,6 point 10,6 }'))
    assert not [d for d in validate(m) if "line_feature" in d.message]
    svg = render(m)
    stream = svg.split('data-kind="stream"', 1)[1].split("/>", 1)[0]
    assert f'stroke="{water}"' in stream
    canal = svg.split('data-kind="canal"', 1)[1].split("</g>", 1)[0]
    assert canal.count("<path") == 2 and canal.count(water) == 2


def test_ticked_walls_are_strokes_across_the_outline():
    # `line_style ticked` (a dome's rim): no wall stroke, a path of short ticks;
    # on a circle every tick is radial
    import math
    import re
    m = parse('map "M" { grid { bounds 12 x 12 } }\nroom "d" { circle at 6,6 radius 3 line_style ticked }\n')
    assert not [d for d in validate(m) if "line_style" in d.message]
    svg = render(m)
    assert 'class="wall"' not in svg
    ticks = " ".join(re.findall(r'<path class="tick" d="([^"]+)"', svg))
    segs = re.findall(r"M([-\d.]+),([-\d.]+) L([-\d.]+),([-\d.]+)", ticks)
    assert len(segs) > 100                         # close together: ~0.16 apart round 2πr ≈ 19
    for x0, y0, x1, y1 in (map(float, t) for t in segs):
        r0, r1 = math.hypot(x0 - 6, y0 - 6), math.hypot(x1 - 6, y1 - 6)
        assert min(r0, r1) < 3 < max(r0, r1)       # straddles the outline …
        cross = abs((x0 - 6) * (y1 - 6) - (y0 - 6) * (x1 - 6)) / (r0 * r1)
        assert cross < 0.05                        # … across it (radial, near enough)


def test_bridge_takes_a_width_and_draws_a_band_with_two_edges():
    m = parse(_map('line_feature "b" { kind bridge point 1,2 point 10,2 width 1.5 }'))
    lf = m.line_features[0]
    assert (lf.kind, lf.width) == ("bridge", 1.5)
    assert not [d for d in validate(m) if "line_feature" in d.message.lower() and "kind" in d.message.lower()]
    svg = render(m)
    assert 'data-kind="bridge"' in svg
    assert 'stroke-width="1.5"' in svg
    assert svg.count('class="line-feature"') == 2
