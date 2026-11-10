"""Finding a table and asking to join (DEL-204 part B): logged-in accounts list the public tables, ask to join one with
a note, talk with its hosts on the request and withdraw it; the host or a co-host reads the table's requests, accepts
one (a player's seat) or declines it. A full table takes no request and no accept, and makes no observer a player.
Each change publishes `join_requests` to the table's host and co-hosts."""

import pytest

from delve.play import house_rules, seats
from tests.web.conftest import log_in, make_account
from tests.web.test_join_api import browser, campaign, joined, seats_events, token_seat  # noqa: F401
from tests.web.test_preferences_api import published
from tests.web.test_seats_identity import make_campaign

NOTE = "Hi! I'd love to join on Tuesdays."


def public(storage, campaign, slots=None, description="Newcomers welcome."):  # noqa: F811
    return storage.campaigns.set_listing(campaign.id, "public", description, slots)


@pytest.fixture
def listed(storage, campaign):  # noqa: F811
    return public(storage, campaign)


@pytest.fixture
def account(storage, browser):  # noqa: F811
    """`account("boris", address)`: a browser logged in to a new account of that username."""

    def make(username="boris", address="10.0.0.40"):
        made = make_account(storage, username)
        client = browser(address)
        log_in(client, username)
        return made, client

    return make


def requests_events(app):
    return [(e.data, e.scope, e.campaign_id, e.roles) for e in published(app) if e.type == "join_requests"]


def ask(client, campaign, note=NOTE):  # noqa: F811
    return client.post(f"/api/tables/{campaign.id}/requests", json={"note": note})


def requests_path(campaign, request_id=None, action=None):  # noqa: F811
    path = f"/api/campaigns/{campaign.id}/requests"
    return path if request_id is None else f"{path}/{request_id}/{action}"


# ----- the public tables -----


def test_an_account_lists_the_public_tables(storage, campaign, listed, account):  # noqa: F811
    rule = storage.house_rules.create(title="Honest dice", body_md="All rolls are in the open.")
    house_rules.set_campaign_house_rules(storage, campaign.id, bundle_ids=[], rule_ids=[rule.id])
    private = make_campaign(storage, "Friday")
    seats.owner_seat(storage, private.id)
    done = public(storage, make_campaign(storage, "Done"))
    storage.campaigns.set_status(done.id, "complete")
    _, client = account()
    answer = client.get("/api/tables")
    assert answer.status_code == 200, answer.text
    assert answer.json() == [
        {
            "campaign_id": campaign.id,
            "name": "Tuesday",
            "module_title": "The Crypt",
            "ruleset": "osric",
            "ruleset_title": "osric",
            "setting": "greyhawk",
            "setting_title": "Greyhawk",
            "description": "Newcomers welcome.",
            "slots": None,
            "observers": "anyone",
            "taken": 0,
            "full": False,
            "house_rules": [{"id": rule.id, "title": "Honest dice", "body_md": "All rolls are in the open."}],
            "schedule": None,
            "next_sessions": [],
            "host": {"display_name": "Host", "profile": None},
            "people": [{"seat_id": seats.owner_seat(storage, campaign.id).id, "name": "Host", "role": "host", "profile": None}],
            "seated": False,
            "request": None,
        }
    ], "not the private table nor the complete one; a ruleset without a title is named by its id"


def test_the_most_recently_played_table_comes_first(storage, campaign, listed, account):  # noqa: F811
    later = public(storage, make_campaign(storage, "Friday"))
    never = public(storage, make_campaign(storage, "Sunday"))
    for table in (campaign, later):  # played in that order
        storage.story.append(table.id, None, "dm_text", {"text": "…"})
    _, client = account()
    assert [t["campaign_id"] for t in client.get("/api/tables").json()] == [later.id, campaign.id, never.id]


def test_the_listing_shows_the_host_s_profile_and_the_account_s_place(storage, campaign, listed, account):  # noqa: F811
    hostess = make_account(storage, "hana")
    host = storage.seats.create(campaign.id, "Hana", "en", "player", account_id=hostess.id)
    seats.set_role(storage, campaign.id, host.id, "host", by=seats.owner_seat(storage, campaign.id))
    public(storage, campaign, slots=2)
    boris, client = account()
    asked = ask(client, campaign).json()["request"]
    table = client.get("/api/tables").json()[0]
    assert table["host"]["display_name"] == "hana" and table["host"]["profile"]["account_id"] == hostess.id
    assert (table["taken"], table["full"], table["seated"]) == (1, False, False), "the old host is a co-host now"
    assert table["request"] == {"id": asked["id"], "status": "pending"}
    storage.seats.create(campaign.id, "Boris", "en", "player", account_id=boris.id)
    table = client.get("/api/tables").json()[0]
    assert (table["seated"], table["full"]) == (True, True)
    assert [(p["name"], p["role"]) for p in table["people"]] == [("Hana", "host"), ("Host", "cohost"), ("Boris", "player")]
    assert table["people"][0]["profile"]["account_id"] == hostess.id
    # Find a table shows them, so any account reads their card; not the note for the host.
    card = client.get(f"/api/profiles/{hostess.id}")
    assert card.status_code == 200 and "host_note" not in card.json()


