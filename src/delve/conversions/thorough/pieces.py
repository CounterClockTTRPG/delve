"""The pieces of a thorough conversion (thorough conversion Task 4): one text cleaned, one map traced, each an agent
session whose end Delve records in the job folder's `state.json` (`Workspace`), and the rules for its retries, its
skip and the pause.

A piece that is finished (done or skipped) is never run again. Otherwise it gets up to `ATTEMPTS` attempts, counted
across runs of the job: an attempt fails when the session raises (crashed, timed out) or when `check()`, the piece's
expected outputs, names files missing. After the last failed attempt the piece is skipped and becomes a doubt, and
the run goes on. A session that hit the usage limit (`AgentResult.limited`) uses no attempt: `Paused` is raised with
its reset time, and the job pauses. A session stopped halfway (Delve stopping) ends nothing, and is started over.

A piece started over starts from a clean slate (owner decision, DEL-92): a session that ended no attempt (stopped
halfway, cancelled by a pause, or at the usage limit) leaves the piece `running` in `state.json`, and before the next
session begins the piece's `clear` removes what it left in the piece's own files, never another piece's. A failed
attempt's files stay for the retry, as before.

What each attempt cost, a failed one too, is added to the job's cost (`spend`) and to the piece's once, when the
attempt ends; a finished piece's cost is never added again. A session stopped before its end (timed out, or
cancelled by a pause or Delve stopping) sends no cost: the tokens its stream showed (`seen_usage` on the error,
`claude_cli.agent`) are recorded instead, and the making's doubts say the cost is incomplete, with an estimate at
the job's own rate (`stopped_doubt`, review finding 7). The job's `cost_usd` stays what was measured."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from delve.conversions.thorough.workspace import FINISHED, Workspace
from delve.dm.provider import Usage
from delve.domain.settings import BackendChoice
from delve.modules.books.calls import Halt

PieceOutcome = Literal["done", "skipped", "paused"]
"""How a piece ends a run: done, skipped after its last attempt, or paused at the usage limit (raised as `Paused`)."""

ATTEMPTS = 3
"""Attempts per piece: one and two retries."""
RESUME_GRACE = 60.0
"""Seconds after the usage limit's reset at which a paused job resumes by itself."""
RESUME_UNKNOWN = 15 * 60.0
"""Seconds until a paused job tries again when the limit's notice gave no reset time it could read."""

USAGE_LIMIT = "The Claude usage limit was reached."
SKIPPED = "Skipped after {attempts} failed attempts: {error}"
COST_INCOMPLETE = (
    "Cost incomplete: {sessions} sessions stopped before their end, so the cost shown leaves them out. They used "
    "{tokens} tokens"
)
COST_INCOMPLETE_ONE = (
    "Cost incomplete: 1 session stopped before its end, so the cost shown leaves it out. It used {tokens} tokens"
)
ESTIMATED = ": about ${cost:.2f}, estimated at this job's rate."
NO_RATE = "; no session of this job ended, so there is no rate to estimate the cost from."
COST_PART = "cost"
"""The `part` of the cost's doubt, `doubts/cost.json`."""


class AgentResult(Protocol):
    """What a piece's agent session answers (`delve.dm.claude_cli.agent.AgentRun`)."""

    @property
    def usage(self) -> Usage | None: ...

    @property
    def limited(self) -> bool: ...

    @property
    def resets_at(self) -> str | None: ...


AgentRunner = Callable[[str, Path, BackendChoice], Awaitable[AgentResult]]
"""Runs one agent session, `(prompt, job folder, choice)`, in the folder (`claude_cli.agent.run_agent`, with the
app's data directory and repository), thorough conversion Task 6."""


class Paused(Halt):
    """The usage limit was reached: the job pauses until `resets_at` (the notice's time, None when it gave none). A
    `Halt`, so the books' steps that make a failed call a warning (classifying, entities) let it through."""

    def __init__(self, resets_at: str | None, reason: str = USAGE_LIMIT) -> None:
        self.resets_at = resets_at
        self.reason = reason
        super().__init__(reason)


