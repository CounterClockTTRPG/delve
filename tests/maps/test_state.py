"""Map state: positions and discovery per character (plateau 1, Task 4)."""

import re

import pytest

from delve.maps.dsl import SessionView, parse
from delve.maps.state import (
    CharacterView,
    MapState,
    NoPosition,
    UnknownNode,
    discover_door,
    from_json,
    groups,
    leave,
    merge,
    move,
    place,
    render_dm,
    render_view,
    reveal,
    reveal_secret,
    set_door,
    start,
    to_json,
    upgrade,
    view,
)
from tests.fixtures import SAMPLES

CRYPT = (SAMPLES / "crypt.dmap").read_text()

# A secret room behind a secret door in the vestry, with a marker in it, and a
# secret marker in the entry hall.
PLANTED = CRYPT + """
room "hidden_crypt" {
  rect 44,14 4 x 6
  label "SECRET-XYZZY"
}
door at 46,20 { connects room.vestry_alcove, room.hidden_crypt type secret }
marker "ritualist" at 46,17 label "SECRET-XYZZY" in room.hidden_crypt
marker "lurker" at 8,8 label "SECRET-LURKER" secret
"""


@pytest.fixture
def crypt():
    return parse(CRYPT)


def _parties(svg: str) -> list[str]:
    return re.findall(r'<g class="party" data-node="([^"]*)"', svg)


def _split(dmap) -> MapState:
    """A and B enter together; B walks to the throne room, A falls down a chute
    into the vestry."""
    s = move(MapState.empty(), dmap, ["A", "B"], "room.entry_hall")
    s = move(s, dmap, ["B"], "corridor.main_hall")
    s = move(s, dmap, ["B"], "room.throne_chamber")
    return move(s, dmap, ["A"], "room.vestry_alcove")


def test_move_discovers_node_and_visible_doors(crypt):
    s = move(MapState.empty(), crypt, ["A"], "room.throne_chamber")
    assert s.characters["A"] == CharacterView(
        location="room.throne_chamber",
        nodes=frozenset({"room.throne_chamber"}),
        doors=frozenset({"17,10", "35,10"}),
    )


def test_move_resolves_bare_names_and_labels(crypt):
    s = move(MapState.empty(), crypt, ["A"], "Throne Room")
    assert s.characters["A"].location == "room.throne_chamber"


def test_characters_apart_know_different_rooms(crypt):
    s = _split(crypt)
    assert s.characters["A"].nodes == {"room.entry_hall", "room.vestry_alcove"}
    assert s.characters["B"].nodes == {
        "room.entry_hall", "corridor.main_hall", "room.throne_chamber",
    }
    assert "42,20" in s.characters["A"].doors
    assert "42,20" not in s.characters["B"].doors


def test_meeting_merges_discovery(crypt):
    s = _split(crypt)
    s = move(s, crypt, ["A"], "corridor.curved_passage")
    assert "room.vestry_alcove" not in s.characters["B"].nodes
    s = move(s, crypt, ["A"], "room.throne_chamber")
    everything = {
        "room.entry_hall", "corridor.main_hall", "room.throne_chamber",
        "room.vestry_alcove", "corridor.curved_passage",
    }
    assert s.characters["A"].nodes == everything
    assert s.characters["B"].nodes == everything
    assert s.characters["A"].doors == s.characters["B"].doors


def test_merge_joins_characters_sharing_a_location():
    s = MapState(characters={
        "A": CharacterView("room.x", frozenset({"room.x", "room.y"}), frozenset({"1,1"})),
        "B": CharacterView("room.x", frozenset({"room.x", "room.z"}), frozenset()),
        "C": CharacterView(None, frozenset({"room.w"}), frozenset()),
    })
    m = merge(s)
    assert m.characters["A"] == m.characters["B"] == CharacterView(
        "room.x", frozenset({"room.x", "room.y", "room.z"}), frozenset({"1,1"}),
    )
    assert m.characters["C"] == s.characters["C"]


