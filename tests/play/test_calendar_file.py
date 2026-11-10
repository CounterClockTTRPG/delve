"""A schedule as an iCalendar file (DEL-236): one event a session, in UTC, its text escaped and its lines folded."""

from datetime import UTC, datetime

from delve.play.calendar_file import calendar_file

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
SESSION = {"on": "2026-11-07", "starts_at": "2026-11-07T19:00:00+00:00", "ends_at": "2026-11-07T21:00:00+00:00"}


def lines_of(text: str) -> list[str]:
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    return text.replace("\r\n ", "").split("\r\n")[:-1]


def test_a_session_is_an_event_in_utc_with_its_link():
    lines = lines_of(calendar_file("cmp_1", "Tuesday", [SESSION], NOW, "https://delve.party/play/cmp_1"))
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    event = lines[lines.index("BEGIN:VEVENT") : lines.index("END:VEVENT") + 1]
    assert "UID:cmp_1-2026-11-07@delve" in event and "DTSTAMP:20261101T120000Z" in event
    assert "DTSTART:20261107T190000Z" in event and "DTEND:20261107T210000Z" in event
    assert "SUMMARY:Tuesday" in event and "URL:https://delve.party/play/cmp_1" in event


def test_names_are_escaped_and_long_lines_folded_within_75_octets():
    name = "Ruins, of; Adventure\\ — Phlan's night\nwatch " * 3
    text = calendar_file("cmp_1", name, [SESSION], NOW)
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))
    summary = next(line for line in lines_of(text) if line.startswith("SUMMARY:"))
    assert summary.startswith("SUMMARY:Ruins\\, of\\; Adventure\\\\ — Phlan's night\\nwatch ")


def test_no_sessions_is_an_empty_calendar():
    lines = lines_of(calendar_file("cmp_1", "Tuesday", [], NOW))
    assert "BEGIN:VEVENT" not in lines and lines[-1] == "END:VCALENDAR"
