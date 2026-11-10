"""A campaign's own maps over the API (campaign maps, 2026-10-23): made, saved, rendered and played as the campaign's,
never the module's; refused where a name clashes, a source doesn't parse, or the table stands on a map being removed."""

from tests.fixtures import SAMPLES
from tests.web.test_campaigns_api import campaign, character, crypt_module, played

COTTAGE = (SAMPLES / "cottage.dmap").read_text()


def own(campaign_id: str, name: str = "") -> str:
    return f"/api/campaigns/{campaign_id}/own-maps" + (f"/{name}" if name else "")


def made(local, campaign_id: str, name: str = "slums", source: str = COTTAGE) -> dict:
    assert local.post(own(campaign_id), json={"name": name}).status_code == 201
    response = local.put(own(campaign_id, name), json={"source": source})
    assert response.status_code == 200, response.json()
    return response.json()


def test_a_campaign_map_is_made_saved_and_played_but_stays_out_of_the_module(local):
    started, (ana, _) = played(local)
    detail = made(local, started["id"])
    assert detail["name"] == "slums" and detail["own"] is True and detail["campaign_id"] == started["id"]
    assert detail["module_id"] == started["module_id"] and detail["role"] == "map" and detail["is_default"] is False
    assert [m["name"] for m in local.get(own(started["id"])).json()] == ["slums"]
    # Played: the campaign lists it, and the party can be moved onto it.
    campaign_json = local.get(f"/api/campaigns/{started['id']}").json()
    assert campaign_json["maps"] == ["crypt", "slums"] and campaign_json["own_maps"] == ["slums"]
    moved = local.post(
        f"/api/campaigns/{started['id']}/maps/slums/move", json={"characters": [ana], "to": "room.kitchen"}
    )
    assert moved.status_code == 200, moved.json()
    # Not the module's.
    module = local.get(f"/api/modules/{started['module_id']}").json()
    assert [m["name"] for m in module["maps"]] == ["crypt"]


def test_a_name_the_campaign_already_plays_is_refused(local):
    started, _ = played(local)
    assert local.post(own(started["id"]), json={"name": "crypt"}).status_code == 409
    made(local, started["id"])
    assert local.post(own(started["id"]), json={"name": "slums"}).status_code == 409


def test_a_source_that_does_not_parse_is_not_saved(local):
    started, _ = played(local)
    made(local, started["id"])
    response = local.put(own(started["id"], "slums"), json={"source": "map broken {"})
    assert response.status_code == 400 and "line" in response.json()
    assert local.get(own(started["id"], "slums")).json()["source"] == COTTAGE


def test_render_feature_names_and_simplify_use_the_modules_libraries(local):
    started, _ = played(local)
    made(local, started["id"])
    rendered = local.post(own(started["id"], "slums") + "/render", json={})
    assert rendered.status_code == 200 and rendered.json()["svg"].startswith("<svg")
    assert local.post(own(started["id"], "slums") + "/feature-names", json={}).status_code == 200
    assert local.post(own(started["id"], "slums") + "/simplify", json={}).json()["saved"] is False


def test_rename_and_delete_until_the_table_has_played_on_it(local):
    started, (ana, _) = played(local)
    made(local, started["id"])
    renamed = local.put(own(started["id"], "slums"), json={"new_name": "the-slums"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "the-slums"
    local.post(f"/api/campaigns/{started['id']}/maps/the-slums/move", json={"characters": [ana], "to": "room.kitchen"})
    assert local.put(own(started["id"], "the-slums"), json={"new_name": "slums"}).status_code == 409
    assert local.request("DELETE", own(started["id"], "the-slums"), json={}).status_code == 409
    # A map nobody stands on can go.
    made(local, started["id"], "market")
    assert local.request("DELETE", own(started["id"], "market"), json={}).status_code == 204
    assert [m["name"] for m in local.get(own(started["id"])).json()] == ["the-slums"]


def test_an_upgrade_keeps_the_campaigns_maps(local):
    started, (ana, _) = played(local)
    made(local, started["id"])
    local.post(f"/api/campaigns/{started['id']}/maps/slums/move", json={"characters": [ana], "to": "room.kitchen"})
    module_id = started["module_id"]
    assert local.post(f"/api/modules/{module_id}/maps", json={"name": "tower", "role": "map"}).status_code == 201
    local.put(f"/api/modules/{module_id}/maps/tower", json={"source": COTTAGE})
    assert local.post(f"/api/campaigns/{started['id']}/upgrade", json={}).status_code == 200
    upgraded = local.get(f"/api/campaigns/{started['id']}").json()
    assert upgraded["maps"] == ["crypt", "tower", "slums"]
    state = local.get(f"/api/campaigns/{started['id']}/maps/slums/state").json()
    assert state["characters"][ana]["location"] == "room.kitchen"


def test_unknown_campaign_and_map(local):
    module = crypt_module(local)
    started = campaign(local, module["id"])
    character(local, started["id"], "Ana")
    assert local.get(own("cmp_000000000000")).status_code == 404
    assert local.get(own(started["id"], "nowhere")).status_code == 404