def test_view_union_and_party_location_only_when_together(crypt):
    s = _split(crypt)
    s = set_door(s, "17,10", "open")
    s = reveal_secret(s, "room.entry_hall/feature@10,9")
    apart = view(s, ["A", "B"])
    assert isinstance(apart, SessionView)
    assert apart.discovered_nodes == {
        "room.entry_hall", "corridor.main_hall", "room.throne_chamber", "room.vestry_alcove",
    }
    assert apart.party_location is None
    assert apart.door_states == {"17,10": "open"}
    assert apart.revealed == {"room.entry_hall/feature@10,9"}
    assert view(s, ["A"]).party_location == "room.vestry_alcove"
    together = move(s, crypt, ["A"], "room.throne_chamber")
    assert view(together, ["A", "B"]).party_location == "room.throne_chamber"
    assert view(s, []) == SessionView(door_states={"17,10": "open"},
                                      revealed=frozenset({"room.entry_hall/feature@10,9"}))


def test_groups_sorted(crypt):
    s = _split(crypt)
    s = move(s, crypt, ["C"], "room.throne_chamber")
    s = place(s, crypt, ["D"], "room.entry_hall")
    assert groups(s, ["A", "B", "C", "D", "nobody"]) == [
        ("room.entry_hall", frozenset({"D"})),
        ("room.throne_chamber", frozenset({"B", "C"})),
        ("room.vestry_alcove", frozenset({"A"})),
    ]
    assert groups(s, ["A"]) == [("room.vestry_alcove", frozenset({"A"}))]


def test_place_sets_location_without_discovering(crypt):
    s = place(MapState.empty(), crypt, ["A"], "room.vestry_alcove")
    assert s.characters["A"] == CharacterView("room.vestry_alcove", frozenset(), frozenset())


def test_reveal_discovers_without_moving(crypt):
    s = move(MapState.empty(), crypt, ["A"], "room.entry_hall")
    s = reveal(s, crypt, ["A"], "room.vestry_alcove")
    assert s.characters["A"].location == "room.entry_hall"
    assert {"room.vestry_alcove", "room.entry_hall"} <= s.characters["A"].nodes
    assert "42,20" in s.characters["A"].doors
    s = reveal(s, crypt, ["A"], "room.throne_chamber", reveal_doors=False)
    assert "room.throne_chamber" in s.characters["A"].nodes
    assert "35,10" not in s.characters["A"].doors


def test_start_places_at_party_start(crypt):
    dmap = parse(CRYPT.replace('  legend\n', '  legend\n  party_start "entry_hall"\n'))
    s = start(MapState.empty(), dmap, ["A", "B"])
    for cid in ("A", "B"):
        assert s.characters[cid] == CharacterView(
            "room.entry_hall", frozenset({"room.entry_hall"}), frozenset({"15,10"}),
        )
    # Without a party start, as in dungml, nobody is placed.
    assert start(MapState.empty(), crypt, ["A"]) == MapState.empty()


def test_render_view_two_groups_two_discs(crypt):
    s = _split(crypt)
    svg = render_view(s, crypt, ["A", "B"])
    assert _parties(svg) == ["room.throne_chamber", "room.vestry_alcove"]
    assert _parties(render_view(s, crypt, ["A"])) == ["room.vestry_alcove"]


def test_render_dm_draws_every_group(crypt):
    s = move(_split(crypt), crypt, ["C"], "room.entry_hall")
    svg = render_dm(s, crypt)
    assert _parties(svg) == ["room.entry_hall", "room.throne_chamber", "room.vestry_alcove"]
    assert "curved_passage" in svg  # the full map, not the fog view


