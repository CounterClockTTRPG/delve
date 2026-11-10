"""The `claude -p` DM provider (spec §6.1): a resident, isolated `claude` per active campaign, ported from ttrpg2's
`tools/dm_session.py`.

- **A beat** goes to the campaign's resident; its reply streams back as `DMEvent`s. One reply runs at a time per
  campaign, and a reply nobody reads any more (a cancel, a closed page) still runs to its `result`, so the next beat
  never reads the end of the last one.
- **The conversation id** is kept per campaign in a `SessionStore`, with the context size of the last reply.
- **Auto-reset:** once that context passes `DELVE_DM_RESET_TOKENS` and no fight is live, a hidden handover turn runs
  on the old conversation, the conversation is cleared, and the next one starts with the rehydrate note and the
  handover appended to the addenda. The player sees no break.
- **Side calls** are one-shot `claude -p` runs with no tools, on the small model; a **vision call** is one too, with
  a picture, as one stream-json message on stdin. Given `on_usage`, a side call answers in JSON, and both report the
  `result`'s usage and cost.
- **Costs:** a resident's `total_cost_usd` adds up over its replies, so what it had spent is kept per campaign
  (`_spent`), from 0 for each new process, and each reply's `Usage` is its own cost (faithful modules G2).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import errno
import json
import os
import re
import shutil
import signal
import sys
import tempfile
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from delve.dm.claude_cli import account
from delve.dm.claude_cli.argv import build_argv, side_argv, vision_argv, write_mcp_config, write_system_prompt
from delve.dm.claude_cli.effort import TurnContext, auto_effort, turn_effort
from delve.dm.claude_cli.resident import Resident, turn_timeout
from delve.dm.claude_cli.stream import SessionId, StreamState, context_tokens, parse_line
from delve.dm.prompt import HANDOVER_PREFIX, HANDOVER_PROMPT, REHYDRATE
from delve.dm.provider import ConversationSpec, DMError, DMEvent, TurnEnd, Usage
from delve.domain.backends import ModelInfo, ProviderCapabilities
from delve.domain.settings import BackendChoice, Effort, Job

PROVIDER_ID = "claude-cli"

CLAUDE_CLI_CAPABILITIES = ProviderCapabilities(
    id=PROVIDER_ID,
    title="Claude (claude -p)",
    # Thorough conversion runs agents with file tools, which only the CLI has (thorough conversion Task 1).
    jobs=frozenset({Job.DM, Job.SIDE, Job.TRANSLATION, Job.CONVERSION, Job.CONVERSION_THOROUGH, Job.NOVEL}),
    # No model is the CLI's own (no `--model`), which Preferences call Provider default. It was once stored as
    # "default"; Preferences read that as no model (`web.routes.preferences`).
    models=("opus", "sonnet", "haiku"),
    efforts=(Effort.AUTO, Effort.LOW, Effort.MEDIUM, Effort.HIGH, Effort.MAX),
    model_info={
        "opus": ModelInfo("Opus (most capable)", "", None, False),
        "sonnet": ModelInfo("Sonnet", "", None, False),
        "haiku": ModelInfo("Haiku (fastest)", "", None, False),
    },
)

# 150k (DEL-78; ttrpg2's was 250k): every beat re-reads the whole context, and sessions ran at 150–290k, so a lower
# threshold saves on every beat. A reset throws away what isn't stored yet, so it waits for a safe boundary and a
# handover note; `DELVE_DM_RESET_TOKENS` sets it per install.
DEFAULT_RESET_TOKENS = 150_000
SIDE_TIMEOUT = 90.0
MAX_VISION_BYTES = 5_000_000
"""The largest picture a vision call sends; `delve.maps.vision.fit_for_vision` makes a picture fit."""
NOT_INSTALLED = "claude is not installed (not found on PATH)"
TOO_LONG = "claude can't start: its command line is too long"

# The rehydrate note and the handover come from the DM's prompt, the one source of their texts (ttrpg2's
# `_REHYDRATE_ADDENDUM`, `_HANDOVER_PROMPT` and `_handover_addendum`, with Delve's tools and words).
REHYDRATE_ADDENDUM = REHYDRATE


def handover_addendum(text: str) -> str:
    """The handover note, wrapped for the rehydrated conversation's addenda (ttrpg2 `_handover_addendum`)."""
    return HANDOVER_PREFIX + text.strip()


