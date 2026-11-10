"""Map state per character, against the campaign's pinned revision (plateau 1, Task 7)."""

import re

from delve.domain.modules import ModuleMap
from tests.fixtures.rulesets import over
from tests.web.test_campaigns_api import (
    CRYPT,
    MAP,
    campaign,
    character,
    characters_view,
    crypt_module,
    move,
    played,
    state_path,
)
from tests.web.test_preferences_api import published

# A secret room behind a secret door in the vestry, with a marker in it, and a secret marker in the entry hall.
PLANTED = (
    CRYPT
    + """
room "hidden_crypt" {
  rect 44,14 4 x 6
  label "SECRET-XYZZY"
}
door at 46,20 { connects room.vestry_alcove, room.hidden_crypt type secret }
marker "ritualist" at 46,17 label "SECRET-XYZZY" in room.hidden_crypt
marker "lurker" at 8,8 label "SECRET-LURKER" secret
"""
)
# A second room labelled "Vestry", so the label names two nodes.
TWO_VESTRIES = CRYPT + '\nroom "annex" {\n  rect 44,14 4 x 6\n  label "Vestry"\n}\n'
WITH_START = CRYPT.replace("  legend\n", '  legend\n  party_start "entry_hall"\n', 1)


def parties(svg: str) -> list[str]:
    return re.findall(r'<g class="party" data-node="([^"]*)"', svg)


def dm_view(local, campaign_id: str):
    return local.get(f"{state_path(campaign_id)}/dm-view")


def test_move_and_view(local):
    started, (ana, bo) = played(local)
    response = move(local, started["id"], [ana, bo], "room.entry_hall")
    assert response.status_code == 200
    state = response.json()
    assert state["characters"][ana] == {
        "location": "room.entry_hall",
        "nodes": ["room.entry_hall"],
        "doors": state["characters"][ana]["doors"],
    }
    assert "15,10" in state["characters"][ana]["doors"]
    assert state["characters"][bo] == state["characters"][ana]
    assert state["door_states"] == {}
    assert state["revealed"] == []
    assert state["groups"] == [{"location": "room.entry_hall", "characters": sorted([ana, bo])}]
    assert local.get(f"{state_path(started['id'])}/state").json() == state

    view = characters_view(local, started["id"], [ana, bo])
    assert view.status_code == 200
    assert set(view.json()) == {"svg"}
    assert parties(view.json()["svg"]) == ["room.entry_hall"]
    assert "Entry Hall" in view.json()["svg"]
    assert "Throne Room" not in view.json()["svg"]


def test_state_of_a_new_map_is_empty(local):
    started, _ = played(local)
    state = local.get(f"{state_path(started['id'])}/state").json()
    assert state == {"characters": {}, "door_states": {}, "revealed": [], "groups": []}


def test_split_party_views_differ_and_merge_on_meeting(local):
    started, (ana, bo) = played(local)
    cid = started["id"]
    move(local, cid, [ana, bo], "room.entry_hall")
    move(local, cid, [bo], "corridor.main_hall")
    move(local, cid, [bo], "room.throne_chamber")
    split = move(local, cid, [ana], "room.vestry_alcove").json()  # down the chute
    assert split["groups"] == [
        {"location": "room.throne_chamber", "characters": [bo]},
        {"location": "room.vestry_alcove", "characters": [ana]},
    ]

    ana_view = characters_view(local, cid, [ana]).json()["svg"]
    bo_view = characters_view(local, cid, [bo]).json()["svg"]
    assert ana_view != bo_view
    assert parties(ana_view) == ["room.vestry_alcove"]
    assert parties(bo_view) == ["room.throne_chamber"]
    assert "Throne Room" in bo_view and "Throne Room" not in ana_view
    assert "Vestry" in ana_view and "Vestry" not in bo_view
    both = characters_view(local, cid, [ana, bo]).json()["svg"]
    assert parties(both) == ["room.throne_chamber", "room.vestry_alcove"]
    assert sorted(parties(dm_view(local, cid).json()["svg"])) == ["room.throne_chamber", "room.vestry_alcove"]

    move(local, cid, [ana], "corridor.curved_passage")
    met = move(local, cid, [ana], "room.throne_chamber").json()
    known = {"room.entry_hall", "corridor.main_hall", "room.throne_chamber", "room.vestry_alcove",
             "corridor.curved_passage"}
    assert set(met["characters"][ana]["nodes"]) == known
    # They know the same, and each came in its own way (DEL-271).
    known_by = {cid: {k: v for k, v in met["characters"][cid].items() if k != "came_from"} for cid in (ana, bo)}
    assert known_by[bo] == known_by[ana]
    assert (met["characters"][ana]["came_from"], met["characters"][bo]["came_from"]) == (
        "corridor.curved_passage", "corridor.main_hall"
    )
    assert met["groups"] == [{"location": "room.throne_chamber", "characters": sorted([ana, bo])}]
    assert characters_view(local, cid, [bo]).json()["svg"] == characters_view(local, cid, [ana]).json()["svg"]