def test_a_fight_draws_the_characters_not_the_party_disc_where_they_stand(crypt):
    """In a fight each character is a token of its own (DEL-128): the party's disc goes from the node where the party's
    tokens stand, and stays for a group elsewhere, or a node where only the enemies stand."""
    from delve.maps.tokens import Token

    s = _split(crypt)
    fight = (
        Token("A", "Ana", "room.vestry_alcove", "party"),
        Token("mon_1", "Goblin 1", "room.vestry_alcove", "enemy"),
        Token("mon_2", "Goblin 2", "room.throne_chamber", "enemy"),
    )
    assert _parties(render_view(s, crypt, ["A", "B"], fight)) == ["room.throne_chamber"]
    assert _parties(render_dm(s, crypt, fight)) == ["room.throne_chamber"]
    assert _parties(render_view(s, crypt, ["A", "B"])) == ["room.throne_chamber", "room.vestry_alcove"]


@pytest.fixture
def drawn(monkeypatch):
    """How often a view is drawn."""
    from delve.maps import state as state_module

    state_module.clear_views()
    calls = []
    render = state_module.render_fogged

    def counting(*args, **kwargs):
        calls.append(kwargs.get("full", False))
        return render(*args, **kwargs)

    monkeypatch.setattr(state_module, "render_fogged", counting)
    yield calls
    state_module.clear_views()


def test_a_view_is_drawn_once_for_what_it_shows(crypt, drawn):
    """Every seat redraws the map after every map event (DEL-166): the same view of the same map is drawn once."""
    from delve.maps.tokens import Token

    s = _split(crypt)
    first = render_view(s, crypt, ["A", "B"])
    assert render_view(s, crypt, ["B", "A"]) is first  # the same knowledge, the same discs
    dm = render_dm(s, crypt)
    assert render_dm(s, crypt) is dm
    assert drawn == [False, True]
    # What the view shows changes it: who looks, where they stand, what they found, the fight's tokens, another map.
    render_view(s, crypt, ["A"])
    moved = move(s, crypt, ["A"], "room.entry_hall")
    render_view(moved, crypt, ["A", "B"])
    goblin = [Token("mon_1", "Goblin", "room.throne_chamber", "enemy")]
    with_goblin = render_dm(s, crypt, goblin)
    assert "mon_1" in with_goblin and "mon_1" not in dm
    assert render_dm(s, crypt, goblin) is with_goblin
    render_dm(s, crypt.model_copy())
    assert drawn == [False, True, False, False, True, True]


def test_the_view_cache_is_bounded(crypt, drawn):
    from delve.maps import state as state_module

    s = _split(crypt)
    maps = [crypt.model_copy() for _ in range(state_module.VIEW_CACHE_SIZE + 1)]
    for dmap in maps:
        render_dm(s, dmap)
    render_dm(s, maps[0])  # the oldest was dropped
    assert len(drawn) == state_module.VIEW_CACHE_SIZE + 2


def test_render_view_without_position_raises(crypt):
    s = reveal(MapState.empty(), crypt, ["A"], "room.entry_hall")
    with pytest.raises(NoPosition):
        render_view(s, crypt, ["A"])
    with pytest.raises(NoPosition):
        render_view(s, crypt, ["nobody"])


def test_fog_view_hides_undiscovered_secret_and_marker():
    dmap = parse(PLANTED)
    s = move(MapState.empty(), dmap, ["A"], "room.entry_hall")
    s = move(s, dmap, ["A"], "room.vestry_alcove")  # next to the secret room
    svg = render_view(s, dmap, ["A"])
    assert "SECRET-XYZZY" not in svg
    assert "SECRET-LURKER" not in svg
    assert "hidden_crypt" not in svg
    assert "46,20" not in s.characters["A"].doors  # the secret door stays hidden
    assert "SECRET-LURKER" in render_view(reveal_secret(s, "map/marker:lurker"), dmap, ["A"])
    found = move(s, dmap, ["A"], "room.hidden_crypt")
    assert "SECRET-XYZZY" in render_view(found, dmap, ["A"])
    assert "SECRET-XYZZY" in render_dm(s, dmap)


