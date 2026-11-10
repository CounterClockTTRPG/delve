"""The beat runner (plan 2b Task 6; spec §7.1): a beat opens with the act, the DM's reply streams into the story and
the DM log, and the beat closes as done, failed or cancelled. It runs in a background task of its own, so it survives
the browser going away."""

import asyncio
import json

import pytest

from delve.dm.fake import FakeDM
from delve.dm.provider import DMError, TextDelta, ToolCall, ToolResult, TurnEnd
from delve.dm.tools import all_specs
from delve.domain.settings import BackendChoice
from delve.play import seats, table
from delve.play.context import context_for
from delve.play.sessions import new_session
from delve.play.table import (
    PUBLISH_EVERY,
    AppServices,
    BeatRunning,
    PendingCalls,
    cancel_beat,
    current_beat,
    dm_log,
    feed,
    run_beat,
    settle,
    story,
    wait_beat,
)
from tests.fixtures.play_reference import PlayReference
from tests.fixtures.rulesets import over

SPECS = {spec.name: spec for spec in all_specs()}


@pytest.fixture
def act(owner_seat):
    """`act(text, *character_ids)`: the owner seat's act."""

    def make(text: str, *character_ids: str) -> dict:
        return {
            "seat_id": owner_seat.id,
            "kind": "act",
            "characters": list(character_ids),
            "text": text,
            "original": text,
            "language": "en",
            "at": "",
        }

    return make


def services_for(storage, dm, events: list | None = None) -> AppServices:
    published = events if events is not None else []
    return AppServices(
        storage=storage,
        catalogs=over(PlayReference()),
        spec_lookup=SPECS.get,
        dm=lambda campaign_id: (dm, BackendChoice("fake")),
        side=lambda campaign_id: (dm, BackendChoice("fake")),
        publish=lambda kind, data, **where: published.append((kind, data)),
    )


class GatedDM(FakeDM):
    """A fake DM whose replies wait for `gate` before they end, like a DM still thinking."""

    def __init__(self, script):
        super().__init__(script)
        self.gate = asyncio.Event()

    async def open(self, spec):
        conversation = await super().open(spec)
        send, gate = conversation.send, self.gate

        async def gated(text):
            async for event in send(text):
                if isinstance(event, TurnEnd) and event.reason == "done":
                    await gate.wait()
                yield event

        conversation.send = gated
        return conversation


class SlowDM(FakeDM):
    """A fake DM that writes its text slowly, `pause` seconds before each delta, as a real one streams."""

    def __init__(self, script, pause: float):
        super().__init__(script)
        self.pause = pause

    async def open(self, spec):
        conversation = await super().open(spec)
        send, pause = conversation.send, self.pause

        async def slow(text):
            async for event in send(text):
                if isinstance(event, TextDelta):
                    await asyncio.sleep(pause)
                yield event

        conversation.send = slow
        return conversation


class BrokenDM(FakeDM):
    async def open(self, spec):
        raise RuntimeError("the provider is broken")


def kinds(storage, campaign_id) -> list[str]:
    return [entry.kind for entry in story(storage, campaign_id, seats.owner_seat(storage, campaign_id))["entries"]]


def test_beat_streams_story_and_closes(storage, campaign, act):
    dm = FakeDM(
        [
            [
                TextDelta("The door "),
                TextDelta("creaks open."),
                ToolCall("t1", "roll", {"notation": "1d20", "purpose": "listen"}),
                ToolResult("t1", True, {"notation": "1d20", "rolls": [14], "total": 14}),
                TextDelta(" You hear nothing."),
            ]
        ]
    )
    events: list = []
    services = services_for(storage, dm, events)

    async def scenario():
        beat = await run_beat(services, campaign.id, act("We open the door."))
        assert beat.status == "running" and current_beat(storage, campaign.id).id == beat.id
        return beat, await wait_beat(services, campaign.id)

    beat, closed = asyncio.run(scenario())
    assert closed.id == beat.id and closed.status == "done" and closed.closed_at
    entries = story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]
    assert [e.kind for e in entries] == ["player_act", "dm_text", "tool", "dm_text"]
    assert entries[1].payload == {"text": "The door creaks open."}
    assert entries[2].payload == {"name": "roll"}
    assert entries[3].payload == {"text": " You hear nothing."}
    assert "We open the door." in dm.sent[0]

    # Every DM event is in the DM log, a reply's deltas as one row (DEL-241: it was a row per delta); each stored
    # entry and the beat's start and end are published.
    raw = [e.raw_event_json for e in dm_log(storage, campaign.id, beat.id)]
    assert [r["type"] for r in raw] == ["text", "tool_call", "tool_result", "text", "turn_end"]
    assert raw[0]["text"] == "The door creaks open." and raw[3]["text"] == " You hear nothing."
    published = [kind for kind, _ in events]
    assert published[0] == "beat" and published[-1] == "beat"
    last = events[-1][1]
    assert last == {
        "campaign_id": campaign.id,
        "beat_id": beat.id,
        "status": "done",
        "submitted": [act("x")["seat_id"]],
        "deadline": None,
        "beat": {**last["beat"], "status": "done"},
    }
    told = [data["entry"]["id"] for kind, data in events if kind == "story"]
    assert set(told) == {e.id for e in entries}
    assert all(data["campaign_id"] == campaign.id for _, data in events)


