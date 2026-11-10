"""The play API (plan 2b Task 7): Act answers 202 and the DM's reply arrives in the story; a second act while the DM
answers is refused with 409; a reloaded page rebuilds from the story and the state (Review Focus 1); the state hides
the enemies' hit points; the campaign's table options override Preferences; the DM log is the DM view's only."""

import asyncio
import json
import threading
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delve.dice import ScriptedRng
from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
from delve.dm.provider import TextDelta, ToolCall, ToolResult, TurnEnd
from delve.domain.backends import Registry
from delve.domain.modules import ModuleMap
from delve.domain.settings import BackendChoice, Effort
from delve.play import characters, combat, days, weather
from delve.play.context import context_for
from delve.rules.catalog import register_rulesets
from delve.web.seats import SEAT_COOKIE, new_seat_token, token_hash
from tests.fixtures.combat import GOBLIN, CombatReference
from tests.fixtures.rulesets import over
from tests.web.conftest import BASE_URL, make_registries
from tests.web.test_preferences_api import published

SECRET = "SECRET-XYZZY"


class GatedDM(FakeDM):
    """A fake DM whose replies wait for `gate` (a threading.Event) before they end, like a DM still thinking."""

    def __init__(self, script):
        super().__init__(script)
        self.gate = threading.Event()
        self.gate.set()
        self.choices: list[BackendChoice] = []

    async def open(self, spec):
        self.choices.append(spec.choice)
        conversation = await super().open(spec)
        send, gate = conversation.send, self.gate

        async def gated(text):
            async for event in send(text):
                if isinstance(event, TurnEnd) and event.reason == "done":
                    while not gate.is_set():
                        await asyncio.sleep(0.01)
                yield event

        conversation.send = gated
        return conversation


@pytest.fixture
def dm():
    return GatedDM([])


@pytest.fixture
def registries(dm):
    """The web fakes, with the gated DM and OSRIC over a small reference, so the state has a primer."""
    registries = make_registries()
    registries.dm = Registry()
    registries.dm.register(FAKE_DM_CAPABILITIES, lambda: dm)
    registries.rulesets = Registry()
    registries.catalogs = over(CombatReference(goblins=True))
    register_rulesets(registries.rulesets, registries.catalogs.rulesets)
    return registries


@pytest.fixture
def campaign(storage):
    module = storage.modules.create("The Crypt")
    storage.modules.put_map(module.id, ModuleMap("crypt", "map", "map crypt {}\n", is_default=True))
    revision = storage.revisions.snapshot(module.id)
    return storage.campaigns.create("Tuesday", module.id, revision.number, ruleset="osric", setting="greyhawk")


def path(campaign, rest: str) -> str:
    return f"/api/campaigns/{campaign.id}/{rest}"


