"""Beats, the story, the DM log and the players' feed (plan 2b Task 2; spec §7.1, §7.5)."""

import json

import pytest

from delve.dm.provider import DMError, TextDelta, ToolCall, ToolResult, TurnEnd, Usage
from delve.dm.tools import all_specs
from delve.dm.tools.redact import player_row
from delve.play import seats
from delve.play.table import (
    BeatRunning,
    PendingCalls,
    add_entry,
    close_beat,
    current_beat,
    dm_log,
    feed,
    feed_entry_for,
    log_dm_event,
    open_beat,
    story,
)
from tests.fixtures.rulesets import over

SECRET = "SECRET-XYZZY"
SPECS = {spec.name: spec for spec in all_specs()}


@pytest.fixture
def act(owner_seat):
    """`act(text, *character_ids)`: the owner seat's act."""

    def make(text: str, *character_ids: str) -> dict:
        return {"player": owner_seat.id, "character_ids": list(character_ids), "kind": "act", "text": text}

    return make


def test_one_beat_at_a_time(storage, campaign, act):
    first = open_beat(storage, campaign.id, act("We open the door.", "chr_aaaaaaaaaaaa"))
    assert first.id.startswith("beat_") and len(first.id) == len("beat_") + 12
    assert (first.campaign_id, first.number, first.status) == (campaign.id, 1, "running")
    assert first.submissions == (act("We open the door.", "chr_aaaaaaaaaaaa"),)
    assert first.opened_at and first.closed_at is None
    assert current_beat(storage, campaign.id) == first

    with pytest.raises(BeatRunning) as refused:
        open_beat(storage, campaign.id, act("And again."))
    assert refused.value.message == "the DM is still answering"
    assert [e.kind for e in story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]] == ["player_act"]

    done = close_beat(storage, first.id, "done")
    assert done.status == "done" and done.closed_at
    assert current_beat(storage, campaign.id) is None
    second = open_beat(storage, campaign.id, act("We go in."))
    assert second.number == 2 and second.id != first.id
    assert close_beat(storage, second.id, "failed").status == "failed"
    with pytest.raises(ValueError):
        close_beat(storage, second.id, "running")


def test_story_paging(storage, campaign, act):
    for n in range(7):
        beat = open_beat(storage, campaign.id, act(f"act {n}"))
        close_beat(storage, beat.id, "done")
    page = story(storage, campaign.id, seats.owner_seat(storage, campaign.id), limit=3)
    assert [e.payload["text"] for e in page["entries"]] == ["act 4", "act 5", "act 6"]
    assert page["has_more"] is True
    seqs = [e.seq for e in page["entries"]]
    assert seqs == sorted(seqs)
    earlier = story(storage, campaign.id, seats.owner_seat(storage, campaign.id), before_seq=seqs[0], limit=3)
    assert [e.payload["text"] for e in earlier["entries"]] == ["act 1", "act 2", "act 3"]
    rest = story(storage, campaign.id, seats.owner_seat(storage, campaign.id), before_seq=earlier["entries"][0].seq, limit=3)
    assert [e.payload["text"] for e in rest["entries"]] == ["act 0"] and rest["has_more"] is False
    assert story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["has_more"] is False and len(story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]) == 7


def _play(storage, campaign_id, beat_id, events):
    pending = PendingCalls(campaign_id, beat_id)
    for event in events:
        feed(storage, event, {"event": repr(event)}, SPECS.get, pending)
    return [e for e in story(storage, campaign_id, seats.owner_seat(storage, campaign_id))["entries"] if e.beat_id == beat_id]


