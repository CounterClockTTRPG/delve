"""One agent session of a thorough conversion (thorough conversion Task 2): a `claude -p` with file tools, confined to
its job folder by the CLI's own permission rules.

- **Tools:** Read, Write, Edit, Glob, Grep and Bash (`--tools`), and nothing else: no MCP server
  (`--strict-mcp-config` with no `--mcp-config`), no WebFetch or WebSearch, no slash commands, no user, project or
  local settings (`--setting-sources ""`), and no transcript kept in the owner's `~/.claude`
  (`--no-session-persistence`): the job's work is in its folder only.
- **Permissions** (`agent_settings`, given with `--settings`, in `dontAsk` mode, so whatever no rule allows is refused):
  Read, Write and Edit are allowed in the folder (`./**`, the agent's working directory); Glob and Grep have no allow
  of their own and go by the Read rules (review finding 6). Bash runs only the `qa` wrapper, by its absolute path
  (Delve's tools, which check every path they get): it is outside the folder and Edit is denied on its directory, so
  no agent can rewrite it into another command (review finding 1). Read and Edit are denied on the data directory
  (its database files and token by pattern too), the repository, the home directory, `/proc` and `/etc`; Edit also on
  the files Delve keeps in the folder for itself (`records`, review finding 8). A deny rule beats every allow rule, so
  where the folder lies inside one of those, what is denied is everything beside the path down to it: each entry next
  to each directory on the way. Read rules also hold for Glob and Grep, and Edit rules for Write.
- **The run** (`run_agent`): the prompt on stdin, the folder as working directory, the stream read as `_stream_answer`
  reads it. The usage limit (`stream.USAGE_LIMIT`, the DM's detection) is no error: the run answers `limited`, with
  the reset time as the notice says it, so the job pauses. What the session spent before the limit is still in its
  `usage`: an agent may work an hour before it meets the limit. A session stopped before its end (timed out,
  cancelled) has no cost; what its stream showed it used is on the error (`seen_usage`, review finding 7).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import signal
import tempfile
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from delve.dm.claude_cli import account
from delve.dm.claude_cli.argv import CLAUDE, DEFAULT_MODEL
from delve.dm.claude_cli.provider import NOT_INSTALLED, ClaudeCliError, _stream_answer, _usage
from delve.dm.claude_cli.resident import LINE_LIMIT
from delve.dm.claude_cli.stream import RESETS, USAGE_LIMIT, context_tokens
from delve.dm.provider import Usage
from delve.domain.settings import BackendChoice, Effort

AGENT_TIMEOUT = 3 * 3600.0
"""How long one agent session may run, in seconds: a trace of a big map runs long."""

TOOLS = "Read,Write,Edit,Glob,Grep,Bash"
DATA_DIR_PATTERNS = ("*.db*", "token")
"""The data dir's files denied by pattern as well as by name: the database with its journal and WAL, and the token."""
SYSTEM = (Path("/proc"), Path("/etc"))
"""System folders denied whole: a process's environment, the machine's configuration."""
STDERR_LINES = 40


@dataclass(frozen=True)
class AgentRun:
    """What one agent session answered: its final text, its usage and cost (None without a `result`), whether the
    usage limit stopped it and when the limit resets (as the notice says it, e.g. "2:50pm (UTC)"), and its
    conversation id."""

    text: str
    usage: Usage | None
    limited: bool
    resets_at: str | None
    session_id: str | None


class AgentStopped(ClaudeCliError):
    """A session stopped before its end (timed out): it sent no `result`, so its cost is unknown. `seen_usage` is
    what its stream showed it used (each message's usage once, no cost), None when it showed none. A cancelled
    session's `CancelledError` carries a `seen_usage` too (review finding 7)."""

    def __init__(self, message: str, seen_usage: Usage | None) -> None:
        super().__init__(message)
        self.seen_usage = seen_usage


