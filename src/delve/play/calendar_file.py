"""A table's schedule as a calendar file (DEL-236): its next sessions as iCalendar events (RFC 5545), for a player to
import into their own calendar. Each session is an event of its own, in UTC, so a session the host moved or skipped
is as the table shows it; the file is what the schedule is when it is downloaded, and a later change means
downloading it again (a calendar app can't log in to follow it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

CALENDAR_SESSIONS = 12
"""How many of the next sessions the file holds: about a quarter of a weekly table's."""
_FOLD = 75


def calendar_file(
    campaign_id: str, name: str, sessions: list[dict[str, Any]], now: datetime, link: str | None = None
) -> str:
    """The `sessions` (`schedule.next_sessions`' shape) of the campaign `name` as an iCalendar text, with `link` to
    its play screen in each event when given. Lines end in CRLF and are folded at 75 octets, as RFC 5545 says."""
    stamp = _instant(now)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Delve//Table schedule//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_text(name)}"]  # fmt: skip
    for session in sessions:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{campaign_id}-{session['on']}@delve",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_instant(datetime.fromisoformat(session['starts_at']))}",
            f"DTEND:{_instant(datetime.fromisoformat(session['ends_at']))}",
            f"SUMMARY:{_text(name)}",
        ]
        if link:
            lines += [f"DESCRIPTION:{_text(f'Play at {link}')}", f"URL:{link}"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)


def _instant(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _text(value: str) -> str:
    """A TEXT value: backslashes, semicolons, commas and line breaks escaped."""
    escaped = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line: str) -> str:
    """A content line folded at 75 octets: each further part on a line of its own after a space, never inside a
    character's UTF-8 bytes."""
    parts: list[str] = []
    current, size = "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > (_FOLD if not parts else _FOLD - 1):
            parts.append(current)
            current, size = "", 0
        current += char
        size += width
    parts.append(current)
    return "\r\n ".join(parts)
