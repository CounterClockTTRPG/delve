"""`play.moves`: moving on the map through `delve.maps.state`, the room split into perceived and DM-only, doors and room
notes (ttrpg2 `tests/test_rooms.py`, against Delve's per-character map state)."""

import pytest

from delve.dice import ScriptedRng
from delve.domain.modules import ModuleMap
from delve.maps import state as map_state
from delve.play import characters, moves
from delve.play.context import NotFound, PlayError, context_for
from tests.fixtures import SAMPLES
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

# A hidden room behind a secret door off the vestry, its label and the DM's notes planted (Review Focus 4), and in
# the vestry a secret trapdoor and a secret way to the cottage.
CRYPT = (
    (SAMPLES / "crypt.dmap")
    .read_text()
    .replace(
        'room "vestry_alcove" {',
        'room "vestry_alcove" {\n  feature chest at 44,24 id trapdoor_4 { secret description "A trapdoor under the rug." }',
    )
    + """
room "hidden_crypt" {
  rect 44,14 4 x 6
  label "SECRET-XYZZY"
  description "SECRET-XYZZY bones."
  dm_notes "SECRET-XYZZY the ritualist hides here."
}
door at 46,20 { connects room.vestry_alcove, room.hidden_crypt type secret }
exit at 46,26 { to "cottage" at 2,2  secret }
"""
)
COTTAGE = (SAMPLES / "cottage.dmap").read_text()


@pytest.fixture
def ctx(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", CRYPT, is_default=True))
    storage.modules.put_map(module.id, ModuleMap("cottage", "map", COTTAGE, is_default=False))
    campaign = storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng(()), catalogs=over(PlayReference()))
    for name in ("Garrek", "Pippa"):
        characters.create(ctx, name=name, sheet={"hp_max": 8})
    characters.create(ctx, name="Tira", kind="npc", sheet={})
    return ctx


def ids(ctx, *names):
    return [characters.get(ctx, n).id for n in names]


def stored(ctx, name="crypt"):
    raw = ctx.storage.map_states.get(ctx.campaign_id, name)
    return map_state.from_json(raw) if raw else map_state.MapState.empty()


def events(ctx, type):
    return [e.data for e in ctx.storage.events.list(ctx.campaign_id) if e.type == type]


def test_move_updates_map_state_and_logs(ctx):
    """The map is updated in code as part of the move (feature review: "make map updates reliable"), on the
    campaign's default map when none is named, and the move is logged once."""
    garrek, pippa = ids(ctx, "Garrek", "Pippa")
    out = moves.move(ctx, to="Entry Hall")
    state = stored(ctx)
    assert {cid: v.location for cid, v in state.characters.items()} == {
        garrek: "room.entry_hall",
        pippa: "room.entry_hall",
    }
    assert "room.entry_hall" in state.characters[garrek].nodes and "15,10" in state.characters[garrek].doors
    assert out["map"] == "crypt"
    assert out["perceived"]["room"] == "room.entry_hall" and out["perceived"]["label"] == "Entry Hall"
    assert out["groups"] == [
        {
            "location": "room.entry_hall",
            "label": "Entry Hall",
            "characters": [{"id": garrek, "name": "Garrek"}, {"id": pippa, "name": "Pippa"}],
        }
    ]
    assert events(ctx, "moved") == [
        {
            "map": "crypt",
            "node": "room.entry_hall",
            "label": "Entry Hall",
            "characters": [garrek, pippa],
            "names": ["Garrek", "Pippa"],
        }
    ]


def test_split_move_only_named_characters(ctx):
    """Spec §7.4: characters can be in different places, each knowing what they discovered; together again, they
    share it."""
    garrek, pippa = ids(ctx, "Garrek", "Pippa")
    moves.move(ctx, to="room.entry_hall")
    out = moves.move(ctx, to="corridor.main_hall", characters=["Pippa"])
    assert [g["location"] for g in out["groups"]] == ["corridor.main_hall", "room.entry_hall"]
    moves.move(ctx, to="Throne Room", characters=["pippa"])
    state = stored(ctx)
    assert "room.throne_chamber" in state.characters[pippa].nodes
    assert "room.throne_chamber" not in state.characters[garrek].nodes
    moves.move(ctx, to="Throne Room", characters=["Garrek"])
    assert stored(ctx).characters[garrek].nodes == stored(ctx).characters[pippa].nodes
    # an NPC can be moved too
    moves.move(ctx, to="room.entry_hall", characters=["Tira"])
    assert stored(ctx).characters[ids(ctx, "Tira")[0]].location == "room.entry_hall"


