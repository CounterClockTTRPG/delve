import pytest

from delve.dm.claude_cli.stream import SessionId, StreamState, parse_line
from delve.dm.provider import DMError, TextDelta, ToolCall, ToolResult, TurnEnd, Usage


def delta(kind: str, **fields) -> dict:
    return {"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": kind, **fields}}}


def assistant(*blocks) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


USAGE = {"input_tokens": 12, "output_tokens": 40, "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 300}


def test_parse_line_mapping():
    state = StreamState()
    lines = [
        {"type": "system", "subtype": "init", "session_id": "sess-1", "tools": []},
        {"type": "stream_event", "event": {"type": "message_start", "message": {}}},
        delta("thinking_delta", thinking="They might be lying."),
        assistant({"type": "thinking", "thinking": "They might be lying."}),
        delta("text_delta", text="The door "),
        delta("text_delta", text="creaks."),
        assistant({"type": "text", "text": "The door creaks."}),
        delta("input_json_delta", partial_json='{"room": "'),
        assistant({"type": "tool_use", "id": "toolu_1", "name": "mcp__delve__move_party", "input": {"room": "R2"}}),
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": [{"type": "text", "text": '{"ok": true}'}],
             "is_error": False},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_2", "content": "no such room", "is_error": True},
        ]}},
        {"type": "result", "subtype": "success", "is_error": False, "result": "The door creaks.",
         "total_cost_usd": 0.02, "usage": USAGE, "duration_ms": 900},
    ]  # fmt: skip
    events = [event for line in lines for event in parse_line(line, state)]
    assert events == [
        SessionId("sess-1"),
        TextDelta("The door "),
        TextDelta("creaks."),
        ToolCall("toolu_1", "move_party", {"room": "R2"}),
        ToolResult("toolu_1", True, {"ok": True}),
        ToolResult("toolu_2", False, "no such room"),
        Usage(9312, 40, 0.02),
        TurnEnd("done"),
    ]


def test_full_text_block_is_kept_without_deltas():
    state = StreamState()
    assert parse_line(assistant({"type": "text", "text": "Hello."}), state) == [TextDelta("Hello.")]
    # A new turn starts after a result: deltas of the earlier turn don't hide this one's text.
    parse_line(delta("text_delta", text="x"), state)
    parse_line({"type": "result", "is_error": False, "usage": USAGE}, state)
    assert parse_line(assistant({"type": "text", "text": "Again."}), state) == [TextDelta("Again.")]


MESSAGE_START = {"type": "stream_event", "event": {"type": "message_start", "message": {}}}


def _text(lines: list[dict]) -> str:
    state = StreamState()
    return "".join(e.text for line in lines for e in parse_line(line, state) if isinstance(e, TextDelta))


def test_text_after_a_tool_use_without_deltas_shows_once():
    """D3: a reply's second message, after a tool call, is a new message. Its full text block shows even when no deltas
    came for it, and the first message's text shows once."""
    lines = [
        MESSAGE_START,
        delta("text_delta", text="The door "),
        delta("text_delta", text="creaks."),
        assistant({"type": "text", "text": "The door creaks."}),
        assistant({"type": "tool_use", "id": "toolu_1", "name": "mcp__delve__roll", "input": {"notation": "1d6"}}),
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"total": 4}', "is_error": False},
        ]}},
        MESSAGE_START,
        assistant({"type": "text", "text": " A draught."}),
        {"type": "result", "is_error": False, "usage": USAGE},
    ]  # fmt: skip
    assert _text(lines) == "The door creaks. A draught."


def test_full_block_before_its_deltas_shows_once():
    lines = [
        MESSAGE_START,
        assistant({"type": "text", "text": "The door creaks."}),
        delta("text_delta", text="The door "),
        delta("text_delta", text="creaks."),
        {"type": "result", "is_error": False, "usage": USAGE},
    ]
    assert _text(lines) == "The door creaks."


def test_only_delve_prefix_is_stripped():
    [call] = parse_line(assistant({"type": "tool_use", "id": "t", "name": "mcp__other__read", "input": {}}))
    assert call == ToolCall("t", "mcp__other__read", {})


