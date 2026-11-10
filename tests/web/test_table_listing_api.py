"""The table's listing and removing a seat (DEL-204 part A): an organiser sets a campaign's visibility, its players'
description and its places for players; everyone at the table reads them with the house rules, and so does the join
link. A full table seats no new player; an observer always joins. The host, or a co-host, removes a seat from the
table as Leave would; only the host removes a co-host."""

from delve.play import house_rules as play_house_rules
from tests.web.conftest import PASSWORD, log_in, make_account
from tests.web.test_join_api import browser, campaign, garrek, joined, seats_events, token_seat  # noqa: F401
from tests.web.test_preferences_api import published

LISTING = {"visibility": "public", "description": "We play on **Tuesdays**. Newcomers welcome.", "slots": 2}


def listing_path(campaign) -> str:  # noqa: F811
    return f"/api/campaigns/{campaign.id}/listing"


def remove_path(campaign, seat_id: str) -> str:  # noqa: F811
    return f"/api/campaigns/{campaign.id}/seats/{seat_id}/remove"


# ----- the listing -----


def test_a_new_campaign_is_private_without_a_limit(local, campaign):  # noqa: F811
    listed = local.get("/api/campaigns").json()[0]
    assert (listed["visibility"], listed["description"], listed["slots"]) == ("private", "", None)
    page = local.get(f"/api/campaigns/{campaign.id}").json()
    assert (page["visibility"], page["description"], page["slots"]) == ("private", "", None)


def test_an_organiser_sets_the_listing(app, local, storage, campaign):  # noqa: F811
    put = local.put(listing_path(campaign), json={**LISTING, "description": "  We play on **Tuesdays**.  "})
    assert put.status_code == 200, put.text
    page = local.get(f"/api/campaigns/{campaign.id}").json()
    assert put.json() == page, "the campaign as its page reads it"
    assert (page["visibility"], page["description"], page["slots"]) == ("public", "We play on **Tuesdays**.", 2)
    stored = storage.campaigns.get(campaign.id)
    assert (stored.visibility, stored.description, stored.slots) == ("public", "We play on **Tuesdays**.", 2)
    assert local.put(listing_path(campaign), json={**LISTING, "slots": None}).json()["slots"] is None

    events = published(app)
    assert [e.data for e in events if e.type == "campaigns"] == [{"id": campaign.id}] * 2
    told = [(e.data, e.scope, e.campaign_id) for e in events if e.type == "table_listing"]
    assert told == [({"campaign_id": campaign.id}, "table", campaign.id)] * 2


def test_a_wrong_listing_is_422(local, storage, campaign):  # noqa: F811
    for wrong in (
        {**LISTING, "visibility": "secret"},
        {**LISTING, "description": "x" * 4001},
        {**LISTING, "slots": 0},
        {**LISTING, "slots": 21},
        {**LISTING, "slots": "3"},
        {**LISTING, "slots": True},
        {**LISTING, "description": None},
        {"visibility": "public", "description": ""},
        {**LISTING, "tone": "grim"},
    ):
        answer = local.put(listing_path(campaign), json=wrong)
        assert answer.status_code == 422 and "error" in answer.json(), wrong
    stored = storage.campaigns.get(campaign.id)
    assert (stored.visibility, stored.description, stored.slots) == ("private", "", None)
    edge = local.put(listing_path(campaign), json={**LISTING, "description": " " + "x" * 4000 + " ", "slots": 20})
    assert edge.status_code == 200 and len(edge.json()["description"]) == 4000, "4000 after strip"
    assert local.put("/api/campaigns/cmp_nope/listing", json=LISTING).status_code == 404


def test_only_an_organiser_sets_the_listing(storage, campaign, token_seat):  # noqa: F811
    _, cohost = token_seat("Bo", "cohost")
    refused = cohost.put(listing_path(campaign), json=LISTING)
    assert refused.status_code == 403
    assert storage.campaigns.get(campaign.id).visibility == "private"