def test_second_act_while_running_409(storage, campaign, act):
    dm = GatedDM([[TextDelta("Hm.")]])
    services = services_for(storage, dm)

    async def scenario():
        first = await run_beat(services, campaign.id, act("We wait."))
        await asyncio.sleep(0.01)
        with pytest.raises(BeatRunning) as refused:
            await run_beat(services, campaign.id, act("And wait again."))
        assert refused.value.message == "the DM is still answering"
        assert current_beat(storage, campaign.id).id == first.id
        dm.gate.set()
        return await wait_beat(services, campaign.id)

    assert asyncio.run(scenario()).status == "done"
    assert kinds(storage, campaign.id) == ["player_act", "dm_text"]


def test_beat_survives_client_disconnect(storage, campaign, act):
    """The request that opened the beat goes away (the browser reloads): the beat runs on to its end."""
    dm = GatedDM([[TextDelta("The corridor "), TextDelta("bends left.")]])
    services = services_for(storage, dm)

    async def scenario():
        async def request():
            await run_beat(services, campaign.id, act("We go on."))
            await asyncio.Event().wait()  # the client keeps the request open until it goes away

        client = asyncio.create_task(request())
        await asyncio.sleep(0.01)
        client.cancel()
        with pytest.raises(asyncio.CancelledError):
            await client
        # The story so far is there for the reloaded page, and the beat still runs.
        assert kinds(storage, campaign.id) == ["player_act", "dm_text"]
        assert current_beat(storage, campaign.id).status == "running"
        dm.gate.set()
        return await wait_beat(services, campaign.id)

    assert asyncio.run(scenario()).status == "done"
    assert story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"][-1].payload == {"text": "The corridor bends left."}


def test_dm_failure_becomes_dm_error_entry(storage, campaign, act):
    dm = FakeDM(
        [
            [TextDelta("You step"), DMError("claude stopped (exit code 1)", True, "stderr: boom"), TurnEnd("error")],
            [TextDelta("You step in.")],
        ]
    )
    services = services_for(storage, dm)

    async def two_beats():
        await run_beat(services, campaign.id, act("We step in."))
        failed = await wait_beat(services, campaign.id)
        await run_beat(services, campaign.id, act("We step in, again."))
        return failed, await wait_beat(services, campaign.id)

    failed, done = asyncio.run(two_beats())
    assert (failed.status, done.status) == ("failed", "done")
    entries = story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]
    assert [e.kind for e in entries] == ["player_act", "dm_text", "dm_error", "player_act", "dm_text"]
    assert entries[2].payload == {
        "message": "The DM didn't answer: claude stopped (exit code 1)",
        "retryable": True,
        "resets_at": None,
    }
    # The stderr tail is in the DM log only.
    assert "boom" in json.dumps([e.raw_event_json for e in dm_log(storage, campaign.id, failed.id)])
    assert "boom" not in json.dumps([e.payload for e in entries])

    # A provider that fails outright ends the beat the same way, never a hung beat.
    broken = services_for(storage, BrokenDM([]))

    async def broken_beat():
        await run_beat(broken, campaign.id, act("Hello?"))
        return await wait_beat(broken, campaign.id)

    assert asyncio.run(broken_beat()).status == "failed"
    last = story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"][-1]
    assert last.kind == "dm_error" and last.payload["message"].startswith("The DM didn't answer: ")
    assert "broken" not in last.payload["message"]


