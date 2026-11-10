"""The internal tool endpoint the DM's bridge calls (plan 2b Task 4, Review Focus 5): only loopback clients with the
per-process secret, never the owner token alone."""

import itertools

import pytest
from fastapi.testclient import TestClient

from delve.dice import SeededRng
from delve.dm.bridge import BRIDGE_HEADER
from delve.dm.tools import ToolHost, all_specs
from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.play.table import close_beat, open_beat
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over
from tests.web.conftest import BASE_URL
from tests.web.test_preferences_api import published


def act(storage, campaign) -> dict:
    """The owner seat's act."""
    seat = seats.owner_seat(storage, campaign.id)
    return {"player": seat.id, "character_ids": [], "kind": "act", "text": "We look around."}


@pytest.fixture
def host(app, storage):
    seeds = itertools.count(1)
    app.state.tool_host = ToolHost(storage, lambda: SeededRng(next(seeds)), catalogs=over(PlayReference()))
    return app.state.tool_host


@pytest.fixture
def campaign(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")


@pytest.fixture
def bridge(app):
    """The bridge: a client on this machine that sends the secret."""
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50001)) as client:
        client.headers[BRIDGE_HEADER] = app.state.bridge_secret
        yield client


def call_path(campaign_id: str) -> str:
    return f"/internal/dm/{campaign_id}/call"


ROLL = {"name": "roll", "args": {"notation": "1d20", "purpose": "the lever"}}


def test_internal_requires_secret_and_loopback(app, host, campaign, local, lan, bridge, token, storage):
    open_beat(storage, campaign.id, act(storage, campaign))
    secret = app.state.bridge_secret
    assert len(secret) >= 32
    refused = [
        lan.get("/internal/dm/tools", headers={BRIDGE_HEADER: secret}),  # from the LAN, even with the secret
        lan.post(call_path(campaign.id), json=ROLL, headers={BRIDGE_HEADER: secret}),
        local.get("/internal/dm/tools"),  # this machine, no secret
        local.post(call_path(campaign.id), json=ROLL),
        local.post(call_path(campaign.id), json=ROLL, headers={BRIDGE_HEADER: secret + "x"}),  # a wrong secret
        local.post(call_path(campaign.id), json=ROLL, headers={BRIDGE_HEADER: ""}),
        lan.post(call_path(campaign.id), json=ROLL, headers={"Authorization": f"Bearer {token}"}),  # owner token
        local.post(call_path(campaign.id), json=ROLL, headers={"Authorization": f"Bearer {token}"}),
        lan.post(call_path(campaign.id), content=b"x", headers={BRIDGE_HEADER: secret, "Content-Type": "text/plain"}),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert all(set(r.json()) == {"error"} for r in refused)
    assert storage.rolls.list(campaign.id) == []

    assert bridge.get("/internal/dm/tools").status_code == 200
    assert bridge.post(call_path(campaign.id), json=ROLL).status_code == 200


def test_tools_list_is_the_tool_host(host, bridge):
    tools = bridge.get("/internal/dm/tools").json()
    assert [t["name"] for t in tools] == [s.name for s in all_specs()]
    roll = next(t for t in tools if t["name"] == "roll")
    spec = host.spec("roll")
    assert roll == {"name": "roll", "description": spec.description, "inputSchema": spec.params}


def test_call_runs_tool_in_current_beat(host, campaign, bridge, storage):
    outside = bridge.post(call_path(campaign.id), json=ROLL)
    assert outside.status_code == 409 and outside.json() == {"error": "no beat is running"}

    beat = open_beat(storage, campaign.id, act(storage, campaign))
    first = bridge.post(call_path(campaign.id), json=ROLL).json()
    assert first["total"] >= 1
    (logged,) = storage.rolls.list(campaign.id)
    assert logged.key.beat == beat.id
    # The no-re-roll rule holds over the bridge: the same roll again in the beat is the stored one.
    assert bridge.post(call_path(campaign.id), json=ROLL).json() == first
    refused = bridge.post(call_path(campaign.id), json={"name": "roll", "args": {"notation": "999999d6"}})
    assert refused.status_code == 200 and "error" in refused.json()
    unknown = bridge.post(call_path(campaign.id), json={"name": "no_such_tool", "args": {}})
    assert unknown.status_code == 200 and unknown.json()["error"] == "Unknown tool 'no_such_tool'."

    close_beat(storage, beat.id, "done")
    assert bridge.post(call_path(campaign.id), json=ROLL).json() == {"error": "no beat is running"}
    assert bridge.post(call_path("cmp_000000000000"), json=ROLL).json() == {"error": "no beat is running"}


def test_mutating_call_publishes_one_event_of_its_areas(app, host, campaign, bridge, storage):
    """One `changed` event per call, of the areas its tool names (DEL-168): a roll, which no seat reads again, none."""
    open_beat(storage, campaign.id, act(storage, campaign))
    storage.map_states.put(campaign.id, "crypt", {"characters": {}})
    before = len(published(app))
    bridge.post(call_path(campaign.id), json={"name": "party_status", "args": {}})
    bridge.post(call_path(campaign.id), json={"name": "roll", "args": {"notation": "999999d6"}})
    bridge.post(call_path(campaign.id), json=ROLL)
    assert len(published(app)) == before  # a read, a refused write and a roll change nothing a seat reads

    bridge.post(call_path(campaign.id), json={"name": "advance_time", "args": {"minutes": 10}})
    bridge.post(call_path(campaign.id), json={"name": "new_session", "args": {"title": "The crypt"}})
    # A batch's: those of the steps that ran, once.
    steps = [ROLL | {"tool": "roll"}, {"tool": "advance_time", "args": {"minutes": 5}}, {"tool": "roll", "args": {}}]
    bridge.post(call_path(campaign.id), json={"name": "batch", "args": {"steps": steps, "stop_on_error": False}})
    events = [(e.type, e.data) for e in published(app)[before:]]
    told = {"campaign_id": campaign.id, "maps": []}
    assert events == [
        ("changed", told | {"areas": ["world"]}),
        ("changed", told | {"areas": ["state"]}),
        ("changed", told | {"areas": ["world"]}),
    ]


def test_changed_names_every_map_for_map_state(app, storage, campaign, bridge):
    """A tool that may move the party names the campaign's maps, so each seat reads their views again; one that names no
    areas is every area, as before areas were named."""
    from delve.dm.tools.schema import ToolSpec

    def spec(name: str, areas: tuple[str, ...] | None) -> ToolSpec:
        return ToolSpec(name, "", {"type": "object"}, lambda ctx, args: {}, mutates=True, player_visible=True, areas=areas)

    app.state.tool_host = ToolHost(
        storage,lambda: SeededRng(1), specs=[spec("walk", ("map_state",)), spec("anything", None)], catalogs=over(PlayReference()))
    open_beat(storage, campaign.id, act(storage, campaign))
    storage.map_states.put(campaign.id, "crypt", {"characters": {}})
    before = len(published(app))
    bridge.post(call_path(campaign.id), json={"name": "walk", "args": {}})
    bridge.post(call_path(campaign.id), json={"name": "anything", "args": {}})
    events = [(e.type, e.data) for e in published(app)[before:]]
    assert events == [
        ("changed", {"campaign_id": campaign.id, "areas": ["map_state"], "maps": ["crypt"]}),
        (
            "changed",
            {
                "campaign_id": campaign.id,
                "areas": ["characters", "map_state", "combat", "world", "state"],
                "maps": ["crypt"],
            },
        ),
    ]
