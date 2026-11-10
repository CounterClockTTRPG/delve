"""`play.factions` (plan 6 Task 5, Decision 6): factions, their clocks and their standing, seeded from the module when
a campaign is created (or on first use, for an older one). A countdown clock loses a day with each new day and
completes once; a progress clock moves only when the DM advances it. The party's reputation with an NPC's faction
moves the NPC's reaction. Notes, strength, the reputation number and the clocks are the DM's."""

import json

import pytest

from delve.dice import ScriptedRng, SeededRng
from delve.dm.tools import ToolHost
from delve.dm.tools.redact import player_view
from delve.domain.world import Faction
from delve.modules.source import ModuleSource
from delve.play import characters, days, factions, quests
from delve.play.context import NotFound, PlayError
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

SECRET = "SECRET-XYZZY"

SOURCE = ModuleSource(
    entities={
        "factions": [
            {
                "id": "cult",
                "name": "Cult of the Elder Eye",
                "alignment": "CE",
                "scope": "local",
                "goals": ["Wake the eye", "Silence the abbot"],
                "description": f"{SECRET}: the abbot is one of them.",
                "clocks": [
                    {"name": "The eye wakes", "days": 10, "on_complete": f"{SECRET}: the crypt floods with dark."},
                    {"name": "The abbey falls", "segments": 6, "filled": 2},
                ],
            }
        ],
        "npcs": [{"id": "abbot", "name": "Abbot Hesk", "faction": "faction:cult"}],
        "quests": [
            {
                "id": "find-the-relic",
                "name": "Find the relic",
                "giver": "npc:abbot",
                "scope": "local",
                "stakes": "The abbey loses its ward.",
                "related": ["faction:cult"],
                "description": f"{SECRET}: the relic is a fake.",
            }
        ],
    }
)


@pytest.fixture
def call(storage, campaign):
    """`call(tool, **args)`: a tool call on the campaign, in one beat."""
    host = ToolHost(storage, lambda: SeededRng(1), catalogs=over(PlayReference()))
    return lambda tool, /, **args: host.call(campaign.id, "beat-1", tool, args)


@pytest.fixture
def seeded(ctx):
    factions.seed(ctx, SOURCE)
    return ctx


def _clock(ctx, label):
    return next(c for c in ctx.storage.clocks.list(ctx.campaign_id) if c.label == label)


def test_seeding_from_the_module(seeded):
    ctx = seeded
    [cult] = ctx.storage.factions.list(ctx.campaign_id)
    assert (cult.id, cult.name, cult.alignment, cult.scope) == ("cult", "Cult of the Elder Eye", "CE", "local")
    assert cult.goals == "Wake the eye; Silence the abbot"
    assert (cult.known, cult.strength, cult.reputation, cult.source_ref) == (False, 100, 0, "faction:cult")
    assert SECRET in cult.notes_md

    eye, abbey = ctx.storage.clocks.list(ctx.campaign_id)
    assert (eye.label, eye.kind, eye.days_remaining, eye.faction_id) == ("The eye wakes", "countdown", 10, "cult")
    assert SECRET in eye.on_complete and eye.started_day == 1 and eye.done_day is None
    assert (abbey.kind, abbey.segments, abbey.filled, abbey.days_remaining) == ("progress", 6, 2, None)

    [relic] = ctx.storage.quests.list(ctx.campaign_id)
    assert (relic.id, relic.title, relic.giver, relic.status, relic.known) == (
        "find-the-relic",
        "Find the relic",
        "Abbot Hesk",
        "available",
        False,
    )
    assert relic.stakes == "The abbey loses its ward." and relic.related == ("faction:cult",)
    assert relic.source_ref == "quest:find-the-relic" and SECRET in relic.notes_md


def test_an_upgrade_adds_new_entities_and_keeps_play_state(seeded):
    ctx = seeded
    factions.update_faction(ctx, "cult", reputation_change=30, known=True)
    factions.advance_clock(ctx, _clock(ctx, "The abbey falls").id, 1)
    quests.update_quest(ctx, "find-the-relic", status="active")
    grown = ModuleSource(
        entities={
            "factions": [
                {**SOURCE.entities["factions"][0], "alignment": "NE"},
                {"id": "guard", "name": "The Abbey Guard", "clocks": [{"name": "Patrol returns", "days": 3}]},
            ],
            "quests": [*SOURCE.entities["quests"], {"id": "bury-the-dead", "name": "Bury the dead"}],
        }
    )
    added = factions.seed(ctx, grown)
    assert added == {"factions": 1, "clocks": 1, "quests": 1}
    cult = ctx.storage.factions.get(ctx.campaign_id, "cult")
    assert (cult.reputation, cult.known, cult.alignment) == (30, True, "CE")  # play state is never overwritten
    assert _clock(ctx, "The abbey falls").filled == 3
    assert len(ctx.storage.clocks.list(ctx.campaign_id, faction_id="cult")) == 2  # no clock twice
    assert ctx.storage.quests.get(ctx.campaign_id, "find-the-relic").status == "active"
    assert ctx.storage.quests.get(ctx.campaign_id, "bury-the-dead").status == "available"
    assert factions.seed(ctx, grown) == {"factions": 0, "clocks": 0, "quests": 0}