def test_view_without_position_409_map_offline(local):
    started, (ana, bo) = played(local)
    cid = started["id"]
    for params in ({"characters": ana}, {"characters": ""}, {}, {"characters": "chr_000000000000"}):
        response = local.get(f"{state_path(cid)}/view", params=params)
        assert response.status_code == 409, params
        assert response.json() == {"error": "map offline"}
    move(local, cid, [bo], "room.entry_hall")
    assert characters_view(local, cid, [ana]).json() == {"error": "map offline"}
    assert characters_view(local, cid, [ana, bo]).status_code == 200


def test_broken_pinned_map_409(local, storage):
    module = crypt_module(local)
    storage.modules.put_map(module["id"], ModuleMap(MAP, "map", 'map "Broken" {\n  grid {\n', True))
    started = campaign(local, module["id"])
    ana = character(local, started["id"], "Ana")["id"]
    storage.map_states.put(started["id"], MAP, {"characters": {ana: {"location": "room.entry_hall"}}})

    for response in (
        characters_view(local, started["id"], [ana]),
        dm_view(local, started["id"]),
        move(local, started["id"], [ana], "room.entry_hall"),
        local.post(f"{state_path(started['id'])}/start", json={"characters": [ana]}),
        local.post(f"{state_path(started['id'])}/reveal", json={"characters": [ana], "node": "room.entry_hall"}),
    ):
        assert response.status_code == 409
        assert response.json() == {"error": "map offline"}
    assert local.get(f"{state_path(started['id'])}/state").status_code == 200


def test_view_never_contains_planted_secret(local):
    started, (ana,) = played(local, PLANTED, names=("Ana",))
    cid = started["id"]
    move(local, cid, [ana], "room.entry_hall")
    move(local, cid, [ana], "room.vestry_alcove")
    view = characters_view(local, cid, [ana]).json()["svg"]
    assert "Vestry" in view
    assert "SECRET-XYZZY" not in view
    assert "SECRET-LURKER" not in view
    assert "hidden_crypt" not in view

    dm = dm_view(local, cid).json()["svg"]
    assert "SECRET-XYZZY" in dm, "the planted secret is on the map"

    local.post(f"{state_path(cid)}/reveal", json={"characters": [ana], "node": "room.hidden_crypt"})
    assert "SECRET-XYZZY" in characters_view(local, cid, [ana]).json()["svg"]


def test_view_has_no_dm_switch(local):
    started, (ana, _) = played(local, PLANTED)
    cid = started["id"]
    move(local, cid, [ana], "room.entry_hall")
    plain = local.get(f"{state_path(cid)}/view?characters={ana}")
    assert plain.status_code == 200
    for switch in ("scope=gm", "full=1", "view=dm", "scope=dm", "full=true", "dm=1"):
        response = local.get(f"{state_path(cid)}/view?characters={ana}&{switch}")
        assert response.status_code == 200
        assert response.content == plain.content, switch
    assert "SECRET-XYZZY" not in plain.text