def test_cancel_beat_closes_it_cancelled(storage, campaign, act):
    dm = GatedDM([[TextDelta("Let me think…")], [TextDelta("Yes?")]])
    services = services_for(storage, dm)

    async def scenario():
        await run_beat(services, campaign.id, act("We wait."))
        await asyncio.sleep(0.01)
        assert await cancel_beat(services, campaign.id) is True
        cancelled = await wait_beat(services, campaign.id)
        assert await cancel_beat(services, campaign.id) is False
        dm.gate.set()
        await run_beat(services, campaign.id, act("Hello?"))
        return cancelled, await wait_beat(services, campaign.id)

    cancelled, done = asyncio.run(scenario())
    assert (cancelled.status, done.status) == ("cancelled", "done")


def test_orphaned_beat_is_closed_before_the_next_act(storage, campaign, act):
    """A beat left running by a Delve that stopped mid-beat no longer blocks the table."""
    from delve.play.table import open_beat

    stale = open_beat(storage, campaign.id, act("We were saying…"))
    services = services_for(storage, FakeDM([[TextDelta("Where were we?")]]))

    async def scenario():
        await run_beat(services, campaign.id, act("Go on."))
        return await wait_beat(services, campaign.id)

    assert asyncio.run(scenario()).status == "done"
    assert storage.beats.get(stale.id).status == "failed"
    assert kinds(storage, campaign.id) == ["player_act", "dm_error", "player_act", "dm_text"]


def test_a_failed_beat_leaves_the_rounds_outcomes_untold(storage, campaign, act):
    """A round resolved but not narrated: neither the beat a stopped Delve left running (closed as failed by the next
    act) nor a beat that fails releases it, as nobody told it; the next beat that ends done does."""
    from delve.dice import ScriptedRng
    from delve.play import characters, combat
    from delve.play.table import open_beat
    from tests.fixtures.combat import GARREK, PIPPA, CombatReference, setup_fight

    def at(*values):
        return context_for(storage, campaign.id, "beat-0", ScriptedRng(values), catalogs=over(CombatReference()))

    characters.create(at(), name="Garrek", sheet=GARREK)
    characters.create(at(), name="Pippa", sheet=PIPPA)
    setup_fight(at)
    combat.combat_round(at(19, 6), [{"attacker": "Garrek", "target": "Goblin 1"}])
    fight_id = storage.combats.live(campaign.id)[0]

    def released():
        return storage.combat_rounds.get(fight_id, 1).released_at is not None

    open_beat(storage, campaign.id, act("We were saying…"))
    failing = [TextDelta("Garrek"), DMError("claude stopped (exit code 1)", True, ""), TurnEnd("error")]
    services = services_for(storage, FakeDM([failing, [TextDelta("Garrek's blow fells the goblin.")]]))

    async def beat(text):
        await run_beat(services, campaign.id, act(text))
        return await wait_beat(services, campaign.id)

    assert asyncio.run(beat("Go on.")).status == "failed"
    assert not released()
    assert asyncio.run(beat("Again.")).status == "done"
    assert released()


def test_first_beat_primes_session(storage, campaign, act):
    dm = FakeDM([[TextDelta("Welcome.")], [TextDelta("On you go.")]])
    services = services_for(storage, dm)
    garrek = storage.characters.create(campaign.id, "Garrek")
    storage.characters.create(campaign.id, "Pippa")

    async def beat(text, *who):
        await run_beat(services, campaign.id, act(text, *who))
        return await wait_beat(services, campaign.id)

    asyncio.run(beat("We arrive at the crypt."))
    first = dm.sent[0]
    assert "session_primer" in first and "new_session" in first
    assert first.rstrip().endswith("\n\n> We arrive at the crypt.")

    # Once the session has started, a beat is the act alone; acting characters are named unless it's everyone.
    new_session(context_for(storage, campaign.id, "beat-1", catalogs=over(PlayReference())), "The Crypt")
    asyncio.run(beat("I check the door.", garrek.id))
    assert dm.sent[1] == "Garrek:\n> I check the door."
    # The DM sees only the act, never the hidden instruction, in the story.
    assert all("session_primer" not in json.dumps(e.payload) for e in story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"])


def test_recap_entry(storage, campaign, act):
    recap = "The party found the crypt and **rested** at the inn."
    dm = FakeDM(
        [
            [
                TextDelta("And so the evening ends."),
                ToolCall("t1", "end_session", {"recap": recap}),
                ToolResult("t1", True, {"session": 1, "title": "The Crypt", "recap_md": recap}),
            ]
        ]
    )
    services = services_for(storage, dm)

    async def scenario():
        await run_beat(services, campaign.id, act("Let's end the session here."))
        return await wait_beat(services, campaign.id)

    asyncio.run(scenario())
    entries = story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]
    assert [e.kind for e in entries] == ["player_act", "dm_text", "tool", "recap"]
    assert entries[-1].payload == {"text": recap, "session": 1, "title": "The Crypt"}