def agent_settings(
    folder: Path, *, repo: Path, data_dir: Path, home: Path, qa: Path, records: Sequence[str] = ()
) -> dict:
    """The `--settings` of an agent working in `folder`, whose Bash runs only `qa` (an absolute path, as the command
    is written: a Bash rule matches the command's words, not a path), and who may read but never change `records`,
    paths in the folder (`dir/**` for all below a directory). Absolute paths in file rules are written
    `//path`, as the CLI reads them (a single `/` is relative to the settings file). `ValueError` when the folder is
    one of the denied roots, or `qa` is in the folder."""
    folder, qa = folder.resolve(), qa.resolve()
    if qa.is_relative_to(folder):
        raise ValueError(f"the qa wrapper {qa} is in the job folder")
    data_dir = data_dir.resolve()
    denied: list[str] = [f"Edit(/{qa.parent}/**)", *(f"Edit(/{folder}/{record})" for record in records)]
    for tool in ("Read", "Edit"):  # what the snapshot below can't see: a database file made later
        denied += [f"{tool}(/{data_dir}/{pattern})" for pattern in DATA_DIR_PATTERNS]
    for root in (data_dir, repo, home, *SYSTEM):
        for path in _beside(folder, root.resolve()):
            for tool in ("Read", "Edit"):
                rule = f"{tool}(/{path}/**)" if path.is_dir() else f"{tool}(/{path})"
                if rule not in denied:
                    denied.append(rule)
    return {
        "permissions": {
            "allow": ["Read(./**)", "Write(./**)", "Edit(./**)", f"Bash({shlex.quote(str(qa))}:*)"],
            "deny": [*denied, "WebFetch", "WebSearch"],
            "defaultMode": "dontAsk",
        }
    }


def _beside(folder: Path, root: Path) -> list[Path]:
    """What to deny of `root` so that only `folder` stays open: `root` itself when the folder isn't in it, else every
    entry next to each directory on the way from `root` down to the folder."""
    if folder == root:
        raise ValueError(f"the job folder is {root} itself")
    if not folder.is_relative_to(root):
        return [root]
    paths: list[Path] = []
    here = root
    for part in folder.relative_to(root).parts:
        with contextlib.suppress(OSError):
            paths += sorted(entry for entry in here.iterdir() if entry.name != part)
        here = here / part
    return paths


def agent_argv(*, model: str | None, effort: Effort | None, settings: Path) -> list[str]:
    """An agent's argv: file tools and Bash, the permission settings of `agent_settings`, and nothing of the user's.
    The prompt isn't in it: the caller writes it to stdin, as for `side_argv`."""
    argv = [
        CLAUDE, "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--tools", TOOLS,
        "--settings", str(settings),
        "--permission-mode", "dontAsk",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]  # fmt: skip
    if model and model != DEFAULT_MODEL:
        argv += ["--model", model]
    if effort is not None and effort is not Effort.AUTO:
        argv += ["--effort", str(effort)]
    return argv


async def run_agent(
    prompt: str,
    folder: Path,
    choice: BackendChoice,
    *,
    timeout: float,
    repo: Path,
    data_dir: Path,
    qa: Path,
    records: Sequence[str] = (),
) -> AgentRun:
    """Run one agent session in `folder`, its Bash for `qa` alone, `records` its to read only, and answer what it
    did.

    `ClaudeCliError` when `claude` is missing, fails (an exit code other than 0, or an error `result`) or doesn't end
    within `timeout` seconds; the timeout, and a cancel, kill its whole process group. The usage limit is no error
    (`AgentRun.limited`). The settings file is written outside the folder, so the agent can't rewrite its rules, and
    removed after the run.
    """
    folder = folder.resolve()
    settings = agent_settings(folder, repo=repo, data_dir=data_dir, home=Path.home(), qa=qa, records=records)
    with tempfile.TemporaryDirectory(prefix="delve-agent-") as tmp:
        path = Path(tmp) / "settings.json"
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        argv = agent_argv(model=choice.model, effort=choice.effort, settings=path)
        lines, code, stderr = await _run(argv, prompt.encode("utf-8"), folder, timeout)
    return _answer(lines, code, stderr)


