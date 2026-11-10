"""The table's schedule (DEL-204 part C): an organiser sets when the table plays, or clears it; the host or a co-host
moves, skips or resets the next session; and every place that shows a table shows its next sessions, as UTC instants
for each viewer to read in their own time."""

from datetime import UTC, datetime

import pytest

from delve.play.clock import FakeClock
from tests.web.conftest import log_in, make_account
from tests.web.test_join_api import browser, campaign, joined, token_seat  # noqa: F401
from tests.web.test_join_requests_api import account, public  # noqa: F401
from tests.web.test_preferences_api import published

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
RULE = {"every_weeks": 2, "first": "2026-11-07", "start": "20:00", "end": "22:00", "time_zone": "Europe/Brussels"}
STORED = {**RULE, "changes": []}
NEXT = [
    {"on": "2026-11-07", "starts_at": "2026-11-07T19:00:00+00:00", "ends_at": "2026-11-07T21:00:00+00:00", "moved": False},
    {"on": "2026-11-21", "starts_at": "2026-11-21T19:00:00+00:00", "ends_at": "2026-11-21T21:00:00+00:00", "moved": False},
    {"on": "2026-12-05", "starts_at": "2026-12-05T19:00:00+00:00", "ends_at": "2026-12-05T21:00:00+00:00", "moved": False},
]


@pytest.fixture(autouse=True)
def clock(app):
    """The app's time, `NOW`."""
    app.state.clock = FakeClock(NOW)
    return app.state.clock


def schedule_path(campaign, *rest) -> str:  # noqa: F811
    return "/".join([f"/api/campaigns/{campaign.id}/schedule", *rest])


def put_null(client, campaign):  # noqa: F811
    return client.put(schedule_path(campaign), content=b"null", headers={"content-type": "application/json"})


@pytest.fixture
def scheduled(storage, campaign):  # noqa: F811
    return storage.campaigns.set_schedule(campaign.id, STORED)


# ----- setting it -----


def test_a_new_campaign_has_no_schedule(local, campaign):  # noqa: F811
    listed = local.get("/api/campaigns").json()[0]
    assert (listed["schedule"], listed["next_sessions"]) == (None, [])
    page = local.get(f"/api/campaigns/{campaign.id}").json()
    assert (page["schedule"], page["next_sessions"]) == (None, [])


def test_an_organiser_sets_the_schedule(app, local, storage, campaign):  # noqa: F811
    put = local.put(schedule_path(campaign), json={**RULE, "changes": [{"on": "2026-11-21", "to": None}]})
    assert put.status_code == 200, put.text
    page = local.get(f"/api/campaigns/{campaign.id}").json()
    assert put.json() == page, "the campaign as its page reads it"
    assert page["schedule"] == {**RULE, "changes": [{"on": "2026-11-21", "to": None}]}
    assert [s["on"] for s in page["next_sessions"]] == ["2026-11-07", "2026-12-05", "2026-12-19"]
    assert storage.campaigns.get(campaign.id).schedule == page["schedule"]
    assert local.get("/api/campaigns").json()[0]["next_sessions"] == page["next_sessions"]

    cleared = put_null(local, campaign)
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["schedule"], cleared.json()["next_sessions"]) == (None, [])
    assert storage.campaigns.get(campaign.id).schedule is None

    events = published(app)
    assert [e.data for e in events if e.type == "campaigns"] == [{"id": campaign.id}] * 2
    told = [(e.data, e.scope, e.campaign_id) for e in events if e.type == "table_listing"]
    assert told == [({"campaign_id": campaign.id}, "table", campaign.id)] * 2


def test_a_schedule_s_past_changes_are_dropped(local, campaign):  # noqa: F811
    over = {**RULE, "first": "2026-10-03", "changes": [{"on": "2026-10-17", "to": None}]}
    assert local.put(schedule_path(campaign), json=over).json()["schedule"]["changes"] == []


def test_a_wrong_schedule_is_422(local, storage, campaign):  # noqa: F811
    for wrong in (
        {**RULE, "time_zone": "Mars/Olympus"},
        {**RULE, "every_weeks": 5},
        {**RULE, "first": "2026-02-30"},
        {**RULE, "start": "20h"},
        {**RULE, "changes": [{"on": "2026-11-14", "to": None}]},
        {**RULE, "weekday": "saturday"},
        {k: v for k, v in RULE.items() if k != "end"},
        [RULE],
    ):
        answer = local.put(schedule_path(campaign), json=wrong)
        assert answer.status_code == 422 and "error" in answer.json(), wrong
    assert local.put(schedule_path(campaign)).status_code in (415, 422), "a write needs a JSON body"
    assert storage.campaigns.get(campaign.id).schedule is None
    assert local.put("/api/campaigns/cmp_nope/schedule", json=RULE).status_code == 404


