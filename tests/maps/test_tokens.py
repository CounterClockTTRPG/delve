"""Combat tokens as DSL markers on the map, fog-safe (plateau 2a, Task 7)."""

import re

from delve.maps.dsl import fog_of_war, node_centroid, parse, render_fogged
from delve.maps.state import MapState, move
from delve.maps.tokens import Token, entry_points, with_tokens
from tests.fixtures import SAMPLES

CRYPT = (SAMPLES / "crypt.dmap").read_text()

TOKENS = [
    Token("chr_00000000000a", "Garrek", "room.entry_hall", "party"),
    Token("chr_00000000000b", "Pippa", "entry_hall", "party"),
    Token("mon_1", "Goblin 1", "room.throne_chamber", "enemy"),
    Token("mon_2", "Goblin 2", "room.throne_chamber", "enemy", portrait_ref="tokens/goblin.png"),
]


def _token_names(svg: str) -> list[str]:
    return re.findall(r'<g class="marker" data-name="([^"]*)"', svg)


def test_tokens_in_undiscovered_rooms_not_in_fog_view():
    """Fog keeps only the markers in discovered nodes (the plateau 1 invariant): goblins waiting in the throne room
    the characters haven't found never show on their map, not even their labels."""
    dmap = with_tokens(parse(CRYPT), TOKENS)
    fogged = render_fogged(dmap, ["room.entry_hall"], [])
    assert sorted(_token_names(fogged)) == ["chr_00000000000a", "chr_00000000000b"]
    assert "Goblin" not in fogged
    assert {m.name for m in fog_of_war(dmap, ["room.entry_hall"], []).markers} == {
        "chr_00000000000a",
        "chr_00000000000b",
    }

    seen = render_fogged(dmap, ["room.entry_hall", "room.throne_chamber"], [])
    assert sorted(_token_names(seen)) == ["chr_00000000000a", "chr_00000000000b", "mon_1", "mon_2"]


def test_dm_view_shows_every_token():
    dmap = with_tokens(parse(CRYPT), TOKENS)
    full = render_fogged(dmap, (), (), full=True)
    assert sorted(_token_names(full)) == ["chr_00000000000a", "chr_00000000000b", "mon_1", "mon_2"]
    assert 'data-tag="enemy"' in full and 'data-tag="party"' in full


def test_tokens_anchored_in_their_node_near_its_centroid_and_apart():
    dmap = with_tokens(parse(CRYPT), TOKENS)
    markers = {m.name: m for m in dmap.markers}
    assert markers["chr_00000000000a"].location == "room.entry_hall"
    assert markers["chr_00000000000b"].location == "room.entry_hall"  # a bare name resolves to its node
    assert markers["mon_2"].image == "tokens/goblin.png"
    assert markers["mon_1"].label == "Goblin 1"
    cx, cy = node_centroid(dmap, "room.throne_chamber")
    for name in ("mon_1", "mon_2"):
        x, y = markers[name].position
        assert abs(x - cx) <= 2 and abs(y - cy) <= 2
    assert markers["mon_1"].position != markers["mon_2"].position


def test_tokens_without_a_known_node_are_not_drawn():
    dmap = parse(CRYPT)
    drawn = with_tokens(dmap, [Token("mon_9", "Lost", "room.nowhere", "enemy"), Token("mon_8", "Off", None, "enemy")])
    assert drawn.markers == dmap.markers


def test_with_tokens_leaves_the_map_alone():
    dmap = parse(CRYPT)
    before = list(dmap.markers)
    with_tokens(dmap, TOKENS)
    assert dmap.markers == before


# ----- the sides apart (DEL-271) -----

FIGHT = [
    Token("chr_00000000000a", "Garrek", "room.throne_chamber", "party", rank=0),
    Token("chr_00000000000b", "Pippa", "room.throne_chamber", "party", rank=1),
    Token("mon_1", "Goblin 1", "room.throne_chamber", "enemy"),
    Token("mon_2", "Goblin 2", "room.throne_chamber", "enemy"),
    Token("mon_3", "Goblin 3", "room.throne_chamber", "enemy"),
]


