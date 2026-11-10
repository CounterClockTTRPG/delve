"""A character leaves the party through the campaign page (table voice and fixes Task C2): `PUT …/characters/{id}/
departure`, the organiser's, and `play/state`, whose party leaves the departed out and lists them apart."""

from fastapi.testclient import TestClient

from delve.dice import ScriptedRng, SeededRng
from delve.play import characters, combat, departures
from delve.play.context import context_for
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.rulesets import over
from tests.web.conftest import BASE_URL
from tests.web.test_house_rules_api import published
from tests.web.test_play_api import CombatReference, campaign, dm, path, registries  # noqa: F401


def seat_client(app, storage, cid: str, name: str, role: str = "player", **kw) -> TestClient:
    token = new_seat_token()
    storage.seats.create(cid, name, "en", role, token_hash=token_hash(token), **kw)
    client = TestClient(app, base_url=BASE_URL)
    client.cookies.set(SEAT_COOKIE, token)
    return client


def make_party(storage, campaign):  # noqa: F811
    ctx = context_for(storage, campaign.id, "beat-1", SeededRng(3), catalogs=over(CombatReference(goblins=True)))
    garrek = characters.create(ctx, name="Garrek", sheet={"hp_max": 12, "ac": 4, "thac0": 18, "weapon": "long sword"})
    tansy = characters.create(ctx, name="Tansy", sheet={"hp_max": 6, "ac": 7, "thac0": 20, "weapon": "dagger"})
    return ctx, garrek, tansy


def departure(client, campaign, character_id, value):  # noqa: F811
    return client.put(path(campaign, f"characters/{character_id}/departure"), json={"departure": value})


def test_departure_route_leaves_and_returns(local, app, storage, campaign):  # noqa: F811
    _ctx, _garrek, tansy = make_party(storage, campaign)
    response = departure(local, campaign, tansy.id, "died")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["id"] == tansy.id and body["departure"] == "died" and body["departed_at"]
    assert storage.characters.get(tansy.id).departure == "died"
    assert ("characters", {"campaign_id": campaign.id}) in published(app)

    again = departure(local, campaign, tansy.id, "died")
    assert again.status_code == 200 and again.json()["departed_at"] == body["departed_at"], "the same again: as it was"
    changed = departure(local, campaign, tansy.id, "retired").json()
    assert changed["departure"] == "retired" and changed["departed_at"] == body["departed_at"]

    back = departure(local, campaign, tansy.id, None)
    assert back.status_code == 200 and back.json()["departure"] is None and back.json()["departed_at"] is None
    assert departure(local, campaign, tansy.id, None).status_code == 200, "returning one in the party changes nothing"
    types = [e.data.get("departure") for e in storage.events.list(campaign.id) if e.type == "departure"]
    assert types == ["died", "retired", None]


def test_departure_route_refusals(local, storage, campaign):  # noqa: F811
    ctx, garrek, _tansy = make_party(storage, campaign)
    tira = characters.create(ctx, name="Tira", kind="npc", sheet={})
    bad = departure(local, campaign, garrek.id, "vanished")
    assert bad.status_code == 422 and "error" in bad.json()
    assert local.put(path(campaign, f"characters/{garrek.id}/departure"), json={}).status_code == 422
    npc = departure(local, campaign, tira.id, "left")
    assert npc.status_code == 409 and "NPC" in npc.json()["error"]
    assert departure(local, campaign, "chr_nobody", "left").status_code == 404


def test_departure_route_organiser_only(app, storage, campaign):  # noqa: F811
    _ctx, garrek, _tansy = make_party(storage, campaign)
    player = seat_client(app, storage, campaign.id, "Ana")
    refused = departure(player, campaign, garrek.id, "left")
    assert refused.status_code == 403 and "error" in refused.json()
    host = seat_client(app, storage, campaign.id, "Bo", "cohost")
    assert departure(host, campaign, garrek.id, "left").status_code == 403, "a co-host is no organiser"
    organiser = seat_client(app, storage, campaign.id, "Cy", organiser=True)
    assert departure(organiser, campaign, garrek.id, "left").status_code == 200
    assert storage.characters.get(garrek.id).departure == "left"


def test_departure_route_leaves_the_fight(local, storage, campaign):  # noqa: F811
    ctx, _garrek, tansy = make_party(storage, campaign)
    combat.setup_combat(ctx, enemies=[{"name": "goblin", "count": 1, "hp": 5}], surprise=False)
    assert departure(local, campaign, tansy.id, "left").status_code == 200
    fighter = combat.combatant(ctx, tansy.id)
    assert fighter is not None and "removed" in fighter.conditions


def test_play_state_leaves_departed_out(local, storage, campaign):  # noqa: F811
    ctx, garrek, tansy = make_party(storage, campaign)
    departures.leave_party(ctx, tansy.id, "died")
    state = local.get(path(campaign, "play/state")).json()
    assert [pc["id"] for pc in state["party"]] == [garrek.id]
    assert state["marching_order"] == [garrek.id]
    assert state["departed"] == [{"id": tansy.id, "name": "Tansy", "departure": "died"}]


def test_play_state_without_departures_has_none(local, storage, campaign):  # noqa: F811
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng([]), catalogs=over(CombatReference()))
    characters.create(ctx, name="Garrek", sheet={"hp_max": 12})
    assert local.get(path(campaign, "play/state")).json()["departed"] == []