def test_feed_merges_text_and_pairs_tool_rows(storage, campaign, act):
    beat = open_beat(storage, campaign.id, act("We roll for the lever."))
    entries = _play(
        storage,
        campaign.id,
        beat.id,
        [
            TextDelta("The lever "),
            TextDelta("groans."),
            ToolCall("t1", "roll", {"notation": "1d20", "purpose": "the lever"}),
            ToolResult("t1", True, {"total": 14, "notation": "1d20", "faces": [14]}),
            TextDelta("It gives "),
            TextDelta("way."),
            Usage(100, 20, None),
            TurnEnd("done"),
        ],
    )
    assert [e.kind for e in entries] == ["player_act", "dm_text", "tool", "dm_text"]
    assert entries[1].payload == {"text": "The lever groans."}
    # Spec §7.5's allow-list: a tool's name, never its inputs or its result (the DM's words, a monster's numbers).
    assert entries[2].payload == {"name": "roll"}
    assert entries[3].payload == {"text": "It gives way."}

    # A result in claude's stream-json form (a JSON string or text blocks) is read the same way.
    pending = PendingCalls(campaign.id, beat.id)
    feed_entry_for(ToolCall("t2", "roll", {"notation": "1d6"}), SPECS.get, pending)
    entry = feed_entry_for(ToolResult("t2", True, [{"type": "text", "text": '{"total": 3}'}]), SPECS.get, pending)
    # The stored row keeps its call's id, for the host's look at the call (DEL-172); `player_row` drops it.
    assert entry.payload == {"name": "roll", "call_id": "t2"} and pending.calls == {}


def test_a_reply_without_a_note_for_the_host_streams_at_once(campaign):
    """Solo play stays as fast: each delta shows at once."""
    pending = PendingCalls(campaign.id, "beat_000000000000")
    shown = [feed_entry_for(TextDelta(text), SPECS.get, pending) for text in ("The lever ", "groans", ".\n", "It")]
    assert [e.payload["text"] if e else None for e in shown] == [
        "The lever ",
        "The lever groans",
        "The lever groans.\n",
        "The lever groans.\nIt",
    ]
    assert len({e.id for e in shown}) == 1
    # A paragraph that starts like a note, and isn't one, shows once it isn't.
    assert feed_entry_for(TextDelta("\n\n("), SPECS.get, pending).payload["text"] == "The lever groans.\nIt\n\n"
    later = feed_entry_for(TextDelta("The door creaks.)"), SPECS.get, pending)
    assert later.payload["text"] == "The lever groans.\nIt\n\n(The door creaks.)"


def test_a_note_for_the_host_is_the_hosts_alone(storage, campaign, owner_seat, act):
    """dm.md's `(ooc, for the host:` paragraph never shows to the table, not even in part: it is its own `dm_text`,
    for the host's seat. The narration around it streams as it does."""
    pending = PendingCalls(campaign.id, "beat_000000000000", host_seat=owner_seat.id)
    deltas = [
        "The hall is quiet.",
        "\n\n(oo",
        "c, for the host: ",
        f"{SECRET}.)",
        "\n\nA draught.",
        "\n\n(OOC, for the host: more)",
    ]
    shown = [feed_entry_for(TextDelta(text), SPECS.get, pending) for text in deltas]
    assert [e.payload["text"] if e else None for e in shown] == [
        "The hall is quiet.",
        "The hall is quiet.\n\n",
        None,
        None,
        "The hall is quiet.\n\nA draught.",
        "The hall is quiet.\n\nA draught.\n\n",
    ]
    assert feed_entry_for(TurnEnd("done"), SPECS.get, pending) is None
    reply, note = pending.ended
    assert reply.id == shown[0].id and reply.payload == {"text": "The hall is quiet.\n\nA draught."}
    assert note.kind == "dm_text" and note.audience == {"seats": [owner_seat.id]}
    assert note.payload == {"text": f"(ooc, for the host: {SECRET}.)\n\n(OOC, for the host: more)"}

    # Through `feed`, the note is stored with the reply's end, and the next reply starts afresh.
    beat = open_beat(storage, campaign.id, act("We wait."))
    pending = PendingCalls(campaign.id, beat.id, host_seat=owner_seat.id)
    for text in ("Dark.", "\n\n(ooc, for the host: a note)"):
        feed(storage, TextDelta(text), {}, SPECS.get, pending)
    stored = feed(storage, ToolCall("t1", "roll", {"notation": "1d6"}), {}, SPECS.get, pending)
    assert [(e.payload, e.audience) for e in stored] == [
        ({"text": "Dark."}, None),
        ({"text": "(ooc, for the host: a note)"}, {"seats": [owner_seat.id]}),
    ]
    [after] = feed(storage, TextDelta("Light."), {}, SPECS.get, pending)
    assert after.payload == {"text": "Light."}