def test_unknown_node_404_candidates(local):
    started, (ana, _) = played(local, TWO_VESTRIES)
    cid = started["id"]
    for path, body in (
        ("move", {"characters": [ana], "to": "Vestry"}),
        ("reveal", {"characters": [ana], "node": "Vestry"}),
    ):
        response = local.post(f"{state_path(cid)}/{path}", json=body)
        assert response.status_code == 404
        assert response.json() == {
            "error": "unknown node 'Vestry'",
            "candidates": [{"id": "room.annex", "label": "Vestry"}, {"id": "room.vestry_alcove", "label": "Vestry"}],
        }
    nowhere = move(local, cid, [ana], "nowhere")
    assert nowhere.status_code == 404
    assert nowhere.json() == {"error": "unknown node 'nowhere'", "candidates": []}
    assert local.get(f"{state_path(cid)}/state").json()["characters"] == {}
    assert move(local, cid, [ana], "Entry Hall").json()["characters"][ana]["location"] == "room.entry_hall"


def test_unknown_map_404(local):
    started, (ana, _) = played(local)
    for response in (
        local.get(f"{state_path(started['id'], 'nowhere')}/state"),
        local.get(f"{state_path(started['id'], 'nowhere')}/view", params={"characters": ana}),
        local.get(f"{state_path(started['id'], 'nowhere')}/dm-view"),
        local.post(f"{state_path(started['id'], 'nowhere')}/move", json={"characters": [ana], "to": "x"}),
    ):
        assert response.status_code == 404
        assert response.json() == {"error": "No such map."}


def test_moves_only_the_campaigns_characters(local):
    started, (ana, _) = played(local)
    _, (stranger,) = played(local, names=("Stranger",))
    for characters in ([stranger], [ana, stranger], ["chr_000000000000"], []):
        response = move(local, started["id"], characters, "room.entry_hall")
        assert response.status_code == 400, characters
        assert "error" in response.json()
    assert local.get(f"{state_path(started['id'])}/state").json()["characters"] == {}


def test_start_places_at_party_start(local):
    started, (ana, bo) = played(local, WITH_START)
    response = local.post(f"{state_path(started['id'])}/start", json={"characters": [ana, bo]})
    assert response.status_code == 200
    state = response.json()
    assert state["characters"][ana]["location"] == "room.entry_hall"
    assert state["characters"][ana]["nodes"] == ["room.entry_hall"]
    assert state["groups"] == [{"location": "room.entry_hall", "characters": sorted([ana, bo])}]


def test_reveal_door_and_secret(local):
    started, (ana, bo) = played(local, PLANTED)
    cid = started["id"]
    move(local, cid, [ana, bo], "room.entry_hall")

    revealed = local.post(f"{state_path(cid)}/reveal", json={"characters": [bo], "node": "room.throne_chamber"})
    assert revealed.status_code == 200
    state = revealed.json()
    assert state["characters"][bo]["location"] == "room.entry_hall", "reveal doesn't move"
    assert "room.throne_chamber" in state["characters"][bo]["nodes"]
    assert "room.throne_chamber" in state["characters"][ana]["nodes"], "together, they share what they know"

    door = local.post(f"{state_path(cid)}/door", json={"door": "15,10", "state": "open"})
    assert door.status_code == 200
    assert door.json()["door_states"] == {"15,10": "open"}
    unknown_door = local.post(f"{state_path(cid)}/door", json={"door": "1,1", "state": "open"})
    assert unknown_door.status_code == 404
    assert unknown_door.json() == {"error": "unknown door '1,1'"}

    assert "SECRET-LURKER" not in characters_view(local, cid, [ana]).json()["svg"]
    key = "map/marker:lurker"
    secret = local.post(f"{state_path(cid)}/secret", json={"key": key})
    assert secret.status_code == 200
    assert secret.json()["revealed"] == [key]
    assert "SECRET-LURKER" in characters_view(local, cid, [ana]).json()["svg"]
    unknown_secret = local.post(f"{state_path(cid)}/secret", json={"key": "map/marker:nobody"})
    assert unknown_secret.status_code == 404
    assert unknown_secret.json() == {"error": "unknown secret 'map/marker:nobody'"}