def test_upgrade_keeps_surviving_and_drops_missing():
    old = parse(PLANTED)
    s = move(MapState.empty(), old, ["A"], "room.vestry_alcove")
    s = move(s, old, ["A"], "room.hidden_crypt")
    s = move(s, old, ["B"], "room.entry_hall")
    s = set_door(s, "46,20", "open")
    s = set_door(s, "15,10", "open")
    s = reveal_secret(s, "map/marker:lurker")
    s = reveal_secret(s, "room.vestry_alcove/feature@49,26")
    new = parse(CRYPT)
    u = upgrade(s, new)
    assert u.characters["A"] == CharacterView(
        None, frozenset({"room.vestry_alcove"}), frozenset({"42,20"}),
    )
    assert u.characters["B"] == s.characters["B"]
    assert u.door_states == {"15,10": "open"}
    assert u.revealed == {"room.vestry_alcove/feature@49,26"}


def test_json_roundtrip(crypt):
    s = set_door(reveal_secret(_split(crypt), "room.entry_hall/feature@10,9"), "15,10", "open")
    s = place(s, crypt, ["C"], "room.throne_chamber")
    s = MapState(characters={**s.characters, "D": CharacterView(None, frozenset(), frozenset())},
                 door_states=s.door_states, revealed=s.revealed)
    raw = to_json(s)
    assert raw["characters"]["A"] == {
        "location": "room.vestry_alcove",
        "nodes": ["room.entry_hall", "room.vestry_alcove"],
        "doors": ["15,10", "42,20"],
        "came_from": "room.entry_hall",  # down the chute from the entry hall (DEL-271)
    }
    assert raw["characters"]["D"] == {"location": None, "nodes": [], "doors": []}
    assert raw["door_states"] == {"15,10": "open"}
    assert raw["revealed"] == ["room.entry_hall/feature@10,9"]
    assert from_json(raw) == s
    assert from_json(to_json(MapState.empty())) == MapState.empty()


def test_unknown_node_lists_candidates():
    dmap = parse(CRYPT + 'room "entry_annex" { rect 5,30 4 x 4 label "Entry" }\n'
                 'corridor "side" { width 1 segment line from 9,32 to 12,32 label "Entry" }\n')
    for op in (place, move, reveal):
        with pytest.raises(UnknownNode) as err:
            op(MapState.empty(), dmap, ["A"], "Entry")
        assert err.value.query == "Entry"
        assert [c["id"] for c in err.value.candidates] == ["corridor.side", "room.entry_annex"]
    with pytest.raises(UnknownNode) as err:
        move(MapState.empty(), dmap, ["A"], "room.nowhere")
    assert err.value.candidates == []


def test_leave_clears_the_location_and_keeps_what_they_know(crypt):
    """A character who goes to another map is no longer on this one (plateau 2a, Task 8)."""
    s = _split(crypt)
    gone = leave(s, ["A", "Z"])  # Z was never on the map
    assert gone.characters["A"].location is None
    assert gone.characters["A"].nodes == s.characters["A"].nodes
    assert gone.characters["B"] == s.characters["B"] and "Z" not in gone.characters
    assert groups(gone, ["A", "B"]) == [("room.throne_chamber", frozenset({"B"}))]


def test_discover_door_for_the_finders_and_whoever_stands_with_them():
    dmap = parse(PLANTED)
    s = move(MapState.empty(), dmap, ["A", "B"], "room.vestry_alcove")
    s = move(s, dmap, ["C"], "room.entry_hall")
    assert "46,20" not in s.characters["A"].doors
    found = discover_door(s, ["A"], "46,20")
    assert "46,20" in found.characters["A"].doors and "46,20" in found.characters["B"].doors  # merged
    assert "46,20" not in found.characters["C"].doors
