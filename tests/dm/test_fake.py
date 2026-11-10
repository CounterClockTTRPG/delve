import asyncio
import json

import pytest

from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM, event_to_dict
from delve.dm.provider import ConversationSpec, DMError, TextDelta, ToolCall, ToolResult, TurnEnd, Usage
from delve.domain.settings import BackendChoice, Effort, Job

SPEC = ConversationSpec(campaign_id="c1", system_prompt="You are the DM.", choice=BackendChoice("fake", "fake-large"))


async def collect(conversation, text):
    return [event async for event in conversation.send(text)]


def test_capabilities():
    caps = FakeDM([]).capabilities
    assert caps is FAKE_DM_CAPABILITIES
    assert caps.id == "fake"
    assert caps.jobs == frozenset({Job.DM, Job.SIDE, Job.TRANSLATION, Job.CONVERSION, Job.NOVEL})
    assert caps.models == ("fake-large", "fake-small")
    assert caps.efforts == tuple(Effort)


def test_send_replays_in_order_and_ends_once():
    script = [
        [TextDelta("The door "), TextDelta("creaks."), Usage(10, 4, None)],
        [ToolCall("t1", "roll", {"dice": "1d20"}), ToolResult("t1", True, 17), TurnEnd("done")],
    ]

    async def run():
        conversation = await FakeDM(script).open(SPEC)
        return await collect(conversation, "I open the door"), await collect(conversation, "I attack")

    first, second = asyncio.run(run())
    assert first == [TextDelta("The door "), TextDelta("creaks."), Usage(10, 4, None), TurnEnd("done")]
    assert second == script[1]
    for events in (first, second):
        assert sum(isinstance(event, TurnEnd) for event in events) == 1
        assert isinstance(events[-1], TurnEnd)


def test_exhausted_script_errors():
    async def run():
        conversation = await FakeDM([[TextDelta("Only this.")]]).open(SPEC)
        await collect(conversation, "one")
        return await collect(conversation, "two")

    assert asyncio.run(run()) == [DMError("script exhausted", False), TurnEnd("error")]


def test_cancel_ends_with_cancelled():
    script = [[TextDelta("a"), TextDelta("b"), TextDelta("c")], [TextDelta("next")]]

    async def run():
        conversation = await FakeDM(script).open(SPEC)
        events = []
        async for event in conversation.send("go"):
            events.append(event)
            if event == TextDelta("a"):
                await conversation.cancel()
        return events, await collect(conversation, "again")

    events, after = asyncio.run(run())
    assert events == [TextDelta("a"), TurnEnd("cancelled")]
    assert after == [TextDelta("next"), TurnEnd("done")]


def test_side_call_returns_answer():
    dm = FakeDM([], side_answers={"Translate: hello": "hallo"})
    choice = BackendChoice("fake", "fake-small")
    assert asyncio.run(dm.side_call("Translate: hello", choice)) == "hallo"


def test_side_handler_answers_and_every_side_prompt_is_recorded():
    dm = FakeDM([], side_answers={"Hi": "scripted"}, side_handler=lambda prompt: prompt.upper())
    choice = BackendChoice("fake", "fake-small")

    async def calls():
        return [await dm.side_call("Hi", choice), await dm.side_call("convert this", choice, timeout=600)]

    assert asyncio.run(calls()) == ["scripted", "CONVERT THIS"]
    assert dm.side_prompts == ["Hi", "convert this"]
    assert dm.side_timeouts == [None, 600]


def test_a_failing_side_handler_raises():
    def fail(prompt: str) -> str:
        raise RuntimeError("overloaded")

    dm = FakeDM([], side_handler=fail)
    with pytest.raises(RuntimeError, match="overloaded"):
        asyncio.run(dm.side_call("Hi", BackendChoice("fake")))


def test_from_json_roundtrip(tmp_path):
    script = [
        [TextDelta("Hi."), ToolCall("t1", "roll", {"dice": "2d6"}), ToolResult("t1", True, {"total": 7})],
        [Usage(100, 20, 0.01), DMError("overloaded", True), TurnEnd("error")],
    ]
    path = tmp_path / "script.json"
    path.write_text(json.dumps([[event_to_dict(event) for event in entry] for entry in script]))
    assert json.loads(path.read_text())[0][0] == {"type": "text", "text": "Hi."}

    async def run():
        conversation = await FakeDM.from_json(path).open(SPEC)
        return await collect(conversation, "one"), await collect(conversation, "two")

    first, second = asyncio.run(run())
    assert first == [*script[0], TurnEnd("done")]
    assert second == script[1]


def test_sent_records_inputs():
    dm = FakeDM([[TextDelta("x")], [TextDelta("y")]])

    async def run():
        conversation = await dm.open(SPEC)
        await collect(conversation, "first")
        await collect(conversation, "second")
        await conversation.close()

    asyncio.run(run())
    assert dm.sent == ["first", "second"]


def test_open_keeps_resume_id():
    async def run():
        dm = FakeDM([])
        return (await dm.open(SPEC)).id, (await dm.open(ConversationSpec("c1", "p", SPEC.choice, "abc"))).id

    fresh, resumed = asyncio.run(run())
    assert fresh and fresh != "abc"
    assert resumed == "abc"


def test_side_and_vision_calls_report_their_usage_when_given_one():
    usage = Usage(120, 30, 0.01)
    dm = FakeDM([], side_handler=lambda prompt: "ok", vision_handler=lambda *_: "seen", side_usage=usage)
    heard: list[Usage] = []
    choice = BackendChoice("fake", "fake-large")

    async def run():
        await dm.side_call("A question.", choice, on_usage=heard.append)
        await dm.vision_call("A look.", b"png", "image/png", choice, on_usage=heard.append)
        await dm.side_call("No one listens.", choice)

    asyncio.run(run())
    assert heard == [usage, usage]
    silent: list[Usage] = []
    asyncio.run(FakeDM([]).side_call("Nothing to report.", choice, on_usage=silent.append))
    assert silent == []
