"""Markers in the players' view: only those whose node is discovered.

Combat tokens are DSL markers. A marker's node is its `in room.X`, else the
node its position falls in. One standing in no node has nothing to fog by,
and used to be kept — so every enemy showed on the players' screen.
"""
from __future__ import annotations

from delve.maps.dsl import fog_of_war, parse, render_fogged

SRC = """
map "M" { grid { bounds 30 x 10 } }
room "a" { rect 1,1 6 x 6 }
room "b" { rect 10,1 6 x 6 }
door at 7,4 { connects room.a, room.b }
marker "Outside Orc" at 22,8 tag enemy
marker "Fighter" at 3,3 tag party in room.a
marker "Goblin" at 12,4 tag enemy in room.b
marker "Placed Rat" at 5,5 tag enemy
marker "Lurking Rat" at 13,5 tag enemy
layer "tokens" {
  marker "Layer Outside" at 24,8 tag enemy
  marker "Layer Anchored" at 4,5 tag enemy in room.a
}
"""

ALL = {
    "Outside Orc", "Fighter", "Goblin", "Placed Rat", "Lurking Rat",
    "Layer Outside", "Layer Anchored",
}


def _names(dmap) -> set[str]:
    return {m.name for m in dmap.markers} | {
        m.name for layer in dmap.layers for m in layer.markers
    }


def test_fog_drops_markers_in_no_room() -> None:
    fogged = fog_of_war(parse(SRC), {"room.a", "room.b"}, {"7,4"})
    assert "Outside Orc" not in _names(fogged)
    assert "Layer Outside" not in _names(fogged)


def test_fog_keeps_markers_in_discovered_rooms_only() -> None:
    fogged = fog_of_war(parse(SRC), {"room.a"}, set())
    # Fighter and Layer Anchored by `in room.a`, Placed Rat by position.
    assert _names(fogged) == {"Fighter", "Layer Anchored", "Placed Rat"}


def test_fog_keeps_markers_once_their_room_is_discovered() -> None:
    fogged = fog_of_war(parse(SRC), {"room.a", "room.b"}, {"7,4"})
    assert _names(fogged) == ALL - {"Outside Orc", "Layer Outside"}


def test_explicit_location_wins_over_position() -> None:
    src = SRC + 'marker "Misfiled" at 3,3 tag enemy in room.b\n'
    assert "Misfiled" not in _names(fog_of_war(parse(src), {"room.a"}, set()))


def test_fogged_svg_omits_marker_in_no_room() -> None:
    svg = render_fogged(parse(SRC), {"room.a", "room.b"}, {"7,4"})
    assert 'data-name="Outside Orc"' not in svg
    assert 'data-name="Goblin"' in svg


def test_gm_view_keeps_every_marker() -> None:
    svg = render_fogged(parse(SRC), {"room.a"}, set(), full=True)
    for name in ALL:
        assert f'data-name="{name}"' in svg


def test_party_marker_unaffected() -> None:
    svg = render_fogged(parse(SRC), {"room.a"}, set(), party_location="room.a")
    assert 'class="party-start"' in svg