def settle(client, campaign, timeout: float = 5.0) -> dict:
    """Wait until no beat is running; the state then."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(path(campaign, "play/state")).json()
        if state["beat"] is None:
            return state
        time.sleep(0.02)
    raise AssertionError("the beat is still running")


def test_a_batch_counts_and_shows_as_its_steps(app, local, dm, campaign):
    steps = [{"tool": "roll", "args": {"notation": "1d6"}}, {"tool": "roll", "args": {"notation": "1d8"}}]
    steps.append({"tool": "advance_time", "args": {"minutes": 10}})
    answers = {"ran": 3, "requested": 3, "stopped_early": False, "results": [
        {"step": 0, "tool": "roll", "result": {"total": 3}},
        {"step": 1, "tool": "roll", "result": {"total": 5}},
        {"step": 2, "tool": "advance_time", "result": {"minutes": 10}},
    ]}  # fmt: skip
    dm._script = [
        [
            ToolCall("t1", "batch", {"steps": steps}),
            ToolResult("t1", True, answers),
            ToolCall("t2", "roll", {"notation": "1d20"}),
            ToolResult("t2", True, {"notation": "1d20", "rolls": [12], "total": 12}),
            TextDelta("Time passes."),
        ]
    ]
    assert local.post(path(campaign, "act"), json={"text": "We rest."}).status_code == 202
    settle(local, campaign)
    assert [e.data["tool_count"] for e in published(app) if e.type == "beat_tools"] == [3, 4]
    rows = [e["payload"] for e in local.get(path(campaign, "story")).json()["entries"] if e["kind"] == "tool"]
    assert rows[0] == {
        "name": "batch",
        "steps": [{"step": 0, "name": "roll"}, {"step": 1, "name": "roll"}, {"step": 2, "name": "advance_time"}],
    }


def test_act_202_then_story_entries(app, local, dm, campaign):
    dm._script = [
        [
            TextDelta("The lever "),
            TextDelta("moves."),
            ToolCall("t1", "roll", {"notation": "1d20", "purpose": "the lever"}),
            ToolResult("t1", True, {"notation": "1d20", "rolls": [12], "total": 12}),
            ToolCall("t2", "dm_secrets", {}),
            ToolResult("t2", True, {"secrets": [SECRET]}),
            TextDelta(" Nothing happens."),
        ]
    ]
    answer = local.post(path(campaign, "act"), json={"text": "I pull the lever."})
    assert answer.status_code == 202
    beat = answer.json()["beat"]
    assert beat["id"].startswith("beat_") and beat["status"] == "running"
    assert {"elapsed_s", "opened_at"} <= beat.keys() and "tool_count" not in beat
    settle(local, campaign)

    page = local.get(path(campaign, "story")).json()
    assert page["has_more"] is False
    entries = page["entries"]
    assert [e["kind"] for e in entries] == ["player_act", "dm_text", "tool", "dm_text"]
    assert entries[0]["payload"]["text"] == "I pull the lever."
    assert entries[1]["payload"] == {"text": "The lever moves."}
    assert entries[2]["payload"]["name"] == "roll"
    assert all({"id", "seq", "kind", "payload", "beat_id", "at", "campaign_id"} <= e.keys() for e in entries)
    assert SECRET not in json.dumps(page)

    events = published(app)
    kinds = [e.type for e in events if e.data.get("campaign_id") == campaign.id]
    assert kinds[0] == "beat" and kinds[-1] == "beat" and "story" in kinds
    closed = [e.data["beat"] for e in events if e.type == "beat"][-1]
    assert closed["status"] == "done" and "tool_count" not in closed
    # The tool count is the host's and the co-hosts' alone (plan 7 Task 18).
    tools = [e for e in events if e.type == "beat_tools"]
    assert [e.data["tool_count"] for e in tools] == [1, 2]
    assert all(e.data["beat_id"] == beat["id"] and e.data["campaign_id"] == campaign.id for e in tools)
    host = app.state.storage.seats.owner_seat(campaign.id)
    assert all(e.scope == "table" and e.audience == {"seats": [host.id]} for e in tools)
    assert SECRET not in json.dumps([e.data for e in events])

    assert local.post(path(campaign, "act"), json={"text": "  "}).status_code == 422
    assert local.post(path(campaign, "act"), json={"text": "Go", "characters": ["chr_nobody"]}).status_code == 422
    assert local.post("/api/campaigns/cmp_000000000000/act", json={"text": "Go"}).status_code == 404


def test_act_409_while_running(local, dm, campaign):
    dm._script = [[TextDelta("Hm…")], [TextDelta("Yes.")]]
    dm.gate.clear()
    assert local.post(path(campaign, "act"), json={"text": "We wait."}).status_code == 202
    again = local.post(path(campaign, "act"), json={"text": "We wait more."})
    assert again.status_code == 409
    assert again.json()["error"] == "the DM is still answering"
    dm.gate.set()
    settle(local, campaign)
    assert local.post(path(campaign, "act"), json={"text": "We go on."}).status_code == 202
    settle(local, campaign)

    # Cancel stops a running beat.
    dm._script = [[TextDelta("Let me think…")]]
    dm.gate.clear()
    local.post(path(campaign, "act"), json={"text": "We think."})
    assert local.post(path(campaign, "cancel"), json={}).json() == {"cancelled": True}
    settle(local, campaign)
    dm.gate.set()
    assert local.post(path(campaign, "cancel"), json={}).json() == {"cancelled": False}


def test_story_paging_after_reload(app, local, dm, campaign, token):
    from fastapi.testclient import TestClient

    from tests.web.conftest import BASE_URL

    for n in range(3):
        dm._script = [[TextDelta(f"Reply {n}.")]]
        local.post(path(campaign, "act"), json={"text": f"Act {n}."})
        settle(local, campaign)

    # A beat in the middle of its answer: the DM has said something and called a tool, and is still thinking.
    dm._script = [[TextDelta("The corridor "), ToolCall("t1", "roll", {"notation": "1d6"}), ToolResult("t1", True, {"total": 3})]]
    dm.gate.clear()
    beat = local.post(path(campaign, "act"), json={"text": "We follow the corridor."}).json()["beat"]
    deadline = time.monotonic() + 5
    while len(local.get(path(campaign, "story")).json()["entries"]) < 9 and time.monotonic() < deadline:
        time.sleep(0.02)

    # The reloaded page: a new client, the story and the state read again.
    with TestClient(app, base_url=BASE_URL, client=("127.0.0.1", 50002)) as reloaded:
        state = reloaded.get(path(campaign, "play/state")).json()
        assert state["beat"]["id"] == beat["id"] and state["beat"]["status"] == "running"
        assert "tool_count" not in state["beat"] and state["beat"]["elapsed_s"] >= 0
        newest = reloaded.get(path(campaign, "story"), params={"limit": 4}).json()
        assert newest["has_more"] is True
        assert [e["kind"] for e in newest["entries"]] == ["dm_text", "player_act", "dm_text", "tool"]
        assert newest["entries"][-2]["payload"] == {"text": "The corridor "}
        earlier = reloaded.get(path(campaign, "story"), params={"before": newest["entries"][0]["seq"]}).json()
        assert [e["payload"]["text"] for e in earlier["entries"]] == ["Act 0.", "Reply 0.", "Act 1.", "Reply 1.", "Act 2."]
        assert earlier["has_more"] is False
        assert reloaded.get(path(campaign, "story"), params={"limit": 0}).status_code == 422

    dm.gate.set()
    settle(local, campaign)
    assert local.get(path(campaign, "story")).json()["entries"][-1]["kind"] == "tool"


def test_play_state_hides_enemy_hp(local, storage, campaign):
    ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng([5, 4, 3, 4, 2, 6]), catalogs=over(CombatReference(goblins=True)))
    garrek = characters.create(ctx, name="Garrek", sheet={"hp_max": 12, "ac": 4, "thac0": 18, "weapon": "long sword"})
    characters.create(ctx, name="Pippa", sheet={"hp_max": 6, "ac": 7, "thac0": 20, "weapon": "dagger"})
    tira = characters.create(ctx, name="Tira", kind="npc", sheet={"notes_md": f"{SECRET}: she is the cult."})
    combat.setup_combat(ctx, enemies=[{**GOBLIN, "hp": 7}], surprise=True)

    state = local.get(path(campaign, "play/state")).json()
    assert [pc["name"] for pc in state["party"]] == ["Garrek", "Pippa"]
    assert state["marching_order"] == [pc["id"] for pc in state["party"]]
    assert {"hp", "hp_max", "ac", "conditions", "spells"} <= state["party"][0].keys()
    assert state["party"][0]["id"] == garrek.id and state["party"][0]["hp_max"] == 12
    fight = state["combat"]
    assert fight["round"] == 1
    goblins = [s for s in fight["slots"] if s["side"] != "party"]
    assert len(goblins) == 2 and all("hp" not in g and "hp_max" not in g and "ac" not in g for g in goblins)
    assert state["session_number"] == 1 and state["time_of_day"].startswith("06:00")
    assert state["beat"] is None
    assert SECRET not in json.dumps(state) and tira.id not in json.dumps(state)

    # The marching order, front first, from the party sidebar.
    pippa = state["party"][1]["id"]
    assert local.put(path(campaign, "marching-order"), json={"order": [pippa]}).json()["order"] == [pippa, garrek.id]
    assert [pc["name"] for pc in local.get(path(campaign, "play/state")).json()["party"]] == ["Pippa", "Garrek"]
    assert local.put(path(campaign, "marching-order"), json={"order": [tira.id]}).status_code == 422


def test_play_state_has_the_date_and_the_weather_it_never_rolls(local, storage, campaign):
    """Every seat sees the date and today's weather (plan 6 Task 4); reading the state never rolls it."""
    state = local.get(path(campaign, "play/state")).json()
    assert (state["date"], state["weather"]) == ("1 Planting 576 CY", None)
    assert storage.rolls.list(campaign.id) == [] and storage.campaign_states.get(campaign.id).weather == ()
    weather.weather(context_for(storage, campaign.id, "beat-1", ScriptedRng([18]), catalogs=over(CombatReference())), "wilderness")
    state = local.get(path(campaign, "play/state")).json()
    assert state["weather"]["label"] == "afternoon storm" and state["weather"]["effect"].startswith("Brief downpour")
    assert set(state["weather"]) == {"label", "effect"}