def test_error_result_is_a_dm_error():
    events = parse_line({"type": "result", "is_error": True, "subtype": "error_max_turns", "result": "", "usage": USAGE})
    assert events == [Usage(9312, 40, None), DMError("claude ended the reply with an error (error_max_turns)", False),
                      TurnEnd("error")]  # fmt: skip


def test_unknown_lines_are_ignored():
    assert parse_line({"type": "rate_limit_event"}) == []
    assert parse_line({"type": "system", "subtype": "status"}) == []


def test_usage_is_the_last_requests_context_not_the_replys_sum():
    # A reply with tool calls makes several API requests. `result`'s usage adds them all up (346k for a 43k context
    # in the 2026-10-18 live eval), which tripped the auto-reset after one beat; the context is the last request's.
    def request(context: int, *blocks) -> dict:
        usage = {"input_tokens": 2, "cache_creation_input_tokens": 100, "cache_read_input_tokens": context - 102}
        return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks), "usage": usage}}

    state = StreamState()
    parse_line(request(34666, {"type": "tool_use", "id": "t1", "name": "mcp__delve__room", "input": {}}), state)
    parse_line({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}]}},
               state)  # fmt: skip
    parse_line(request(43235, {"type": "text", "text": "The lock gives."}), state)
    summed = {"input_tokens": 20, "cache_creation_input_tokens": 9000, "cache_read_input_tokens": 337232, "output_tokens": 7}
    events = parse_line({"type": "result", "is_error": False, "usage": summed}, state)
    assert events[0] == Usage(43235, 7, None)
    # The next reply counts afresh: without per-request usage, the result's own figure is all there is.
    assert parse_line({"type": "result", "is_error": False, "usage": USAGE}, state)[0] == Usage(9312, 40, None)


def test_a_reply_costs_what_its_process_spent_on_it():
    """`total_cost_usd` adds up over a resident process's replies (P-e): a reply's cost is the rise since the last."""

    def result(total: float) -> dict:
        return {"type": "result", "is_error": False, "usage": USAGE, "total_cost_usd": total}

    state = StreamState()
    assert parse_line(result(0.10), state)[0].cost_usd == pytest.approx(0.10)
    assert parse_line(result(0.25), state)[0].cost_usd == pytest.approx(0.15)
    assert state.spent == pytest.approx(0.25)
    restarted = StreamState()
    assert parse_line(result(0.05), restarted)[0].cost_usd == pytest.approx(0.05), "a new process: the whole value"
    assert parse_line(result(0.04), StreamState(spent=0.25))[0].cost_usd == pytest.approx(0.04), "never below zero"


def test_a_usage_limit_is_a_pause_not_narration():
    # claude's answer once the account's limit is reached: the notice as a text block, then an error result that
    # says "success". The players saw it as the DM's narration, then "ended the reply with an error (success)".
    notice = "You've hit your session limit · resets 2:50pm (UTC)"
    state = StreamState(spent=12.5)
    events = parse_line({"type": "assistant", "message": {"content": [{"type": "text", "text": notice}]}}, state)
    assert events == [], "the notice is no narration"
    done = parse_line(
        {"type": "result", "subtype": "success", "is_error": True, "result": notice, "total_cost_usd": 0.85,
         "usage": {"input_tokens": 0, "output_tokens": 0}},
        state,
    )  # fmt: skip
    usage, error, end = done
    assert usage == Usage(0, 0, None), "a reply nobody answered costs nothing"
    assert error == DMError("The DM is paused: Claude's usage limit is reached. It resets 2:50pm (UTC).", True)
    assert end == TurnEnd("error")


def test_an_error_result_says_its_own_text():
    state = StreamState()
    _, error, _ = parse_line(
        {"type": "result", "subtype": "success", "is_error": True, "result": "API Error: 529 overloaded"}, state
    )
    assert error == DMError("claude ended the reply with an error: API Error: 529 overloaded", False)


def test_narration_about_a_limit_is_narration():
    state = StreamState()
    line = "The guard sighs: you've hit your limit of questions for today."
    events = parse_line({"type": "assistant", "message": {"content": [{"type": "text", "text": line}]}}, state)
    assert events == [TextDelta(line)]
