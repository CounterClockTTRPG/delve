"""The DM's `leave_party` and `rejoin_party`, and `party_status`'s departed (table voice and fixes Task C2)."""

from delve.dm.tools.redact import player_view
from tests.dm.tools.conftest import GARREK, PIPPA


def test_leave_party_tool(call, host, storage):
    garrek = call("create_character", name="Garrek", sheet=GARREK)
    call("create_character", name="Pippa", sheet=PIPPA)
    out = call("leave_party", character="Garrek", reason="died")
    assert out == {"character_id": garrek["id"], "name": "Garrek", "departure": "died", "left_fight": False}
    assert storage.characters.get(garrek["id"]).departure == "died"
    spec = host.spec("leave_party")
    assert spec.mutates and spec.player_visible
    assert player_view(spec, {"character": "Garrek", "reason": "died"}, out) == {}
    refused = call("leave_party", character="Garrek", reason="died")
    assert "already" in refused["error"]
    assert "error" in call("leave_party", character="Garrek", reason="vanished"), "the schema allows only the three"
    assert "Pippa" in str(call("leave_party", character="Nobody", reason="left").get("candidates"))


def test_rejoin_party_tool(call, host, storage):
    garrek = call("create_character", name="Garrek", sheet=GARREK)
    call("leave_party", character="Garrek", reason="retired")
    assert call("rejoin_party", character="Garrek") == {
        "character_id": garrek["id"],
        "name": "Garrek",
        "departure": None,
    }
    assert storage.characters.get(garrek["id"]).departure is None
    assert "hasn't left" in call("rejoin_party", character="Garrek")["error"]
    spec = host.spec("rejoin_party")
    assert spec.mutates and spec.player_visible


def test_party_lists_departed_apart(call):
    call("create_character", name="Garrek", sheet=GARREK)
    pippa = call("create_character", name="Pippa", sheet=PIPPA)
    call("leave_party", character="Pippa", reason="left")
    status = call("party_status")
    assert [c["name"] for c in status["party"]] == ["Garrek"]
    assert status["marching_order"] == ["Garrek"]
    assert status["departed"] == [{"id": pippa["id"], "name": "Pippa", "departure": "left"}]


def test_leaving_in_a_fight_through_the_tool(call):
    call("create_character", name="Garrek", sheet=GARREK)
    call("create_character", name="Pippa", sheet=PIPPA)
    call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 5}])
    assert call("leave_party", character="Pippa", reason="left")["left_fight"] is True
    fighters = {c["name"]: c for c in call("combat_status")["combatants"]}
    assert "removed" in fighters["Pippa"]["conditions"]