async def run_piece(
    ws: Workspace,
    piece_id: str,
    attempt: Callable[[], Awaitable[AgentResult]],
    check: Callable[[], list[str]],
    *,
    spend: Callable[[Usage], None] | None = None,
    outputs: Sequence[str] = (),
    clear: Callable[[], None] | None = None,
) -> PieceOutcome:
    """Run `piece_id` until it is done or out of attempts; a done piece records its `outputs` (paths in the folder).
    Answers `done` or `skipped` (an outcome already recorded is answered without running); `Paused` at the usage
    limit. `clear` (in a thread) removes the piece's own files, before a session that follows one stopped halfway
    (DEL-92)."""
    record = ws.piece(piece_id)
    if record is not None and record.status in FINISHED:
        return record.status
    attempts = record.attempts if record is not None else 0
    error = (record.error if record is not None else None) or ""
    while attempts < ATTEMPTS:
        if ws.was_stopped(piece_id) and clear is not None:
            await asyncio.to_thread(clear)
        ws.began(piece_id)
        try:
            run = await attempt()
        except asyncio.CancelledError as cancelled:  # a pause or Delve stopping: started over, no attempt
            _stopped(ws, piece_id, cancelled)
            raise
        except Exception as raised:  # noqa: BLE001 (a crashed or timed-out session is a failed attempt)
            error = str(raised) or type(raised).__name__
            ws.failed(piece_id, error)
            _stopped(ws, piece_id, raised)
            attempts += 1
            continue
        cost = run.usage.cost_usd if run.usage is not None else None
        tokens = _tokens(run.usage) if cost is not None else None
        if run.usage is not None and spend is not None:
            spend(run.usage)
        if run.limited:
            ws.spent(piece_id, cost, tokens=tokens)  # what it spent before the limit, without using an attempt
            raise Paused(run.resets_at)
        missing = check()
        if not missing:
            ws.done(piece_id, cost, list(outputs), tokens=tokens)
            return "done"
        error = "Missing: " + ", ".join(missing)
        ws.failed(piece_id, error, cost=cost, tokens=tokens)
        attempts += 1
    message = SKIPPED.format(attempts=attempts, error=error)
    ws.skipped(piece_id, message)
    ws.doubt(f"{piece_id}.skipped", [{"part": piece_id, "pages": [], "kind": "other", "text": message}])
    return "skipped"


def _tokens(usage: Usage | None) -> int | None:
    return usage.input_tokens + usage.output_tokens if usage is not None else None


def _stopped(ws: Workspace, piece_id: str, error: BaseException) -> None:
    """Record a session stopped before its end, if `error` says it was (`seen_usage`, None when its stream showed
    no usage); any other error was no session stopped by Delve."""
    if hasattr(error, "seen_usage"):
        seen = error.seen_usage
        ws.stopped(piece_id, _tokens(seen) if isinstance(seen, Usage) else None)


def stopped_doubt(ws: Workspace) -> dict[str, Any] | None:
    """The doubt that says the job's cost is incomplete, when sessions were stopped before their end: how many, the
    tokens they used, and their cost estimated at the job's own rate (the cost per token of its sessions that
    ended), when it has one. None when no session was stopped."""
    state = ws.state()
    if not state.stopped:
        return None
    tokens = sum(int(stopped.get("tokens") or 0) for stopped in state.stopped)
    measured = [(p.cost_usd, p.tokens) for p in state.pieces.values() if p.cost_usd is not None and p.tokens]
    paid, counted = sum(cost for cost, _ in measured), sum(count for _, count in measured)
    sessions = len(state.stopped)
    text = (COST_INCOMPLETE_ONE if sessions == 1 else COST_INCOMPLETE).format(sessions=sessions, tokens=f"{tokens:,}")
    text += ESTIMATED.format(cost=tokens * paid / counted) if counted else NO_RATE
    return {"part": COST_PART, "pages": [], "kind": "other", "text": text}


# ----- when a paused job resumes -----

_CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(([^)]+)\))?", re.IGNORECASE)


def resume_delay(resets_at: str | None, now: datetime) -> float:
    """Seconds from `now` until a job paused at the usage limit resumes: `RESUME_GRACE` after its reset, read as an
    ISO time or as the notice's clock time ("2:50pm (UTC)", "3am (Europe/Brussels)", the next such time);
    `RESUME_UNKNOWN` when there is none or it can't be read."""
    reset = _reset_time(resets_at, now) if resets_at else None
    if reset is None:
        return RESUME_UNKNOWN
    return max(0.0, (reset - now).total_seconds()) + RESUME_GRACE


def _reset_time(resets_at: str, now: datetime) -> datetime | None:
    try:
        reset = datetime.fromisoformat(resets_at.strip())
    except ValueError:
        pass
    else:
        return reset if reset.tzinfo is not None else reset.replace(tzinfo=UTC)
    match = _CLOCK.match(resets_at.strip())
    if match is None:
        return None
    hour, minute, half, zone = int(match[1]), int(match[2] or 0), (match[3] or "").lower(), match[4]
    if half:
        hour = hour % 12 + (12 if half == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    try:
        tz = ZoneInfo(zone.strip()) if zone and zone.strip().upper() != "UTC" else UTC
    except (ZoneInfoNotFoundError, ValueError):
        return None
    local = now.astimezone(tz)
    reset = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset < local:
        reset += timedelta(days=1)
    return reset
