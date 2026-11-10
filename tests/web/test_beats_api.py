"""The beat routes (plan 4 Task 4): act and pass are a seat's submission, go is the host's, typing reaches the table
and is never stored, the host sets the beat timer and its fallback, the timer runs on the app's clock, and the start
of Delve closes an open beat."""

import time

import pytest
from fastapi.testclient import TestClient

from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.provider import TextDelta
from delve.domain.backends import Registry
from delve.domain.modules import ModuleMap
from delve.play import seats
from delve.play.clock import FileClock
from delve.web.app import create_app
from delve.web.routes.play import table_of
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.web.conftest import BASE_URL, make_registries, playing
from tests.web.test_preferences_api import published


@pytest.fixture
def dm():
    return FakeDM([[TextDelta(f"Reply {n}.")] for n in range(1, 9)])


@pytest.fixture
def registries(dm):
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    return registries


@pytest.fixture
def campaign(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    campaign = storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")
    playing(storage, campaign.id)
    return campaign


@pytest.fixture
def host(storage, campaign):
    return seats.owner_seat(storage, campaign.id)


@pytest.fixture
def sit(app, storage):
    """`sit(campaign, name, role="player", *character_ids)`: a seat playing those characters, and a browser on the LAN
    that holds its token."""
    clients = []

    def make(campaign, name, role="player", *character_ids):
        token = new_seat_token()
        seat = storage.seats.create(campaign.id, name, "en", role, token_hash=token_hash(token))
        for character_id in character_ids:
            storage.seats.set_controller(character_id, seat.id)
        client = TestClient(app, base_url=BASE_URL)
        client.__enter__()
        client.cookies.set(SEAT_COOKIE, token)
        clients.append(client)
        return seat, client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def path(campaign, rest: str) -> str:
    return f"/api/campaigns/{campaign.id}/{rest}"


def settle(storage, campaign, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while storage.beats.current(campaign.id) is not None:
        if time.monotonic() > deadline:
            raise AssertionError("the beat is still open or running")
        time.sleep(0.02)


def present(app, *seat_ids):
    """Who the table counts as present, as the event stream would."""
    table_of(app).present = lambda campaign_id: set(seat_ids)


def test_solo_act_closes_at_once(app, local, storage, dm, campaign, host):
    answer = local.post(path(campaign, "act"), json={"text": "We go in."})
    assert answer.status_code == 202
    assert answer.json()["beat"]["status"] == "running" and answer.json()["beat"]["submitted"] == [host.id]
    settle(storage, campaign)
    assert dm.sent[-1].endswith("We go in.")


def test_two_seats_pass_and_go(app, local, storage, dm, campaign, host, sit):
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    storage.characters.create(campaign.id, "Pip")  # nobody plays Pip: the host does
    ana, ana_client = sit(campaign, "Ana", "player", garrek.id)
    bo, bo_client = sit(campaign, "Bo", "player", mira.id)
    present(app, host.id, ana.id, bo.id)

    opened = ana_client.post(path(campaign, "act"), json={"text": "I listen."})
    assert opened.status_code == 202 and opened.json()["beat"]["status"] == "open"
    assert opened.json()["beat"]["submitted"] == [ana.id]
    passed = bo_client.post(path(campaign, "pass"), json={})
    assert passed.status_code == 202 and passed.json()["beat"]["status"] == "open", "the host hasn't acted"

    refused = bo_client.post(path(campaign, "go"), json={})
    assert refused.status_code == 403 and refused.json() == {"error": "Only the host can do that."}
    went = local.post(path(campaign, "go"), json={})
    assert went.status_code == 202 and went.json()["beat"]["status"] == "running"
    assert local.post(path(campaign, "go"), json={}).status_code == 409
    settle(storage, campaign)
    assert dm.sent[-1].endswith(
        "Ana (playing Garrek):\n> I listen.\nBo passes.\n(Pip holds back this beat: they do nothing.)"
    )
    assert local.post(path(campaign, "go"), json={}).json() == {
        "error": "There is no open beat.",
        "hint": "A beat opens with the first act or pass.",
    }


def test_acting_for_another_seats_character_is_422(app, storage, campaign, host, sit):
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    _ana, ana_client = sit(campaign, "Ana", "player", garrek.id)
    refused = ana_client.post(path(campaign, "act"), json={"text": "I help.", "characters": [mira.id]})
    assert refused.status_code == 422 and refused.json()["error"] == "You don't play Mira."


def test_an_observer_cant_act_or_pass(app, storage, campaign, sit):
    _cy, cy_client = sit(campaign, "Cy", "observer")
    for route, body in (("act", {"text": "I watch."}), ("pass", {})):
        refused = cy_client.post(path(campaign, route), json=body)
        assert refused.status_code == 403 and refused.json() == {"error": "Observers don't act."}
    assert storage.beats.current(campaign.id) is None


def test_typing_reaches_the_table_and_is_never_stored(app, storage, campaign, sit):
    ana, ana_client = sit(campaign, "Ana")
    assert ana_client.post(path(campaign, "typing"), json={"state": "typing"}).status_code == 204
    assert ana_client.post(path(campaign, "typing"), json={"state": "idle"}).status_code == 204
    assert ana_client.post(path(campaign, "typing"), json={"state": "shouting"}).status_code == 422
    typing = [e for e in published(app) if e.type == "typing"]
    assert [e.data for e in typing] == [
        {"campaign_id": campaign.id, "seat_id": ana.id, "state": "typing"},
        {"campaign_id": campaign.id, "seat_id": ana.id, "state": "idle"},
    ]
    assert all(e.scope == "table" and e.campaign_id == campaign.id for e in typing)
    assert storage.beats.current(campaign.id) is None and storage.story.list(campaign.id) == []


def test_an_option_sent_alone_changes_it_alone(app, local, storage, campaign, host):
    """The table options popover sends only what changed (DEL-168): the timer stays as it was, unarmed, unpublished."""
    local.put(path(campaign, "play/options"), json={"beat_timer_s": 180, "effort": "high"})
    before = len(published(app))
    put = local.put(path(campaign, "play/options"), json={"tone": "horror"})
    assert put.status_code == 200
    assert (put.json()["tone"], put.json()["beat_timer_s"], put.json()["effort"]) == ("horror", 180, "high")
    assert [e.type for e in published(app)[before:]] == []
    # A null effort is the Preferences choice again.
    assert local.put(path(campaign, "play/options"), json={"effort": None}).json()["effort"] is None


def test_the_host_sets_the_timer_and_its_fallback(app, local, storage, campaign, host, sit):
    _ana, ana_client = sit(campaign, "Ana")
    put = local.put(path(campaign, "play/options"), json={"beat_timer_s": 180, "fallback": "in_character"})
    assert put.status_code == 200 and put.json()["beat_timer_s"] == 180 and put.json()["fallback"] == "in_character"
    for wrong in ({"beat_timer_s": 10}, {"beat_timer_s": 3600}, {"beat_timer_s": "soon"}, {"fallback": "flee"}):
        assert local.put(path(campaign, "play/options"), json=wrong).status_code == 422, wrong
    assert local.put(path(campaign, "play/options"), json={"beat_timer_s": None}).json()["beat_timer_s"] is None
    assert ana_client.put(path(campaign, "play/options"), json={"beat_timer_s": 60}).status_code == 403
    assert ana_client.get(path(campaign, "play/options")).status_code == 403

    # A host who isn't an organiser sets the timer, but not the DM's settings.
    _cohost, cohost_client = sit(campaign, "Bo", "cohost")
    assert cohost_client.put(path(campaign, "play/options"), json={"beat_timer_s": 60}).status_code == 200
    refused = cohost_client.put(path(campaign, "play/options"), json={"tone": "horror"})
    assert refused.status_code == 403 and refused.json() == {"error": "Only an organiser can change the DM's options."}


def test_the_timer_runs_on_the_apps_clock(config, storage, registries, static_dir, campaign, tmp_path, dm):
    """`delve serve` reads its clock from `DELVE_CLOCK_FILE`: writing seconds there moves the table's time on."""
    clock_file = tmp_path / "clock"
    app = create_app(config, storage, registries, static_dir=static_dir, clock=FileClock(clock_file))
    host = seats.owner_seat(storage, campaign.id)
    garrek = storage.characters.create(campaign.id, "Garrek")
    token = new_seat_token()
    ana = storage.seats.create(campaign.id, "Ana", "en", "player", token_hash=token_hash(token))
    storage.seats.set_controller(garrek.id, ana.id)
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50000)) as local:
        present(app, host.id, ana.id)
        local.put(path(campaign, "play/options"), json={"beat_timer_s": 30})
        opened = local.post(path(campaign, "act"), json={"text": "I wait for Ana."}).json()["beat"]
        assert opened["status"] == "open" and opened["deadline"] is not None
        time.sleep(0.6)
        assert storage.beats.current(campaign.id).status == "open"
        clock_file.write_text("31")
        settle(storage, campaign)
    assert dm.sent[-1].splitlines()[-3:] == [
        "Host:",
        "> I wait for Ana.",
        "(Garrek holds back this beat: they do nothing.)",
    ]


