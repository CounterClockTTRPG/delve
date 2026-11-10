#!/usr/bin/env python3
"""A fake `claude` for tests: it replays a script as stream-json and calls the MCP server it is given for real.

Tests never run the real `claude`. They put this file on `PATH` as `claude` with `install(bin_dir)`, which writes a
small wrapper that runs it with the test's Python (the one that has the `mcp` SDK).

**The script** is named by `FAKE_CLAUDE_SCRIPT`: a path to a JSON file, or the JSON itself. It is either a list of
turns, or `{"turns": [...], "side": ["answer", ...]}`. Turns are taken in order across every process that reads the
same script, so a respawned resident goes on with the next turn; the position is kept in `<script>.cursor` (or in
`FAKE_CLAUDE_CURSOR`). The object may also hold `"translations": {"<words>": "<English>", ...}` (see side calls). A turn
is a list of steps, or an object (`"vision": [...]` holds the vision calls' answers):

    {"steps": [...], "usage": {"input_tokens": 300000, ...}, "is_error": false, "result": "…", "cost": 0.01}

Steps:
- `{"text": "…"}`: the DM's text, as `text_delta`s and then once more as the full `assistant` block, as `claude` does;
- `{"thinking": "…"}`: a thinking block, which the provider must drop;
- `{"tool": "name", "args": {…}}`: a `tool_use` named `mcp__<server>__name` (with partial `input_json_delta`s), then
  a real `call_tool` on the server of `--mcp-config` over stdio, then its `tool_result`. With `"result": …` the
  server isn't called and that result is printed instead (`"is_error": true` marks it an error);
- `{"sleep": seconds}`, `{"stderr": "…"}`;
- `{"crash": code}`: write to stderr and exit with that code, before the turn's `result`;
- `{"hang": true}`: stop answering, without exiting.

When the script runs out, a turn answers "(fake claude: script exhausted)".

**Side calls** (`-p` without `--input-format stream-json`) read the prompt from stdin, to its end, as `claude -p` does
without a prompt argument, and print the next `side` answer as plain text, or `(fake answer)` when there is none.
With `--output-format json` (a side call that wants its usage), the answer is one `result` object instead, its
`total_cost_usd` the script's `side_cost` (0 by default).
A translation's side call (`delve.play.translate`: its first line is `Translate the text below from <name> (<code>)
into <name> (<code>).`, and its text follows a line `THE TEXT:`) is answered by its prompt instead, and takes no `side`
answer: into English from the script's `translations` (the text as it is when it isn't there), and into another
language as `<CODE>: <text>`, such as `NL: The hall is dark.`.

**Vision calls** (`--input-format stream-json` without `--mcp-config`, as `vision_argv` builds them) read the one
stream-json message on stdin, which must hold an image block, and answer the next `vision` item, or `(fake vision
answer)` when there is none, as an `assistant` line and a `result` line. They take no `side` answer.

**Answers by prompt:** the object's `"prompts": [{"has": ["<words>", ...], "answer": "…"}, ...]` answer a side or a
vision call by its prompt instead, the first rule whose every `has` is in the prompt, and take no `side` or `vision`
item: a conversion's calls run at once, so their order isn't fixed (the classify, entities, dedupe, gaps and
draw-from-page calls of `tests/e2e/test_a_faithful_book.py`).

**Logs**, for assertions: `FAKE_CLAUDE_ARGV_LOG` gets one JSON line per process, `{"argv", "cwd", "pid", "tmpdir"}` (its
`CLAUDE_CODE_TMPDIR`), and
`FAKE_CLAUDE_INPUT_LOG` one line per message received, `{"pid", "text"}`, and `FAKE_CLAUDE_VISION_LOG` one line per
vision call, `{"prompt", "media_type", "size"}` (the picture's size in bytes).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import fcntl
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

FAKE_CLAUDE = Path(__file__).resolve()
TRANSLATE = re.compile(r"Translate the text below from .+ \((?P<source>[\w-]+)\) into .+ \((?P<target>[\w-]+)\)\.")
THE_TEXT = "\nTHE TEXT:\n"


def install(bin_dir: Path) -> Path:
    """Write `bin_dir/claude`, which runs this fake with the current Python. Put `bin_dir` first on `PATH`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "claude"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def _log(env_name: str, record: dict[str, Any]) -> None:
    path = os.environ.get(env_name)
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def _flag(argv: list[str], name: str) -> str | None:
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return None


def _load_script() -> tuple[list[Any], list[str], dict[str, str], list[str], Path | None, float, list[dict[str, Any]]]:
    raw = os.environ.get("FAKE_CLAUDE_SCRIPT", "[]")
    path = None
    if not raw.lstrip().startswith(("[", "{")):
        path = Path(raw)
        raw = path.read_text(encoding="utf-8")
    script = json.loads(raw)
    if isinstance(script, list):
        return script, [], {}, [], path, 0.0, []
    return (
        list(script.get("turns", [])),
        list(script.get("side", [])),
        dict(script.get("translations", {})),
        list(script.get("vision", [])),
        path,
        float(script.get("side_cost", 0.0)),
        list(script.get("prompts", [])),
    )


