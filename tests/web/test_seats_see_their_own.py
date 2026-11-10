"""What a seat gets of the table's state (the fourth-wall audit of plan 4): where the groups are and the fight only
for the groups its characters are in, an NPC as a name and nothing more, the owner's seat that nobody else takes
down, and Cancel for the host and co-hosts only.

At the planted crypt (`table`: Ana plays Garrek, Bo plays Tira, Cy observes), Garrek finds the hidden crypt, whose
label holds `SECRET-XYZZY`, while Tira stays in the entry hall.
"""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.dice import SeededRng
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.domain.backends import Registry
from delve.play import combat
from delve.play.context import context_for
from delve.rules.catalog import register_rulesets
from delve.rules.classic import combat as rules
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.combat import CombatReference
from tests.fixtures.rulesets import over
from tests.web.conftest import BASE_URL, make_registries
from tests.web.test_campaigns_api import move
from tests.web.test_fourth_wall_per_seat import table  # noqa: F401  (the fixture)
from tests.web.test_map_state_api import state_path

SECRET = "SECRET-XYZZY"


@pytest.fixture
def registries():
    """The web fakes, with OSRIC over a small reference, so the state has a primer with the positions."""
    registries = make_registries()
    registries.dm = Registry()
    dm = FakeDM([])
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    registries.rulesets = Registry()
    registries.catalogs = over(CombatReference(goblins=True))
    register_rulesets(registries.rulesets, registries.catalogs.rulesets)
    return registries


@pytest.fixture
def split(local, table):  # noqa: F811
    """Garrek goes into the hidden crypt; Tira stays in the entry hall."""
    cid, garrek = table["campaign"], table["garrek"]
    assert move(local, cid, [garrek], "room.vestry_alcove").status_code == 200
    revealed = local.post(f"{state_path(cid)}/reveal", json={"characters": [garrek], "node": "room.hidden_crypt"})
    assert revealed.status_code == 200, revealed.text
    assert move(local, cid, [garrek], "room.hidden_crypt").status_code == 200
    return table


def state(client, cid: str) -> dict:
    response = client.get(f"/api/campaigns/{cid}/play/state")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_host_sees_every_group(local, split):
    """The host's single-player switcher shows every group."""
    positions = state(local, split["campaign"])["positions"]
    assert sorted(p["location"] for p in positions) == ["room.entry_hall", "room.hidden_crypt"]
    assert SECRET in json.dumps(positions)


def test_a_player_sees_only_their_own_groups(split):
    cid = split["campaign"]
    _, ana, _ = split["Ana"]
    _, bo, _ = split["Bo"]
    assert [(p["location"], p["characters"]) for p in state(ana, cid)["positions"]] == [
        ("room.hidden_crypt", ["Garrek"])
    ]
    bos = state(bo, cid)["positions"]
    assert [(p["location"], p["characters"]) for p in bos] == [("room.entry_hall", ["Tira"])]
    assert SECRET not in json.dumps(bos)


def test_an_observer_sees_no_group(split):
    _, cy, _ = split["Cy"]
    assert state(cy, split["campaign"])["positions"] == []


def test_a_player_sees_the_fight_only_when_their_characters_fight(app, local, storage, split):
    """The whole party joins a fight; a PC claimed later isn't in it, and neither is its player's view of it."""
    cid = split["campaign"]
    ctx = context_for(storage, cid, "beat-1", SeededRng(4), catalogs=over(CombatReference(goblins=True)))
    combat.setup_combat(ctx, enemies=[{"name": "goblin", "count": 2}], surprise=False)
    _, ana, _ = split["Ana"]
    _, cy, _ = split["Cy"]
    assert state(local, cid)["combat"]["round"] == 1
    assert state(ana, cid)["combat"]["round"] == 1
    assert state(cy, cid)["combat"] is None

    token = new_seat_token()
    dee = storage.seats.create(cid, "Dee", "en", "player", token_hash=token_hash(token))
    storage.seats.set_controller(storage.characters.create(cid, "Hob").id, dee.id)
    with TestClient(app, base_url=BASE_URL) as client:
        client.cookies.set(SEAT_COOKIE, token)
        assert state(client, cid)["combat"] is None


