"""`claude`'s stream-json, line by line, as Delve's `DMEvent`s (the mapping table of the ttrpg2 DM-driver survey)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from delve.dm.claude_cli import account
from delve.dm.provider import DMError, DMEvent, TextDelta, ToolCall, ToolResult, TurnEnd, Usage

TOOL_PREFIX = "mcp__delve__"

# The notice `claude` answers with once the account's usage limit is reached ("You've hit your session limit · resets
# 2:50pm (UTC)"): a text block, then an error result. It is no narration: the beat pauses, and can be tried again.
USAGE_LIMIT = re.compile(r"you've hit your (?:session|usage|weekly|5-hour|opus) limit", re.IGNORECASE)
RESETS = re.compile(r"resets\s+(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class SessionId:
    """The conversation id `claude` reports at the start of a reply; `--resume` takes it."""

    id: str


@dataclass
class StreamState:
    """What one reply has shown so far. `claude` streams text as deltas and then sends it again as a full block,
    so the full block is dropped once deltas were seen, and deltas after a full block that showed are dropped too
    (`blocks_shown`). Both are per message: a reply with tool calls is several messages, each opened by its
    `message_start`, so a later message's text shows whether its deltas came or not (D3). `context` is the last
    request's context: a reply with tool calls makes several requests, and `result`'s usage adds them all up. A
    `result` starts the next reply afresh.

    `spent` is what the process had spent before this reply: `result`'s `total_cost_usd` adds up over a resident
    process's replies, so a reply's own cost is the rise since then (faithful modules G2), and `spent` moves on to the
    total. A new process starts from 0."""

    deltas_seen: bool = False
    blocks_shown: bool = False
    context: int | None = None
    spent: float = 0.0
    limit: str | None = None
    """The usage-limit notice this reply gave as text (`USAGE_LIMIT`), held back from the story."""


def parse_line(obj: dict[str, Any], state: StreamState | None = None) -> list[DMEvent | SessionId]:
    """The events in one parsed stream-json line. Thinking, partial tool input and unknown lines give nothing."""
    state = state if state is not None else StreamState()
    kind = obj.get("type")
    if kind == "system":
        session_id = obj.get("session_id")
        return [SessionId(session_id)] if obj.get("subtype") == "init" and isinstance(session_id, str) else []
    if kind == "stream_event":
        event = obj.get("event") or {}
        delta = event.get("delta") or {}
        if event.get("type") == "message_start":
            state.deltas_seen = state.blocks_shown = False
        elif event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            state.deltas_seen = True
            if USAGE_LIMIT.search(delta.get("text", "")):
                state.limit = delta["text"]
                return []
            return [] if state.blocks_shown else [TextDelta(delta.get("text", ""))]
        return []
    if kind == "assistant":
        usage = (obj.get("message") or {}).get("usage")
        if isinstance(usage, dict):
            state.context = context_tokens(usage)
        return _assistant(_content(obj), state)
    if kind == "user":
        return [_tool_result(block) for block in _content(obj) if block.get("type") == "tool_result"]
    if kind == "rate_limit_event":
        account.note(obj)
        return []
    if kind == "result":
        context, state.deltas_seen, state.blocks_shown, state.context = state.context, False, False, None
        return _result(obj, context, state)
    return []


def _content(obj: dict[str, Any]) -> list[dict[str, Any]]:
    content = (obj.get("message") or {}).get("content")
    return [block for block in content if isinstance(block, dict)] if isinstance(content, list) else []


def _assistant(blocks: list[dict[str, Any]], state: StreamState) -> list[DMEvent | SessionId]:
    events: list[DMEvent | SessionId] = []
    for block in blocks:
        if block.get("type") == "text" and USAGE_LIMIT.search(block.get("text") or ""):
            state.limit = block["text"]
        elif block.get("type") == "text" and not state.deltas_seen and block.get("text"):
            state.blocks_shown = True
            events.append(TextDelta(block["text"]))
        elif block.get("type") == "tool_use":
            name = str(block.get("name", ""))
            name = name.removeprefix(TOOL_PREFIX)
            events.append(ToolCall(str(block.get("id", "")), name, dict(block.get("input") or {})))
    return events


def _tool_result(block: dict[str, Any]) -> ToolResult:
    """A tool's answer: the bridge's JSON when it is JSON, else the text as it is."""
    content = block.get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            pass
    return ToolResult(str(block.get("tool_use_id", "")), not block.get("is_error", False), content)


def context_tokens(usage: dict[str, Any]) -> int:
    """The context the model saw: fresh input, cache writes and cache reads (ttrpg2 `_session_context_tokens`)."""
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return sum(int(usage.get(key) or 0) for key in keys)


def _result(obj: dict[str, Any], context: int | None, state: StreamState) -> list[DMEvent | SessionId]:
    usage = obj.get("usage") or {}
    total = obj.get("total_cost_usd")
    said = str(obj.get("result") or "").strip()
    limit, state.limit = state.limit or (said if USAGE_LIMIT.search(said) else None), None
    cost = None
    if isinstance(total, int | float) and limit is None:  # a reply the limit refused answered nothing: no cost
        # A total below what was spent is a process that started afresh: its whole total is this reply's.
        cost = float(total) - state.spent if total >= state.spent else float(total)
        state.spent = float(total)
    events: list[DMEvent | SessionId] = [
        Usage(context_tokens(usage) if context is None else context, int(usage.get("output_tokens") or 0), cost)
    ]
    if limit is not None:
        resets = RESETS.search(limit)
        when = f" It resets {resets.group(1).rstrip('.')}." if resets else ""
        paused = DMError(f"The DM is paused: Claude's usage limit is reached.{when}", True, resets_at=account.limit_resets_at())
        events += [paused, TurnEnd("error")]
    elif obj.get("is_error"):
        # An error result's subtype can say "success": its own text says what went wrong.
        why = f": {said}" if said else f" ({obj.get('subtype', 'error')})"
        events += [DMError(f"claude ended the reply with an error{why}", False), TurnEnd("error")]
    else:
        events.append(TurnEnd("done"))
    return events