def reset_tokens() -> int:
    """The context size that triggers an auto-reset: `DELVE_DM_RESET_TOKENS`, default 150000."""
    return int(os.environ.get("DELVE_DM_RESET_TOKENS") or DEFAULT_RESET_TOKENS)


class SessionStore(Protocol):
    """Where the DM's conversation id is kept per campaign (`storage.dm_sessions`)."""

    def get(self, campaign_id: str) -> dict | None:
        """`{provider, session_id, context_tokens, updated_at}`, or None."""
        ...

    def set(self, campaign_id: str, provider: str, session_id: str, context_tokens: int) -> None: ...

    def clear(self, campaign_id: str) -> None: ...


class MemorySessions:
    """A `SessionStore` in memory, for tests and for running without storage."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def get(self, campaign_id: str) -> dict | None:
        row = self._rows.get(campaign_id)
        return dict(row) if row is not None else None

    def set(self, campaign_id: str, provider: str, session_id: str, context_tokens: int) -> None:
        self._rows[campaign_id] = {
            "provider": provider,
            "session_id": session_id,
            "context_tokens": context_tokens,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def clear(self, campaign_id: str) -> None:
        self._rows.pop(campaign_id, None)


class ClaudeCliError(RuntimeError):
    """A side call that got no answer: `claude` missing, failed or too slow."""


def cli_folder(cwd: str) -> Path:
    """The folder the Claude CLI keeps for a working directory: `<its config dir>/projects/<the path, with every
    character but a letter or a digit a dash>`."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))


async def _one_shot(argv: list[str], stdin: bytes, limit: float) -> bytes:
    """Run a one-shot `claude` in a temp directory with `stdin`, and answer its stdout. `ClaudeCliError` when it is
    missing, fails, or doesn't end within `limit` seconds, which kills its process group, as a cancel does.

    It leaves nothing behind (DEL-155): every call has a directory of its own, and the CLI keeps a folder for each
    directory, under its temp dir and under its config's `projects`; 513 and 3009 of them had piled up. Its temp dir
    is in the call's directory, so it goes with it, and its `projects` folder is removed once the call ends."""
    with tempfile.TemporaryDirectory(prefix="delve-side-") as cwd:
        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=cwd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    env={**os.environ, "CLAUDE_CODE_TMPDIR": str(Path(cwd) / "tmp")},
                )
            except FileNotFoundError as error:
                raise ClaudeCliError(NOT_INSTALLED) from error
            try:
                out, err = await asyncio.wait_for(proc.communicate(stdin), limit)
            except TimeoutError as error:
                await _kill(proc)
                raise ClaudeCliError(f"no answer within {limit:g} s") from error
            except asyncio.CancelledError:  # a paused conversion's other calls: their claude stops with them
                await _kill(proc)
                raise
        finally:
            shutil.rmtree(cli_folder(cwd), ignore_errors=True)
    if proc.returncode != 0:
        said = err.decode("utf-8", "replace").strip() or stopped_reason(out.decode("utf-8", "replace"))
        raise ClaudeCliError(f"claude stopped (exit code {proc.returncode}): {said[-500:]}")
    return out


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """Kill a one-shot `claude`'s process group and reap it."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    await proc.wait()


def stopped_reason(stdout: str) -> str:
    """Why a `claude` that exited non-zero stopped, from its stdout, where the CLI writes it with stderr empty: the
    last `result`'s text (json, stream-json), else the last line of plain text; "" for none."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except ValueError:
            return line
        if isinstance(obj, dict) and obj.get("type") == "result":
            return str(obj.get("result") or obj.get("errors") or obj.get("subtype") or "").strip()
    return ""