def test_everyone_at_the_table_reads_the_listing(local, storage, campaign, joined, token_seat):  # noqa: F811
    rules = [
        storage.house_rules.create(title="Honest dice", body_md="All rolls are in the open.", phases=["always"]),
        storage.house_rules.create(title="Off", body_md="Disabled.", enabled=False),
        storage.house_rules.create(title="Max HP", body_md="Start at maximum HP."),
    ]
    play_house_rules.set_campaign_house_rules(storage, campaign.id, bundle_ids=[], rule_ids=[r.id for r in rules])
    local.put(listing_path(campaign), json={**LISTING, "slots": 3})
    ana, _ = joined("Ana")
    joined("Bo", role="observer")
    token_seat("Cy", "cohost")
    answer = ana.get(listing_path(campaign))
    assert answer.status_code == 200
    assert answer.json() == {
        "visibility": "public",
        "description": LISTING["description"],
        "slots": 3,
        "taken": 2,
        "house_rules": [
            {"id": rules[0].id, "title": "Honest dice", "body_md": "All rolls are in the open."},
            {"id": rules[2].id, "title": "Max HP", "body_md": "Start at maximum HP."},
        ],
        "schedule": None,
        "next_sessions": [],
    }, "the player and the co-host take a place; the host and the observer none"
    assert local.get(listing_path(campaign)).json()["taken"] == 2


def test_the_listing_is_the_tables_own(browser, campaign):  # noqa: F811
    assert browser().get(listing_path(campaign)).status_code == 401


def test_the_join_link_shows_the_listing(local, storage, browser, campaign):  # noqa: F811
    rule = storage.house_rules.create(title="Honest dice", body_md="All rolls are in the open.")
    play_house_rules.set_campaign_house_rules(storage, campaign.id, bundle_ids=[], rule_ids=[rule.id])
    local.put(listing_path(campaign), json=LISTING)
    shown = browser().get(f"/api/join/{campaign.join_token}").json()["campaign"]
    assert shown == {
        "name": "Tuesday",
        "host": "Host",
        "module_title": "The Crypt",
        "description": LISTING["description"],
        "slots": 2,
        "observers": "anyone",
        "taken": 0,
        "full": False,
        "house_rules": [{"id": rule.id, "title": "Honest dice", "body_md": "All rolls are in the open."}],
        "next_sessions": [],
    }
    local.put(listing_path(campaign), json={**LISTING, "slots": None})
    unlimited = browser("10.0.0.8").get(f"/api/join/{campaign.join_token}").json()["campaign"]
    assert (unlimited["slots"], unlimited["full"]) == (None, False)


# ----- a full table -----


def test_a_full_table_seats_no_new_player(app, local, storage, browser, campaign, joined):  # noqa: F811
    local.put(listing_path(campaign), json={**LISTING, "slots": 1})
    joined("Ana")
    assert browser("10.0.0.8").get(f"/api/join/{campaign.join_token}").json()["campaign"]["full"] is True
    before = len(seats_events(app))

    make_account(storage, "boris")
    bo = browser("10.0.0.9")
    log_in(bo, "boris")
    refused = bo.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert refused.status_code == 409 and refused.json() == {"error": "The table is full."}

    body = {"username": "cyril", "password": PASSWORD, "display_name": "Cy", "language": "en", "role": "player"}
    made = browser("10.0.0.10").post(f"/api/join/{campaign.join_token}/account", json=body)
    assert made.status_code == 409 and made.json() == {"error": "The table is full."}
    assert storage.accounts.by_username("cyril") is None, "refused before the account is made"
    assert len(seats_events(app)) == before

    watching = bo.post(f"/api/join/{campaign.join_token}", json={"role": "observer"})
    assert watching.status_code == 201, "an observer always joins"
    observer = browser("10.0.0.11").post(f"/api/join/{campaign.join_token}/account", json={**body, "role": "observer"})
    assert observer.status_code == 201


def test_a_seated_account_gets_its_seat_back_at_a_full_table(local, storage, browser, campaign):  # noqa: F811
    make_account(storage)
    ana = browser()
    log_in(ana)
    seat = ana.post(f"/api/join/{campaign.join_token}", json={"role": "player"}).json()["seat"]
    local.put(listing_path(campaign), json={**LISTING, "slots": 1})
    again = ana.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert again.status_code == 200 and again.json()["seat"]["id"] == seat["id"]