def test_only_an_account_lists_the_tables(local, browser, listed, token_seat):  # noqa: F811
    assert browser().get("/api/tables").status_code == 401
    assert local.get("/api/tables").status_code == 403, "the owner token alone is no account"
    _, seat_client = token_seat()
    assert seat_client.get("/api/tables").status_code == 403


def test_the_owner_account_sees_them_seated(storage, listed, browser):  # noqa: F811
    make_account(storage, "olga", owner=True)
    client = browser()
    log_in(client, "olga")
    assert client.get("/api/tables").json()[0]["seated"] is True


# ----- asking -----


def test_asking_to_join(app, storage, campaign, listed, account):  # noqa: F811
    boris, client = account()
    answer = ask(client, campaign, f"  {NOTE}  ")
    assert answer.status_code == 201, answer.text
    asked = answer.json()["request"]
    assert asked["id"].startswith("jrq_") and asked["campaign_id"] == campaign.id
    assert (asked["status"], asked["decided_at"], asked["seat_id"]) == ("pending", None, None)
    assert [(m["from"], m["name"], m["text"]) for m in asked["messages"]] == [("player", "boris", NOTE)]
    assert asked["account"]["id"] == boris.id and asked["account"]["display_name"] == "boris"
    assert asked["account"]["profile"]["account_id"] == boris.id
    assert requests_events(app) == [({"campaign_id": campaign.id}, "table", campaign.id, ("host", "cohost"))]


def test_a_request_without_a_note(campaign, listed, account):  # noqa: F811
    _, client = account()
    answer = client.post(f"/api/tables/{campaign.id}/requests", json={"note": ""})
    assert answer.status_code == 201 and answer.json()["request"]["messages"] == []


def test_asking_is_refused(app, storage, campaign, account, joined):  # noqa: F811
    _, client = account()
    assert ask(client, campaign).status_code == 404, "a private table isn't there"
    assert client.post("/api/tables/cmp_nope/requests", json={"note": ""}).status_code == 404
    public(storage, campaign)
    long = ask(client, campaign, "x" * 1001)
    assert long.status_code == 422 and "error" in long.json()
    assert ask(client, campaign).status_code == 201
    again = ask(client, campaign)
    assert again.status_code == 409 and again.json() == {"error": "You asked already: wait for the host."}

    seated, _ = joined("Ana")
    at = ask(seated, campaign)
    assert at.status_code == 409 and at.json() == {"error": "You're at this table already."}

    public(storage, campaign, slots=1)
    _, late = account("cyril", "10.0.0.41")
    full = ask(late, campaign)
    assert full.status_code == 409 and full.json() == {"error": "The table is full."}
    assert len(requests_events(app)) == 1


def test_a_complete_table_takes_no_request(storage, campaign, listed, account):  # noqa: F811
    storage.campaigns.set_status(campaign.id, "complete")
    _, client = account()
    assert ask(client, campaign).status_code == 404


def test_the_account_reads_its_requests(storage, campaign, listed, account):  # noqa: F811
    other = public(storage, make_campaign(storage, "Friday"))
    seats.owner_seat(storage, other.id)
    _, client = account()
    first = ask(client, campaign).json()["request"]
    second = ask(client, other, "").json()["request"]
    mine = client.get("/api/account/requests").json()
    assert [r["id"] for r in mine] == [second["id"], first["id"]], "newest first"
    assert mine[1] == {**first, "campaign": {"id": campaign.id, "name": "Tuesday", "module_title": "The Crypt"}}
    _, stranger = account("cyril", "10.0.0.41")
    assert stranger.get("/api/account/requests").json() == []


# ----- talking -----