def test_an_npc_reaches_a_seat_as_its_name_alone(local, storage, table):  # noqa: F811
    """An allow-list: id, name and kind. Never its background, alignment, state or portrait prompt."""
    cid = table["campaign"]
    grik = storage.characters.get(table["grik"])
    sheet = replace(grik.sheet, background=f"{SECRET}: a cult spy", alignment="chaotic evil", portrait_prompt=SECRET)
    storage.characters.save(replace(grik, sheet=sheet))
    for client in (local, table["Ana"][1], table["Cy"][1]):
        listed = client.get(f"/api/campaigns/{cid}/characters").json()
        assert next(c for c in listed if c["id"] == grik.id) == {"id": grik.id, "name": "Grik", "kind": "npc"}
        assert SECRET not in json.dumps(listed)
        pc = next(c for c in listed if c["id"] == table["garrek"])
        assert {"sheet", "state", "order", "encumbrance"} <= pc.keys(), "PCs are unchanged"


def test_nobody_but_the_owner_takes_the_owners_seat_down(local, storage, table):  # noqa: F811
    cid = table["campaign"]
    ana_seat, ana, _ = table["Ana"]
    owner = storage.seats.owner_seat(cid)
    assert local.put(f"/api/campaigns/{cid}/seats/{ana_seat.id}", json={"role": "host"}).status_code == 200
    for role in ("observer", "player"):
        refused = ana.put(f"/api/campaigns/{cid}/seats/{owner.id}", json={"role": role})
        assert refused.status_code == 403
        assert refused.json() == {"error": "Only the owner can change the owner's seat to that role."}
    assert storage.seats.get(owner.id).role == "cohost"

    # The owner steps down by their own choice, and takes the host role back at any time.
    assert local.put(f"/api/campaigns/{cid}/seats/{owner.id}", json={"role": "observer"}).status_code == 200
    back = local.put(f"/api/campaigns/{cid}/seats/{owner.id}", json={"role": "host"})
    assert back.status_code == 200, back.text
    assert back.json()["role"] == "host" and storage.seats.get(ana_seat.id).role == "cohost"
    assert local.post(f"/api/campaigns/{cid}/invite", json={}).status_code != 403


def test_cancel_is_for_the_host_and_co_hosts(local, storage, table):  # noqa: F811
    cid = table["campaign"]
    for name in ("Ana", "Cy"):
        refused = table[name][1].post(f"/api/campaigns/{cid}/cancel", json={})
        assert refused.status_code == 403, name
    assert local.post(f"/api/campaigns/{cid}/cancel", json={}).json() == {"cancelled": False}
    ana_seat, ana, _ = table["Ana"]
    assert local.put(f"/api/campaigns/{cid}/seats/{ana_seat.id}", json={"role": "cohost"}).status_code == 200
    assert ana.post(f"/api/campaigns/{cid}/cancel", json={}).json() == {"cancelled": False}


def test_a_player_never_reads_a_hidden_enemy_or_an_untold_death(local, storage, table):  # noqa: F811
    """Priya's finding: play/state's `combat` is the timeline's, redacted. An enemy in a room the party hasn't found
    stays unnamed, and a death the DM hasn't narrated yet stays unknown, in play/state and in the timeline alike."""
    cid = table["campaign"]
    ctx = context_for(storage, cid, "beat-1", SeededRng(4), catalogs=over(CombatReference(goblins=True)))
    lurker = {"name": "goblin", "count": 1, "label": f"{SECRET} the lurker", "node": "room.throne_chamber"}
    combat.setup_combat(ctx, enemies=[lurker, {"name": "goblin", "count": 1}], surprise=False)
    # The round is resolved, and the goblin in the hall died in it, but the DM hasn't told it yet.
    id, raw = storage.combats.live(cid)
    fight = rules.from_json(raw)
    goblin = fight.combatants["mon_2"]
    combatants = {**fight.combatants, "mon_2": replace(goblin, hp=-10)}
    storage.combats.save(id, fight.phase, rules.to_json(replace(fight, combatants=combatants)))
    row = storage.combat_rounds.latest(id)
    outcomes = {"acted": [], "downed": [], "dead": ["mon_2"], "fled": [], "completed": [], "interrupted": []}
    storage.combat_rounds.put(replace(row, outcomes=outcomes, resolved_at="2026-10-25T12:00:00+00:00"))

    _, ana, _ = table["Ana"]
    seen = state(ana, cid)["combat"]
    timeline = ana.get(f"/api/campaigns/{cid}/timeline").json()["fight"]
    assert seen == timeline
    for shown in (json.dumps(seen), json.dumps(timeline)):
        assert SECRET not in shown and "lurker" not in shown and "mon_1" not in shown
        assert "dead" not in shown and "throne" not in shown
    assert [s["state"] for s in timeline["slots"] if s["side"] == "enemy"] == ["waiting", "waiting"]
    assert [s["key"] for s in timeline["slots"] if s["name"] is None] == ["unseen-1"]
