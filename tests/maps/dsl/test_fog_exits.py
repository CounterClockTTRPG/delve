"""Exits in the players' view: only those whose node is discovered (DEL-125).

An exit written inside a room goes with the room, but a top-level exit (`exit at x,y { to … }`, how a map's stairs to
another map are usually written) was kept whole, so the players saw the stairs of rooms they had never been in: the
hidden stair "7" of the Temple of Elemental Evil's moathouse dungeon. A top-level exit's node is the one its position
falls in; one in no node, on a seam or just outside a doorway, goes with the nearest node.
"""
from __future__ import annotations

from delve.maps.dsl import fog_of_war, parse, render_fogged

SRC = """
map "M" { grid { bounds 30 x 10 } }
room "a" { rect 1,1 6 x 6 }
room "b" { rect 10,1 6 x 6 }
door at 7,4 { connects room.a, room.b }
exit at 3,3 { to "up" at 1,1 label "Up" }
exit at 13,4 { to "down" at 1,1 label "Stairs" }
exit at 16.5,4 { to "outside" at 1,1 label "Out the back" }
layer "deeper" {
  exit at 12,2 { to "pit" at 1,1 label "Pit" }
}
"""


def _labels(dmap) -> set[str]:
    exits = [*dmap.exits, *(e for layer in dmap.layers for e in layer.exits)]
    return {e.label.text for e in exits if e.label}


def test_fog_hides_the_exits_of_undiscovered_rooms() -> None:
    assert _labels(fog_of_war(parse(SRC), {"room.a"}, set())) == {"Up"}


def test_fog_shows_them_once_their_room_is_discovered() -> None:
    assert _labels(fog_of_war(parse(SRC), {"room.a", "room.b"}, {"7,4"})) == {"Up", "Stairs", "Out the back", "Pit"}


def test_an_exit_in_no_room_goes_with_the_nearest() -> None:
    assert "Out the back" in _labels(fog_of_war(parse(SRC), {"room.b"}, set()))
    assert "Out the back" not in _labels(fog_of_war(parse(SRC), {"room.a"}, set()))


def test_fogged_svg_omits_the_stairs_of_an_undiscovered_room() -> None:
    svg = render_fogged(parse(SRC), {"room.a"}, set())
    assert "Stairs" not in svg
    assert "Up" in svg


def test_gm_view_keeps_every_exit() -> None:
    svg = render_fogged(parse(SRC), {"room.a"}, set(), full=True)
    for label in ("Up", "Stairs", "Out the back", "Pit"):
        assert label in svg
