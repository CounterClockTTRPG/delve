"""An account's seats (players and tavern Task C3): the seat dependencies find an account's live seat at each table,
and nowhere else; a seat token made before accounts works as it did."""

from dataclasses import replace
from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from delve.play import seats
from delve.web.routes.rulesets import Reader, ruleset_reader
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, make_account, session_for
from tests.web.test_seats_identity import add_probes, make_campaign

NO_SEAT = {"error": "You have no seat at this table."}


@pytest.fixture
def campaign(storage):
    return make_campaign(storage)


@pytest.fixture
def other(storage):
    return make_campaign(storage, "Friday")


@pytest.fixture
def ana(storage):
    return make_account(storage)


@pytest.fixture
def player(app, storage, ana):
    """A browser on the LAN, logged in as `ana`."""
    with TestClient(app, base_url=BASE_URL) as client:
        session_for(storage, ana, client)
        yield client


def test_table_seat_finds_the_accounts_seat(app, storage, ana, player, campaign, other):
    add_probes(app)
    seat = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    assert player.get(f"/api/campaigns/{campaign.id}/seats").status_code == 200
    assert player.get(f"/api/campaigns/{campaign.id}/probe-table").json() == {"seat": seat.id}
    assert player.get(f"/api/campaigns/{campaign.id}/play/state").status_code == 200
    refused = player.get(f"/api/campaigns/{other.id}/seats")
    assert refused.status_code == 403 and refused.json() == NO_SEAT
    assert player.get("/api/campaigns/cmp_000000000000/probe-table").status_code == 404

    seats.leave(storage, seat)
    refused = player.get(f"/api/campaigns/{campaign.id}/probe-table")
    assert refused.status_code == 403 and refused.json() == NO_SEAT, "a seat that left is no seat"


def test_host_and_actor_seats_for_accounts(app, storage, ana, player, campaign):
    add_probes(app)
    seat = storage.seats.create(campaign.id, "Ana", "en", "observer", account_id=ana.id)
    assert player.get(f"/api/campaigns/{campaign.id}/probe-host").status_code == 403
    refused = player.get(f"/api/campaigns/{campaign.id}/probe-actor")
    assert refused.status_code == 403 and refused.json() == {"error": "Observers don't act."}
    storage.seats.save(replace(seat, role="cohost"))
    assert player.get(f"/api/campaigns/{campaign.id}/probe-host").json() == {"seat": seat.id}
    assert player.get(f"/api/campaigns/{campaign.id}/probe-actor").json() == {"seat": seat.id}


def test_an_owner_account_has_the_owner_seat(app, storage, lan, campaign):
    add_probes(app)
    session_for(storage, make_account(storage, "olga", owner=True), lan)
    owner_seat = seats.owner_seat(storage, campaign.id)
    assert lan.get(f"/api/campaigns/{campaign.id}/probe-host").json() == {"seat": owner_seat.id}


def test_an_organiser_account_has_no_seat_it_wasnt_given(app, storage, lan, campaign):
    add_probes(app)
    session_for(storage, make_account(storage, "otto", organiser=True), lan)
    assert lan.get(f"/api/campaigns/{campaign.id}/probe-table").json() == NO_SEAT
    assert lan.get(f"/api/campaigns/{campaign.id}").status_code == 200, "an organiser route, as an organiser"


def test_old_seat_tokens_still_work(join, campaign, other, app, storage):
    """A seat made by a token before accounts: the probes of `test_seats_identity` answer as they did."""
    add_probes(app)
    seat, client = join(campaign.id)
    assert seat.account_id is None
    assert client.get("/api/probe-principal").json() == {"id": f"seat:{seat.id}", "roles": [], "seat": seat.id}
    assert client.get(f"/api/campaigns/{campaign.id}/probe-table").json() == {"seat": seat.id}
    assert client.get(f"/api/campaigns/{campaign.id}/probe-actor").json() == {"seat": seat.id}
    assert client.get(f"/api/campaigns/{campaign.id}/probe-host").status_code == 403
    refused = client.get(f"/api/campaigns/{other.id}/probe-table")
    assert refused.status_code == 403 and refused.json() == {"error": "This seat is for another table."}
    assert client.get("/api/modules").status_code == 403
    me = client.get(f"/api/me?campaign={campaign.id}").json()
    assert me["account"] is None and me["seat"]["id"] == seat.id


