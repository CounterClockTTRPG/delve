"""The table's session state through the API (DEL-199): `play/state`'s `table`, the host's start, break, back to the
story and end, the raised hands, seats away and the parts PCs take mid-session (DEL-224), the refused acts while the
table gathers or rests, and the `table` event."""

from dataclasses import replace

import pytest

from delve.domain.campaigns import TableSession
from delve.domain.modules import ModuleMap
from tests.web.test_beats_api import dm, host, path, present, registries, settle, sit  # noqa: F401


@pytest.fixture
def campaign(storage):
    """A new campaign, its table gathering by the pregame's rule: no row stored yet."""
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    return storage.campaigns.create(
        "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting="greyhawk"
    )
from tests.web.test_preferences_api import published


@pytest.fixture
def gathering(storage, campaign):
    storage.table_sessions.put(TableSession(campaign.id, "gathering"))


@pytest.fixture
def ana(storage, campaign, sit):  # noqa: F811
    """Ana, a player of Garrek, at the table with the host."""
    garrek = storage.characters.create(campaign.id, "Garrek")
    return sit(campaign, "Ana", "player", garrek.id)


def table_events(app):
    return [e for e in published(app) if e.type == "table"]


def test_play_state_has_the_table_and_no_pregame(app, local, storage, campaign, host, ana):  # noqa: F811
    _seat, ana_client = ana
    state = ana_client.get(path(campaign, "play/state")).json()
    assert "pregame" not in state
    assert state["table"] == {
        "state": "gathering", "since": None, "solo": False, "absent": {}, "hands": [], "away": []
    }  # fmt: skip
    storage.story.append(campaign.id, None, "player_act", {"text": "I open the door."})
    assert ana_client.get(path(campaign, "play/state")).json()["table"]["state"] == "playing"
    storage.story.append(campaign.id, None, "recap", {"text": "A door was opened."})
    assert ana_client.get(path(campaign, "play/state")).json()["table"]["state"] == "gathering"


def test_while_gathering_acts_wait_for_the_host(app, local, storage, campaign, host, ana, gathering):  # noqa: F811
    _seat, ana_client = ana
    for client, route, body in ((ana_client, "act", {"text": "I listen."}), (ana_client, "pass", {})):
        refused = client.post(path(campaign, route), json=body)
        assert refused.status_code == 409
        assert refused.json()["error"] == "The session hasn't started yet: the host starts it."
    assert storage.beats.current(campaign.id) is None


def test_a_solo_table_s_act_starts_the_session(app, local, storage, dm, campaign, host, gathering):  # noqa: F811
    assert local.post(path(campaign, "act"), json={"text": "We go in."}).status_code == 202
    settle(storage, campaign)
    assert local.get(path(campaign, "play/state")).json()["table"]["state"] == "playing"
    (event,) = table_events(app)
    assert event.scope == "table" and event.campaign_id == campaign.id
    assert event.data["campaign_id"] == campaign.id and event.data["table"]["state"] == "playing"


def test_the_host_starts_the_session(app, local, storage, dm, campaign, host, ana, gathering):  # noqa: F811
    _seat, ana_client = ana
    garrek = storage.characters.list(campaign.id)[0]
    assert ana_client.post(path(campaign, "session/start"), json={}).status_code == 403
    unknown = local.post(path(campaign, "session/start"), json={"absent": {"chr_000000000000": "out"}})
    assert unknown.status_code == 422
    assert local.post(path(campaign, "session/start"), json={"absent": {garrek.id: "sleep"}}).status_code == 422
    started = local.post(path(campaign, "session/start"), json={"absent": {garrek.id: "in_character"}})
    assert started.status_code == 202
    body = started.json()
    assert body["table"]["state"] == "playing" and body["table"]["absent"] == {garrek.id: "in_character"}
    assert body["beat"]["status"] == "running" and body["beat"]["submitted"] == []
    settle(storage, campaign)
    assert dm.sent[-1].splitlines()[-1].startswith("[Not from a player: the host starts this session")
    assert "Garrek" in dm.sent[-1]
    again = local.post(path(campaign, "session/start"), json={})
    assert again.status_code == 409
    assert table_events(app)[-1].data["table"]["state"] == "playing"


def test_start_with_no_absent_pcs(app, local, storage, dm, campaign, host, gathering):  # noqa: F811
    started = local.post(path(campaign, "session/start"), json={})
    assert started.status_code == 202 and started.json()["table"]["absent"] == {}
    settle(storage, campaign)


def test_a_break_and_back_to_the_story(app, local, storage, dm, campaign, host, ana):  # noqa: F811
    _seat, ana_client = ana
    storage.table_sessions.put(TableSession(campaign.id, "playing"))
    assert local.post(path(campaign, "session/resume"), json={}).status_code == 409
    assert ana_client.post(path(campaign, "session/break"), json={}).status_code == 403
    resting = local.post(path(campaign, "session/break"), json={})
    assert resting.status_code == 200 and resting.json()["table"]["state"] == "break"
    assert resting.json()["table"]["since"] is not None
    assert local.post(path(campaign, "session/break"), json={}).status_code == 409
    for client, route, body in (
        (ana_client, "act", {"text": "I listen."}),
        (ana_client, "pass", {}),
        (local, "go", {}),
    ):
        refused = client.post(path(campaign, route), json=body)
        assert refused.status_code == 409 and refused.json()["error"] == "The table is on a break.", route
    back = local.post(path(campaign, "session/resume"), json={})
    assert back.status_code == 200 and back.json()["table"]["state"] == "playing"
    assert [e.data["table"]["state"] for e in table_events(app)] == ["break", "playing"]