def test_only_an_organiser_sets_the_schedule(storage, campaign, token_seat):  # noqa: F811
    _, cohost = token_seat("Bo", "cohost")
    assert cohost.put(schedule_path(campaign), json=RULE).status_code == 403
    assert storage.campaigns.get(campaign.id).schedule is None


# ----- the next session -----


def test_the_host_skips_moves_and_resets_the_next_session(app, local, storage, campaign, scheduled):  # noqa: F811
    skipped = local.post(schedule_path(campaign, "next"), json={"skip": True})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json() == {"schedule": {**RULE, "changes": [{"on": "2026-11-07", "to": None}]}, "next_sessions": [
        *NEXT[1:],
        {**NEXT[0], "on": "2026-12-19", "starts_at": "2026-12-19T19:00:00+00:00", "ends_at": "2026-12-19T21:00:00+00:00"},
    ], "emailed": 0}
    assert storage.campaigns.get(campaign.id).schedule == skipped.json()["schedule"]

    reset = local.post(schedule_path(campaign, "next"), json={"reset": True}).json()
    assert reset == {"schedule": STORED, "next_sessions": NEXT, "emailed": 0}

    moved = local.post(schedule_path(campaign, "next"), json={"to": "2026-11-08T18:30"}).json()
    assert moved["schedule"]["changes"] == [{"on": "2026-11-07", "to": "2026-11-08T18:30"}]
    assert moved["next_sessions"][0] == {
        "on": "2026-11-07",
        "starts_at": "2026-11-08T17:30:00+00:00",
        "ends_at": "2026-11-08T19:30:00+00:00",
        "moved": True,
    }
    told = [(e.data, e.scope, e.campaign_id) for e in published(app) if e.type == "table_listing"]
    assert told == [({"campaign_id": campaign.id}, "table", campaign.id)] * 3


def test_a_co_host_changes_the_next_session_and_a_player_does_not(campaign, scheduled, token_seat):  # noqa: F811
    _, cohost = token_seat("Bo", "cohost")
    assert cohost.post(schedule_path(campaign, "next"), json={"skip": True}).status_code == 200
    _, player = token_seat("Cy", "player")
    assert player.post(schedule_path(campaign, "next"), json={"skip": True}).status_code == 403


def test_changing_the_next_session_is_refused(local, storage, campaign):  # noqa: F811
    without = local.post(schedule_path(campaign, "next"), json={"skip": True})
    assert without.status_code == 409 and "error" in without.json(), "no schedule"
    storage.campaigns.set_schedule(campaign.id, STORED)
    for wrong in (
        {"to": "2026-10-31T20:00"},
        {"to": "2026-11-08"},
        {"to": 7},
        {"skip": False},
        {"skip": True, "to": "2026-11-08T18:30"},
        {"reset": "yes"},
        {},
        {"move": "later"},
    ):
        answer = local.post(schedule_path(campaign, "next"), json=wrong)
        assert answer.status_code == 422 and "error" in answer.json(), wrong
    assert local.post(schedule_path(campaign, "next")).status_code in (415, 422), "a write needs a JSON body"
    assert storage.campaigns.get(campaign.id).schedule == STORED


# ----- where the next sessions show -----


def test_the_listing_shows_the_schedule(local, campaign, scheduled, joined):  # noqa: F811
    ana, _ = joined("Ana")
    listing = ana.get(f"/api/campaigns/{campaign.id}/listing").json()
    assert (listing["schedule"], listing["next_sessions"]) == (STORED, NEXT)


def test_find_a_table_and_my_tables_show_the_next_sessions(storage, campaign, scheduled, account, joined):  # noqa: F811
    public(storage, campaign)
    _, client = account()
    table = client.get("/api/tables").json()[0]
    assert (table["schedule"], table["next_sessions"]) == (STORED, NEXT)
    ana, _ = joined("Ana")
    assert ana.get("/api/account/tables").json()[0]["next_sessions"] == NEXT


def test_the_join_link_and_the_play_state_show_the_next_sessions(local, browser, campaign, scheduled, joined):  # noqa: F811
    link = browser().get(f"/api/join/{campaign.join_token}").json()
    assert link["campaign"]["next_sessions"] == NEXT
    ana, _ = joined("Ana")
    assert ana.get(f"/api/campaigns/{campaign.id}/play/state").json()["next_sessions"] == NEXT