SCENE = "The hall is quiet.\n\nDust lies thick on the altar."


def _dm_texts(entries) -> list[str]:
    return [e.payload["text"] for e in entries if e.kind == "dm_text"]


def _scene_twice(again: str) -> list:
    """The scene as two deltas, a roll, then `again`, a delta at a time."""
    return [
        TextDelta("The hall is quiet.\n\n"),
        TextDelta("Dust lies thick on the altar."),
        ToolCall("t1", "roll", {"notation": "1d6", "purpose": "search"}),
        ToolResult("t1", True, {"total": 4}),
        *[TextDelta(word) for word in again.split(" ") for word in (word, " ")][:-1],
        TurnEnd("done"),
    ]


def test_a_paragraph_told_again_after_a_tool_is_dropped(storage, campaign, act, caplog):
    """D3, Review Focus 3: the model repeats the scene after a tool call. It is told once: the repeat, with its
    whitespace collapsed, equals the beat's earlier `dm_text`, so it never reaches the table, and the log says so."""
    beat = open_beat(storage, campaign.id, act("We look around."))
    with caplog.at_level("WARNING", logger="delve.play.table"):
        again = _scene_twice("The hall is  quiet.\n Dust lies thick on the altar.\n")
        entries = _play(storage, campaign.id, beat.id, again)
    assert [e.kind for e in entries] == ["player_act", "dm_text", "tool"]
    assert _dm_texts(entries) == [SCENE]
    assert "told again" in caplog.text and beat.id in caplog.text


def test_a_paragraph_that_starts_the_same_still_shows(storage, campaign, act):
    """Only an exact repeat is dropped: a reply that only starts like the scene, or that is a part of it, still
    shows, and is held back only while it may still be a repeat."""
    beat = open_beat(storage, campaign.id, act("We look around."))
    entries = _play(storage, campaign.id, beat.id, _scene_twice(SCENE + " More."))
    assert _dm_texts(entries) == [SCENE, SCENE + " More."]

    beat2 = close_beat(storage, beat.id, "done") and open_beat(storage, campaign.id, act("And again."))
    entries = _play(storage, campaign.id, beat2.id, _scene_twice("The hall is quiet."))
    assert _dm_texts(entries) == [SCENE, "The hall is quiet."]

    # The guard is per beat: the next beat may tell the scene again.
    beat3 = close_beat(storage, beat2.id, "done") and open_beat(storage, campaign.id, act("Once more."))
    entries = _play(storage, campaign.id, beat3.id, [TextDelta(SCENE), TurnEnd("done")])
    assert _dm_texts(entries) == [SCENE]


def test_a_repeat_after_a_batchs_tell_and_line_is_dropped(storage, campaign, act, owner_seat):
    """The guard works with the entries a `batch`'s steps make (`_made_by`): the tell and the said line reach the
    story, and the scene repeated after the batch is told once. A tell is not the table's reply: one with the scene's
    words is kept."""
    import asyncio

    from delve.dm.fake import FakeDM
    from delve.dm.tools.say import said_line
    from delve.domain.settings import BackendChoice
    from delve.play.table import AppServices, run_beat, wait_beat
    from tests.fixtures.play_reference import PlayReference

    bollo = storage.characters.create(campaign.id, "Bollo", kind="npc")
    pc = storage.characters.create(campaign.id, "Seven Lanterns", kind="pc")
    line = said_line(bollo, "Nothing but moor.", "shake")
    results = {
        "ran": 2,
        "requested": 2,
        "stopped_early": False,
        "results": [
            {"step": 0, "tool": "say", "result": {"said": line}},
            {"step": 1, "tool": "tell", "result": {"told": {"characters": [pc.id], "text": SCENE}}},
        ],
    }
    dm = FakeDM(
        [[TextDelta(SCENE), ToolCall("b1", "batch", {"steps": []}), ToolResult("b1", True, json.dumps(results)),
          TextDelta(SCENE.replace("\n\n", "\n")), TurnEnd("done")]]
    )  # fmt: skip
    services = AppServices(
        storage=storage,
        catalogs=over(PlayReference()),
        spec_lookup=SPECS.get,
        dm=lambda campaign_id: (dm, BackendChoice("fake")),
        side=lambda campaign_id: (dm, BackendChoice("fake")),
    )
    submission = {"seat_id": owner_seat.id, "kind": "act", "characters": [], "text": "Hello.", "original": "Hello.",
                  "language": "en", "at": ""}  # fmt: skip

    async def scenario():
        await run_beat(services, campaign.id, submission)
        return await wait_beat(services, campaign.id)

    assert asyncio.run(scenario()).status == "done"
    entries = [e for e in storage.story.list(campaign.id) if e.kind != "player_act"]
    assert [(e.kind, e.payload.get("told_to")) for e in entries] == [
        ("dm_text", None), ("tool", None), ("say", None), ("dm_text", [pc.id])
    ]  # fmt: skip
    assert entries[0].payload == {"text": SCENE} and entries[3].payload["text"] == SCENE