def test_the_start_of_delve_closes_an_open_beat(config, storage, registries, static_dir, campaign, dm):
    """Review Focus 4: a restart during an open beat closes it on start, with the submissions it has."""
    host = seats.owner_seat(storage, campaign.id)
    submission = {"seat_id": host.id, "kind": "act", "characters": [], "text": "We were saying…", "original":
                  "We were saying…", "language": "en", "at": "2026-10-18T10:00:00+00:00"}
    beat = storage.beats.open(campaign.id, [submission])
    app = create_app(config, storage, registries, static_dir=static_dir)
    with TestClient(app, base_url=BASE_URL):
        settle(storage, campaign)
    assert storage.beats.get(beat.id).status == "done"
    assert dm.sent[-1].endswith("We were saying…")


def test_a_seat_leaving_through_the_route_closes_the_beat_it_held_up(app, storage, dm, campaign, host, sit):
    """Review Focus 3, through the API: Bo leaves, the beat closes with Ana's act, and Mira holds back."""
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    ana, ana_client = sit(campaign, "Ana", "player", garrek.id)
    bo, bo_client = sit(campaign, "Bo", "player", mira.id)
    present(app, ana.id, bo.id)  # the host is away: present, they would play Mira once she is free
    assert ana_client.post(path(campaign, "act"), json={"text": "I listen."}).json()["beat"]["status"] == "open"
    assert bo_client.post(path(campaign, "leave"), json={}).status_code == 204
    settle(storage, campaign)
    assert dm.sent[-1].splitlines()[-3:] == [
        "Ana (playing Garrek):",
        "> I listen.",
        "(Mira holds back this beat: they do nothing.)",
    ]