def test_the_next_sessions_move_on_with_the_time(app, local, campaign, scheduled, clock):  # noqa: F811
    app.state.clock = FakeClock(datetime(2026, 11, 7, 20, 0, tzinfo=UTC))
    playing = local.get(f"/api/campaigns/{campaign.id}").json()["next_sessions"]
    assert [s["on"] for s in playing] == ["2026-11-07", "2026-11-21", "2026-12-05"], "under way: not yet ended"
    app.state.clock = FakeClock(datetime(2026, 11, 7, 21, 0, tzinfo=UTC))
    assert local.get(f"/api/campaigns/{campaign.id}").json()["next_sessions"][0]["on"] == "2026-11-21"


# ----- the calendar file (DEL-236) -----


def test_anyone_at_the_table_downloads_the_next_sessions_as_a_calendar(local, storage, campaign, joined, browser):  # noqa: F811
    """The next sessions, a skipped one left out and a moved one where it went, each an event in UTC linking to the
    play screen; 404 without a schedule, and nothing for a browser not at the table."""
    ana, _ = joined("Ana")
    assert ana.get(schedule_path(campaign) + ".ics").status_code == 404
    storage.campaigns.set_schedule(
        campaign.id, {**RULE, "changes": [{"on": "2026-11-21", "to": None}, {"on": "2026-12-05", "to": "2026-12-06T18:00"}]}
    )
    got = ana.get(schedule_path(campaign) + ".ics")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("text/calendar")
    assert got.headers["content-disposition"].startswith("attachment; filename=") and ".ics" in got.headers["content-disposition"]
    text = got.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 12
    starts = [line.split(":", 1)[1] for line in text.split("\r\n") if line.startswith("DTSTART:")]
    assert starts[:3] == ["20261107T190000Z", "20261206T170000Z", "20261219T190000Z"], "skipped and moved as they are"
    unfolded = text.replace("\r\n ", "")
    assert f"/play/{campaign.id}" in unfolded and f"UID:{campaign.id}-2026-11-07@delve" in unfolded
    stranger = browser("10.0.0.99")
    assert stranger.get(schedule_path(campaign) + ".ics").status_code in (401, 403)


# ----- telling the players (DEL-314) -----

FAR = "2100-01-01T00:00:00+00:00"


@pytest.fixture
def mail_on(config):
    from delve.mail.settings import MailSettings, save, save_key

    save(config.data_dir, MailSettings(provider="emailit", sender="d@example.org", public_url="https://delve.example"))
    save_key(config.data_dir, "k-1")


@pytest.fixture
def players(storage, campaign, scheduled, joined, mail_on, browser):  # noqa: F811
    """The owner at the host's seat with an address, Ana (Brussels) and Bob (no zone) as players with addresses, a quiet
    player with the host switch off and an observer."""
    from dataclasses import replace

    owner = make_account(storage, "boss", owner=True)
    storage.accounts.set_email(owner.id, email="boss@example.org", email_pending=None)
    found = {}
    for name, role in (("Ana", "player"), ("Bob", "player"), ("Quiet", "player"), ("Obs", "observer")):
        _, seat = joined(name, "en", role)
        made = storage.accounts.get(storage.seats.get(seat["id"]).account_id)
        storage.accounts.set_email(made.id, email=f"{name.lower()}@example.org", email_pending=None)
        found[name] = made
    ana = found["Ana"]
    storage.accounts.save_profile(ana.id, replace(ana.profile, time_zone="Europe/Brussels", language="nl"))
    storage.accounts.set_mail_switches(found["Quiet"].id, mail_host=False, mail_board=True)
    log_in(host_browser := browser("10.0.0.99"), "boss")
    found["host"] = host_browser
    return found


def queued(storage):
    return storage.mail.due(FAR, 50)


def test_a_skip_without_the_email_flag_tells_nobody(storage, campaign, players):  # noqa: F811
    answer = players["host"].post(schedule_path(campaign, "next"), json={"skip": True})
    assert answer.status_code == 200
    assert answer.json().get("emailed", 0) == 0
    assert queued(storage) == []


