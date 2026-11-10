"""The initiative timeline's route and events, per seat (table voice and fixes Tasks B2.1, B2.2), and the fourth wall
for both: a `SECRET-XYZZY` is an unseen monster's name, its spell and its spell's reason for breaking, and a seen
monster's spell. No seat reads it, through `GET …/timeline` or the event stream and its replay.

The table is the fourth wall's (`tests/web/test_fourth_wall_per_seat.py`): Ana plays Garrek, Bo plays Tira, Cy
observes, all in the crypt's entry hall."""

import asyncio
import json
from dataclasses import replace

from fastapi.testclient import TestClient

from delve.dice import SeededRng
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.play import combat
from delve.play.context import context_for
from delve.rules.classic import combat as rules
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.combat import CombatReference
from tests.fixtures.rulesets import over
from tests.web.conftest import BASE_URL
from tests.web.test_fourth_wall_per_seat import (  # noqa: F401  (the fixtures)
    act_and_wait,
    dm,
    read_until,
    registries,
    table,
)

SECRET = "SECRET-XYZZY"
GOBLINS = {"name": "goblin", "count": 2, "hp": 5, "ac": 6, "thac0": 20, "dmg": "1d6", "weapon_speed": 6}


def spell(what: str) -> dict:
    return {
        "kind": "spell",
        "what": what,
        "started_round": 1,
        "started_count": 1,
        "completes_round": 1,
        "completes_count": 9,
        "state": "ongoing",
        "reason": None,
    }


def a_fight(storage, cid: str, *, resolve: bool = False) -> str:
    """Two goblins against the party: Goblin 1 in the entry hall, casting a secret spell; Goblin 2, named the secret,
    in the hidden crypt nobody has found, casting it too. With `resolve`, round 1 is resolved and not yet released,
    and the secret is the reason Goblin 2's spell broke."""
    ctx = context_for(storage, cid, "beat-x", SeededRng(7), catalogs=over(CombatReference()))
    combat.setup_combat(ctx, enemies=[GOBLINS], surprise=False)
    if resolve:
        combat.combat_round(ctx, [])
    id, raw = storage.combats.live(cid)
    fight = rules.from_json(raw)
    nodes = {"mon_1": "room.entry_hall", "mon_2": "room.hidden_crypt"}
    combatants = {k: replace(c, node=nodes.get(k, c.node)) for k, c in fight.combatants.items()}
    fight = replace(fight, combatants=combatants, declared={"mon_2": {"spell": SECRET}})
    storage.combats.save(id, fight.phase, rules.to_json(fight))
    row = storage.combat_rounds.latest(id)

    def planted(slot: dict) -> dict:
        if slot["side"] == "party":
            return slot
        name = SECRET if slot["id"] == "mon_2" else slot["name"]
        return {**slot, "name": name, "node": nodes[slot["id"]], "ongoing": spell(SECRET)}

    outcomes = row.outcomes
    if outcomes is not None:
        outcomes = {**outcomes, "interrupted": [{"id": "mon_2", "what": SECRET, "reason": SECRET}]}
    storage.combat_rounds.put(replace(row, slots=tuple(planted(dict(s)) for s in row.slots), outcomes=outcomes))
    return id


def timeline(client, cid: str):
    response = client.get(f"/api/campaigns/{cid}/timeline")
    assert response.status_code == 200, response.json()
    return response.json()


def test_without_a_fight_every_seat_reads_null(local, table):  # noqa: F811
    cid = table["campaign"]
    for client in (local, table["Ana"][1], table["Bo"][1], table["Cy"][1]):
        assert timeline(client, cid) == {"fight": None}


def test_each_seat_reads_its_own_timeline(app, local, storage, table):  # noqa: F811
    cid = table["campaign"]
    id = a_fight(storage, cid)
    for client in (local, table["Ana"][1], table["Bo"][1]):
        fight = timeline(client, cid)["fight"]
        assert fight["combat_id"] == id and fight["round"] == 1 and fight["released"] is False
        names = {s["key"]: s["name"] for s in fight["slots"]}
        assert names["mon_1"] == "Goblin 1" and names["unseen-1"] is None
        assert {table["garrek"], table["tira"]} <= set(names)
        seen = next(s for s in fight["slots"] if s["key"] == "mon_1")
        assert seen["ongoing"]["kind"] == "spell" and seen["ongoing"]["what"] is None
        assert SECRET not in json.dumps(fight) and "mon_2" not in json.dumps(fight)
    assert timeline(table["Cy"][1], cid) == {"fight": None}


def test_a_player_none_of_whose_characters_fights_reads_null(app, storage, table):  # noqa: F811
    cid = table["campaign"]
    a_fight(storage, cid)
    token = new_seat_token()
    storage.seats.create(cid, "Dee", "en", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as dee:
        dee.cookies.set(SEAT_COOKIE, token)
        assert timeline(dee, cid) == {"fight": None}


def test_another_tables_seat_is_refused(app, local, storage, table):  # noqa: F811
    module_id = storage.campaigns.get(table["campaign"]).module_id
    other = local.post("/api/campaigns", json={"name": "Elsewhere", "module_id": module_id}).json()
    a_fight(storage, table["campaign"])
    response = table["Ana"][1].get(f"/api/campaigns/{other['id']}/timeline")
    assert response.status_code in (403, 404)
    assert "error" in response.json()


def test_the_events_and_their_replay_carry_nothing_of_the_dms(app, local, dm, storage, table):  # noqa: F811
    """A beat whose DM resolved round 1 and narrated it: the stream says `initiative`, then `outcomes`, to every seat,
    with no name in them; each seat's timeline after it shows the outcomes and never the secret."""
    cid = table["campaign"]
    id = a_fight(storage, cid, resolve=True)
    dm.then(ToolCall("c1", "combat_round", {"actions": []}), ToolResult("c1", True, "{}"), TextDelta("Steel rings."))
    last = act_and_wait(app, local, cid)

    for name, cookie in (("owner", None), ("Ana", table["Ana"][2]), ("Bo", table["Bo"][2]), ("Cy", table["Cy"][2])):
        frames = [f for f in asyncio.run(read_until(app, "/api/events?since=0", last, cookie)) if "event: timeline" in f]
        changes = [json.loads(f.split("data: ", 1)[1])["change"] for f in frames]
        assert changes == ["initiative", "outcomes"], name
        for frame in frames:
            data = json.loads(frame.split("data: ", 1)[1])
            assert set(data) == {"campaign_id", "combat_id", "round", "change"}, name
            assert data["combat_id"] == id and data["round"] == 1
        assert SECRET not in "\n".join(frames) and "Goblin" not in "\n".join(frames), name

    for client in (local, table["Ana"][1], table["Bo"][1]):
        fight = timeline(client, cid)["fight"]
        assert fight["released"] is True
        hidden = next(s for s in fight["slots"] if s["key"] == "unseen-1")
        assert hidden["ongoing"] is None and hidden["name"] is None
        assert SECRET not in json.dumps(fight)