# ----- pending acts and private acts (plan 7 Task 17) -----


def test_pending_acts_through_the_routes(app, local, storage, dm, campaign, host, sit):
    garrek = storage.characters.create(campaign.id, "Garrek")
    mira = storage.characters.create(campaign.id, "Mira")
    storage.characters.create(campaign.id, "Pip")  # the host plays Pip: the beat waits for the host
    ana, ana_client = sit(campaign, "Ana", "player", garrek.id)
    bo, bo_client = sit(campaign, "Bo", "player", mira.id)
    _cy, cy_client = sit(campaign, "Cy", "observer")
    present(app, host.id, ana.id, bo.id)

    assert ana_client.get(path(campaign, "beat/pending")).json() == {"pending": []}
    assert ana_client.post(path(campaign, "act"), json={"text": "I listen."}).status_code == 202
    secret = bo_client.post(path(campaign, "act"), json={"text": "I pocket the gem.", "private": True})
    assert secret.status_code == 202

    ana_sees = ana_client.get(path(campaign, "beat/pending")).json()["pending"]
    assert [(p["name"], p["text"], p["private"]) for p in ana_sees] == [("Ana", "I listen.", False)]
    bo_sees = bo_client.get(path(campaign, "beat/pending")).json()["pending"]
    assert [(p["name"], p["text"]) for p in bo_sees] == [("Bo", "I pocket the gem."), ("Ana", "I listen.")]
    assert cy_client.get(path(campaign, "beat/pending")).json() == {"pending": []}, "an observer sees none"

    refused = ana_client.post(path(campaign, "pass"), json={"private": True})
    assert refused.status_code == 422

    assert local.post(path(campaign, "go"), json={}).status_code == 202
    settle(storage, campaign)
    assert "Bo (playing Mira), privately (only the DM knows" in dm.sent[-1]
    assert "I pocket the gem." not in local.get(path(campaign, "story")).text
    assert "I pocket the gem." in bo_client.get(path(campaign, "story")).text


def test_a_solo_private_act_closes_at_once(app, local, storage, dm, campaign, host):
    answer = local.post(path(campaign, "act"), json={"text": "I read the letter.", "private": True})
    assert answer.status_code == 202 and answer.json()["beat"]["status"] == "running"
    settle(storage, campaign)
    assert dm.sent[-1].endswith("Host, privately (only the DM knows; tell them the outcome with tell, and keep it out "
                                "of your reply):\n> I read the letter.")


def test_the_portrait_style_is_an_organisers_and_every_seat_reads_it(app, local, storage, campaign, host, sit):
    _ana, ana_client = sit(campaign, "Ana")
    _bo, bo_client = sit(campaign, "Bo", "cohost")
    _cy, cy_client = sit(campaign, "Cy", "observer")
    assert local.get(path(campaign, "play/options")).json()["portrait_style"] is None, "as in Preferences (DEL-252)"
    put = local.put(path(campaign, "play/options"), json={"portrait_style": "inkwash"})
    assert put.status_code == 200 and put.json()["portrait_style"] == "inkwash"
    assert local.put(path(campaign, "play/options"), json={"portrait_style": "cubist"}).status_code == 422

    # A host seat that isn't an organiser doesn't choose it.
    refused = bo_client.put(path(campaign, "play/options"), json={"portrait_style": "anime"})
    assert refused.status_code == 403
    assert local.get(path(campaign, "play/options")).json()["portrait_style"] == "inkwash"

    # Every seat draws the portraits in it: the play state carries it, and nothing more of the options.
    for client in (local, ana_client, bo_client, cy_client):
        state = client.get(path(campaign, "play/state"))
        assert state.status_code == 200 and state.json()["portrait_style"] == "inkwash"
        assert "tone" not in state.json()
