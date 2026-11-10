"""Hotseat over the API (DEL-365): the host sets the players at their screen in the table options, every seat reads
them in the play state, and the host's screen acts once for each of them."""

from fastapi.testclient import TestClient

from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL
from tests.web.test_play_api import campaign, path, settle  # noqa: F401 (fixture)
from tests.web.test_talk_api import dm, registries  # noqa: F401 (fixtures)


def test_the_host_seats_two_players_and_each_acts(local, storage, campaign):  # noqa: F811
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    assert local.get(path(campaign, "play/state")).json()["hotseat"] == {"on": False, "seat_id": None, "players": []}
    put = local.put(
        path(campaign, "play/options"),
        json={
            "hotseat": True,
            "hotseat_players": [{"name": "Anna", "characters": [garrek.id]}, {"name": "Ben", "characters": [mira.id]}],
        },
    )
    assert put.status_code == 200, put.json()
    players = put.json()["hotseat_players"]
    assert [p["name"] for p in players] == ["Anna", "Ben"] and put.json()["hotseat"] is True
    state = local.get(path(campaign, "play/state")).json()["hotseat"]
    assert state["on"] is True and [p["characters"] for p in state["players"]] == [[garrek.id], [mira.id]]

    anna, ben = (p["id"] for p in players)
    first = local.post(path(campaign, "act"), json={"text": "I listen.", "player": anna})
    assert first.status_code == 202 and first.json()["beat"]["status"] == "open"
    pending = local.get(path(campaign, "beat/pending")).json()["pending"]
    assert [(p["name"], p["hotseat"]) for p in pending] == [("Anna", anna)]
    private = local.post(path(campaign, "act"), json={"text": "A secret.", "player": ben, "private": True})
    assert private.status_code == 422 and "shared screen" in private.json()["error"]
    second = local.post(path(campaign, "pass"), json={"player": ben})
    assert second.status_code == 202 and second.json()["beat"]["status"] == "running"
    settle(local, campaign)
    acts = [e for e in local.get(path(campaign, "story")).json()["entries"] if e["kind"] == "player_act"]
    assert [a["payload"]["name"] for a in acts] == ["Anna"]


def test_only_the_host_sets_up_the_hotseat(app, local, storage, campaign):  # noqa: F811
    token = new_seat_token()
    storage.seats.create(campaign.id, "Dee", "en", "cohost", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL) as dee:
        dee.cookies.set(SEAT_COOKIE, token)
        refused = dee.put(path(campaign, "play/options"), json={"hotseat": True})
        assert refused.status_code == 403 and refused.json()["error"] == "Only the host can set up the hotseat."
    bad = local.put(path(campaign, "play/options"), json={"hotseat_players": [{"name": ""}]})
    assert bad.status_code == 422 and "needs a name" in bad.json()["error"]