def test_a_batchs_lines_and_tells_reach_the_story(storage, campaign, act, owner_seat):
    """A `say` or a `tell` the DM makes as a step of `batch` reaches the story as it would on its own: Bollo's two
    lines as said lines, in order, and the tell for its PC alone. Before, only the batch's own row showed, and the
    narration around the lines read as if he had said nothing."""
    from delve.dm.tools.say import said_line

    bollo = storage.characters.create(campaign.id, "Bollo", kind="npc")
    pc = storage.characters.create(campaign.id, "Seven Lanterns", kind="pc")
    first = said_line(bollo, "Nothing but moor between here and the mounds.", "shake")
    second = said_line(bollo, "There's a ruin up north, in the Blackened Forest.", "thinking")
    results = {
        "ran": 4,
        "requested": 4,
        "stopped_early": False,
        "results": [
            {"step": 0, "tool": "say", "result": {"said": first}},
            {"step": 1, "tool": "advance_time", "result": {"minutes": 5}},
            {"step": 2, "tool": "say", "result": {"said": second}},
            {"step": 3, "tool": "tell", "result": {"told": {"characters": [pc.id], "text": "The barmaid looks at you."}}},
        ],
    }
    dm = FakeDM(
        [
            [
                TextDelta("Bollo scratches his jaw."),
                ToolCall("b1", "batch", {"steps": []}),
                ToolResult("b1", True, json.dumps(results)),
                TextDelta("What next?"),
            ]
        ]
    )
    services = services_for(storage, dm)

    async def scenario():
        await run_beat(services, campaign.id, act("Any abandoned houses between here and the mounds?"))
        return await wait_beat(services, campaign.id)

    asyncio.run(scenario())
    entries = story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]
    said = [e.payload["text"] for e in entries if e.kind == "say"]
    assert said == [first["text"], second["text"]]
    [told] = [e for e in storage.story.list(campaign.id) if e.kind == "dm_text" and e.payload.get("told_to")]
    assert told.payload == {"text": "The barmaid looks at you.", "told_to": [pc.id]}


# ----- streaming the reply: only its new words, few writes (DEL-241) -----


def test_a_streamed_reply_sends_its_new_words_and_is_stored_and_logged_once(storage, campaign, act, monkeypatch):
    """Review P3: 400 deltas made 2,037 statements and sent the whole reply each time. Now the reply goes out whole
    when it first shows and when it ends, its words between as `story_text` events, a few at a time, which rebuild
    it exactly; it is stored at those two points, and the DM log keeps it as one row."""
    monkeypatch.setattr(table, "STORE_EVERY", 60.0)  # however slow the machine, no store while it streams
    words = [f"word{n} " for n in range(30)]
    events: list = []
    services = services_for(storage, SlowDM([[TextDelta(w) for w in words]], pause=PUBLISH_EVERY / 4), events)
    put = []
    real_put = storage.story.put

    def counted(entry):
        if entry.kind == "dm_text":
            put.append(entry.payload["text"])
        return real_put(entry)

    storage.story.put = counted

    async def scenario():
        beat = await run_beat(services, campaign.id, act("Go on."))
        return beat, await wait_beat(services, campaign.id)

    beat, closed = asyncio.run(scenario())
    assert closed.status == "done"
    [reply] = [e for e in storage.story.list(campaign.id) if e.kind == "dm_text"]
    assert reply.payload["text"] == "".join(words), "the story's text is the reply's, whole"
    assert put == [words[0], "".join(words)], "stored when it first shows and at its end"
    whole = [d["entry"]["payload"]["text"] for kind, d in events if kind == "story" and d["entry"]["id"] == reply.id]
    assert whole == [words[0], "".join(words)]
    streamed = [data for kind, data in events if kind == "story_text"]
    assert 3 <= len(streamed) < len(words) - 1, "the words since the last send go together"
    text = whole[0]
    for data in streamed:
        assert (data["campaign_id"], data["entry_id"], data["at"]) == (campaign.id, reply.id, len(text))
        text += data["text"]
    assert reply.payload["text"].startswith(text)
    raw = [e.raw_event_json for e in dm_log(storage, campaign.id, beat.id)]
    assert raw == [{"type": "text", "text": "".join(words)}, {"type": "turn_end", "reason": "done"}]