def _by_prompt(prompt: str, rules: list[dict[str, Any]]) -> str | None:
    """The answer of the first rule whose every `has` is in `prompt`; None when no rule has it."""
    return next((rule["answer"] for rule in rules if all(words in prompt for words in rule["has"])), None)


def _translation(prompt: str, translations: dict[str, str]) -> str | None:
    """The answer to a translation's side call, by its prompt; None for any other prompt."""
    asked = TRANSLATE.match(prompt)
    if asked is None or THE_TEXT not in prompt:
        return None
    text = prompt.split(THE_TEXT, 1)[1]
    if asked["target"].split("-")[0].lower() == "en":
        return translations.get(text, text)
    return f"{asked['target'].upper()}: {text}"


def _take(kind: str, items: list[Any], script_path: Path | None) -> Any | None:
    """The next item of `kind` ("turns", "side" or "vision"), counted in the cursor file shared by every fake process."""
    cursor_name = os.environ.get("FAKE_CLAUDE_CURSOR")
    if cursor_name:
        cursor = Path(cursor_name)
    elif script_path is not None:
        cursor = script_path.with_name(script_path.name + ".cursor")
    else:
        cursor = None
    if cursor is None:
        return items.pop(0) if items else None
    with open(cursor, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        counts = json.loads(fh.read() or "{}")
        index = counts.get(kind, 0)
        counts[kind] = index + 1
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(counts))
    return items[index] if index < len(items) else None


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


class _Tools:
    """The MCP server of `--mcp-config`, started on the first tool call and kept for the life of the process."""

    def __init__(self, argv: list[str]) -> None:
        self.server_name, self.params = self._server(argv)
        self._stack = contextlib.AsyncExitStack()
        self._session = None

    @staticmethod
    def _server(argv: list[str]):
        raw = _flag(argv, "--mcp-config")
        if not raw:
            return "delve", None
        text = raw if raw.lstrip().startswith("{") else Path(raw).read_text(encoding="utf-8")
        servers = json.loads(text).get("mcpServers", {})
        if not servers:
            return "delve", None
        name, server = next(iter(servers.items()))
        from mcp.client.stdio import StdioServerParameters

        env = {**os.environ, **server.get("env", {})}
        return name, StdioServerParameters(command=server["command"], args=server.get("args", []), env=env)

    async def call(self, name: str, args: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        if self.params is None:
            return [{"type": "text", "text": json.dumps({"error": "fake claude: no MCP server configured"})}], True
        if self._session is None:
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client

            read, write = await self._stack.enter_async_context(stdio_client(self.params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
        result = await self._session.call_tool(name, args)
        content = [{"type": "text", "text": item.text} for item in result.content if item.type == "text"]
        return content, bool(result.isError)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._stack.aclose()


async def _play_turn(turn: Any, session_id: str, tools: _Tools) -> None:
    if turn is None:
        turn = {"steps": [{"text": "(fake claude: script exhausted)"}]}
    if isinstance(turn, list):
        turn = {"steps": turn}
    _emit({"type": "system", "subtype": "init", "session_id": session_id, "model": "fake", "tools": []})
    texts: list[str] = []
    for number, step in enumerate(turn.get("steps", [])):
        if "text" in step:
            text = step["text"]
            texts.append(text)
            _emit(
                {
                    "type": "stream_event",
                    "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                }
            )
            for start in range(0, len(text), 8):
                _emit(
                    {
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": text[start : start + 8]},
                        },
                    }
                )
            _emit(
                {
                    "type": "assistant",
                    "session_id": session_id,
                    "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
                }
            )
        elif "thinking" in step:
            _emit(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "thinking_delta", "thinking": step["thinking"]},
                    },
                }
            )
            _emit(
                {
                    "type": "assistant",
                    "session_id": session_id,
                    "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": step["thinking"]}]},
                }
            )
        elif "tool" in step:
            use_id = f"toolu_{number:02d}{uuid.uuid4().hex[:10]}"
            args = step.get("args", {})
            name = f"mcp__{tools.server_name}__{step['tool']}"
            _emit(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_start",
                        "index": 1,
                        "content_block": {"type": "tool_use", "id": use_id, "name": name, "input": {}},
                    },
                }
            )
            _emit(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "index": 1,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(args)[:12]},
                    },
                }
            )
            _emit(
                {
                    "type": "assistant",
                    "session_id": session_id,
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": use_id, "name": name, "input": args}],
                    },
                }
            )
            if "result" in step:
                result = step["result"]
                content = [{"type": "text", "text": result if isinstance(result, str) else json.dumps(result)}]
                is_error = bool(step.get("is_error", False))
            else:
                content, is_error = await tools.call(step["tool"], args)
            _emit(
                {
                    "type": "user",
                    "session_id": session_id,
                    "message": {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": use_id, "content": content, "is_error": is_error}
                        ],
                    },
                }
            )
        elif "sleep" in step:
            await asyncio.sleep(float(step["sleep"]))
        elif "stderr" in step:
            sys.stderr.write(step["stderr"] + "\n")
            sys.stderr.flush()
        elif "crash" in step:
            sys.stderr.write(f"fake claude: crashing with code {step['crash']}\n")
            sys.stderr.flush()
            os._exit(int(step["crash"]))
        elif step.get("hang"):
            await asyncio.Event().wait()
    usage = {
        "input_tokens": 1200,
        "output_tokens": 80,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        **turn.get("usage", {}),
    }
    is_error = bool(turn.get("is_error", False))
    _emit(
        {
            "type": "result",
            "subtype": "error_during_execution" if is_error else "success",
            "is_error": is_error,
            "result": turn.get("result", "".join(texts)),
            "session_id": session_id,
            "total_cost_usd": turn.get("cost", 0.0),
            "duration_ms": 10,
            "usage": usage,
        }
    )