def test_an_older_campaign_is_seeded_on_first_use(storage, campaign, ctx, call):
    """A campaign from before plateau 6 has no faction, clock or quest: the first tool that reads them seeds them
    from its pinned revision."""
    storage.module_sources.put(campaign.module_id, SOURCE)
    module = storage.modules.get(campaign.module_id)
    revision = storage.revisions.snapshot(module.id)
    storage.campaigns.set_revision(campaign.id, revision.number)
    assert storage.factions.list(campaign.id) == []
    listed = call("factions")
    assert [f["id"] for f in listed["factions"]] == ["cult"]
    assert len(storage.clocks.list(campaign.id)) == 2 and len(storage.quests.list(campaign.id)) == 1
    call("factions")
    assert len(storage.clocks.list(campaign.id)) == 2  # seeded once


def test_a_countdown_completes_once_and_never_again(seeded):
    ctx = seeded
    passed = days.pass_days(ctx, 30)
    [done] = passed["clocks"]["completed"]
    assert (done["label"], done["days_remaining"], done["done_day"]) == ("The eye wakes", 0, 11)
    assert SECRET in done["on_complete"]
    eye = _clock(ctx, "The eye wakes")
    assert (eye.days_remaining, eye.done_day) == (0, 11)
    assert "completed" not in days.pass_days(ctx, 5).get("clocks", {})


def test_urgent_clocks_are_reported_once_per_pass(seeded):
    """Over a pass of several days a clock is urgent (1-7 days left) as it stands at the end, once."""
    ctx = seeded
    passed = days.pass_days(ctx, 6)
    [urgent] = passed["clocks"]["urgent"]
    assert (urgent["label"], urgent["days_remaining"]) == ("The eye wakes", 4)
    assert "completed" not in passed["clocks"]
    assert days.pass_days(ctx, 4)["clocks"]["urgent"] == ()  # it completed on the last day


def test_a_progress_clock_does_not_tick_with_days(seeded):
    ctx = seeded
    days.pass_days(ctx, 20)
    abbey = _clock(ctx, "The abbey falls")
    assert (abbey.filled, abbey.done_day) == (2, None)
    out = factions.advance_clock(ctx, abbey.id, 3)
    assert out["clock"]["filled"] == 5 and "completed" not in out
    out = factions.advance_clock(ctx, abbey.id)
    assert out["completed"] is True and out["clock"]["done_day"] == 21
    with pytest.raises(PlayError):
        factions.advance_clock(ctx, abbey.id)
    with pytest.raises(PlayError):
        factions.advance_clock(ctx, _clock(ctx, "The eye wakes").id)  # a countdown ticks with the days


def test_a_clock_is_complete_when_made_with_nothing_left(seeded):
    """`add_clock` and the organisers' clocks route agree (`factions.shaped_clock`): a countdown made at 0 days is
    complete on the day it is made, as a full progress clock is (the DM's tool asks for 1 day or more); a negative
    count of days, or a clock of no segments, is refused."""
    ctx = seeded
    done = factions.add_clock(ctx, "Too late", days=0)
    assert done["clock"]["done_day"] == factions.day_number(ctx) and done["completed"] is True
    assert factions.add_clock(ctx, "Soon", days=1)["clock"]["done_day"] is None
    with pytest.raises(PlayError):
        factions.add_clock(ctx, "Back in time", days=-2)
    with pytest.raises(PlayError):
        factions.add_clock(ctx, "Empty", segments=0)


def test_add_clock_takes_days_or_segments(seeded, call):
    ctx = seeded
    out = call("add_clock", label="Ransom due", days=5, faction="Cult of the Elder Eye", on_complete="They kill him.")
    assert out["clock"]["kind"] == "countdown" and out["clock"]["faction"] == "cult"
    assert call("add_clock", label="The siege", segments=4)["clock"]["kind"] == "progress"
    assert "error" in call("add_clock", label="Both", days=3, segments=4)
    assert "error" in call("add_clock", label="Neither")
    unknown = call("add_clock", label="Lost", days=2, faction="the guild")
    assert unknown["candidates"] == [{"id": "cult", "name": "Cult of the Elder Eye"}]
    listed = call("clocks")["clocks"]
    assert [c["label"] for c in listed] == ["Ransom due", "The eye wakes", "The abbey falls", "The siege"]
    ransom = listed[0]["id"]
    assert call("remove_clock", id=ransom)["removed"]["label"] == "Ransom due"
    assert "error" in call("remove_clock", id=ransom)
    assert len(ctx.storage.clocks.list(ctx.campaign_id)) == 3