def _stream_answer(output: str) -> tuple[str, Usage | None]:
    """The answer of a stream-json (or JSON) reply: its `result` line's `result`, else its assistant text blocks
    joined, and the `result` line's usage and cost (None without one). `ClaudeCliError` for a `result` that is an
    error."""
    texts: list[str] = []
    usage: Usage | None = None
    for raw in output.splitlines():
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(obj, dict) or account.note(obj):
            continue
        if obj.get("type") == "assistant":
            content = (obj.get("message") or {}).get("content") or []
            texts += [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
        elif obj.get("type") == "result":
            if obj.get("is_error"):
                raise ClaudeCliError(f"claude failed: {str(obj.get('result') or obj.get('subtype'))[-500:]}")
            usage = _usage(obj)
            result = obj.get("result")
            if isinstance(result, str) and result.strip():
                return result.strip(), usage
    return "".join(texts).strip(), usage


def _usage(result: dict) -> Usage:
    """A one-shot call's usage: its one process spent `total_cost_usd` on it alone."""
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cost = result.get("total_cost_usd")
    return Usage(
        context_tokens(usage), int(usage.get("output_tokens") or 0), float(cost) if isinstance(cost, int | float) else None
    )


_SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")
_WAKE = object()


class ClaudeCliProvider:
    """The `claude -p` DMProvider.

    `bridge_url` and `bridge_secret` are what `delve dm-bridge` gets to reach the running Delve; `bridge_command`
    runs `delve` (by default this Python's `-m delve`). `turn_context(campaign_id)` tells whether a fight is live and
    which NPCs there are, for the auto effort and the reset's safe boundary.
    """

    capabilities = CLAUDE_CLI_CAPABILITIES

    def __init__(
        self,
        data_dir: Path,
        sessions: SessionStore,
        *,
        bridge_url: str = "",
        bridge_secret: str = "",
        bridge_command: list[str] | None = None,
        turn_context: Callable[[str], TurnContext] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.sessions = sessions
        self.bridge_url = bridge_url
        self.bridge_secret = bridge_secret
        self.bridge_command = bridge_command or [sys.executable, "-m", "delve"]
        self.turn_context = turn_context or (lambda campaign_id: TurnContext())
        self._residents: dict[str, Resident] = {}
        # What each campaign's resident had spent by its last `result` (`total_cost_usd`), from 0 for a new one.
        self._spent: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # Per campaign, the auto effort its conversation runs at and whether a fight was live (`_auto_effort`).
        self._auto: dict[str, tuple[Effort, bool]] = {}
        self._tasks: set[asyncio.Task] = set()

    async def open(self, spec: ConversationSpec) -> ClaudeCliConversation:
        """A conversation for the campaign, resuming `spec.resume_id` or else the stored conversation id."""
        if not _SAFE_ID.fullmatch(spec.campaign_id):
            raise ValueError(f"not a campaign id: {spec.campaign_id!r}")
        resume = spec.resume_id
        if resume is None:
            stored = self.sessions.get(spec.campaign_id)
            if stored is not None and stored.get("provider") == PROVIDER_ID:
                resume = stored.get("session_id")
        return ClaudeCliConversation(self, spec, resume or "")

    async def side_call(
        self,
        prompt: str,
        choice: BackendChoice,
        *,
        timeout: float | None = None,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> str:
        """A one-shot `claude -p` with ttrpg2's `_AUX_ARGS`, in a temp directory; the answer is its plain text. The
        prompt goes on stdin, so a long one fits. It waits `timeout` seconds when given (a conversion's step), else
        `SIDE_TIMEOUT`. With `on_usage`, it asks for `--output-format json` and reports the `result`'s usage."""
        argv = side_argv(model=choice.model, effort=choice.effort)
        if on_usage is not None:
            argv += ["--output-format", "json"]
        out = await _one_shot(argv, prompt.encode("utf-8"), SIDE_TIMEOUT if timeout is None else timeout)
        if on_usage is None:
            answer, usage = out.decode("utf-8", "replace").strip(), None
        else:
            answer, usage = _stream_answer(out.decode("utf-8", "replace"))
        if not answer:
            raise ClaudeCliError("claude gave an empty answer")
        if on_usage is not None and usage is not None:
            on_usage(usage)
        return answer

    async def vision_call(
        self,
        prompt: str,
        image: bytes,
        media_type: str,
        choice: BackendChoice,
        *,
        timeout: float | None = None,
        on_usage: Callable[[Usage], None] | None = None,
    ) -> str:
        """A one-shot `claude -p` that sees `image`: one stream-json message on stdin, the picture as a base64 block
        and then the prompt. The answer is the `result` line's, else the assistant's text. Its errors, its timeout
        and `on_usage` are `side_call`'s; a picture over `MAX_VISION_BYTES` is refused before `claude` runs."""
        if len(image) > MAX_VISION_BYTES:
            raise ClaudeCliError(f"the picture is too big for Claude ({len(image)} bytes, at most {MAX_VISION_BYTES})")
        argv = vision_argv(model=choice.model, effort=choice.effort)
        message = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        }
        line = (json.dumps(message) + "\n").encode("utf-8")
        out = await _one_shot(argv, line, SIDE_TIMEOUT if timeout is None else timeout)
        answer, usage = _stream_answer(out.decode("utf-8", "replace"))
        if not answer:
            raise ClaudeCliError("claude gave an empty answer")
        if on_usage is not None and usage is not None:
            on_usage(usage)
        return answer

    async def reset(self, campaign_id: str) -> None:
        """Start the campaign's DM afresh: stop its resident and forget its conversation (ttrpg2 `force_reset`)."""
        await self._drop(campaign_id)
        self.sessions.clear(campaign_id)

    async def close(self) -> None:
        """Stop every resident, and wait for the replies that were still running to end."""
        for campaign_id in list(self._residents):
            await self._drop(campaign_id)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def dm_dir(self, campaign_id: str) -> Path:
        """The DM's working directory: `<data dir>/dm/<campaign id>/`, never the repo or the home directory."""
        return self.data_dir / "dm" / campaign_id

    # A beat

    def _start(self, conversation: ClaudeCliConversation, text: str, out: Callable[[object], None]) -> None:
        task = asyncio.create_task(self._run_beat(conversation, text, out))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_beat(self, conversation: ClaudeCliConversation, text: str, out: Callable[[object], None]) -> None:
        campaign_id = conversation.spec.campaign_id
        async with self._locks.setdefault(campaign_id, asyncio.Lock()):
            try:
                ctx = self.turn_context(campaign_id)
                chosen = conversation.spec.choice.effort
                effort = self._auto_effort(campaign_id, text, ctx) if chosen is Effort.AUTO else turn_effort(chosen, text, ctx)
                addenda = [conversation.spec.system_prompt] if conversation.spec.system_prompt else []
                if self._reset_due(conversation, ctx):
                    handover = await self._reply(conversation, addenda, effort, HANDOVER_PROMPT, lambda event: None)
                    self.sessions.clear(campaign_id)
                    conversation.id = ""
                    addenda = [*addenda, REHYDRATE_ADDENDUM]
                    if handover:
                        addenda.append(handover_addendum(handover))
                await self._reply(conversation, addenda, effort, text, out)
            except FileNotFoundError as error:
                out(DMError(NOT_INSTALLED, False, str(error)))
                out(TurnEnd("error"))
            except OSError as error:
                # Too long a command line fails the same way every time: Retry would never help (DEL-160).
                fatal = error.errno == errno.E2BIG
                out(DMError(TOO_LONG if fatal else f"the DM provider failed: {type(error).__name__}", not fatal, repr(error)))
                out(TurnEnd("error"))
            except Exception as error:  # noqa: BLE001 (a beat always ends with a TurnEnd, never a hung page)
                out(DMError(f"the DM provider failed: {type(error).__name__}", True, repr(error)))
                out(TurnEnd("error"))

    def _auto_effort(self, campaign_id: str, text: str, ctx: TurnContext) -> Effort:
        """`auto`, held: another effort is another claude process, which reads the whole prompt cache again. So the
        effort is decided (`auto_effort`) at the conversation's first beat and when a fight starts or ends, and kept
        in between."""
        held = self._auto.get(campaign_id)
        effort = auto_effort(text, ctx) if held is None or held[1] != ctx.in_combat else held[0]
        self._auto[campaign_id] = (effort, ctx.in_combat)
        return effort

    def _reset_due(self, conversation: ClaudeCliConversation, ctx: TurnContext) -> bool:
        """At a safe boundary (no live fight), when the stored context of this conversation passed the threshold."""
        stored = self.sessions.get(conversation.spec.campaign_id)
        if not conversation.id or stored is None or ctx.in_combat:
            return False
        if stored.get("provider") != PROVIDER_ID or stored.get("session_id") != conversation.id:
            return False
        return int(stored.get("context_tokens") or 0) >= reset_tokens()

    async def _reply(
        self,
        conversation: ClaudeCliConversation,
        addenda: list[str],
        effort: Effort | None,
        text: str,
        out: Callable[[object], None],
    ) -> str:
        """Send `text` to the resident and pass the reply's events to `out`, up to its `TurnEnd`.

        Returns the reply's result text. A crash, the end of the output or the timeout ends the reply with a
        `DMError` and `TurnEnd("error")`, and the resident is dropped, so the next beat starts a fresh one.
        """
        campaign_id = conversation.spec.campaign_id
        mcp_config = write_mcp_config(
            self.dm_dir(campaign_id) / "mcp.json",
            command=self.bridge_command,
            url=self.bridge_url,
            campaign_id=campaign_id,
            secret=self.bridge_secret,
        )
        sid = conversation.id or None
        argv = build_argv(
            mcp_config=mcp_config,
            model=conversation.spec.choice.model,
            effort=effort,
            system_prompt=write_system_prompt(self.dm_dir(campaign_id), addenda),
            resume=sid,
            resident=True,
        )
        resident = await self._resident(campaign_id, argv, sid)
        try:
            await resident.send(text)
        except (OSError, RuntimeError):
            # It died between the check and the write: start over once rather than drop the beat.
            await self._drop(campaign_id)
            resident = await self._resident(campaign_id, argv, sid)
            await resident.send(text)

        timeout = turn_timeout()
        deadline = asyncio.get_running_loop().time() + timeout
        state = StreamState(spent=self._spent.get(campaign_id, 0.0))
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            try:
                if remaining <= 0:
                    raise TimeoutError
                obj = await resident.next_line(remaining)
            except TimeoutError:
                await self._fail(campaign_id, resident, f"no answer within {timeout:g} s", out)
                return ""
            except ValueError:
                await self._fail(campaign_id, resident, "claude wrote a line that is too long", out)
                return ""
            if obj is None:
                code = await resident.proc.wait()
                await self._fail(campaign_id, resident, f"claude stopped (exit code {code})", out)
                return ""
            for event in parse_line(obj, state):
                if isinstance(event, SessionId):
                    resident.observed_sid = event.id
                    if event.id != conversation.id:
                        conversation.id = event.id
                        self.sessions.set(campaign_id, PROVIDER_ID, event.id, 0)
                    continue
                if isinstance(event, Usage) and conversation.id:
                    self.sessions.set(campaign_id, PROVIDER_ID, conversation.id, event.input_tokens)
                out(event)
            if obj.get("type") == "result":
                self._spent[campaign_id] = state.spent
                result = obj.get("result")
                return result.strip() if isinstance(result, str) else ""

    async def _fail(self, campaign_id: str, resident: Resident, message: str, out: Callable[[object], None]) -> None:
        tail = await resident.stderr_tail()
        await self._drop(campaign_id)
        out(DMError(message, True, tail))
        out(TurnEnd("error"))

    async def _resident(self, campaign_id: str, argv: list[str], sid: str | None) -> Resident:
        """The campaign's resident if it can take this beat; else a new one (the argv changed or it died)."""
        resident = self._residents.get(campaign_id)
        if resident is not None and resident.matches(argv, sid):
            return resident
        await self._drop(campaign_id)
        resident = await Resident.spawn(argv, self.dm_dir(campaign_id), sid)
        self._residents[campaign_id] = resident
        self._spent[campaign_id] = 0.0
        return resident

    async def _drop(self, campaign_id: str) -> None:
        resident = self._residents.pop(campaign_id, None)
        self._spent.pop(campaign_id, None)
        if resident is not None:
            await resident.kill()


class ClaudeCliConversation:
    """One campaign's DM conversation. `id` is the `claude` conversation id, empty until the first reply."""

    def __init__(self, provider: ClaudeCliProvider, spec: ConversationSpec, id: str) -> None:
        self._provider = provider
        self.spec = spec
        self.id = id
        self._cancelled = False
        self._queue: asyncio.Queue | None = None

    async def send(self, text: str) -> AsyncIterator[DMEvent]:
        """Send a beat and stream the reply, which always ends with exactly one `TurnEnd`.

        The reply runs in its own task: when this stream is cancelled or abandoned, the reply still runs to its
        end, and the campaign's next beat waits for that.
        """
        self._cancelled = False
        queue: asyncio.Queue = asyncio.Queue()
        self._queue = queue
        self._provider._start(self, text, queue.put_nowait)
        while True:
            event = await queue.get()
            if self._cancelled:
                yield TurnEnd("cancelled")
                return
            if event is _WAKE:
                continue
            yield event
            if isinstance(event, TurnEnd):
                return

    async def cancel(self) -> None:
        """End the stream with `TurnEnd("cancelled")`; the reply itself is drained to its `result`."""
        self._cancelled = True
        if self._queue is not None:
            self._queue.put_nowait(_WAKE)

    async def close(self) -> None:
        """Stop streaming. The campaign's resident stays warm for the next beat."""
        await self.cancel()