def test_play_state_of_a_campaign_deleted_while_read_is_404(local, storage, campaign, monkeypatch):
    """A tab still open on a campaign the host deletes reads its state once more: a 404, never a 500 (seen in the
    browser checks, voice.spec.ts)."""
    days_today = days.today

    def deleted_meanwhile(ctx):
        storage.campaigns.delete(campaign.id)
        return days_today(ctx)

    monkeypatch.setattr(days, "today", deleted_meanwhile)
    answer = local.get(path(campaign, "play/state"))
    assert answer.status_code == 404 and answer.json() == {"error": "No such campaign."}


def test_play_state_has_the_partys_purse(local, storage, campaign):
    """Every seat sees the party's purse, the coin the DM's tools keep (owner, 2026-10-22): an empty one is all zeros,
    and a purse the DM filled reads back by its coins."""
    assert local.get(path(campaign, "play/state")).json()["coin"] == {"pp": 0, "gp": 0, "ep": 0, "sp": 0, "cp": 0}
    state = storage.campaign_states.get(campaign.id)
    storage.campaign_states.put(replace(state, coin={"gp": 98, "sp": 9, "cp": 9}))
    assert local.get(path(campaign, "play/state")).json()["coin"] == {"pp": 0, "gp": 98, "ep": 0, "sp": 9, "cp": 9}