def test_a_skip_tells_the_reachable_players_but_not_the_host(app, storage, campaign, players):  # noqa: F811
    answer = players["host"].post(schedule_path(campaign, "next"), json={"skip": True, "email": {"note": "Flu, sorry."}})
    assert answer.status_code == 200, answer.text
    assert answer.json()["emailed"] == 2
    sent = queued(storage)
    assert sorted(m.account_id for m in sent) == sorted([players["Ana"].id, players["Bob"].id])
    assert {m.kind for m in sent} == {"schedule"}
    assert all(m.unsubscribe for m in sent)
    ana = next(m for m in sent if m.account_id == players["Ana"].id)
    assert ana.language == "nl"
    assert "Tuesday" in ana.subject
    assert "Flu, sorry." in ana.text
    assert "https://delve.example/play/" in ana.text
    assert "@" not in answer.text, "no address in the answer"
    assert "example.org" not in repr(published(app)), "none in the events"
    assert all("example.org" not in repr(m) for m in sent), "none in the outbox"


def test_a_move_names_the_new_time_in_each_players_zone(storage, campaign, players):  # noqa: F811
    answer = players["host"].post(schedule_path(campaign, "next"), json={"to": "2026-11-08T18:30", "email": {"note": ""}})
    assert answer.status_code == 200, answer.text
    assert answer.json()["emailed"] == 2
    by = {m.account_id: m for m in queued(storage)}
    ana, bob = by[players["Ana"].id], by[players["Bob"].id]
    assert "2026-11-08 18:30" in ana.text and "Europe/Brussels" in ana.text
    assert "2026-11-08 18:30" in bob.text and "Europe/Brussels" in bob.text
    assert "2026-11-07 20:00" in ana.text, "the old time"


def test_a_players_own_zone_is_used(storage, campaign, players):  # noqa: F811
    from dataclasses import replace

    bob = players["Bob"]
    storage.accounts.save_profile(bob.id, replace(bob.profile, time_zone="America/New_York"))
    players["host"].post(schedule_path(campaign, "next"), json={"to": "2026-11-08T18:30", "email": {"note": ""}})
    mail = next(m for m in queued(storage) if m.account_id == bob.id)
    assert "2026-11-08 12:30" in mail.text and "America/New_York" in mail.text


def test_a_reset_sends_nothing_and_mail_off_sends_nothing(storage, campaign, scheduled, players, config):  # noqa: F811
    reset = players["host"].post(schedule_path(campaign, "next"), json={"reset": True, "email": {"note": ""}})
    assert reset.status_code == 200 and reset.json().get("emailed", 0) == 0
    assert queued(storage) == []
    from delve.mail.settings import remove_key

    remove_key(config.data_dir)
    off = players["host"].post(schedule_path(campaign, "next"), json={"skip": True, "email": {"note": ""}})
    assert off.status_code == 200 and off.json()["emailed"] == 0
    assert queued(storage) == []


def test_the_note_is_at_most_500_characters(storage, campaign, players):  # noqa: F811
    for email in ({"note": "x" * 501}, {"note": 3}, {}, "yes"):
        assert players["host"].post(schedule_path(campaign, "next"), json={"skip": True, "email": email}).status_code == 422
    assert players["host"].post(schedule_path(campaign, "next"), json={"skip": True, "email": {"note": "x" * 500}}).status_code == 200
    assert players["host"].post(schedule_path(campaign, "next"), json={"email": {"note": ""}}).status_code == 422


def test_a_skip_during_a_session_names_the_next_one_it_skips(app, storage, campaign, players):  # noqa: F811
    """Tonight's session under way: the skip acts on the next not yet started, and the email names that one."""
    app.state.clock = FakeClock(datetime(2026, 11, 7, 19, 30, tzinfo=UTC))
    answer = players["host"].post(schedule_path(campaign, "next"), json={"skip": True, "email": {"note": ""}})
    assert answer.status_code == 200, answer.text
    assert answer.json()["schedule"]["changes"] == [{"on": "2026-11-21", "to": None}]
    mail = next(m for m in queued(storage) if m.account_id == players["Ana"].id)
    assert "2026-11-21 20:00" in mail.text
    assert "2026-11-07 20:00" not in mail.text


def test_a_move_past_the_following_session_names_where_it_went(storage, campaign, players):  # noqa: F811
    answer = players["host"].post(schedule_path(campaign, "next"), json={"to": "2026-11-25T18:30", "email": {"note": ""}})
    assert answer.status_code == 200, answer.text
    mail = next(m for m in queued(storage) if m.account_id == players["Ana"].id)
    assert "2026-11-07 20:00" in mail.text, "the old time"
    assert "2026-11-25 18:30" in mail.text, "the new time, not the following session's"
    assert "2026-11-21 20:00" not in mail.text
