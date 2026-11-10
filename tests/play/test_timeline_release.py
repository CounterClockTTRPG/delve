"""A round's outcomes reach the table once the DM's text for it has arrived (table voice and fixes Task B2.2): the
beat runner's hooks release the resolved rounds and publish `timeline` events that carry no content."""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from delve.dice import ScriptedRng
from delve.dm.provider import TextDelta, ToolCall, ToolResult
from delve.domain.campaigns import Beat, StoryEntry
from delve.play import characters, combat
from delve.play.clock import FakeClock
from delve.play.context import context_for
from delve.play.table import AppServices
from delve.play.timeline import after_beat, after_event, timeline_for
from tests.fixtures.combat import GARREK, PIPPA, CombatReference, setup_fight
from tests.fixtures.rulesets import over


@pytest.fixture
def at(storage, campaign):
    def make(*values: int, beat: str = "beat-1"):
        return context_for(storage, campaign.id, beat, ScriptedRng(values), catalogs=over(CombatReference()))

    return make


@pytest.fixture
def party(at):
    ctx = at()
    return [characters.create(ctx, name="Garrek", sheet=GARREK), characters.create(ctx, name="Pippa", sheet=PIPPA)]


@pytest.fixture
def published():
    return []


@pytest.fixture
def services(storage, published):
    def publish(kind, data, **where):
        published.append((kind, data, where))

    return AppServices(storage, lambda name: None, dm=None, side=None, publish=publish)


def result(name: str, id: str = "call-1"):
    """A tool call and its result, as the runner sees them."""
    return ToolCall(id, name, {}), ToolResult(id, True, {})


def feed(services, campaign, *events, stored=()):
    for event in events:
        after_event(services, campaign.id, "beat-1", event, list(stored))


def entry(campaign, kind="dm_text", audience=None):
    """A story entry as the runner stored it (the hook reads only its kind and its audience)."""
    return StoryEntry("sty_1", campaign.id, "beat-1", 1, kind, {"text": "Garrek's blow fells the goblin."}, audience=audience)


def narration(storage, campaign):
    return entry(campaign)


def a_resolved_round(at, services, campaign):
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    feed(services, campaign, *result("setup_combat", "call-1"))
    combat.combat_round(at(19, 6), [{"attacker": "Garrek", "target": "Goblin 1"}])
    feed(services, campaign, *result("combat_round", "call-2"))


def test_initiative_rolled_is_published(storage, campaign, at, party, services, published):
    setup_fight(at)
    feed(services, campaign, *result("setup_combat"))
    id = storage.combats.live(campaign.id)[0]
    assert [(k, d) for k, d, _ in published] == [
        ("timeline", {"campaign_id": campaign.id, "combat_id": id, "round": 1, "change": "initiative"})
    ]
    assert published[0][2] == {"scope": "table", "campaign_id": campaign.id}


def test_outcomes_hidden_until_dm_text(storage, campaign, at, party, services, published, owner_seat):
    a_resolved_round(at, services, campaign)
    feed(services, campaign, TextDelta("Ga"), stored=[entry(campaign, "tool")])
    fight = timeline_for(storage, campaign.id, owner_seat)["fight"]
    assert fight["released"] is False and {s["state"] for s in fight["slots"]} == {"waiting"}
    # A note for the host is no narration for the table.
    note = entry(campaign, audience={"seats": [owner_seat.id]})
    feed(services, campaign, TextDelta("x"), stored=[note])
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is False
    assert "outcomes" not in [d["change"] for k, d, _ in published]

    feed(services, campaign, TextDelta("Garrek"), stored=[narration(storage, campaign)])
    fight = timeline_for(storage, campaign.id, owner_seat)["fight"]
    assert fight["released"] is True
    assert {s["name"]: s["state"] for s in fight["slots"]}["Goblin 1"] == "dead"
    assert published[-1][1]["change"] == "outcomes" and published[-1][1]["round"] == 1


def test_outcomes_after_reload(storage, campaign, at, party, services, owner_seat):
    a_resolved_round(at, services, campaign)
    feed(services, campaign, TextDelta("Garrek"), stored=[narration(storage, campaign)])
    # A fresh read, as a reloaded page makes it, from what is stored.
    fight = timeline_for(storage, campaign.id, owner_seat)["fight"]
    assert fight["released"] is True and fight["slots"][0]["ongoing"]["state"] == "completed"


def test_text_before_the_round_releases_nothing(storage, campaign, at, party, services, owner_seat):
    setup_fight(at)
    feed(services, campaign, *result("setup_combat"))
    feed(services, campaign, TextDelta("The goblins"), stored=[narration(storage, campaign)])
    id = storage.combats.live(campaign.id)[0]
    assert storage.combat_rounds.get(id, 1).released_at is None


def test_beat_end_releases_the_rest(storage, campaign, at, party, services, published, owner_seat):
    a_resolved_round(at, services, campaign)
    after_beat(services, Beat("beat-1", campaign.id, 1, "done"))
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is True
    assert published[-1][1]["change"] == "outcomes"