def test_feed_drops_dm_only_tools_and_error_candidates(storage, campaign):
    pending = PendingCalls(campaign.id, "beat_000000000000")
    assert feed_entry_for(ToolCall("t1", "dm_secrets", {}), SPECS.get, pending) is None
    assert feed_entry_for(ToolResult("t1", True, {"secrets": []}), SPECS.get, pending) is None
    assert feed_entry_for(ToolCall("t2", "move_party", {"to": "Vestry"}), SPECS.get, pending) is None
    refused = {"error": "No room 'Vestry'.", "hint": "Name one.", "candidates": [{"id": "x", "label": "Hidden"}]}
    entry = feed_entry_for(ToolResult("t2", False, json.dumps(refused)), SPECS.get, pending)
    # A refusal shows that it failed, not its message: "No room 'Vestry'" names the room the DM asked for.
    assert entry.kind == "tool" and entry.payload == {"name": "move_party", "failed": True, "call_id": "t2"}
    # An answer that is a refusal, without is_error, is a refusal too.
    feed_entry_for(ToolCall("t3", "roll", {"notation": "999d6"}), SPECS.get, pending)
    entry = feed_entry_for(
        ToolResult("t3", True, {"error": "too many dice", "hint": "at most 100"}), SPECS.get, pending
    )
    assert entry.payload == {"name": "roll", "failed": True, "call_id": "t3"}
    # Unknown tools, results without their call, usage and the end of the reply never reach the feed.
    feed_entry_for(ToolCall("t4", "not_a_tool", {}), SPECS.get, pending)
    assert feed_entry_for(ToolResult("t4", True, {"x": 1}), SPECS.get, pending) is None
    assert feed_entry_for(ToolResult("nobody", True, {"x": 1}), SPECS.get, pending) is None
    assert feed_entry_for(Usage(1, 1, 0.1), SPECS.get, pending) is None
    assert feed_entry_for(TurnEnd("done"), SPECS.get, pending) is None
    failed = feed_entry_for(DMError("the DM process exited with code 1", True), SPECS.get, pending)
    assert failed.kind == "dm_error" and failed.payload == {
        "message": "the DM process exited with code 1",
        "retryable": True,
        "resets_at": None,
    }


def test_hidden_rolls_and_encounter_checks_make_no_row(storage, campaign):
    """Review D-d: a roll the players mustn't know failed (`hidden`) and a wandering-monster check leave nothing in the
    story, for any seat; the same roll without `hidden` is a row, for the host and co-hosts."""
    pending = PendingCalls(campaign.id, "beat_000000000000")

    def row(id, tool, args, result):
        feed_entry_for(ToolCall(id, tool, args), SPECS.get, pending)
        return feed_entry_for(ToolResult(id, True, result), SPECS.get, pending)

    assert row("t1", "skill_check", {"character": "Pippa", "skill": "find traps", "hidden": True}, {}) is None
    assert row("t2", "roll", {"notation": "1d6", "purpose": "search", "hidden": True}, {"total": 1}) is None
    assert row("t3", "encounter_check", {"terrain": "dungeon"}, {"triggered": False}) is None
    shown = row("t4", "ability_check", {"character": "Pippa", "ability": "dex"}, {"success": True})
    assert shown.payload == {"name": "ability_check", "call_id": "t4"}