def test_every_seat_reads_its_campaigns_ruleset(app, local, storage, campaign):
    """The play header's Rulesets link goes to the campaign's ruleset (rulesets plan, Task 7), which a seat may not
    read from the campaign itself: the state says it."""
    from tests.web.test_campaigns_api import seat_browser

    assert local.get(path(campaign, "play/state")).json()["ruleset"] == campaign.ruleset
    for role in ("player", "observer"):
        browser = seat_browser(app, storage, campaign.id, role, name=role)
        assert browser.get(path(campaign, "play/state")).json()["ruleset"] == "osric", role


def test_table_options_override(local, storage, dm, campaign):
    assert local.get(path(campaign, "play/options")).json() == {
        "tone": "classic",
        "custom_tone": "",
        "detail": 2,
        "effort": None,
        "model": None,
        "beat_timer_s": None,
        "fallback": "hold_back",
        "paid_images": False,
        "paid_images_per_day": 20,
        "portrait_style": None,  # as in Preferences (DEL-252)
        "xp_awards": ["monsters", "milestones", "roleplay"],
        "enemy_dice": "screen",  # behind the screen (DEL-270)
        "show_dice": True,  # in the story (DEL-280)
        "talk_pictures": False,  # off until the host allows them (DEL-294)
        "hotseat": False,  # one player at each screen (DEL-365)
        "hotseat_players": [],
    }
    put = local.put(path(campaign, "play/options"), json={"tone": "horror", "detail": 0, "effort": "high", "model": "fake-small"})
    assert put.status_code == 200
    assert put.json() == {
        "tone": "horror",
        "custom_tone": "",
        "detail": 0,
        "effort": "high",
        "model": "fake-small",
        "beat_timer_s": None,
        "fallback": "hold_back",
        "paid_images": False,
        "paid_images_per_day": 20,
        "portrait_style": None,
        "xp_awards": ["monsters", "milestones", "roleplay"],
        "enemy_dice": "screen",
        "show_dice": True,
        "talk_pictures": False,
        "hotseat": False,
        "hotseat_players": [],
    }
    assert local.put(path(campaign, "play/options"), json={"tone": "silly"}).status_code == 422
    assert local.put(path(campaign, "play/options"), json={"detail": 7}).status_code == 422
    assert local.put(path(campaign, "play/options"), json={"model": "gpt"}).status_code == 422
    assert local.put(path(campaign, "play/options"), json={"effort": "extreme"}).status_code == 422
    assert local.put(path(campaign, "play/options"), json={"xp_awards": ["charm"]}).status_code == 422
    awards = local.put(path(campaign, "play/options"), json={"xp_awards": ["gold", "monsters", "gold"]})
    assert awards.json()["xp_awards"] == ["monsters", "gold"], "in order, once each"

    # The next beat uses the campaign's model and effort over Preferences' choice, and its tone in the prompt.
    dm._script = [[TextDelta("Dread.")]]
    local.post(path(campaign, "act"), json={"text": "We listen."})
    settle(local, campaign)
    assert dm.choices[-1] == BackendChoice("fake", "fake-small", Effort.HIGH)
    services = local.app.state.table
    assert services.dm(campaign.id)[1] == BackendChoice("fake", "fake-small", Effort.HIGH)
    assert services.side(campaign.id)[1].provider == "fake"

    # Back to Preferences' choice: null.
    local.put(path(campaign, "play/options"), json={"effort": None, "model": None})
    assert services.dm(campaign.id)[1] == BackendChoice("fake", "fake-large", Effort.AUTO)
    assert local.get(path(campaign, "play/options")).json()["tone"] == "horror"


