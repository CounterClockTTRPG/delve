"""The DM's trace, beat by beat: ordered tool calls and narrated text.

Parsed from the stream-json lines `claude -p --output-format stream-json` emits (what `delve.dm.claude_cli` reads),
with two eval-only marker lines, named as in ttrpg2's fixtures so its recordings parse too:

    {"type": "eval_meta", "case": "locked_door", ...}      first line, optional
    {"type": "eval_turn", "index": 0, "player": "..."}     opens each beat

Without eval_turn markers a `result` event closes a beat instead, so a raw recording of one `claude -p` call parses
too. A Claude Code session JSONL (~/.claude/projects/…) has the same assistant/user records and also parses; its
string-content user records open the beats. Other records (`eval_turn_end`, `system`, `stream_event`) are skipped.

Hand-written fixtures only need the records the parser reads:

    {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "..."},
        {"type": "tool_use", "id": "t1", "name": "mcp__delve__roll", "input": {"notation": "1d20"}}]}}
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "{...}"}]}}
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

MCP_PREFIX = "mcp__delve__"


@dataclass
class ToolCall:
    name: str
    """Without the mcp__delve__ prefix."""
    args: dict
    id: str = ""
    raw_name: str = ""
    """The name as the DM called it; empty means one of Delve's tools."""
    result: object = None
    """The parsed JSON when the result is JSON, else its text."""
    is_error: bool = False

    def names(self) -> list[str]:
        """This call's tool name, plus the steps of a `batch`, in order."""
        return [self.name] + ([name for name, _ in self.steps()] if self.name == "batch" else [])

    def steps(self) -> list[tuple[str, dict]]:
        """(name, args) for this call, or for each step of a `batch`."""
        if self.name != "batch":
            return [(self.name, self.args)]
        return [
            (str(step.get("tool", "")).removeprefix(MCP_PREFIX), step.get("args") or {})
            for step in self.args.get("steps") or []
            if isinstance(step, dict)
        ]

    @property
    def is_delves(self) -> bool:
        """Whether the DM called one of Delve's tools, through the bridge."""
        return not self.raw_name or self.raw_name.startswith(MCP_PREFIX)


@dataclass
class Text:
    text: str


@dataclass
class Beat:
    player: str = ""
    events: list = field(default_factory=list)
    """ToolCall | Text, in order."""

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [e for e in self.events if isinstance(e, ToolCall)]

    @property
    def narration(self) -> str:
        return "\n\n".join(e.text for e in self.events if isinstance(e, Text))

    def text_before(self, index: int) -> str:
        """Narration emitted before event `index`."""
        return "\n\n".join(e.text for e in self.events[:index] if isinstance(e, Text))

    def first_index(self, names: Iterable[str]) -> int | None:
        """Index of the first call to any of `names` (batch steps count)."""
        wanted = set(names)
        for i, e in enumerate(self.events):
            if isinstance(e, ToolCall) and wanted.intersection(e.names()):
                return i
        return None


@dataclass
class Trace:
    beats: list[Beat] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [c for b in self.beats for c in b.tool_calls]


def _result_value(content):
    """A tool_result's content as JSON when it parses, else as text."""
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return content
    return content


def parse_events(records: Iterable[dict]) -> Trace:
    trace = Trace()
    beat: Beat | None = None
    calls: dict[str, ToolCall] = {}
    seen_text: set = set()
    split_on_result = True

    def current() -> Beat:
        nonlocal beat
        if beat is None:
            beat = Beat()
            trace.beats.append(beat)
        return beat

    for rec in records:
        kind = rec.get("type")
        if kind == "eval_meta":
            trace.meta = {k: v for k, v in rec.items() if k != "type"}
        elif kind == "eval_turn":
            split_on_result = False
            beat = Beat(player=rec.get("player", ""))
            trace.beats.append(beat)
        elif kind == "result":
            if split_on_result:
                beat = None
        elif kind == "assistant":
            msg = rec.get("message") or {}
            for n, block in enumerate(msg.get("content") or []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    # Partial-message streams can repeat a block; keep one.
                    key = (msg.get("id"), n, text)
                    if text and (msg.get("id") is None or key not in seen_text):
                        seen_text.add(key)
                        current().events.append(Text(text))
                elif block.get("type") == "tool_use":
                    tid = block.get("id") or ""
                    if tid and tid in calls:
                        continue
                    raw = block.get("name") or ""
                    call = ToolCall(
                        name=raw.removeprefix(MCP_PREFIX), args=block.get("input") or {}, id=tid, raw_name=raw
                    )
                    calls[tid] = call
                    current().events.append(call)
        elif kind == "user":
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, str):
                # Session-JSONL player message (stream-json doesn't echo them).
                if split_on_result and not rec.get("isMeta"):
                    beat = Beat(player=content)
                    trace.beats.append(beat)
                continue
            for block in content or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    call = calls.get(block.get("tool_use_id") or "")
                    if call is not None:
                        call.result = _result_value(block.get("content"))
                        call.is_error = bool(block.get("is_error"))
    return trace


def read_records(path: str | Path) -> list[dict]:
    """A fixture's records; blank lines and lines starting with `//` are skipped."""
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            records.append(json.loads(line))
    return records


def load_trace(path: str | Path) -> Trace:
    return parse_events(read_records(path))