def test_planted_secret_not_in_story(storage, campaign, act, owner_seat):
    """Review Focus 3: a secret in a DM-only tool's input and result, a `dm_only` field, a DM-only key of the tool
    and an error's candidates never reaches the story."""
    beat = open_beat(storage, campaign.id, act("We search the vestry."))
    entries = _play(
        storage,
        campaign.id,
        beat.id,
        [
            TextDelta("You search."),
            ToolCall("t1", "dm_note", {"text": f"{SECRET} the ritualist hides here."}),
            ToolResult("t1", True, {"id": "note_1", "text": f"{SECRET} the ritualist hides here."}),
            ToolCall("t2", "room", {}),
            ToolResult("t2", True, {"perceived": {"label": "Vestry"}, "dm_only": {"notes": SECRET}}),
            ToolCall("t3", "get_character", {"ref": "Tira"}),
            ToolResult("t3", True, {"name": "Tira", "notes_md": f"{SECRET}: she is the cult."}),
            ToolCall("t4", "move_party", {"to": "Crypt"}),
            ToolResult("t4", False, {"error": "No room 'Crypt'.", "candidates": [{"id": "x", "label": SECRET}]}),
            ToolCall("t5", "skill_check", {"character": "Pippa", "skill": "find traps"}),
            ToolResult("t5", True, {"success": True, "dm_only": {"trap": SECRET}, "secret_exits": [SECRET]}),
            ToolCall("t6", "rules_lookup", {"query": f"{SECRET} wight level drain"}),
            ToolResult("t6", True, {"results": [{"snippet": "Energy drain…"}]}),
            ToolCall("t7", "setup_combat", {"enemies": [{"name": "Saint Vellis", "as": "wight"}]}),
            ToolResult("t7", True, {"enemies": [{"type": "Saint Vellis", "matched": "wight", "hp": 25}]}),
            TextDelta("Nothing."),
            TurnEnd("done"),
        ],
    )
    shown = json.dumps(
        [[e.kind, e.payload] for e in story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]]
    )
    assert SECRET not in shown
    shown = shown.replace(owner_seat.id, "<seat>")  # a random id may hold any digits
    assert "wight" not in shown and "25" not in shown  # a monster's numbers, and the DM's own words
    assert [e.kind for e in entries] == ["player_act", "dm_text", "tool", "tool", "tool", "tool", "tool", "dm_text"]
    assert [e.payload for e in entries[2:7]] == [
        {"name": "get_character"},
        {"name": "move_party", "failed": True},
        {"name": "skill_check"},
        {"name": "rules_lookup"},
        {"name": "setup_combat"},
    ]


def test_story_cleans_tool_rows_stored_before_the_allow_list(storage, campaign, act):
    """Rows stored by plateau 2b's first build carried inputs and results; the story serves them as the allow-list
    would have stored them."""
    beat = open_beat(storage, campaign.id, act("We open the iron door."))
    leaked = {"name": "setup_combat", "summary": "enemies=[2]", "result": {"enemies": [{"matched": "wight"}]}}
    add_entry(storage, campaign.id, beat.id, "tool", leaked)
    add_entry(storage, campaign.id, beat.id, "tool", {"name": "move_party", "error": "No room 'Hidden Crypt'."})
    rows = [
        e.payload
        for e in story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]
        if e.kind == "tool"
    ]
    assert rows == [{"name": "setup_combat"}, {"name": "move_party", "failed": True}]