def test_update_faction_creates_clamps_and_logs(seeded, call):
    ctx = seeded
    refused = call("update_faction", id="guild", goals="Coin")
    assert "error" in refused and refused["candidates"] == [{"id": "cult", "name": "Cult of the Elder Eye"}]
    made = call("update_faction", id="Thieves Guild", name="The Thieves' Guild", scope="local", known=True)
    assert made["faction"]["id"] == "thieves-guild" and made["faction"]["known"] is True
    assert "error" in call("update_faction", id="  ", name="Nobody")
    out = call("update_faction", id="cult", reputation_change=-150, reason="robbed the shrine", strength=60)
    assert out["faction"]["reputation"] == -100 and out["faction"]["strength"] == 60
    assert "error" in call("update_faction", id="cult", strength=140)
    assert factions.update_faction(ctx, "cult", strength=140)["faction"]["strength"] == 100
    assert (out["before"], out["after"], out["faction"]["standing"]) == (0, -100, "Sworn enemy")
    [event] = [e for e in ctx.storage.events.recent(ctx.campaign_id, 20) if e.type == "reputation_change"]
    assert event.data["before"] == 0 and event.data["after"] == -100 and event.data["notes"] == "robbed the shrine"
    assert call("update_faction", id="Cult of the Elder Eye", notes="They meet at night.")["faction"]["notes_md"] == (
        "They meet at night."
    )
    assert [f["id"] for f in call("factions", known_only=True)["factions"]] == ["thieves-guild"]


@pytest.mark.parametrize(
    ("reputation", "word"),
    [
        (100, "Devoted"),
        (61, "Devoted"),
        (60, "Friendly"),
        (21, "Friendly"),
        (20, "Cordial"),
        (6, "Cordial"),
        (5, "Neutral"),
        (-5, "Neutral"),
        (-6, "Wary"),
        (-20, "Wary"),
        (-21, "Hostile"),
        (-60, "Hostile"),
        (-61, "Sworn enemy"),
        (-100, "Sworn enemy"),
    ],
)
def test_standing_words_at_each_edge(reputation, word):
    assert factions.standing(reputation) == word


def test_reaction_adds_the_npc_factions_reputation(storage, campaign, seeded):
    ctx = seeded
    characters.create(ctx, name="Tira", kind="npc", sheet={"faction": "cult", "disposition": 40})
    factions.update_faction(ctx, "cult", reputation_change=50)
    host = ToolHost(storage, lambda: ScriptedRng([40]), catalogs=over(PlayReference()))
    out = host.call(campaign.id, "beat-1", "reaction", {"npc": "Tira"})
    # OSRIC's d100: the disposition adds one for every 4 points, the reputation one for every 5 (40 / 4, 50 / 5).
    assert (out["raw"], out["disposition_applied"], out["reputation_applied"]) == (40, 10, 10)
    assert out["total"] == 60 and out["result"] == "favourable"


def test_npcs_join_a_faction_by_id_or_name(seeded, call):
    met = call("introduce_npc", race="human", description="a cultist", faction="Cult of the Elder Eye")
    assert met["sheet"]["faction"] == "cult"
    assert "candidates" in call("introduce_npc", race="human", faction="the guild")
    updated = call("update_character", ref=met["id"], patch={"faction": "cult"})
    assert updated["sheet"]["faction"] == "cult"
    assert "candidates" in call("update_character", ref=met["id"], patch={"faction": "nobody"})
    assert call("update_character", ref=met["id"], patch={"faction": ""})["sheet"]["faction"] == ""


def test_the_factions_and_clocks_are_the_dms(seeded, call, storage, campaign):
    """Review Focus 1: the notes, the strength, the reputation number and the clocks stay out of the players' view;
    the clocks that tick in a player-visible pass of days are a DM-only key."""
    host = ToolHost(storage, lambda: SeededRng(1), catalogs=over(PlayReference()))
    for name in ("factions", "update_faction", "add_clock", "advance_clock", "remove_clock", "clocks"):
        assert host.spec(name).player_visible is False, name
    listed = call("factions")
    assert SECRET in json.dumps(listed)
    assert player_view(host.spec("factions"), {}, listed) is None
    passed = call("advance_days", days=12)
    assert SECRET in json.dumps(passed["clocks"])
    for name in ("advance_days", "advance_time", "rest"):
        assert "clocks" in host.spec(name).dm_only_keys, name
    assert player_view(host.spec("advance_days"), {"days": 12}, passed) == {}


def test_faction_lookup_by_id_or_exact_name(seeded):
    ctx = seeded
    assert factions.get(ctx, "cult").id == "cult"
    assert factions.get(ctx, "cult of the elder eye").id == "cult"
    with pytest.raises(NotFound) as refused:
        factions.get(ctx, "Elder Eye")
    assert refused.value.candidates == [{"id": "cult", "name": "Cult of the Elder Eye"}]
    assert isinstance(ctx.storage.factions.get(ctx.campaign_id, "cult"), Faction)