def test_an_organiser_writes_a_custom_tone(app, local, storage, dm, campaign):
    from tests.web.test_campaigns_api import seat_browser

    put = local.put(path(campaign, "play/options"), json={"tone": "custom", "custom_tone": " Like a radio play. "})
    assert put.status_code == 200 and (put.json()["tone"], put.json()["custom_tone"]) == ("custom", "Like a radio play.")
    assert local.get(path(campaign, "play/options")).json()["custom_tone"] == "Like a radio play."
    assert local.put(path(campaign, "play/options"), json={"custom_tone": None}).json()["custom_tone"] == "Like a radio play."
    too_long = local.put(path(campaign, "play/options"), json={"custom_tone": "x" * 2001})
    assert too_long.status_code == 422 and too_long.json()["error"] == "A custom tone is at most 2000 characters."
    assert local.put(path(campaign, "play/options"), json={"custom_tone": 7}).status_code == 422
    cohost = seat_browser(app, storage, campaign.id, "cohost", name="Bo")
    assert cohost.put(path(campaign, "play/options"), json={"custom_tone": "Gentle."}).status_code == 403
    assert local.get(path(campaign, "play/options")).json()["custom_tone"] == "Like a radio play."


def test_dm_log_is_dm_view_only(local, lan, dm, campaign):
    dm._script = [[TextDelta("The door is shut."), ToolCall("t1", "dm_secrets", {}), ToolResult("t1", True, {"secrets": [SECRET]})]]
    local.post(path(campaign, "act"), json={"text": "We look."})
    settle(local, campaign)

    log = local.get(path(campaign, "dm/log"))
    assert log.status_code == 200 and log.headers["cache-control"] == "no-store"
    raw = [e["raw"] for e in log.json()["entries"]]
    assert [r["type"] for r in raw] == ["text", "tool_call", "tool_result", "turn_end"]
    assert SECRET in json.dumps(raw)
    beat_id = log.json()["entries"][0]["beat_id"]
    assert len(local.get(path(campaign, "dm/log"), params={"beat": beat_id}).json()["entries"]) == 4

    # Nothing else the player's screen reads holds it; another device without the token gets nothing.
    for route in ("story", "play/state"):
        assert SECRET not in local.get(path(campaign, route)).text
    assert lan.get(path(campaign, "dm/log")).status_code == 401