def test_feed_stores_a_reply_at_intervals_and_its_last_words_at_its_end(storage, campaign, act):
    from delve.play.table import open_beat

    beat = open_beat(storage, campaign.id, act("We listen."))
    now = [0.0]
    pending = PendingCalls(campaign.id, beat.id, store_every=1.0, clock=lambda: now[0])
    stored = []
    for at, text in ((0.0, "Drip"), (0.4, ", drip"), (1.2, ", drip"), (1.5, "...")):
        now[0] = at
        stored.append([e.payload["text"] for e in feed(storage, TextDelta(text), {}, SPECS.get, pending)])
    assert stored == [["Drip"], [], ["Drip, drip, drip"], []]
    assert pending.reply.payload["text"] == "Drip, drip, drip..."
    # A tool call ends the reply: its last words, unstored though they showed, are stored with it.
    ended = feed(storage, ToolCall("t1", "roll", {"notation": "1d6"}), {"type": "tool_call"}, SPECS.get, pending)
    assert [e.payload for e in ended] == [{"text": "Drip, drip, drip..."}]
    texts = [e.payload["text"] for e in storage.story.list(campaign.id) if e.kind == "dm_text"]
    assert texts == ["Drip, drip, drip..."]
    assert [e.raw_event_json for e in dm_log(storage, campaign.id, beat.id)] == [
        {"type": "text", "text": "Drip, drip, drip..."},
        {"type": "tool_call"},
    ]


def test_settle_keeps_a_reply_cut_off(storage, campaign, act):
    """A cancel or a failure mid-reply: what showed is stored, and the DM log has its row."""
    from delve.play.table import open_beat

    beat = open_beat(storage, campaign.id, act("We wait."))
    pending = PendingCalls(campaign.id, beat.id, store_every=60.0)
    for text in ("Let me ", "think"):
        feed(storage, TextDelta(text), {}, SPECS.get, pending)
    assert [e.payload["text"] for e in settle(storage, pending)] == ["Let me think"]
    assert settle(storage, pending) == [], "once"
    assert [e.payload["text"] for e in storage.story.list(campaign.id) if e.kind == "dm_text"] == ["Let me think"]
    logged = [e.raw_event_json for e in dm_log(storage, campaign.id, beat.id)]
    assert logged == [{"type": "text", "text": "Let me think"}]


def test_a_cancelled_reply_keeps_what_it_showed(storage, campaign, act):
    dm = GatedDM([[TextDelta("Let me "), TextDelta("think…")]])
    events: list = []
    services = services_for(storage, dm, events)

    async def scenario():
        await run_beat(services, campaign.id, act("We wait."))
        await asyncio.sleep(0.05)
        assert await cancel_beat(services, campaign.id) is True
        return await wait_beat(services, campaign.id)

    assert asyncio.run(scenario()).status == "cancelled"
    [reply] = [e for e in storage.story.list(campaign.id) if e.kind == "dm_text"]
    assert reply.payload["text"] == "Let me think…"
    told = [d["entry"]["payload"]["text"] for kind, d in events if kind == "story" and d["entry"]["id"] == reply.id]
    assert told[-1] == "Let me think…"



def test_a_tool_rows_live_event_has_no_call_id(storage, campaign):
    """DEL-172: a stored tool row keeps its `call_id` for the host's look at the call; the `story` event the table
    gets shows the row as story pages do, without it."""
    events: list = []
    entry = table.add_entry(storage, campaign.id, None, "tool", {"name": "roll", "call_id": "toolu_1"})
    table.told(services_for(storage, FakeDM([]), events), entry)
    # Once for the host and once for the co-hosts, each as they see it (DEL-270); a row without dice is the same.
    assert [kind for kind, _ in events] == ["story", "story"]
    assert all(data["entry"]["payload"] == {"name": "roll"} for _, data in events)
    assert storage.story.list(campaign.id)[-1].payload["call_id"] == "toolu_1", "the stored row keeps it"
