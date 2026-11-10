"""The seat identity (plan 4 Task 1, Review Focus 2; spec §11): the owner token or a seat token resolves to a
principal, and a seat token gives rights in its own campaign only, never on an organiser route unless the seat was
granted the organiser role, and never after the seat has left."""

from dataclasses import replace
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.play.accounts import create_account
from delve.web.auth import Principal, current_principal
from delve.web.seats import SEAT_COOKIE, ActorSeat, HostSeat, TableSeat, new_seat_token, token_hash
from tests.fixtures import SAMPLES
from tests.web.conftest import BASE_URL


def add_probes(app):
    @app.get("/api/campaigns/{campaign_id}/probe-table")
    def probe_table(seat: TableSeat):
        return {"seat": seat.id}

    @app.get("/api/campaigns/{campaign_id}/probe-host")
    def probe_host(seat: HostSeat):
        return {"seat": seat.id}

    @app.get("/api/campaigns/{campaign_id}/probe-actor")
    def probe_actor(seat: ActorSeat):
        return {"seat": seat.id}

    @app.get("/api/probe-principal")
    def probe_principal(principal: Annotated[Principal, Depends(current_principal)]):
        return {"id": principal.id, "roles": sorted(principal.roles), "seat": principal.seat and principal.seat.id}


def make_campaign(storage, name="Tuesday"):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create(name, module.id, revision.number, ruleset="osric", setting="greyhawk")


@pytest.fixture
def campaign(storage):
    return make_campaign(storage)


@pytest.fixture
def other(storage):
    return make_campaign(storage, "Friday")


@pytest.fixture
def join(app, storage):
    """`join(campaign_id, role="player", organiser=False)`: a seat at that table, and a browser on the LAN that holds
    its token."""
    clients = []

    def make(campaign_id, role="player", *, organiser=False):
        token = new_seat_token()
        seat = storage.seats.create(campaign_id, "Ana", "nl", role, organiser=organiser, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        return seat, client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def test_seat_tokens_are_random_and_hashed():
    token = new_seat_token()
    assert len(token) >= 43 and token != new_seat_token()
    assert len(token_hash(token)) == 64 and token_hash(token) != token and token_hash(token) == token_hash(token)


def test_the_owner_resolves_to_their_seat_in_each_campaign(app, local, storage, campaign, other):
    add_probes(app)
    assert local.get("/api/probe-principal").json() == {"id": "owner", "roles": ["organiser"], "seat": None}
    mine = local.get(f"/api/campaigns/{campaign.id}/probe-table").json()["seat"]
    theirs = local.get(f"/api/campaigns/{other.id}/probe-table").json()["seat"]
    assert mine == seats.owner_seat(storage, campaign.id).id and theirs == seats.owner_seat(storage, other.id).id
    assert mine != theirs
    assert local.get(f"/api/campaigns/{campaign.id}/probe-host").json() == {"seat": mine}
    assert local.get("/api/campaigns/cmp_000000000000/probe-table").status_code == 404


def test_the_owner_at_a_campaign_deleted_meanwhile_is_404(app, local, storage, campaign, monkeypatch):
    """The campaign is deleted between the seat's check that it exists and the owner seat it makes there (a tab still
    open on a campaign the host just deleted, seen in the browser checks): a 404, never a 500."""
    add_probes(app)
    storage.campaigns.delete(campaign.id)
    monkeypatch.setattr(storage.campaigns, "get", lambda id: campaign)  # it still existed when looked at
    answer = local.get(f"/api/campaigns/{campaign.id}/probe-table")
    assert answer.status_code == 404 and answer.json() == {"error": "No such campaign."}


def test_the_owner_token_on_the_lan_is_the_owner_too(app, lan, token, storage, campaign):
    add_probes(app)
    response = lan.get(f"/api/campaigns/{campaign.id}/probe-table", headers={"Authorization": f"Bearer {token}"})
    assert response.json() == {"seat": seats.owner_seat(storage, campaign.id).id}


def test_a_new_campaign_gets_the_owners_seat_as_host(local, storage):
    module = local.post("/api/modules", json={"title": "The Crypt"}).json()
    local.put(f"/api/modules/{module['id']}/maps/map", json={"source": (SAMPLES / "crypt.dmap").read_text()})
    created = local.post("/api/campaigns", json={"name": "Tuesday", "module_id": module["id"]})
    assert created.status_code == 201
    [seat] = storage.seats.list(created.json()["id"])
    assert seat.owner and seat.role == "host" and seat.name == "Host" and seat.language == "en"
    assert "join_token" not in created.json(), "the join link is the host's, from the invite route"


def test_a_seat_token_works_on_its_own_campaign_only(app, join, campaign, other):
    add_probes(app)
    seat, ana = join(campaign.id)
    assert ana.get("/api/probe-principal").json() == {"id": f"seat:{seat.id}", "roles": [], "seat": seat.id}
    assert ana.get(f"/api/campaigns/{campaign.id}/probe-table").json() == {"seat": seat.id}
    assert ana.get(f"/api/campaigns/{campaign.id}/story").status_code == 200
    assert ana.get(f"/api/campaigns/{campaign.id}/characters").status_code == 200
    assert ana.get(f"/api/campaigns/{campaign.id}/play/state").status_code == 200

    for path in ("probe-table", "story", "characters", "play/state"):
        refused = ana.get(f"/api/campaigns/{other.id}/{path}")
        assert refused.status_code == 403 and refused.json() == {"error": "This seat is for another table."}
    refused = ana.get(f"/api/campaigns/{other.id}/maps/crypt/view")
    assert refused.status_code == 403
    assert ana.get("/api/campaigns/cmp_000000000000/probe-table").status_code == 403


def test_an_unknown_seat_token_is_nobody(app, lan, campaign):
    add_probes(app)
    lan.cookies.set(SEAT_COOKIE, new_seat_token())
    response = lan.get(f"/api/campaigns/{campaign.id}/probe-table")
    assert response.status_code == 401 and response.json() == {"error": "Log in to go on."}


def test_a_seat_token_never_reaches_an_account_s_seat(app, lan, storage, campaign):
    """An account's seat is reached by logging in to the account, never by a token (audit finding 2)."""
    add_probes(app)
    ana = create_account(storage, "ana", "correct horse battery")
    token = new_seat_token()
    storage.seats.create(campaign.id, "Ana", "en", "player", token_hash=token_hash(token), account_id=ana.id)
    lan.cookies.set(SEAT_COOKIE, token)
    assert lan.get(f"/api/campaigns/{campaign.id}/probe-table").status_code == 401


def test_a_seat_cookie_on_this_machine_is_that_seat(app, storage, campaign):
    """A browser on the host's machine that joined as a player is that player, not the owner: a seat token only ever
    gives less."""
    add_probes(app)
    token = new_seat_token()
    seat = storage.seats.create(campaign.id, "Ana", "nl", "player", token_hash=token_hash(token))
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50002)) as client:
        client.cookies.set(SEAT_COOKIE, token)
        assert client.get("/api/probe-principal").json()["id"] == f"seat:{seat.id}"
        assert client.get("/api/modules").status_code == 403