def test_the_player_and_the_hosts_talk(app, local, storage, campaign, listed, account, token_seat):  # noqa: F811
    _, client = account()
    asked = ask(client, campaign).json()["request"]
    _, cohost = token_seat("Bo", "cohost")
    path = f"/api/requests/{asked['id']}/messages"
    by_host = local.post(path, json={"text": "Welcome! We start at eight."})
    assert by_host.status_code == 201, by_host.text
    by_cohost = cohost.post(path, json={"text": "Bring dice."})
    by_player = client.post(path, json={"text": "  See you then.  "})
    assert by_player.status_code == 201
    thread = by_player.json()["request"]["messages"]
    assert [(m["from"], m["name"], m["text"]) for m in thread] == [
        ("player", "boris", NOTE),
        ("host", "Host", "Welcome! We start at eight."),
        ("host", "Bo", "Bring dice."),
        ("player", "boris", "See you then."),
    ]
    assert by_cohost.json()["request"]["messages"][-1]["name"] == "Bo"
    assert len(requests_events(app)) == 4


def test_nobody_else_talks_on_the_request(browser, campaign, listed, account, joined, token_seat):  # noqa: F811
    _, client = account()
    asked = ask(client, campaign).json()["request"]
    path = f"/api/requests/{asked['id']}/messages"
    _, other = account("cyril", "10.0.0.41")
    player, _ = joined("Ana")
    _, observer = token_seat("Dee", "observer")
    for stranger in (other, player, observer):
        assert stranger.post(path, json={"text": "Hello?"}).status_code == 403
    assert browser("10.0.0.42").post(path, json={"text": "Hello?"}).status_code == 401
    assert client.post("/api/requests/jrq_nope/messages", json={"text": "Hi"}).status_code == 404


def test_a_message_that_isnt_allowed(campaign, listed, account):  # noqa: F811
    _, client = account()
    asked = ask(client, campaign).json()["request"]
    path = f"/api/requests/{asked['id']}/messages"
    for wrong in ({"text": ""}, {"text": "   "}, {"text": "x" * 1001}, {"text": 5}, {}):
        assert client.post(path, json=wrong).status_code == 422, wrong
    for n in range(49):
        assert client.post(path, json={"text": f"message {n}"}).status_code == 201
    past = client.post(path, json={"text": "one more"})
    assert past.status_code == 409 and past.json() == {"error": "Talk at the table once you're seated."}


# ----- withdrawing -----


def test_withdrawing(app, campaign, listed, account):  # noqa: F811
    _, client = account()
    asked = ask(client, campaign).json()["request"]
    _, other = account("cyril", "10.0.0.41")
    path = f"/api/requests/{asked['id']}/withdraw"
    assert other.post(path, json={}).status_code == 403
    withdrawn = client.post(path, json={})
    assert withdrawn.status_code == 200 and withdrawn.json()["request"]["status"] == "withdrawn"
    assert withdrawn.json()["request"]["decided_at"]
    assert client.post(path, json={}).status_code == 409
    talk = client.post(f"/api/requests/{asked['id']}/messages", json={"text": "Wait!"})
    assert talk.status_code == 409
    assert len(requests_events(app)) == 2
    assert ask(client, campaign).status_code == 201, "asking again"


# ----- the host's side -----


def test_the_hosts_read_the_table_s_requests(local, storage, campaign, listed, account, joined, token_seat):  # noqa: F811
    _, boris = account()
    _, cyril = account("cyril", "10.0.0.41")
    first = ask(boris, campaign).json()["request"]
    second = ask(cyril, campaign).json()["request"]
    boris.post(f"/api/requests/{first['id']}/withdraw", json={})
    listed_ = local.get(requests_path(campaign))
    assert listed_.status_code == 200
    assert [(r["id"], r["status"]) for r in listed_.json()] == [(second["id"], "pending"), (first["id"], "withdrawn")]
    _, cohost = token_seat("Bo", "cohost")
    assert cohost.get(requests_path(campaign)).status_code == 200
    player, _ = joined("Ana")
    assert player.get(requests_path(campaign)).status_code == 403
    assert boris.get(requests_path(campaign)).status_code == 403, "no seat there"


def test_accepting_seats_the_account(app, local, storage, campaign, listed, account):  # noqa: F811
    boris, client = account()
    asked = ask(client, campaign).json()["request"]
    before = len(seats_events(app))
    accepted = local.post(requests_path(campaign, asked["id"], "accept"), json={})
    assert accepted.status_code == 200, accepted.text
    seat, request = accepted.json()["seat"], accepted.json()["request"]
    assert (seat["name"], seat["role"], seat["profile"]["account_id"]) == ("boris", "player", boris.id)
    assert (request["status"], request["seat_id"]) == ("accepted", seat["id"]) and request["decided_at"]
    assert storage.seats.for_account(boris.id, campaign.id).id == seat["id"]
    assert seats_events(app)[before:] == [{"campaign_id": campaign.id}]
    assert len(requests_events(app)) == 2
    assert client.get(f"/api/campaigns/{campaign.id}/seats").status_code == 200, "seated now"
    assert client.get("/api/tables").json()[0]["seated"] is True
    assert local.post(requests_path(campaign, asked["id"], "accept"), json={}).status_code == 409