def test_text_stored_as_the_round_is_called_doesnt_release_it(storage, campaign, at, party, services, owner_seat):
    """The reply's last words are stored when the `combat_round` call arrives; the tool's writes may have landed
    before (the bridge answers it while the stream is read). Those words are no narration of the round they precede:
    only a text after its result releases it."""
    setup_fight(at, spells=[{"caster": "Pippa", "spell": "sleep"}])
    feed(services, campaign, *result("setup_combat", "call-1"))
    call, answer = result("combat_round", "call-2")
    combat.combat_round(at(19, 6), [{"attacker": "Garrek", "target": "Goblin 1"}])  # the writes land first
    feed(services, campaign, call, stored=[narration(storage, campaign)])  # "Garrek swings…", ended by the call
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is False
    feed(services, campaign, answer)
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is False
    feed(services, campaign, TextDelta("Garrek"), stored=[narration(storage, campaign)])
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is True


def test_rounds_are_rolled_resolved_and_released_by_the_injected_clock(storage, campaign, party, services):
    """The fight's rows keep the time of the clock the table runs on (a test's, `delve serve`'s `FileClock`), not the
    wall clock."""
    rolled = FakeClock(datetime(2031, 3, 4, 5, 6, tzinfo=UTC))

    def at(*values: int):
        ctx = context_for(storage, campaign.id, "beat-1", ScriptedRng(values), catalogs=over(CombatReference()))
        return replace(ctx, clock=rolled)

    services.clock = FakeClock(datetime(2032, 1, 1, tzinfo=UTC))
    a_resolved_round(at, services, campaign)
    after_beat(services, Beat("beat-1", campaign.id, 1, "done"))
    row = storage.combat_rounds.get(storage.combats.live(campaign.id)[0], 1)
    assert row.rolled_at.startswith("2031-03-04") and row.resolved_at.startswith("2031-03-04")
    assert row.released_at.startswith("2032-01-01")


def test_a_failed_beat_releases_nothing(storage, campaign, at, party, services, published, owner_seat):
    """A beat that failed (or was closed as failed by the start of the next act, `_close_orphan`) didn't narrate its
    rounds: Retry does. The next beat that ends done releases what is left."""
    a_resolved_round(at, services, campaign)
    after_beat(services, Beat("beat-1", campaign.id, 1, "failed"))
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is False
    assert "outcomes" not in [d["change"] for _, d, _ in published]
    after_beat(services, Beat("beat-2", campaign.id, 2, "done"))
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is True
    assert published[-1][1]["change"] == "outcomes"


def test_a_cancelled_beat_releases(storage, campaign, at, party, services, owner_seat):
    a_resolved_round(at, services, campaign)
    after_beat(services, Beat("beat-1", campaign.id, 1, "cancelled"))
    assert timeline_for(storage, campaign.id, owner_seat)["fight"]["released"] is True


def test_beat_end_with_nothing_to_release_publishes_nothing(campaign, at, party, services, published):
    after_beat(services, Beat("beat-1", campaign.id, 1, "done"))
    assert published == []


def test_end_of_fight_is_published(storage, campaign, at, party, services, published):
    setup_fight(at)
    feed(services, campaign, *result("setup_combat"))
    id = storage.combats.live(campaign.id)[0]
    combat.end_combat(at())
    feed(services, campaign, *result("end_combat", "call-9"))
    assert published[-1][1] == {"campaign_id": campaign.id, "combat_id": id, "round": 1, "change": "ended"}


def test_events_carry_no_names(storage, campaign, at, party, services, published):
    a_resolved_round(at, services, campaign)
    feed(services, campaign, TextDelta("Garrek"), stored=[narration(storage, campaign)])
    combat.end_combat(at())
    feed(services, campaign, *result("end_combat", "call-9"))
    assert {d["change"] for _, d, _ in published} == {"initiative", "outcomes", "ended"}
    for _, data, where in published:
        assert set(data) == {"campaign_id", "combat_id", "round", "change"}
        assert "audience" not in where
    text = json.dumps([d for _, d, _ in published])
    assert "Goblin" not in text and "Garrek" not in text and "sleep" not in text


def test_a_text_with_no_round_waiting_reads_nothing(services, storage, campaign, monkeypatch):
    """The review's 401 queries for 400 deltas: a text stored when no resolved round waits returns at once
    (DEL-241); a beat's end still looks."""
    asked = []
    unreleased = storage.combat_rounds.unreleased
    monkeypatch.setattr(storage.combat_rounds, "unreleased", lambda cid: asked.append(cid) or unreleased(cid))
    for _ in range(5):
        feed(services, campaign, TextDelta("More words."), stored=[entry(campaign)])
    assert asked == []
    after_beat(services, Beat("beat-1", campaign.id, 1, "done", [], "", ""))
    assert asked == [campaign.id]