def test_dm_log_keeps_raw_stream(storage, campaign, act):
    beat = open_beat(storage, campaign.id, act("Hello."))
    raw = [
        {"type": "stream_event", "event": {"delta": {"type": "thinking_delta", "thinking": f"{SECRET} hmm"}}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__delve__dm_secrets"}]}},
    ]
    for line in raw:
        log_dm_event(storage, campaign.id, beat.id, line)
    close_beat(storage, beat.id, "done")
    other = open_beat(storage, campaign.id, act("x"))
    log_dm_event(storage, campaign.id, other.id, {"type": "result"})
    assert [e.raw_event_json for e in dm_log(storage, campaign.id, beat.id)] == raw
    assert [e.beat_id for e in dm_log(storage, campaign.id)] == [beat.id, beat.id, other.id]
    assert all(e.campaign_id == campaign.id for e in dm_log(storage, campaign.id))
    # The DM log is not the story: nothing of it reaches the entries.
    assert SECRET not in json.dumps(
        [e.payload for e in story(storage, campaign.id, seats.owner_seat(storage, campaign.id))["entries"]]
    )


def test_a_batch_row_names_its_steps_for_the_tools_chip(storage, campaign):
    """A batch's row lists its steps, so the story counts and shows the calls, not the batch: each step's tool and
    whether it was refused. A step the table never sees (a DM-only tool, a hidden call) is left out."""
    pending = PendingCalls(campaign.id, "beat_000000000000")
    steps = [
        {"tool": "advance_time", "args": {"minutes": 10}},
        {"tool": "dm_secrets", "args": {}},
        {"tool": "roll", "args": {"notation": "1d6", "hidden": True}},
        {"tool": "move_party", "args": {"to": "Vestry"}},
        {"tool": "roll", "args": {"notation": "1d20"}},
    ]
    results = {
        "ran": 4,
        "requested": 5,
        "stopped_early": True,
        "results": [
            {"step": 0, "tool": "advance_time", "result": {"minutes": 10}},
            {"step": 1, "tool": "dm_secrets", "result": {"secrets": [SECRET]}},
            {"step": 2, "tool": "roll", "result": {"total": 4}},
            {"step": 3, "tool": "move_party", "result": {"error": "No room 'Vestry'."}},
        ],
    }
    feed_entry_for(ToolCall("t1", "batch", {"steps": steps}), SPECS.get, pending)
    entry = feed_entry_for(ToolResult("t1", True, results), SPECS.get, pending)
    assert entry.payload == {
        "name": "batch",
        "steps": [
            {"step": 0, "name": "advance_time"},
            {"step": 3, "name": "move_party", "failed": True},
            {"step": 4, "name": "roll", "failed": True},
        ],
        "call_id": "t1",
    }, "the last step never ran: it shows as refused"
    assert player_row(entry.payload) == {k: v for k, v in entry.payload.items() if k != "call_id"}
    assert SECRET not in json.dumps(player_row({**entry.payload, "steps": [{"step": 0, "name": "x", "args": SECRET}]}))


def test_a_tool_rows_call_is_found_by_its_id(storage, campaign, act, monkeypatch):
    """A tool row holds its call's id (DEL-172): the host's look at the call reads the beat's DM log for it, without
    replaying the log against the story; a row stored before that is still found by the replay."""
    from dataclasses import replace

    from delve.dm.fake import event_to_dict
    from delve.play.table import tool_call_of

    beat = open_beat(storage, campaign.id, act("We listen."))
    pending = PendingCalls(campaign.id, beat.id)
    events = [
        ToolCall("r1", "roll", {"notation": "1d20", "purpose": "listen"}),
        ToolCall("r2", "roll", {"notation": "1d6", "purpose": "damage"}),
        ToolResult("r2", True, {"total": 3}),
        ToolResult("r1", True, {"total": 12}),
    ]
    stored = [e for event in events for e in feed(storage, event, event_to_dict(event), SPECS.get, pending)]
    first, second = [e for e in stored if e.kind == "tool"]
    assert (first.payload["call_id"], second.payload["call_id"]) == ("r2", "r1")
    with monkeypatch.context() as patched:
        patched.setattr(storage.story, "list", lambda *a, **k: pytest.fail("the story was read"))
        assert tool_call_of(storage, SPECS.get, second) == {
            "name": "roll",
            "args": {"notation": "1d20", "purpose": "listen"},
            "ok": True,
            "result": {"total": 12},
        }
    old = storage.story.put(replace(first, payload={k: v for k, v in first.payload.items() if k != "call_id"}))
    assert tool_call_of(storage, SPECS.get, old)["args"] == {"notation": "1d6", "purpose": "damage"}
    gone = storage.story.put(replace(first, payload={**first.payload, "call_id": "nope"}))
    assert tool_call_of(storage, SPECS.get, gone) is None
