"""One long-lived `claude -p --input-format stream-json` per active campaign (ttrpg2 `_Resident`).

A cold spawn costs about 3 s before the model sees a token; a warm resident adds nothing beyond the API time. One
beat is one stdin line, and its reply ends at the first `result` line.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from collections import deque
from pathlib import Path
from typing import Any

DEFAULT_TURN_TIMEOUT = 900.0
STDERR_LINES = 80
# A tool result can be long (a primer, a module section); stream-json puts each on one line.
LINE_LIMIT = 64 * 1024 * 1024


def turn_timeout() -> float:
    """How long one reply may take before the resident is given up: `DELVE_DM_TURN_TIMEOUT`, default 900 s."""
    return float(os.environ.get("DELVE_DM_TURN_TIMEOUT") or DEFAULT_TURN_TIMEOUT)


def user_line(text: str) -> bytes:
    message = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    return (json.dumps(message) + "\n").encode("utf-8")


class Resident:
    """A running `claude` and what it was started with.

    `signature` is the argv without `--resume`: when it changes, the process must be replaced. The session id is
    compared apart, because the first reply of a new conversation only reports its id: `sid_at_spawn` is the one it
    was started on, `observed_sid` the one it reported.
    """

    def __init__(self, proc: asyncio.subprocess.Process, argv: list[str], sid: str | None) -> None:
        self.proc = proc
        self.argv = argv
        self.signature = signature(argv)
        self.sid_at_spawn = sid
        self.observed_sid: str | None = None
        self._stderr: deque[str] = deque(maxlen=STDERR_LINES)
        self._stderr_task = asyncio.create_task(self._pump_stderr())

    @classmethod
    async def spawn(cls, argv: list[str], cwd: Path, sid: str | None) -> Resident:
        """Start the process in `cwd`. Raises `FileNotFoundError` when `claude` isn't on `PATH`."""
        cwd.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=LINE_LIMIT,
            start_new_session=True,
        )
        return cls(proc, argv, sid)

    async def _pump_stderr(self) -> None:
        """Keep the last lines of stderr, and keep its pipe from filling up between beats."""
        assert self.proc.stderr is not None
        with contextlib.suppress(Exception):
            async for line in self.proc.stderr:
                self._stderr.append(line.decode("utf-8", "replace"))

    def alive(self) -> bool:
        return self.proc.returncode is None

    def matches(self, argv: list[str], sid: str | None) -> bool:
        return self.alive() and self.signature == signature(argv) and sid in (self.sid_at_spawn, self.observed_sid)

    async def stderr_tail(self) -> str:
        """The last lines of stderr, once the process has written them out (a crash prints just before it ends)."""
        if not self.alive():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(self._stderr_task), 1.0)
        return "".join(self._stderr)[-2000:]

    async def send(self, text: str) -> None:
        """Write one beat. Raises `OSError` (a broken pipe) when the process has gone."""
        assert self.proc.stdin is not None
        self.proc.stdin.write(user_line(text))
        await self.proc.stdin.drain()

    async def next_line(self, timeout: float) -> dict[str, Any] | None:
        """The next stream-json object, or None at the end of the output. Raises `TimeoutError`.

        A line that is not JSON is skipped.
        """
        assert self.proc.stdout is not None
        while True:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout)
            if not line:
                return None
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                return obj

    async def kill(self) -> None:
        if self.proc.stdin is not None:
            with contextlib.suppress(Exception):
                self.proc.stdin.close()
        if self.alive():
            # The process group: `claude` and the MCP servers it started.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(self.proc.pid, signal.SIGKILL)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.proc.wait(), 5)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.shield(self._stderr_task), 1)
        self._stderr_task.cancel()


def signature(argv: list[str]) -> tuple[str, ...]:
    """The argv without its `--resume`, which decides whether a resident can take the next beat."""
    if "--resume" in argv:
        index = argv.index("--resume")
        argv = argv[:index] + argv[index + 2 :]
    return tuple(argv)
