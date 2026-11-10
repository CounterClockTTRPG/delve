"""The clock the table keeps time by (plan 4 Task 4): the beat timer's deadline and the event stream's presence.

`SystemClock` is the real time. Tests move time by hand with `FakeClock`. `FileClock` is the real time plus a number of
seconds read from a file, so a test can move the time of a `delve serve` it started: `delve serve` uses it when
`DELVE_CLOCK_FILE` names that file.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

__all__ = ["CLOCK_FILE_ENV", "Clock", "FakeClock", "FileClock", "SystemClock"]

CLOCK_FILE_ENV = "DELVE_CLOCK_FILE"
POLL_SECONDS = 0.5


class Clock(Protocol):
    def now(self) -> datetime:
        """The time now, in UTC."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Wait until `seconds` have passed by this clock."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


class FakeClock:
    """A clock that moves only when `advance` is called; its sleepers wake when their time has come."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)
        self._moved = asyncio.Condition()

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        until = self._now + timedelta(seconds=seconds)
        async with self._moved:
            await self._moved.wait_for(lambda: self._now >= until)

    async def advance(self, seconds: float) -> None:
        """Move the time on, and let the sleepers whose time has come run."""
        self._now += timedelta(seconds=seconds)
        async with self._moved:
            self._moved.notify_all()
        for _ in range(5):  # let woken sleepers run up to their next wait
            await asyncio.sleep(0)


class FileClock:
    """The real time plus the seconds written in `path` (none, or nothing readable: no offset). Its sleeps look at
    the file again every half second, so moving the time wakes them."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def offset(self) -> float:
        try:
            return float(self._path.read_text().strip() or 0)
        except (OSError, ValueError):
            return 0.0

    def now(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.offset())

    async def sleep(self, seconds: float) -> None:
        until = self.now() + timedelta(seconds=seconds)
        while (left := (until - self.now()).total_seconds()) > 0:
            await asyncio.sleep(min(left, POLL_SECONDS))