def test_move_to_another_map_leaves_the_first(ctx):
    garrek, pippa = ids(ctx, "Garrek", "Pippa")
    moves.move(ctx, to="room.entry_hall")
    out = moves.move(ctx, to="kitchen", map="Cottage", characters=["Garrek"])
    assert out["map"] == "cottage" and stored(ctx, "cottage").characters[garrek].location == "room.kitchen"
    assert stored(ctx).characters[garrek].location is None
    assert stored(ctx).characters[pippa].location == "room.entry_hall"
    assert "room.entry_hall" in stored(ctx).characters[garrek].nodes  # what he knew of the crypt stays
    # the characters on two maps: a move without `map` must say which
    with pytest.raises(PlayError):
        moves.move(ctx, to="room.parlor")
    moves.move(ctx, to="room.parlor", characters=["Garrek"])  # Garrek alone is on the cottage map
    assert stored(ctx, "cottage").characters[garrek].location == "room.parlor"
    with pytest.raises(NotFound) as unknown_map:
        moves.move(ctx, to="kitchen", map="Castle")
    assert unknown_map.value.candidates == [{"name": "crypt"}, {"name": "cottage"}]


def test_unknown_room_moves_nothing_and_offers_candidates(ctx):
    """ttrpg2 `test_unknown_room_moves_nothing_and_offers_candidates`."""
    moves.move(ctx, to="room.entry_hall")
    before = ctx.storage.map_states.list(ctx.campaign_id)
    with pytest.raises(NotFound) as caught:
        moves.move(ctx, to="room.nowhere", map="cottage")
    # Nothing is like "nowhere": the map's rooms, so the DM picks one instead of guessing names.
    assert {"id": "room.kitchen", "label": "Kitchen"} in caught.value.candidates
    assert {c["id"] for c in caught.value.candidates} >= {"room.kitchen", "room.parlor", "room.bedroom"}
    assert ctx.storage.map_states.list(ctx.campaign_id) == before
    assert len(events(ctx, "moved")) == 1


def test_an_unknown_room_offers_the_rooms_whose_name_label_or_description_holds_the_word(ctx):
    with pytest.raises(NotFound) as caught:
        moves.move(ctx, to="flour", map="cottage")  # the kitchen's description: "Flour on every surface."
    assert caught.value.candidates == [{"id": "room.kitchen", "label": "Kitchen"}]
    with pytest.raises(NotFound) as caught:
        moves.move(ctx, to="alcove")  # room "vestry_alcove" on the crypt
    assert [c["id"] for c in caught.value.candidates] == ["room.vestry_alcove"]


def test_room_context_split(ctx):
    """The room the characters enter: `perceived` is what they see, `dm_only` the rest (ttrpg2 `move_party`, dungml's
    `room_context`). An undiscovered room, its label and its notes never reach `perceived`."""
    moves.move(ctx, to="room.vestry_alcove")
    out = moves.room(ctx)
    assert out["perceived"]["room"] == "room.vestry_alcove"
    assert [e["door"] for e in out["dm_only"]["secret_exits"]] == ["46,20"]
    assert "SECRET-XYZZY" not in str(out["perceived"])
    hidden = moves.room(ctx, "room.hidden_crypt")
    assert hidden["perceived"] == {}
    assert hidden["dm_only"]["room"]["label"] == "SECRET-XYZZY"
    assert "SECRET-XYZZY" in hidden["dm_only"]["notes"]
    moves.move(ctx, to="room.throne_chamber", characters=["Pippa"])
    with pytest.raises(PlayError) as apart:
        moves.room(ctx)
    assert "different rooms" in apart.value.message
    assert moves.room(ctx, characters=["Pippa"])["perceived"]["room"] == "room.throne_chamber"