def test_fewer_slots_than_taken_removes_nobody(local, storage, campaign, joined):  # noqa: F811
    joined("Ana")
    joined("Bo")
    put = local.put(listing_path(campaign), json={**LISTING, "slots": 1})
    assert put.status_code == 200
    assert len([s for s in storage.seats.list(campaign.id) if s.left_at is None]) == 3
    assert local.get(listing_path(campaign)).json()["taken"] == 2


def test_a_seat_that_left_frees_its_place(local, browser, campaign, joined):  # noqa: F811
    local.put(listing_path(campaign), json={**LISTING, "slots": 1})
    ana, _ = joined("Ana")
    ana.post(f"/api/campaigns/{campaign.id}/leave", json={})
    assert browser("10.0.0.8").get(f"/api/join/{campaign.join_token}").json()["campaign"]["taken"] == 0
    joined("Bo", address="10.0.0.9")


# ----- removing a seat -----


def test_the_host_removes_a_seat(app, local, storage, campaign, joined, garrek):  # noqa: F811
    ana, seat = joined("Ana")
    ana.post(f"/api/campaigns/{campaign.id}/characters/{garrek.id}/claim", json={})
    before = len(seats_events(app))
    removed = local.post(remove_path(campaign, seat["id"]), json={})
    assert removed.status_code == 200, removed.text
    assert removed.json()["seat"]["id"] == seat["id"] and removed.json()["seat"]["present"] is False
    assert storage.seats.get(seat["id"]).left_at is not None
    assert storage.characters.get(garrek.id).controller_id is None, "its characters are free"
    assert seats_events(app)[before:] == [{"campaign_id": campaign.id}]
    assert ana.get(f"/api/campaigns/{campaign.id}/story").status_code == 403
    assert seat["id"] not in [s["id"] for s in local.get(f"/api/campaigns/{campaign.id}/seats").json()]

    back = ana.post(f"/api/join/{campaign.join_token}", json={"role": "player"})
    assert back.status_code == 201 and back.json()["seat"]["id"] != seat["id"], "the join link brings them back"


def test_removing_what_isnt_there_is_404(local, storage, campaign, joined):  # noqa: F811
    _, seat = joined("Ana")
    assert local.post(remove_path(campaign, "seat_nope"), json={}).status_code == 404
    local.post(remove_path(campaign, seat["id"]), json={})
    assert local.post(remove_path(campaign, seat["id"]), json={}).status_code == 404, "gone already"
    other = storage.campaigns.create(
        "Friday", campaign.module_id, campaign.revision, ruleset="osric", setting="greyhawk"
    )
    stranger = storage.seats.create(other.id, "Dee", "en", "player")
    assert local.post(remove_path(campaign, stranger.id), json={}).status_code == 404
    assert storage.seats.get(stranger.id).left_at is None


def test_the_host_and_ones_own_seat_are_not_removed(local, storage, campaign, token_seat):  # noqa: F811
    host = storage.seats.owner_seat(campaign.id)
    bo, cohost = token_seat("Bo", "cohost")
    refused = cohost.post(remove_path(campaign, host.id), json={})
    assert refused.status_code == 409 and refused.json()["error"] == "Hand the host role over first."
    own = cohost.post(remove_path(campaign, bo.id), json={})
    assert own.status_code == 409 and own.json()["error"] == "Leave the table instead."
    assert local.post(remove_path(campaign, host.id), json={}).status_code == 409
    assert storage.seats.get(host.id).left_at is None and storage.seats.get(bo.id).left_at is None


def test_only_the_host_removes_a_cohost(local, storage, campaign, token_seat):  # noqa: F811
    _, cohost = token_seat("Bo", "cohost")
    cy, _ = token_seat("Cy", "cohost")
    dee, _ = token_seat("Dee", "player")
    refused = cohost.post(remove_path(campaign, cy.id), json={})
    assert refused.status_code == 403 and storage.seats.get(cy.id).left_at is None
    assert cohost.post(remove_path(campaign, dee.id), json={}).status_code == 200, "a co-host removes a player"
    assert local.post(remove_path(campaign, cy.id), json={}).status_code == 200, "the host removes a co-host"


def test_a_player_removes_nobody(storage, campaign, token_seat):  # noqa: F811
    _, ana = token_seat("Ana", "player")
    bo, _ = token_seat("Bo", "player")
    assert ana.post(remove_path(campaign, bo.id), json={}).status_code == 403
    assert storage.seats.get(bo.id).left_at is None
