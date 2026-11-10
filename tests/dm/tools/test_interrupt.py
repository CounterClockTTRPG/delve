"""The DM's `interrupt` (table voice and fixes Task B1.3): it breaks an ongoing action, its result splits what the
characters perceive from what only the DM knows, and the players' feed shows nothing of it but its name."""

import json

from delve.dm.tools.redact import player_view
from tests.dm.tools.conftest import SECRET


def test_interrupt_tool_perceived(call, party, host):
    call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 5}], surprise=False)
    call("combat_round", actions=[{"actor": "Garrek", "action": "digs out the horn", "rounds": 2}])
    out = call("interrupt", combatant="Garrek", reason="Garrek was hit")
    assert out == {
        "id": party[0]["id"],
        "name": "Garrek",
        "kind": "other",
        "perceived": "Garrek was hit; digs out the horn is lost",
        "dm_only": {},
    }
    status = call("combat_status")
    garrek = next(c for c in status["combatants"] if c["name"] == "Garrek")
    assert (garrek["ongoing"]["state"], garrek["ongoing"]["reason"]) == ("interrupted", "Garrek was hit")
    spec = host.spec("interrupt")
    assert spec.mutates and spec.player_visible
    assert player_view(spec, {"combatant": "Garrek", "reason": "Garrek was hit"}, out) == {}


def test_interrupt_refuses_without_ongoing_or_reason(call, party):
    call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 5}], surprise=False)
    refused = call("interrupt", combatant="Garrek", reason="Garrek was hit")
    assert refused["error"] == "Garrek has nothing under way to interrupt." and "combat_status" in refused["hint"]
    assert "error" in call("interrupt", combatant="Garrek")  # reason is required by the schema
    assert "error" in call("interrupt", combatant="Garrek", reason="x", extra=1)


def test_interrupt_passes_fourth_wall(call, party, host):
    """An enemy's spell stays the DM's (Decision 10): its name, planted as the secret, is in dm_only, never in what
    the characters perceive, nor in the players' view."""
    call("setup_combat", enemies=[{"name": "goblin", "count": 1, "hp": 5}], surprise=False)
    call("combat_round", actions=[{"actor": "Goblin", "action": SECRET, "rounds": 3}])
    out = call("interrupt", combatant="Goblin", reason="The goblin is knocked down")
    assert out["perceived"] == "The goblin is knocked down; its action is lost"
    assert out["dm_only"] == {"what": SECRET}
    assert SECRET not in json.dumps(out["perceived"])
    assert SECRET not in json.dumps(player_view(host.spec("interrupt"), {}, out))