def test_dm_costs_sum_the_log_per_beat(local, lan, dm, campaign):
    """The campaign page's costs (DEL-172), summed by the server rather than from the whole log."""
    dm._script = [[TextDelta("The door is shut."), ToolCall("t1", "dm_secrets", {}), ToolResult("t1", True, {"secrets": [SECRET]})]]
    local.post(path(campaign, "act"), json={"text": "We look."})
    settle(local, campaign)
    costs = local.get(path(campaign, "dm/costs"))
    assert costs.status_code == 200 and costs.headers["cache-control"] == "no-store"
    beat_id = local.get(path(campaign, "dm/log")).json()["entries"][0]["beat_id"]
    [row] = costs.json()["rows"]
    assert {k: v for k, v in row.items() if k != "at"} == {
        "beat": beat_id, "ask": False, "tools": 1, "input": 0, "output": 0, "cost": None
    }
    assert SECRET not in costs.text
    assert lan.get(path(campaign, "dm/costs")).status_code == 401


def test_the_host_turning_paid_images_on_wakes_the_banner(local, storage, registries):
    """Looks and banners plan Task 2: a banner waits while the scene's model costs money and paid images are off."""
    from tests.web.test_campaigns_api import HeldPainter, banner_painters, crypt_module, settled
    from tests.web.test_campaigns_api import campaign as make_campaign

    painter = HeldPainter()
    banner_painters(registries, storage, painter, "dear")
    cid = make_campaign(local, crypt_module(local)["id"])["id"]
    [row] = storage.campaign_images.list(cid, kind="banner")
    assert row.status == "waiting"

    assert local.put(f"/api/campaigns/{cid}/play/options", json={"paid_images": False}).status_code == 200
    assert storage.campaign_images.get(row.id).status == "waiting", "only turning paid images on wakes it"
    response = local.put(f"/api/campaigns/{cid}/play/options", json={"paid_images": True})

    assert response.status_code == 200, response.json()
    assert storage.campaign_images.get(row.id).status == "painting"
    painter.gate.set()
    assert settled(storage, row.id).status == "done"


# ----- the banner's routes (looks and banners plan Task 3) -----


def test_every_seat_reads_its_own_campaigns_banner(app, local, storage):
    from delve.images.fake import PIXEL_PNG
    from tests.web.test_campaigns_api import campaign as make_campaign
    from tests.web.test_campaigns_api import crypt_module, seat_browser, settled

    module = crypt_module(local)["id"]
    a, b = (make_campaign(local, module, name)["id"] for name in ("A", "B"))
    [row] = storage.campaign_images.list(a, kind="banner")
    assert settled(storage, row.id).status == "done"
    for cid in (a, b):
        [other] = storage.campaign_images.list(cid, kind="banner")
        settled(storage, other.id)

    for role in ("player", "observer"):
        browser = seat_browser(app, storage, a, role, name=role)
        response = browser.get(f"/api/campaigns/{a}/banner")
        assert response.status_code == 200, role
        assert response.content == PIXEL_PNG and response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-cache"
        assert browser.get(f"/api/campaigns/{a}/play/state").json()["banner"] == row.id, role
    stranger = seat_browser(app, storage, b, "player", name="Bo")
    assert stranger.get(f"/api/campaigns/{a}/banner").status_code == 403
    assert local.get(f"/api/campaigns/{a}/banner").content == PIXEL_PNG

    storage.campaign_images.delete(row.id)
    assert local.get(f"/api/campaigns/{a}/banner").status_code == 404
    assert local.get(f"/api/campaigns/{a}/play/state").json()["banner"] is None