def _positions(dmap):
    return {m.name: m.position for m in dmap.markers if m.location == "room.throne_chamber"}


def test_the_party_stands_on_the_side_it_came_in_from_and_the_enemies_across():
    """The party came from the main hall, through the throne chamber's west door (17,10): it stands west of the
    centre, the goblins east; before, they all stood mixed on one grid round the centre."""
    dmap = parse(CRYPT)
    entries = entry_points(dmap, {"room.throne_chamber": "corridor.main_hall"})
    assert entries == {"room.throne_chamber": (17.0, 10.0)}
    at = _positions(with_tokens(dmap, FIGHT, entries))
    cx, _ = node_centroid(dmap, "room.throne_chamber")
    assert all(at[pc][0] < cx for pc in ("chr_00000000000a", "chr_00000000000b"))
    assert all(at[m][0] > cx for m in ("mon_1", "mon_2", "mon_3"))
    assert len(set(at.values())) == 5, "no two on one spot"

    # Came the other way, through the east door from the curved passage: the sides swap.
    east = entry_points(dmap, {"room.throne_chamber": "corridor.curved_passage"})
    at = _positions(with_tokens(dmap, FIGHT, east))
    assert all(at[pc][0] > cx for pc in ("chr_00000000000a", "chr_00000000000b"))
    assert all(at[m][0] < cx for m in ("mon_1", "mon_2", "mon_3"))


def test_the_front_of_the_marching_order_faces_the_enemies():
    party = [Token(f"chr_{i:012d}", f"PC {i}", "room.throne_chamber", "party", rank=i) for i in range(6)]
    goblin = [Token("mon_1", "Goblin", "room.throne_chamber", "enemy")]
    dmap = parse(CRYPT)
    at = _positions(with_tokens(dmap, party + goblin, entry_points(dmap, {"room.throne_chamber": "corridor.main_hall"})))
    front = [at[f"chr_{i:012d}"][0] for i in range(4)]
    back = [at[f"chr_{i:012d}"][0] for i in (4, 5)]
    assert min(front) > max(back), "the first four, nearer the goblin (east), before the last two"


def test_without_a_way_in_the_sides_split_along_the_longer_side():
    dmap = parse(CRYPT)
    at = _positions(with_tokens(dmap, FIGHT))
    cx, _ = node_centroid(dmap, "room.throne_chamber")
    party_x = [at[pc][0] for pc in ("chr_00000000000a", "chr_00000000000b")]
    enemy_x = [at[m][0] for m in ("mon_1", "mon_2", "mon_3")]
    assert max(party_x) < cx < min(enemy_x) or min(party_x) > cx > max(enemy_x), "apart, one side each"


def test_a_side_alone_keeps_the_grid_round_the_centre():
    dmap = parse(CRYPT)
    alone = [t for t in FIGHT if t.side == "enemy"]
    at = _positions(with_tokens(dmap, alone, entry_points(dmap, {"room.throne_chamber": "corridor.main_hall"})))
    cx, cy = node_centroid(dmap, "room.throne_chamber")
    assert all(abs(x - cx) <= 2 and abs(y - cy) <= 2 for x, y in at.values())


def test_a_move_remembers_where_the_character_came_from():
    dmap = parse(CRYPT)
    s = move(MapState.empty(), dmap, ["A"], "room.entry_hall")
    assert s.characters["A"].came_from is None, "a first move comes from nowhere known"
    s = move(s, dmap, ["A"], "corridor.main_hall")
    s = move(s, dmap, ["A"], "room.throne_chamber")
    assert s.characters["A"].came_from == "corridor.main_hall"
    s = move(s, dmap, ["A"], "room.throne_chamber")
    assert s.characters["A"].came_from == "corridor.main_hall", "staying put isn't coming from somewhere"