async def _resident(argv: list[str], turns: list[Any], script_path: Path | None) -> int:
    session_id = _flag(argv, "--resume") or f"fake-{uuid.uuid4().hex[:12]}"
    tools = _Tools(argv)
    loop = asyncio.get_running_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                return 0
            if not line.strip():
                continue
            message = json.loads(line)
            text = "".join(block.get("text", "") for block in message["message"]["content"])
            _log("FAKE_CLAUDE_INPUT_LOG", {"pid": os.getpid(), "text": text})
            await _play_turn(_take("turns", turns, script_path), session_id, tools)
    finally:
        await tools.close()


def _vision(vision: list[str], script_path: Path | None, rules: list[dict[str, Any]]) -> int:
    """One vision call: the stream-json message with its picture, answered by its prompt (`rules`), else with the next
    `vision` item."""
    message = json.loads(sys.stdin.buffer.read().decode("utf-8").strip().splitlines()[0])
    content = message["message"]["content"]
    [image] = [block for block in content if block.get("type") == "image"]
    assert image["source"]["type"] == "base64", "a vision call sends its picture as base64"
    prompt = "".join(block.get("text", "") for block in content if block.get("type") == "text")
    size = len(base64.b64decode(image["source"]["data"]))
    _log("FAKE_CLAUDE_VISION_LOG", {"prompt": prompt, "media_type": image["source"]["media_type"], "size": size})
    answer = _by_prompt(prompt, rules)
    if answer is None:
        answer = _take("vision", vision, script_path)
    answer = answer if answer is not None else "(fake vision answer)"
    session_id = f"fake-{uuid.uuid4().hex[:12]}"
    _emit({"type": "system", "subtype": "init", "session_id": session_id, "model": "fake", "tools": []})
    _emit(
        {
            "type": "assistant",
            "session_id": session_id,
            "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]},
        }
    )
    _emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": answer,
            "session_id": session_id,
            "total_cost_usd": 0.0,
            "duration_ms": 10,
            "usage": {"input_tokens": 1600, "output_tokens": 20},
        }
    )
    return 0


def main(argv: list[str]) -> int:
    _log("FAKE_CLAUDE_ARGV_LOG", {"argv": argv, "cwd": os.getcwd(), "pid": os.getpid(),
                                  "tmpdir": os.environ.get("CLAUDE_CODE_TMPDIR")})
    # As the real CLI does, a folder for the working directory under its config's `projects`, when a test says where.
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    if config:
        folder = Path(config) / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.getcwd()))
        (folder / "memory").mkdir(parents=True, exist_ok=True)
    turns, side, translations, vision, script_path, side_cost, rules = _load_script()
    if _flag(argv, "--input-format") == "stream-json":
        if "--mcp-config" not in argv:
            return _vision(vision, script_path, rules)
        return asyncio.run(_resident(argv, turns, script_path))
    prompt = sys.stdin.buffer.read().decode("utf-8")
    _log("FAKE_CLAUDE_INPUT_LOG", {"pid": os.getpid(), "text": prompt})
    answer = _translation(prompt, translations)
    if answer is None:
        answer = _by_prompt(prompt, rules)
    if answer is None:
        answer = _take("side", side, script_path)
    answer = answer if answer is not None else "(fake answer)"
    if _flag(argv, "--output-format") == "json":
        _emit({"type": "result", "subtype": "success", "is_error": False, "result": answer, "duration_ms": 10,
               "total_cost_usd": side_cost, "usage": {"input_tokens": 1200, "output_tokens": 40}})  # fmt: skip
        return 0
    sys.stdout.write(answer + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