ORGANISER_ROUTES = (
    "/api/campaigns",
    "/api/modules",
    "/api/house-rules",
    "/api/house-rule-bundles",
    "/api/preferences",
    "/api/settings",
    "/api/settings/greyhawk",
    "/api/settings/greyhawk/search?q=hardby",
    "/api/settings/greyhawk/facts",
    "/api/settings/greyhawk/proposals",
    "/api/campaigns/{id}",
    "/api/campaigns/{id}/dm/log",
    "/api/campaigns/{id}/dm/costs",
    "/api/campaigns/{id}/dm/characters",
    "/api/campaigns/{id}/maps/crypt/dm-view",
    "/api/campaigns/{id}/maps/crypt/state",
    "/api/campaigns/{id}/maps/crypt/doors-and-secrets",
    "/api/campaigns/{id}/house-rules",
)


def test_organiser_routes_refuse_a_seat(join, campaign):
    _, ana = join(campaign.id)
    for path in ORGANISER_ROUTES:
        response = ana.get(path.format(id=campaign.id))
        assert response.status_code == 403, path
        assert response.json() == {"error": "This needs the organiser role."}, path
    assert ana.post(f"/api/campaigns/{campaign.id}/characters", json={"name": "Grik"}).status_code == 403


def test_a_seat_granted_organiser_opens_them(join, campaign):
    _, ana = join(campaign.id, organiser=True)
    for path in ORGANISER_ROUTES:
        assert ana.get(path.format(id=campaign.id)).status_code in (200, 409), path  # 409: the map is offline


def test_a_seat_that_left_gets_403(app, join, storage, campaign):
    add_probes(app)
    seat, ana = join(campaign.id, organiser=True)
    seats.leave(storage, seat)
    for path in ("probe-table", "story", "play/state"):
        response = ana.get(f"/api/campaigns/{campaign.id}/{path}")
        assert response.status_code == 403 and response.json() == {"error": "You have left this table."}
    assert ana.post(f"/api/campaigns/{campaign.id}/act", json={"text": "We wait."}).status_code == 403
    assert ana.get("/api/modules").status_code == 403, "a seat that left keeps no organiser rights"


def test_host_and_actor_seats(app, join, storage, campaign):
    add_probes(app)
    seat, ana = join(campaign.id)
    refused = ana.get(f"/api/campaigns/{campaign.id}/probe-host")
    assert refused.status_code == 403 and refused.json() == {"error": "Only the host can do that."}
    assert ana.get(f"/api/campaigns/{campaign.id}/probe-actor").json() == {"seat": seat.id}

    storage.seats.save(replace(seat, role="cohost"))
    assert ana.get(f"/api/campaigns/{campaign.id}/probe-host").json() == {"seat": seat.id}

    storage.seats.save(replace(seat, role="observer"))
    refused = ana.get(f"/api/campaigns/{campaign.id}/probe-actor")
    assert refused.status_code == 403 and refused.json() == {"error": "Observers don't act."}
    assert ana.get(f"/api/campaigns/{campaign.id}/probe-table").status_code == 200, "an observer sees the table"
    refused = ana.post(f"/api/campaigns/{campaign.id}/act", json={"text": "We wait."})
    assert refused.status_code == 403 and refused.json() == {"error": "Observers don't act."}


def test_an_act_is_the_seats(app, join, storage, campaign):
    """The beat's submission names the seat that acted, not the principal."""
    seat, ana = join(campaign.id)
    assert ana.post(f"/api/campaigns/{campaign.id}/act", json={"text": "We wait."}).status_code == 202
    beat = storage.beats.current(campaign.id) or storage.beats.get(
        ana.get(f"/api/campaigns/{campaign.id}/story").json()["entries"][0]["beat_id"]
    )
    assert beat.submissions[0]["seat_id"] == seat.id
