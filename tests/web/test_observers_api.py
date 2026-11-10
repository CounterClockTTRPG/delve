"""Who may watch a table (DEL-215), through the API: anyone with the join link (as before), those a host lets in,
who ask as a player asks at a public table, or nobody. Players join as they always did."""

from tests.web.conftest import PASSWORD
from tests.web.test_join_api import browser, campaign  # noqa: F401
from tests.web.test_join_requests_api import account, public  # noqa: F401


def join_new(client, campaign, role, username):  # noqa: F811
    body = {
        "username": username,
        "password": PASSWORD,
        "display_name": username.title(),
        "language": "en",
        "role": role,
    }
    return client.post(f"/api/join/{campaign.join_token}/account", json=body)


def test_the_host_sets_who_may_watch(local, campaign):  # noqa: F811
    assert local.get(f"/api/campaigns/{campaign.id}").json()["observers"] == "anyone"
    path = f"/api/campaigns/{campaign.id}/table-settings"
    assert local.put(path, json={"observers": "approved"}).json()["observers"] == "approved"
    assert local.put(path, json={"observers": "friends"}).status_code == 422
    assert local.get(f"/api/join/{campaign.join_token}").json()["campaign"]["observers"] == "approved"


def test_anyone_with_the_link_watches_at_once(browser, campaign):  # noqa: F811
    made = join_new(browser("10.0.0.7"), campaign, "observer", "cyril")
    assert made.status_code == 201 and made.json()["seat"]["role"] == "observer"


def test_a_table_that_takes_no_observers_refuses_one_before_the_account_is_made(storage, browser, campaign, account):  # noqa: F811
    storage.campaigns.set_observers(campaign.id, "nobody")
    refused = join_new(browser("10.0.0.7"), campaign, "observer", "cyril")
    assert refused.status_code == 409 and refused.json()["error"] == "This table takes no observers."
    assert storage.accounts.by_username("cyril") is None
    _, client = account("dora")
    assert client.post(f"/api/join/{campaign.join_token}", json={"role": "observer"}).status_code == 409
    assert join_new(browser("10.0.0.8"), campaign, "player", "pia").status_code == 201, "players join as before"


def test_where_the_host_lets_watchers_in_the_link_asks(local, storage, browser, campaign, account):  # noqa: F811
    """Watch on the link asks, for a new account and a logged-in one, and accepting the request seats an observer."""
    storage.campaigns.set_observers(campaign.id, "approved")
    asked = join_new(browser("10.0.0.7"), campaign, "observer", "cyril")
    assert asked.status_code == 202 and "seat" not in asked.json()
    request = asked.json()["join_request"]
    assert (request["role"], request["status"]) == ("observer", "pending")
    assert asked.json()["account"]["username"] == "cyril", "the account is made and logged in"

    _, dora = account("dora")
    again = dora.post(f"/api/join/{campaign.join_token}", json={"role": "observer"})
    assert again.status_code == 202 and again.json()["join_request"]["role"] == "observer"
    assert dora.post(f"/api/join/{campaign.join_token}", json={"role": "observer"}).status_code == 409, "asked already"

    listed = local.get(f"/api/campaigns/{campaign.id}/requests").json()
    assert {r["role"] for r in listed} == {"observer"}
    accepted = local.post(f"/api/campaigns/{campaign.id}/requests/{request['id']}/accept", json={})
    assert accepted.status_code == 200, accepted.text
    seat = storage.seats.get(accepted.json()["request"]["seat_id"])
    assert seat.role == "observer"


def test_find_a_table_asks_to_watch_unless_the_table_takes_none(storage, campaign, account):  # noqa: F811
    public(storage, campaign, slots=1)
    _, client = account("dora")
    path = f"/api/tables/{campaign.id}/requests"
    assert client.get("/api/tables").json()[0]["observers"] == "anyone"
    asked = client.post(path, json={"note": "Just watching.", "role": "observer"})
    assert asked.status_code == 201 and asked.json()["request"]["role"] == "observer"
    _, eve = account("eve", "10.0.0.41")
    assert eve.post(path, json={"role": "spectator"}).status_code == 422
    storage.campaigns.set_observers(campaign.id, "nobody")
    assert eve.post(path, json={"role": "observer"}).status_code == 409
