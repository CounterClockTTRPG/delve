"""render_fogged draws one party disc per group (plateau 1, Task 3)."""

import re
from pathlib import Path

from delve.maps.dsl import build_graph, parse, render_fogged, visible_doors
from tests.fixtures import SAMPLES

DATA = Path(__file__).parent / "data"
NODES = ["room.entry_hall", "corridor.main_hall", "room.throne_chamber"]


def _crypt():
    return parse((SAMPLES / "crypt.dmap").read_text())


def _doors(dmap, nodes):
    graph = build_graph(dmap)
    return sorted(set().union(*(visible_doors(graph, n) for n in nodes)))


def _party_nodes(svg: str) -> list[str]:
    return re.findall(r'<g class="party" data-node="([^"]*)"', svg)


def test_two_groups_draw_two_discs():
    dmap = _crypt()
    svg = render_fogged(
        dmap, NODES, _doors(dmap, NODES),
        party_locations=["room.throne_chamber", "room.entry_hall"],
    )
    assert svg.count('class="party"') == 2
    assert _party_nodes(svg) == ["room.throne_chamber", "room.entry_hall"]


def test_duplicate_locations_draw_once():
    dmap = _crypt()
    svg = render_fogged(
        dmap, NODES, _doors(dmap, NODES),
        party_locations=["room.entry_hall", "room.entry_hall", "room.throne_chamber"],
    )
    assert _party_nodes(svg) == ["room.entry_hall", "room.throne_chamber"]


def test_party_location_drawn_first_when_both_given():
    dmap = _crypt()
    svg = render_fogged(
        dmap, NODES, _doors(dmap, NODES),
        party_location="room.entry_hall",
        party_locations=["room.throne_chamber", "room.entry_hall"],
    )
    assert _party_nodes(svg) == ["room.entry_hall", "room.throne_chamber"]


def test_full_render_draws_every_group():
    dmap = _crypt()
    svg = render_fogged(
        dmap, (), (), full=True,
        party_locations=["room.vestry_alcove", "room.entry_hall"],
    )
    assert _party_nodes(svg) == ["room.vestry_alcove", "room.entry_hall"]


def test_single_party_location_unchanged():
    dmap = _crypt()
    nodes = ["room.entry_hall", "corridor.main_hall"]
    svg = render_fogged(dmap, nodes, _doors(dmap, nodes), party_location="room.entry_hall")
    assert svg == (DATA / "fogged_single.svg").read_text()
