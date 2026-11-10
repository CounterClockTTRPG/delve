"""`GET /api/campaigns/{id}/pregens` (faithful modules Task 19): the pinned revision's pregens for the players, which
the host's picker offers at party creation. Only those who run the table read it: a pregen reaches the players once
it is a character."""

from fastapi.testclient import TestClient

from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL
from tests.web.test_campaigns_api import campaign, crypt_module

SECRET = "SECRET-XYZZY"

NED = {
    "id": "ned",
    "name": "Ned Shakeshaft",
    "summary": "A spy, as the book says.",
    "description": "He works for the smugglers.",
    "race": "Human",
    "class": "Fighter/Thief",
    "level": "3/3",
    "alignment": "Neutral",
    "gear": ["Short sword"],
    "background": "A sailor.",
    "stats": {"adnd2e": {"ability_scores": {"str": "18/76"}, "hp_max": 17}},
}
SPY = {"id": "spy", "name": "The Spy", "audience": "gm", "background": f"{SECRET}: paid by the lizard men."}


def module_with_pregens(local) -> str:
    mid = crypt_module(local)["id"]
    for record in (NED, SPY):
        response = local.put(f"/api/modules/{mid}/entities/pregens/{record['id']}", json=record)
        assert response.status_code == 200, response.json()
    return mid


def seat_client(app, storage, cid: str, name: str, role: str) -> TestClient:
    token = new_seat_token()
    storage.seats.create(cid, name, "en", role, token_hash=token_hash(token))
    client = TestClient(app, base_url=BASE_URL)
    client.cookies.set(SEAT_COOKIE, token)
    return client


def test_the_host_reads_the_player_pregens(app, local, storage):
    mid = module_with_pregens(local)
    cid = campaign(local, mid)["id"]
    path = f"/api/campaigns/{cid}/pregens"

    response = local.get(path)
    assert response.status_code == 200
    assert response.json() == {
        "pregens": [
            {
                "id": "ned",
                "name": "Ned Shakeshaft",
                "race": "Human",
                "class": "Fighter/Thief",
                "level": "3/3",
                "alignment": "Neutral",
                "gear": ["Short sword"],
                "background": "A sailor.",
                "stats": {"adnd2e": {"ability_scores": {"str": "18/76"}, "hp_max": 17}},
            }
        ]
    }
    with seat_client(app, storage, cid, "Dee", "cohost") as dee:
        assert dee.get(path).json() == response.json()


def test_players_and_observers_read_no_pregen(app, local, storage):
    cid = campaign(local, module_with_pregens(local))["id"]
    for name, role in (("Ana", "player"), ("Cy", "observer")):
        with seat_client(app, storage, cid, name, role) as client:
            refused = client.get(f"/api/campaigns/{cid}/pregens")
            assert refused.status_code == 403, name
            assert "Ned" not in refused.text and SECRET not in refused.text, name


def test_the_pregens_are_the_pinned_revisions(local):
    mid = crypt_module(local)["id"]
    cid = campaign(local, mid)["id"]
    assert local.put(f"/api/modules/{mid}/entities/pregens/ned", json=NED).status_code == 200
    assert local.get(f"/api/campaigns/{cid}/pregens").json() == {"pregens": []}
    assert local.get("/api/campaigns/cmp_000000000000/pregens").status_code == 404