def test_accepting_at_a_full_table(local, storage, campaign, listed, account, joined):  # noqa: F811
    boris, client = account()
    asked = ask(client, campaign).json()["request"]
    public(storage, campaign, slots=1)
    joined("Ana")
    refused = local.post(requests_path(campaign, asked["id"], "accept"), json={})
    assert refused.status_code == 409 and refused.json() == {"error": "The table is full."}
    assert storage.join_requests.get(asked["id"]).status == "pending"

    seat = storage.seats.create(campaign.id, "Boris", "en", "player", account_id=boris.id)  # by the link meanwhile
    kept = local.post(requests_path(campaign, asked["id"], "accept"), json={})
    assert kept.status_code == 200 and kept.json()["seat"]["id"] == seat.id
    assert kept.json()["request"]["seat_id"] == seat.id


def test_a_request_of_another_table_is_404(local, storage, campaign, listed, account):  # noqa: F811
    other = public(storage, make_campaign(storage, "Friday"))
    seats.owner_seat(storage, other.id)
    _, client = account()
    elsewhere = ask(client, other).json()["request"]
    for action in ("accept", "decline"):
        assert local.post(requests_path(campaign, elsewhere["id"], action), json={}).status_code == 404
    assert local.post(requests_path(campaign, "jrq_nope", "accept"), json={}).status_code == 404


def test_declining_with_a_reason(app, local, storage, campaign, listed, account, token_seat):  # noqa: F811
    _, client = account()
    asked = ask(client, campaign).json()["request"]
    _, cohost = token_seat("Bo", "cohost")
    declined = cohost.post(requests_path(campaign, asked["id"], "decline"), json={"reason": "We're full this arc."})
    assert declined.status_code == 200, declined.text
    request = declined.json()["request"]
    assert request["status"] == "declined" and request["decided_at"]
    assert (request["messages"][-1]["from"], request["messages"][-1]["name"]) == ("host", "Bo")
    assert request["messages"][-1]["text"] == "We're full this arc."
    assert local.post(requests_path(campaign, asked["id"], "decline"), json={"reason": ""}).status_code == 409
    assert client.get("/api/tables").json()[0]["request"]["status"] == "declined"


def test_declining_without_a_reason(local, campaign, listed, account):  # noqa: F811
    _, client = account()
    asked = ask(client, campaign).json()["request"]
    declined = local.post(requests_path(campaign, asked["id"], "decline"), json={"reason": ""})
    assert declined.status_code == 200 and len(declined.json()["request"]["messages"]) == 1
    _, other = account("cyril", "10.0.0.41")
    second = ask(other, campaign).json()["request"]
    assert local.post(requests_path(campaign, second["id"], "decline"), json={}).status_code == 200
    _, third = account("dora", "10.0.0.42")
    third_request = ask(third, campaign).json()["request"]
    too_long = local.post(requests_path(campaign, third_request["id"], "decline"), json={"reason": "x" * 1001})
    assert too_long.status_code == 422


def test_a_player_neither_accepts_nor_declines(campaign, listed, account, joined):  # noqa: F811
    _, client = account()
    asked = ask(client, campaign).json()["request"]
    player, _ = joined("Ana")
    for action in ("accept", "decline"):
        assert player.post(requests_path(campaign, asked["id"], action), json={}).status_code == 403
        assert client.post(requests_path(campaign, asked["id"], action), json={}).status_code == 403


# ----- a role change at a full table -----


def test_a_full_table_makes_no_observer_a_player(local, storage, campaign, joined):  # noqa: F811
    public(storage, campaign, slots=1)
    joined("Ana")
    _, watcher = joined("Bo", role="observer", address="10.0.0.8")
    path = f"/api/campaigns/{campaign.id}/seats/{watcher['id']}"
    for role in ("player", "cohost"):
        refused = local.put(path, json={"role": role})
        assert refused.status_code == 409 and refused.json() == {"error": "The table is full."}
    assert storage.seats.get(watcher["id"]).role == "observer"
    public(storage, campaign, slots=2)
    assert local.put(path, json={"role": "player"}).status_code == 200