def test_a_secret_found_is_revealed(ctx):
    """Plan Task 22b: `door(found=True)` also takes the key of a secret feature or exit of the party's map, and
    reveals it for everyone. The players' fog view shows it only once it is found."""
    garrek, pippa = ids(ctx, "Garrek", "Pippa")
    moves.move(ctx, to="room.vestry_alcove")
    dmap, _ = moves._parse(moves._revision(ctx), "crypt")
    before = map_state.render_view(stored(ctx), dmap, [garrek, pippa])
    vestry = moves.room(ctx)
    assert "trapdoor_4" in [s["key"] for s in vestry["dm_only"]["secrets"]]
    assert "A trapdoor under the rug." not in str(vestry["perceived"])
    assert vestry["perceived"]["map_exits"] == []

    out = moves.door(ctx, "trapdoor_4", found=True)
    assert (out["map"], out["secret"], out["kind"], out["revealed"]) == ("crypt", "trapdoor_4", "feature", True)
    exit = moves.door(ctx, "map/exit@46,26", found=True)
    assert (exit["secret"], exit["kind"]) == ("map/exit@46,26", "exit")
    assert stored(ctx).revealed == {"trapdoor_4", "map/exit@46,26"}
    assert [(e["secret"], e["found"]) for e in events(ctx, "door")] == [("trapdoor_4", True), ("map/exit@46,26", True)]

    vestry = moves.room(ctx)
    assert {"name": "chest", "description": "A trapdoor under the rug."} in vestry["perceived"]["features"]
    assert [x["target_map"] for x in vestry["perceived"]["map_exits"]] == ["cottage"]
    assert map_state.render_view(stored(ctx), dmap, [garrek, pippa]) != before


def test_a_secret_needs_found(ctx):
    """A secret has no door state; a key that is neither a door nor a secret lists nothing to guess from."""
    moves.move(ctx, to="room.vestry_alcove")
    with pytest.raises(PlayError, match="secret"):
        moves.door(ctx, "trapdoor_4", state="open")
    with pytest.raises(NotFound):
        moves.door(ctx, "trapdoor_9", found=True)
    assert stored(ctx).revealed == frozenset()


def test_room_notes_come_back_on_every_visit(ctx):
    """ttrpg2 `test_note_room_round_trips` and `test_move_returns_that_rooms_notes`."""
    moves.move(ctx, to="room.entry_hall")
    note = moves.note_room(ctx, "Horse tied here.")
    assert note["room"] == "room.entry_hall" and note["note"]["text"] == "Horse tied here."
    moves.note_room(ctx, "Chest looted.", query="Throne Room")
    moves.move(ctx, to="corridor.main_hall")
    back = moves.move(ctx, to="room.entry_hall")
    assert [n["text"] for n in back["room_notes"]] == ["Horse tied here."]
    assert [n["text"] for n in moves.room(ctx, "room.throne_chamber")["room_notes"]] == ["Chest looted."]
    with pytest.raises(NotFound):
        moves.note_room(ctx, "Nowhere.", query="room.nowhere")


def test_door_states(ctx):
    """ttrpg2 `door`: a door's state is the world's, shared by everyone; it is named by its key or by the room it
    leads to from the characters' room. A state recorded also marks the door as seen."""
    moves.move(ctx, to="room.entry_hall")
    out = moves.door(ctx, "corridor.main_hall", state="open")
    assert (out["door"], out["state"], out["discovered"]) == ("15,10", "open", True)
    assert stored(ctx).door_states == {"15,10": "open"}
    moves.door(ctx, "17,10", state="forced")
    assert stored(ctx).door_states == {"15,10": "open", "17,10": "forced"}
    assert [e["door"] for e in events(ctx, "door")] == ["15,10", "17,10"]
    with pytest.raises(PlayError):
        moves.door(ctx, "15,10")  # nothing to record
    with pytest.raises(NotFound):
        moves.door(ctx, "99,99", state="open")
    with pytest.raises(NotFound):
        moves.door(ctx, "room.vestry_alcove", state="open")  # no door from the entry hall to the vestry


def test_secret_door_found(ctx):
    """A found secret door is known to the characters who found it and those with them; it moves from the DM's
    `secret_exits` to the perceived exits."""
    garrek, pippa = ids(ctx, "Garrek", "Pippa")
    moves.move(ctx, to="room.vestry_alcove", characters=["Garrek"])
    moves.move(ctx, to="room.entry_hall", characters=["Pippa"])
    out = moves.door(ctx, "46,20", found=True)
    assert out["discovered"] is True and out["found_by"] == [garrek]
    state = stored(ctx)
    assert "46,20" in state.characters[garrek].doors and "46,20" not in state.characters[pippa].doors
    vestry = moves.room(ctx, characters=["Garrek"])
    assert [e["door"] for e in vestry["perceived"]["exits"] if e["door"] == "46,20"] == ["46,20"]
    assert vestry["dm_only"]["secret_exits"] == []
    # the far side is still unexplored: its name stays DM-only
    assert "SECRET-XYZZY" not in str(vestry["perceived"])
