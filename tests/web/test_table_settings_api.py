"""The host's table settings (table voice and fixes Task S1): voice allowed or off, initiative per combatant or per
side. Switching voice off disconnects everyone in voice; every change tells the organisers' lists and every seat."""

from tests.web.test_beats_api import campaign, dm, host, path, registries, sit  # noqa: F401 (fixtures)
from tests.web.test_preferences_api import published


def test_host_sets_voice_off(app, local, storage, campaign):  # noqa: F811
    put = local.put(path(campaign, "table-settings"), json={"voice": "off"})
    assert put.status_code == 200
    assert (put.json()["id"], put.json()["voice"], put.json()["initiative"]) == (campaign.id, "off", "combatant")
    assert storage.campaigns.get(campaign.id).voice == "off"
    assert local.put(path(campaign, "table-settings"), json={"voice": "allowed"}).json()["voice"] == "allowed"

    events = published(app)
    assert [e.data for e in events if e.type == "campaigns"] == [{"id": campaign.id}] * 2
    options = [(e.data, e.scope, e.campaign_id) for e in events if e.type == "play_options"]
    assert options == [({"campaign_id": campaign.id}, "table", campaign.id)] * 2


def test_voice_off_disconnects(local, campaign, monkeypatch):  # noqa: F811
    from delve.web.routes import voice

    closed = []

    async def disconnect(app, campaign_id, reason="off"):
        closed.append((campaign_id, reason))
        return 2

    monkeypatch.setattr(voice, "disconnect_campaign", disconnect)
    local.put(path(campaign, "table-settings"), json={"voice": "allowed"})
    local.put(path(campaign, "table-settings"), json={"initiative": "side"})
    assert closed == [], "only switching voice off disconnects"
    local.put(path(campaign, "table-settings"), json={"voice": "off"})
    assert closed == [(campaign.id, "off")]


def test_initiative_side(local, storage, campaign):  # noqa: F811
    put = local.put(path(campaign, "table-settings"), json={"initiative": "side"})
    assert put.status_code == 200 and (put.json()["voice"], put.json()["initiative"]) == ("allowed", "side")
    assert storage.campaigns.get(campaign.id).initiative == "side"
    both = local.put(path(campaign, "table-settings"), json={"voice": "off", "initiative": "combatant"}).json()
    assert (both["voice"], both["initiative"]) == ("off", "combatant")


def test_player_seat_403(storage, campaign, sit):  # noqa: F811
    _ana, ana_client = sit(campaign, "Ana")
    refused = ana_client.put(path(campaign, "table-settings"), json={"voice": "off"})
    assert refused.status_code == 403 and "error" in refused.json()
    assert storage.campaigns.get(campaign.id).voice == "allowed"

    _bo, cohost_client = sit(campaign, "Bo", "cohost")
    assert cohost_client.put(path(campaign, "table-settings"), json={"initiative": "side"}).status_code == 200


def test_bad_value_422(local, storage, campaign):  # noqa: F811
    for wrong in ({"voice": "loud"}, {"initiative": "random"}, {"voice": None}, {"initiative": 1}, {"tone": "x"}):
        answer = local.put(path(campaign, "table-settings"), json=wrong)
        assert answer.status_code == 422 and "error" in answer.json(), wrong
    stored = storage.campaigns.get(campaign.id)
    assert (stored.voice, stored.initiative) == ("allowed", "combatant")
    assert local.put("/api/campaigns/cmp_nope/table-settings", json={"voice": "off"}).status_code in (403, 404)