def test_map_state_event_published(local, app):
    started, (ana, bo) = played(local, PLANTED)
    cid = started["id"]
    before = len(published(app))
    move(local, cid, [ana], "room.entry_hall")
    local.post(f"{state_path(cid)}/start", json={"characters": [bo]})
    local.post(f"{state_path(cid)}/reveal", json={"characters": [ana], "node": "room.throne_chamber"})
    local.post(f"{state_path(cid)}/door", json={"door": "15,10", "state": "open"})
    local.post(f"{state_path(cid)}/secret", json={"key": "map/marker:lurker"})
    characters_view(local, cid, [ana])
    dm_view(local, cid)
    local.get(f"{state_path(cid)}/state")
    move(local, cid, [ana], "nowhere")
    events = [(e.type, e.data) for e in published(app)[before:]]
    assert events == [("map_state", {"campaign_id": cid, "map": MAP})] * 5


def _tokens(svg: str) -> list[str]:
    return re.findall(r'<g class="marker" data-name="([^"]*)"', svg)


def test_views_draw_the_live_fight_tokens_fog_safe(local, storage):
    """Plateau 2a, Task 7: the views draw the live fight's tokens. The fog view never shows one in a room the
    characters haven't discovered; the DM view shows them all."""
    from delve.dice import ScriptedRng
    from delve.play import combat
    from delve.play.context import context_for
    from tests.fixtures.play_reference import PlayReference

    started, (ana, bo) = played(local)
    move(local, started["id"], [ana, bo], "room.entry_hall")
    rat = {"name": "rat", "hp": 1, "ac": 7, "thac0": 20, "dmg": "1d3"}
    goblin = {"name": "goblin", "hp": 5, "ac": 6, "thac0": 20, "dmg": "1d6", "node": "room.throne_chamber"}
    ctx = context_for(storage, started["id"], "beat-1", ScriptedRng([1, 1]), catalogs=over(PlayReference()))
    combat.setup_combat(ctx, enemies=[rat, goblin], surprise=False)

    fogged = characters_view(local, started["id"], [ana, bo]).json()["svg"]
    assert sorted(_tokens(fogged)) == sorted([ana, bo, "mon_1"])
    assert "Goblin" not in fogged
    dm = dm_view(local, started["id"]).json()["svg"]
    assert sorted(_tokens(dm)) == sorted([ana, bo, "mon_1", "mon_2"])

    combat.end_combat(context_for(storage, started["id"], "beat-2", catalogs=over(PlayReference())))
    assert _tokens(characters_view(local, started["id"], [ana, bo]).json()["svg"]) == []


def test_doors_and_secrets_of_the_pinned_map(local, storage):
    """Open fixes Task 3: the host's door and secret pickers list the pinned map's doors and secrets, revealed or not,
    on an organiser route; a map that doesn't parse is offline."""
    started, _ = played(local, PLANTED)
    response = local.get(f"{state_path(started['id'])}/doors-and-secrets")
    assert response.status_code == 200
    listed = response.json()
    doors = {door["key"]: door for door in listed["doors"]}
    assert doors["15,10"]["nodes"] == ["room.entry_hall", "corridor.main_hall"]
    assert doors["46,20"] == {"key": "46,20", "type": "secret", "nodes": ["room.vestry_alcove", "room.hidden_crypt"]}
    secrets = {secret["key"]: secret for secret in listed["secrets"]}
    assert secrets["map/marker:lurker"] == {
        "key": "map/marker:lurker",
        "kind": "marker",
        "label": "lurker",
        "node": secrets["map/marker:lurker"]["node"],
    }

    module = crypt_module(local)
    storage.modules.put_map(module["id"], ModuleMap(MAP, "map", 'map "Broken" {\n  grid {\n', True))
    broken = campaign(local, module["id"])
    assert local.get(f"{state_path(broken['id'])}/doors-and-secrets").json() == {"error": "map offline"}
    assert local.get(f"{state_path('cmp_000000000000')}/doors-and-secrets").status_code == 404