async def _run(argv: list[str], stdin: bytes, cwd: Path, timeout: float) -> tuple[list[str], int, str]:
    """The process's stdout lines that `_answer` needs, its exit code and its stderr's tail."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=LINE_LIMIT,
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise ClaudeCliError(NOT_INSTALLED) from error
    lines: list[str] = []
    stderr: deque[str] = deque(maxlen=STDERR_LINES)

    async def feed() -> None:
        assert proc.stdin is not None
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            proc.stdin.write(stdin)
            await proc.stdin.drain()
            proc.stdin.close()

    async def read_out() -> None:
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace")
            if '"rate_limit_event"' in line and account.note(_loads(line)):
                continue
            # A session's stream is long (every tool result is in it); only what the answer is made of is kept.
            if '"assistant"' in line or '"result"' in line or '"system"' in line:
                lines.append(line)

    async def read_err() -> None:
        assert proc.stderr is not None
        async for raw in proc.stderr:
            stderr.append(raw.decode("utf-8", "replace"))

    try:
        await asyncio.wait_for(asyncio.gather(feed(), read_out(), read_err(), proc.wait()), timeout)
    except TimeoutError as error:
        raise AgentStopped(f"no answer within {timeout:g} s", _seen(lines)) from error
    except asyncio.CancelledError as cancelled:
        cancelled.seen_usage = _seen(lines)  # type: ignore[attr-defined]
        raise
    except ValueError as error:
        raise ClaudeCliError("claude wrote a line that is too long") from error
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
    return lines, proc.returncode, "".join(stderr).strip()[-500:]


def _answer(lines: list[str], code: int, stderr: str) -> AgentRun:
    objs = [obj for obj in map(_loads, lines) if obj]
    session_id = next((obj["session_id"] for obj in objs if isinstance(obj.get("session_id"), str)), None)
    notice = next((text for obj in objs for text in _texts(obj) if USAGE_LIMIT.search(text)), None)
    if notice is not None:
        resets = RESETS.search(notice)
        usage = next((_usage(obj) for obj in reversed(objs) if obj.get("type") == "result"), None)
        return AgentRun(notice.strip(), usage, True, resets.group(1).rstrip(".") if resets else None, session_id)
    text, usage = _stream_answer("\n".join(lines))
    if code != 0:
        raise ClaudeCliError(f"claude stopped (exit code {code}): {stderr}")
    return AgentRun(text, usage, False, None, session_id)


def _seen(lines: list[str]) -> Usage | None:
    """What a stopped session's stream showed it used: each assistant message's usage once (a message of several
    content blocks comes as several lines), its context and output tokens summed, with no cost; None for none."""
    usages: dict[str, dict] = {}
    for n, obj in enumerate(map(_loads, lines)):
        message = obj.get("message") if obj.get("type") == "assistant" else None
        if isinstance(message, dict) and isinstance(message.get("usage"), dict):
            usages[str(message.get("id") or n)] = message["usage"]
    if not usages:
        return None
    seen = usages.values()
    return Usage(sum(context_tokens(u) for u in seen), sum(int(u.get("output_tokens") or 0) for u in seen), None)


def _texts(obj: dict) -> list[str]:
    """The texts that may hold the usage-limit notice: an assistant's text blocks, and a `result`'s text."""
    if obj.get("type") == "result":
        return [obj["result"]] if isinstance(obj.get("result"), str) else []
    if obj.get("type") != "assistant":
        return []
    content = (obj.get("message") or {}).get("content") or []
    return [block.get("text") or "" for block in content if isinstance(block, dict) and block.get("type") == "text"]


def _loads(raw: str) -> dict:
    with contextlib.suppress(ValueError):
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    return {}