def test_me_for_an_account(storage, ana, player, campaign, other):
    seat = storage.seats.create(campaign.id, "Ana", "nl", "player", account_id=ana.id)
    me = player.get(f"/api/me?campaign={campaign.id}").json()
    assert me["principal"] == {"id": f"account:{ana.id}", "roles": []}
    assert me["account"] == {
        "id": ana.id,
        "username": "ana",
        "display_name": "ana",
        "language": "en",
        "organiser": False,
        "owner": False,
    }
    assert me["seat"]["id"] == seat.id and me["seat"]["campaign_id"] == campaign.id
    assert me["seat"]["campaign_name"] == "Tuesday"
    assert player.get(f"/api/me?campaign={other.id}").json()["seat"] is None
    assert player.get("/api/me").json()["seat"] is None


def test_me_for_the_owner_has_no_account(local, campaign):
    me = local.get(f"/api/me?campaign={campaign.id}").json()
    assert me["account"] is None and me["seat"]["role"] == "host"


def test_account_reads_rulesets_with_its_table(app, storage, ana, player, campaign, other):
    @app.get("/api/probe-reader")
    def probe(reader: Annotated[Reader, Depends(ruleset_reader)]):
        return {"campaign": reader.campaign and reader.campaign.id, "organiser": reader.organiser}

    storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    read = player.get(f"/api/probe-reader?campaign={campaign.id}")
    assert read.json() == {"campaign": campaign.id, "organiser": False}, "with its table's house rules"
    refused = player.get(f"/api/probe-reader?campaign={other.id}")
    assert refused.status_code == 403 and refused.json() == NO_SEAT
    assert player.get("/api/probe-reader").json() == {"campaign": None, "organiser": False}, "the book alone"
    assert player.get(f"/api/rulesets?campaign={other.id}").status_code == 403
    assert player.get("/api/rulesets").status_code == 200


def test_an_organiser_account_reads_any_tables_rules(app, storage, lan, campaign):
    @app.get("/api/probe-reader")
    def probe(reader: Annotated[Reader, Depends(ruleset_reader)]):
        return {"campaign": reader.campaign and reader.campaign.id, "organiser": reader.organiser}

    session_for(storage, make_account(storage, "otto", organiser=True), lan)
    assert lan.get(f"/api/probe-reader?campaign={campaign.id}").json() == {"campaign": campaign.id, "organiser": True}


def test_organiser_on_an_account_seat_is_the_players_page(storage, ana, local, campaign):
    seat = storage.seats.create(campaign.id, "Ana", "en", "player", account_id=ana.id)
    response = local.put(f"/api/campaigns/{campaign.id}/seats/{seat.id}", json={"organiser": True})
    assert response.status_code == 422
    assert response.json() == {"error": "Give an account organiser rights on the Players page."}
    assert storage.seats.get(seat.id).organiser is False
    assert local.put(f"/api/campaigns/{campaign.id}/seats/{seat.id}", json={"role": "cohost"}).status_code == 200


def test_an_owner_account_makes_a_token_seat_organiser(app, storage, lan, campaign, join):
    session_for(storage, make_account(storage, "olga", owner=True), lan)
    seat, _ = join(campaign.id)
    response = lan.put(f"/api/campaigns/{campaign.id}/seats/{seat.id}", json={"organiser": True})
    assert response.status_code == 200 and storage.seats.get(seat.id).organiser is True


def test_an_organiser_account_cant_make_organisers(storage, campaign, join, app):
    otto = make_account(storage, "otto", organiser=True)
    storage.seats.create(campaign.id, "Otto", "en", "cohost", account_id=otto.id)
    seat, _ = join(campaign.id)
    with TestClient(app, base_url=BASE_URL) as client:
        session_for(storage, otto, client)
        response = client.put(f"/api/campaigns/{campaign.id}/seats/{seat.id}", json={"organiser": True})
    assert response.status_code == 403 and response.json() == {
        "error": "Only the owner of this Delve makes organisers."
    }


@pytest.fixture
def join(app, storage):
    """`join(campaign_id, role="player")`: a seat made by a token, as before accounts, and a LAN browser holding it."""
    clients = []

    def make(campaign_id, role="player"):
        token = new_seat_token()
        seat = storage.seats.create(campaign_id, "Bo", "nl", role, token_hash=token_hash(token))
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        return seat, client

    yield make
    for client in clients:
        client.__exit__(None, None, None)
