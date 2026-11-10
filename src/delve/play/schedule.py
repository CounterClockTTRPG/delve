"""The table's schedule (DEL-204 part C): when the table plays, as a rule and the host's changes to it.

The rule is "every `every_weeks` weeks (1 to 4) from `first`, `start` to `end` local time in `time_zone`", so its
weekday is `first`'s. An `end` before its `start` is a session past midnight, which ends the next day. Its sessions are
`first + k × every_weeks` weeks, each named by its date `on`; the host moves one (`to`, a local date-time in the same
time zone: it keeps its length) or skips it (`to` null). Times are read in the time zone with `zoneinfo`, so a
daylight-saving change keeps 20:00 at 20:00 local and moves it an hour in UTC.

A schedule is a plain dict, as the campaign stores it (`Campaign.schedule`): `parse` checks and normalises one,
dropping the changes already over; `next_sessions` gives the sessions to come as UTC instants, for every viewer to
read in their own time; `change_next` moves, skips or resets the next session not yet started.

Refusals are `PlayError`s (422); `NoSchedule` (409) is for changing the next session of a table without a schedule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from delve.play.context import PlayError

MOST_WEEKS = 4
NEXT_SESSIONS = 3
"""How many of the next sessions a table shows."""
KEYS = ("every_weeks", "first", "start", "end", "time_zone")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME = re.compile(r"\d{2}:\d{2}")
LOCAL = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
SPARE = 2
"""Rule sessions read beyond those asked for: the one or two before `now` that may not have ended yet."""


class NoSchedule(PlayError):
    """The table has no schedule, so it has no next session to change (409)."""


@dataclass(frozen=True)
class _Session:
    on: date
    starts: datetime
    ends: datetime
    moved: bool
    skipped: bool


def _date(raw: Any, what: str) -> date:
    if not isinstance(raw, str) or not DATE.fullmatch(raw):
        raise PlayError(f"{what} is a date, YYYY-MM-DD.")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise PlayError(f"{what} is a date, YYYY-MM-DD.") from None


def _time(raw: Any, what: str) -> time:
    if not isinstance(raw, str) or not TIME.fullmatch(raw):
        raise PlayError(f"{what} is a time, HH:MM.")
    try:
        return time.fromisoformat(raw)
    except ValueError:
        raise PlayError(f"{what} is a time, HH:MM.") from None


def _local(raw: Any, what: str) -> datetime:
    """A local date-time `YYYY-MM-DDTHH:MM`, without its time zone."""
    if not isinstance(raw, str) or not LOCAL.fullmatch(raw):
        raise PlayError(f"{what} is a date and time, YYYY-MM-DDTHH:MM.")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise PlayError(f"{what} is a date and time, YYYY-MM-DDTHH:MM.") from None


def _zone(raw: Any) -> ZoneInfo:
    if not isinstance(raw, str) or not raw:
        raise PlayError("The time zone is a name such as Europe/Brussels.")
    try:
        return ZoneInfo(raw)
    except (ZoneInfoNotFoundError, ValueError):
        raise PlayError(f"No time zone {raw!r}: name one such as Europe/Brussels.") from None


class _Rule:
    """A checked schedule's rule and changes, with what reading its sessions needs."""

    def __init__(self, raw: Any) -> None:
        if not isinstance(raw, dict):
            raise PlayError("A schedule is an object, or null for none.")
        unknown = set(raw) - {*KEYS, "changes"}
        if unknown:
            raise PlayError(f"A schedule has no {', '.join(sorted(unknown))}.")
        missing = [key for key in KEYS if key not in raw]
        if missing:
            raise PlayError(f"A schedule needs {', '.join(missing)}.")
        every = raw["every_weeks"]
        if not isinstance(every, int) or isinstance(every, bool) or not 1 <= every <= MOST_WEEKS:
            raise PlayError(f"A table plays every 1 to {MOST_WEEKS} weeks.")
        self.every_weeks = every
        self.first = _date(raw["first"], "The first session")
        self.start = _time(raw["start"], "The start")
        self.end = _time(raw["end"], "The end")
        if self.end == self.start:
            raise PlayError("A session ends after it starts.")
        self.zone = _zone(raw["time_zone"])
        self.time_zone = raw["time_zone"]
        self.changes: dict[date, datetime | None] = {}
        changes = raw.get("changes", [])
        if not isinstance(changes, list):
            raise PlayError("The changes are a list.")
        for change in changes:
            if not isinstance(change, dict) or set(change) != {"on", "to"}:
                raise PlayError('A change is {"on": a date of the rule, "to": a date and time, or null to skip it}.')
            on = _date(change["on"], "A change's date")
            if not self.on_the_rule(on):
                raise PlayError(f"The table doesn't play on {on.isoformat()}: a change is of a session of the rule.")
            if on in self.changes:
                raise PlayError(f"{on.isoformat()} has two changes.")
            self.changes[on] = None if change["to"] is None else _local(change["to"], "A change's new time")

    @property
    def period(self) -> int:
        return 7 * self.every_weeks

    def on_the_rule(self, on: date) -> bool:
        return on >= self.first and (on - self.first).days % self.period == 0

    def length(self) -> timedelta:
        minutes = (self.end.hour * 60 + self.end.minute - self.start.hour * 60 - self.start.minute) % (24 * 60)
        return timedelta(minutes=minutes)

    def instant(self, local: datetime) -> datetime:
        return local.replace(tzinfo=self.zone).astimezone(UTC)

    def session(self, on: date) -> _Session:
        """The session of the rule on `on`, with its change applied."""
        starts = self.instant(datetime.combine(on, self.start))
        end_day = on + timedelta(days=1) if self.end < self.start else on
        ends = self.instant(datetime.combine(end_day, self.end))
        if on not in self.changes:
            return _Session(on, starts, ends, moved=False, skipped=False)
        to = self.changes[on]
        if to is None:
            return _Session(on, starts, ends, moved=False, skipped=True)
        moved = self.instant(to)
        return _Session(on, moved, moved + self.length(), moved=True, skipped=False)

    def around(self, now: datetime, count: int) -> list[_Session]:
        """The rule's sessions from just before `now` on, `count` and the spare ones, and every changed one, in order
        of their start (a skipped one at its rule time)."""
        days_in = (now.astimezone(UTC).date() - self.first).days - SPARE
        lowest = max(0, days_in // self.period)
        ons = {self.first + timedelta(days=self.period * k) for k in range(lowest, lowest + count + SPARE + 1)}
        return sorted((self.session(on) for on in ons | set(self.changes)), key=lambda s: (s.starts, s.on))

    def upcoming(self, now: datetime, count: int) -> list[_Session]:
        """The sessions not yet ended at `now`, skipped ones too, in order."""
        return [s for s in self.around(now, count + len(self.changes)) if s.ends > now]

    def next_held(self, now: datetime) -> _Session:
        """The next session not yet started and not skipped."""
        return next(s for s in self.upcoming(now, 2) if s.starts > now and not s.skipped)

    def to_dict(self, now: datetime) -> dict[str, Any]:
        """The schedule as stored: its changes in order of their date, those already over dropped, and a move back to
        the rule's own time is no change."""
        kept = []
        for on in sorted(self.changes):
            session, to = self.session(on), self.changes[on]
            if session.ends <= now or (to is not None and to == datetime.combine(on, self.start)):
                continue
            kept.append({"on": on.isoformat(), "to": None if to is None else to.strftime("%Y-%m-%dT%H:%M")})
        return {
            "every_weeks": self.every_weeks,
            "first": self.first.isoformat(),
            "start": self.start.strftime("%H:%M"),
            "end": self.end.strftime("%H:%M"),
            "time_zone": self.time_zone,
            "changes": kept,
        }


def parse(raw: Any, now: datetime) -> dict[str, Any] | None:
    """The schedule checked and as stored (`changes` always there, in order, those over at `now` dropped), or None for
    none; a `PlayError` naming the first field that is wrong."""
    return None if raw is None else _Rule(raw).to_dict(now)


def next_sessions(schedule: dict[str, Any] | None, now: datetime, n: int = NEXT_SESSIONS) -> list[dict[str, Any]]:
    """The next `n` sessions not yet ended at `now`, in order of their start, skipped ones left out: each `{"on": its
    date in the rule, "starts_at", "ends_at": UTC ISO instants, "moved"}`. None for no schedule: no sessions."""
    if schedule is None:
        return []
    rule = _Rule(schedule)
    held = [s for s in rule.upcoming(now, n) if not s.skipped][:n]
    return [_shown(s) for s in held]


def _shown(s: _Session) -> dict[str, Any]:
    return {"on": s.on.isoformat(), "starts_at": s.starts.isoformat(), "ends_at": s.ends.isoformat(), "moved": s.moved}


def next_to_change(schedule: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The session `change_next` skips or moves at `now`, the next not yet started (one under way is not it), shown as
    `next_sessions` shows one."""
    return _shown(_Rule(schedule).next_held(now))


def session_on(schedule: dict[str, Any], on: str) -> dict[str, Any]:
    """The session of the rule on the date `on`, with its change applied (where a move took it), shown as
    `next_sessions` shows one."""
    return _shown(_Rule(schedule).session(_date(on, "The date")))


def change_next(
    schedule: dict[str, Any] | None,
    now: datetime,
    *,
    skip: bool = False,
    to: str | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    """The schedule with its next session not yet started skipped, or moved `to` a local date-time in its time zone
    (still to come at `now`), or, with `reset`, its change dropped: the change of the next session if it is moved,
    else the skip nearest before it, else nothing. `NoSchedule` without a schedule."""
    if schedule is None:
        raise NoSchedule("The table has no schedule.", "Set when you play first.")
    rule = _Rule(schedule)
    if reset:
        window = []
        for session in rule.upcoming(now, 2):
            if session.starts <= now:
                continue
            window.append(session)
            if not session.skipped:
                break
        changed = [s for s in window if s.on in rule.changes]
        if changed:
            del rule.changes[changed[-1].on]
        return rule.to_dict(now)
    target = rule.next_held(now)
    if skip:
        rule.changes[target.on] = None
    else:
        moved = _local(to, "The new time")
        if rule.instant(moved) <= now:
            raise PlayError("The new time is in the past.")
        rule.changes[target.on] = moved
    return rule.to_dict(now)
