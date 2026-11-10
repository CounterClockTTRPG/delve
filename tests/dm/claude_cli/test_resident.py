import asyncio
import time

from delve.dm.provider import ConversationSpec, DMError, TextDelta, ToolCall, ToolResult, TurnEnd
from delve.domain.settings import BackendChoice, Effort


def spec(effort=Effort.LOW, campaign_id="cmp_1") -> ConversationSpec:
    return ConversationSpec(campaign_id, "You are the DM.", BackendChoice("claude-cli", "default", effort))


async def collect(conversation, text):
    return [event async for event in conversation.send(text)]


def text_of(events) -> str:
    return "".join(event.text for event in events if isinstance(event, TextDelta))


def run(provider, scenario):
    async def main():
        try:
            return await scenario()
        finally:
            await provider.close()

    return asyncio.run(main())


def test_resident_turn_and_respawn_on_signature_change(provider, claude, data_dir, sessions):
    claude.script([[{"text": "The door creaks."}], [{"text": "A cold draft."}], [{"text": "Bats!"}]])

    async def scenario():
        conversation = await provider.open(spec())
        first = await collect(conversation, "I open the door.")
        second = await collect(conversation, "I step in.")
        sid = conversation.id
        # A different effort changes the argv: the resident is replaced, and resumes the same conversation.
        third = await collect(await provider.open(spec(Effort.HIGH)), "I run.")
        return first, second, third, sid

    first, second, third, sid = run(provider, scenario)
    assert text_of(first) == "The door creaks."
    assert text_of(second) == "A cold draft."
    assert text_of(third) == "Bats!"
    for events in (first, second, third):
        assert events[-1] == TurnEnd("done")
        assert sum(isinstance(event, TurnEnd) for event in events) == 1

    spawns = claude.spawns()
    assert len(spawns) == 2, "one process for the first two beats, a new one when the effort changed"
    assert spawns[0]["cwd"] == str(data_dir / "dm" / "cmp_1")
    assert "--resume" not in spawns[0]["argv"]
    assert spawns[1]["argv"][spawns[1]["argv"].index("--resume") + 1] == sid
    assert spawns[1]["argv"][spawns[1]["argv"].index("--effort") + 1] == "high"
    assert sid.startswith("fake-")
    assert sessions.get("cmp_1")["session_id"] == sid
    assert [entry["text"] for entry in claude.inputs()] == ["I open the door.", "I step in.", "I run."]


def test_tool_calls_reach_the_mcp_server(provider, claude):
    claude.script([[{"text": "Rolling."}, {"tool": "echo", "args": {"dice": "1d20"}}, {"tool": "fail", "args": {}}]])

    async def scenario():
        return await collect(await provider.open(spec()), "I attack.")

    events = run(provider, scenario)
    calls = [event for event in events if isinstance(event, ToolCall)]
    results = [event for event in events if isinstance(event, ToolResult)]
    assert [(call.name, call.args) for call in calls] == [("echo", {"dice": "1d20"}), ("fail", {})]
    assert results[0] == ToolResult(calls[0].id, True, {"echo": {"dice": "1d20"}})
    assert results[1].ok is False
    assert claude.mcp_calls() == [
        {"name": "echo", "args": {"dice": "1d20"}, "secret": "s3cret"},
        {"name": "fail", "args": {}, "secret": "s3cret"},
    ]


def test_crash_and_hang_end_beat_with_error(provider, claude, monkeypatch):
    # A turn may take 1 s only for the hang: the crash and the restarts start a process, which a loaded machine
    # (parallel CI) can take longer than that to do (DEL-235). The timeout is read at each turn.
    monkeypatch.setenv("DELVE_DM_TURN_TIMEOUT", "30")
    claude.script([
        [{"text": "The floor "}, {"stderr": "warning: something odd"}, {"crash": 3}],
        [{"text": "Back again."}],
        [{"text": "Hmm"}, {"hang": True}],
        [{"text": "Awake."}],
    ])  # fmt: skip

    async def scenario():
        conversation = await provider.open(spec())
        crashed = await collect(conversation, "I step on the tile.")
        after_crash = await collect(conversation, "I get up.")
        monkeypatch.setenv("DELVE_DM_TURN_TIMEOUT", "1")
        started = time.monotonic()
        hung = await collect(conversation, "I wait.")
        waited = time.monotonic() - started
        monkeypatch.setenv("DELVE_DM_TURN_TIMEOUT", "30")
        after_hang = await collect(conversation, "Hello?")
        return crashed, after_crash, hung, waited, after_hang

    crashed, after_crash, hung, waited, after_hang = run(provider, scenario)

    [error] = [event for event in crashed if isinstance(event, DMError)]
    assert error.message == "claude stopped (exit code 3)"
    assert error.retryable is True
    assert "warning: something odd" in error.detail and "crashing with code 3" in error.detail
    assert crashed[-2:] == [error, TurnEnd("error")]
    assert text_of(after_crash) == "Back again."

    [error] = [event for event in hung if isinstance(event, DMError)]
    assert error.message == "no answer within 1 s"
    assert hung[-1] == TurnEnd("error")
    assert waited < 5
    assert text_of(after_hang) == "Awake."

    spawns = claude.spawns()
    assert len(spawns) == 3, "a fresh resident after the crash and after the hang"
    # The fresh residents resume the conversation the crashed one had started.
    assert all("--resume" in spawn["argv"] for spawn in spawns[1:])


def test_cancel_drains(provider, claude):
    claude.script([
        [{"text": "You lunge"}, {"sleep": 0.4}, {"tool": "echo", "args": {"late": True}}, {"text": " and miss."}],
        [{"text": "Next beat."}],
    ])  # fmt: skip

    async def scenario():
        conversation = await provider.open(spec())
        cancelled = []
        async for event in conversation.send("I attack."):
            cancelled.append(event)
            if isinstance(event, TextDelta):
                await conversation.cancel()
        # The cancelled reply is drained to its result first, so this beat gets its own answer.
        return cancelled, await collect(conversation, "I step back.")

    cancelled, after = run(provider, scenario)
    assert cancelled[-1] == TurnEnd("cancelled")
    assert sum(isinstance(event, TurnEnd) for event in cancelled) == 1
    assert not any(isinstance(event, ToolCall) for event in cancelled)
    assert text_of(after) == "Next beat."
    assert claude.mcp_calls()[0]["args"] == {"late": True}, "the cancelled reply ran to its end"
    assert len(claude.spawns()) == 1


def test_one_turn_at_a_time_per_campaign(provider, claude):
    claude.script([[{"text": "One"}, {"sleep": 0.3}, {"text": " done."}], [{"text": "Two."}]])

    async def scenario():
        first = await provider.open(spec())
        second = await provider.open(spec())
        return await asyncio.gather(collect(first, "A"), collect(second, "B"))

    one, two = run(provider, scenario)
    assert text_of(one) == "One done."
    assert text_of(two) == "Two."
    assert [entry["text"] for entry in claude.inputs()] == ["A", "B"]