def test_only_organisers_paint_again(app, local, storage, registries):
    from delve.play.images import PAID_HINT
    from tests.web.test_campaigns_api import HeldPainter, banner_painters, crypt_module, seat_browser, settled
    from tests.web.test_campaigns_api import campaign as make_campaign

    painter = HeldPainter()
    banner_painters(registries, storage, painter, "dear")
    cid = make_campaign(local, crypt_module(local)["id"])["id"]
    path = f"/api/campaigns/{cid}/banner"
    for role in ("player", "observer", "cohost"):
        assert seat_browser(app, storage, cid, role, name=role).post(path, json={}).status_code == 403, role

    closed = local.post(path, json={"hint": "the bell tower"})
    assert closed.status_code == 422
    assert closed.json()["hint"] == PAID_HINT

    assert local.put(f"/api/campaigns/{cid}/play/options", json={"paid_images": True}).status_code == 200
    [woken] = storage.campaign_images.list(cid, kind="banner")
    painter.gate.set()
    assert settled(storage, woken.id).status == "done"

    painter.gate.clear()
    response = local.post(path, json={"hint": "the bell tower"})
    assert response.status_code == 202, response.json()
    assert response.json()["status"] == "painting"
    again = storage.campaign_images.get(response.json()["image_id"])
    assert again.prompt.endswith("Emphasis: the bell tower.")
    second = local.post(path, json={})
    assert second.status_code == 409 and "being painted" in second.json()["error"]

    token = new_seat_token()
    storage.seats.create(cid, "Dee", "en", "player", organiser=True, token_hash=token_hash(token))
    dee = TestClient(app, base_url=BASE_URL)
    dee.cookies.set(SEAT_COOKIE, token)
    assert dee.post(path, json={}).status_code == 409, "an organiser seat may paint again"
    painter.gate.set()
    assert settled(storage, again.id).status == "done"
    assert local.get(f"/api/campaigns/{cid}/play/state").json()["banner"] == again.id


def test_a_campaigns_stored_default_model_still_means_the_clis_own(local, storage, registries, campaign):
    from delve.dm.claude_cli.provider import CLAUDE_CLI_CAPABILITIES
    from delve.play.table import set_play_settings

    registries.dm.register(CLAUDE_CLI_CAPABILITIES, object)
    storage.settings.save({"choices": {"dm": {"provider": "claude-cli", "model": "sonnet", "effort": "medium"}}})
    set_play_settings(storage, campaign.id, {"model": "default", "effort": "high"})
    assert local.app.state.table.dm(campaign.id)[1] == BackendChoice("claude-cli", None, Effort.HIGH), (
        "the retired 'default' is no model, not Preferences' sonnet"
    )


def test_the_campaign_log_pages_the_story(local, dm, campaign):
    """DEL-324: the log's index and a page of it, as the seat saw the story; a page past the last is 404."""
    assert local.get(path(campaign, "log")).json()["pages"] == []
    dm._script = [[TextDelta("The door is shut.")]]
    local.post(path(campaign, "act"), json={"text": "We look."})
    settle(local, campaign)
    out = local.get(path(campaign, "log")).json()
    assert [(p["page"], p["entries"]) for p in out["pages"]] == [(1, 2)]
    assert [e["kind"] for e in out["entries"]] == ["player_act", "dm_text"]
    assert local.get(path(campaign, "log"), params={"page": 2}).status_code == 404