def test_the_host_ends_the_session(app, local, storage, dm, campaign, host, ana):  # noqa: F811
    seat, ana_client = ana
    storage.characters.create(campaign.id, "Pip")  # nobody plays Pip: the host does, and holds the beat up
    present(app, host.id, seat.id)
    assert local.post(path(campaign, "session/end"), json={}).status_code == 409, "the table gathers"
    storage.table_sessions.put(TableSession(campaign.id, "playing"))
    assert ana_client.post(path(campaign, "act"), json={"text": "I listen."}).status_code == 202
    assert local.post(path(campaign, "session/end"), json={}).status_code == 409, "a beat is open"
    assert local.post(path(campaign, "go"), json={}).status_code == 202
    settle(storage, campaign)
    assert ana_client.post(path(campaign, "session/end"), json={}).status_code == 403
    ended = local.post(path(campaign, "session/end"), json={})
    assert ended.status_code == 202
    assert ended.json()["table"]["state"] == "gathering" and ended.json()["beat"]["status"] == "running"
    settle(storage, campaign)
    assert "end_session(recap)" in dm.sent[-1]


def test_raised_hands(app, local, storage, campaign, host, ana, sit):  # noqa: F811
    seat, ana_client = ana
    bo, bo_client = sit(campaign, "Bo", "observer")
    raised = ana_client.post(path(campaign, "hand"), json={"point": "About the map"})
    assert raised.status_code == 200
    (hand,) = raised.json()["table"]["hands"]
    assert hand["seat_id"] == seat.id and hand["point"] == "About the map" and hand["at"]
    assert bo_client.post(path(campaign, "hand"), json={"point": None}).status_code == 200
    again = ana_client.post(path(campaign, "hand"), json={"point": "Never mind"}).json()["table"]["hands"]
    assert [h["seat_id"] for h in again] == [seat.id, bo.id] and again[0]["at"] == hand["at"]
    assert again[0]["point"] == "Never mind"
    assert ana_client.post(path(campaign, "hand"), json={"point": "x" * 201}).status_code == 422
    refused = ana_client.request("DELETE", path(campaign, f"hand/{bo.id}"), json={})
    assert refused.status_code == 403
    assert bo_client.request("DELETE", path(campaign, f"hand/{bo.id}"), json={}).status_code == 200
    lowered = local.request("DELETE", path(campaign, f"hand/{seat.id}"), json={})
    assert lowered.status_code == 200 and lowered.json()["table"]["hands"] == []
    assert local.request("DELETE", path(campaign, f"hand/{seat.id}"), json={}).status_code == 200, "not up: fine"
    assert len(table_events(app)) == 5


def test_stepping_away_and_the_host_s_parts(app, local, storage, campaign, host, ana, sit):  # noqa: F811
    """DEL-224: Ana steps away herself, the host marks Bo away and back, and sets Garrek's part; Bo may do neither
    for another; 409 before the session, 422 for a part that won't do."""
    seat, ana_client = ana
    bo, bo_client = sit(campaign, "Bo", "player")
    garrek = next(c for c in storage.characters.list(campaign.id) if c.name == "Garrek")
    storage.table_sessions.put(TableSession(campaign.id, "gathering"))
    assert ana_client.post(path(campaign, "away"), json={}).status_code == 409
    storage.table_sessions.put(TableSession(campaign.id, "playing"))

    stepped = ana_client.post(path(campaign, "away"), json={"part": "in_character"})
    assert stepped.status_code == 200
    (away,) = stepped.json()["table"]["away"]
    assert away["seat_id"] == seat.id and away["part"] == "in_character" and away["at"]
    assert ana_client.post(path(campaign, "away"), json={"part": "asleep"}).status_code == 422
    assert bo_client.post(path(campaign, "away"), json={"seat_id": seat.id}).status_code == 403
    assert local.post(path(campaign, "away"), json={"seat_id": bo.id}).status_code == 200
    assert bo_client.request("DELETE", path(campaign, f"away/{seat.id}"), json={}).status_code == 403
    back = local.request("DELETE", path(campaign, f"away/{bo.id}"), json={})
    assert [a["seat_id"] for a in back.json()["table"]["away"]] == [seat.id]

    assert bo_client.put(path(campaign, f"parts/{garrek.id}"), json={"part": "out"}).status_code == 403
    assert local.put(path(campaign, f"parts/{garrek.id}"), json={"part": "asleep"}).status_code == 422
    set_out = local.put(path(campaign, f"parts/{garrek.id}"), json={"part": "out"})
    assert set_out.status_code == 200 and set_out.json()["table"]["absent"] == {garrek.id: "out"}
    cleared = local.put(path(campaign, f"parts/{garrek.id}"), json={"part": None})
    assert cleared.json()["table"]["absent"] == {}
    assert ana_client.request("DELETE", path(campaign, f"away/{seat.id}"), json={}).json()["table"]["away"] == []
    assert len(table_events(app)) == 6


def test_the_play_state_says_when_the_session_is_over(local, storage, campaign, host):  # noqa: F811
    """DEL-182: after End the session the header said "Session 1" as if it went on. `session_over` is true from its
    recap until the next session starts."""
    state = lambda: local.get(path(campaign, "play/state")).json()
    assert state()["session_over"] is False
    storage.sessions.start(campaign.id, 1, "Session 1")
    assert state()["session_over"] is False
    storage.sessions.end(campaign.id, 1, "They reached the crypt.")
    assert (state()["session_number"], state()["session_over"]) == (1, True)
    current = storage.campaign_states.get(campaign.id)
    storage.campaign_states.put(replace(current, session=2))
    assert (state()["session_number"], state()["session_over"]) == (2, False)
