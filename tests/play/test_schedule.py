"""The table's schedule (DEL-204 part C): a rule (every N weeks from a first date, a local start and end in a time zone)
with the host's changes to single sessions, moved or skipped; the next sessions as instants, so a daylight-saving
change keeps the local time; and moving, skipping or resetting the next session."""

from datetime import UTC, datetime

import pytest

from delve.play import schedule
from delve.play.context import PlayError

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
FORTNIGHTLY = {"every_weeks": 2, "first": "2026-11-07", "start": "20:00", "end": "22:00", "time_zone": "Europe/Brussels"}


def _rule(**changes):
    return schedule.parse({**FORTNIGHTLY, **changes}, NOW)


def _times(sessions):
    return [(s["on"], s["starts_at"], s["ends_at"], s["moved"]) for s in sessions]


# ----- checking a schedule -----


def test_a_schedule_is_kept_with_its_changes_in_order():
    checked = _rule(changes=[{"on": "2026-12-05", "to": None}, {"on": "2026-11-21", "to": "2026-11-22T19:00"}])
    assert checked == {
        **FORTNIGHTLY,
        "changes": [{"on": "2026-11-21", "to": "2026-11-22T19:00"}, {"on": "2026-12-05", "to": None}],
    }
    assert _rule() == {**FORTNIGHTLY, "changes": []}, "without changes, none"
    assert schedule.parse(None, NOW) is None, "null: no schedule"


def test_changes_in_the_past_are_dropped():
    late = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    checked = schedule.parse(
        {**FORTNIGHTLY, "changes": [{"on": "2026-11-07", "to": None}, {"on": "2026-11-21", "to": "2026-11-22T19:00"}]},
        late,
    )
    assert checked["changes"] == [{"on": "2026-11-21", "to": "2026-11-22T19:00"}], "the moved one is still to come"
    gone = schedule.parse({**FORTNIGHTLY, "changes": [{"on": "2026-11-21", "to": "2026-11-21T10:00"}]}, late)
    assert gone["changes"] == [], "moved to a time already over"


@pytest.mark.parametrize(
    "wrong",
    [
        {"every_weeks": 0},
        {"every_weeks": 5},
        {"every_weeks": "2"},
        {"every_weeks": True},
        {"first": "2026-11-31"},
        {"first": "20261107"},
        {"first": None},
        {"start": "8pm"},
        {"start": "24:00"},
        {"end": "20:00"},
        {"end": "22:0"},
        {"time_zone": "Europe/Atlantis"},
        {"time_zone": "../etc/passwd"},
        {"time_zone": ""},
        {"time_zone": 1},
        {"changes": [{"on": "2026-11-14", "to": None}]},
        {"changes": [{"on": "2026-10-24", "to": None}]},
        {"changes": [{"on": "2026-11-21", "to": "2026-11-22 19:00"}]},
        {"changes": [{"on": "2026-11-21", "to": "2026-11-22T25:00"}]},
        {"changes": [{"on": "2026-11-21"}]},
        {"changes": [{"on": "2026-11-21", "to": None, "why": "holiday"}]},
        {"changes": [{"on": "2026-11-21", "to": None}, {"on": "2026-11-21", "to": "2026-11-22T19:00"}]},
        {"changes": {"on": "2026-11-21", "to": None}},
        {"weekday": "saturday"},
    ],
)
def test_a_wrong_schedule_is_refused(wrong):
    with pytest.raises(PlayError):
        schedule.parse({**FORTNIGHTLY, **wrong}, NOW)


def test_a_schedule_needs_every_field():
    for key in FORTNIGHTLY:
        with pytest.raises(PlayError):
            schedule.parse({k: v for k, v in FORTNIGHTLY.items() if k != key}, NOW)
    with pytest.raises(PlayError):
        schedule.parse(["every", 2], NOW)


# ----- the next sessions -----


def test_every_two_weeks_in_utc():
    assert _times(schedule.next_sessions(_rule(), NOW, 3)) == [
        ("2026-11-07", "2026-11-07T19:00:00+00:00", "2026-11-07T21:00:00+00:00", False),
        ("2026-11-21", "2026-11-21T19:00:00+00:00", "2026-11-21T21:00:00+00:00", False),
        ("2026-12-05", "2026-12-05T19:00:00+00:00", "2026-12-05T21:00:00+00:00", False),
    ]
    later = datetime(2027, 3, 1, tzinfo=UTC)
    assert [s["on"] for s in schedule.next_sessions(_rule(), later, 2)] == ["2027-03-13", "2027-03-27"]
    assert schedule.next_sessions(None, NOW, 3) == [], "no schedule, no sessions"


def test_a_moved_and_a_skipped_session():
    changed = _rule(changes=[{"on": "2026-11-21", "to": "2026-11-22T19:00"}, {"on": "2026-12-05", "to": None}])
    assert _times(schedule.next_sessions(changed, NOW, 3)) == [
        ("2026-11-07", "2026-11-07T19:00:00+00:00", "2026-11-07T21:00:00+00:00", False),
        ("2026-11-21", "2026-11-22T18:00:00+00:00", "2026-11-22T20:00:00+00:00", True),
        ("2026-12-19", "2026-12-19T19:00:00+00:00", "2026-12-19T21:00:00+00:00", False),
    ]


def test_a_session_moved_past_the_next_comes_in_its_order():
    changed = _rule(changes=[{"on": "2026-11-07", "to": "2026-11-28T20:00"}])
    assert [(s["on"], s["starts_at"][:10]) for s in schedule.next_sessions(changed, NOW, 3)] == [
        ("2026-11-21", "2026-11-21"),
        ("2026-11-07", "2026-11-28"),
        ("2026-12-05", "2026-12-05"),
    ]


def test_a_session_past_midnight_ends_the_next_day_and_counts_until_then():
    late = _rule(every_weeks=1, start="22:00", end="01:00")
    first = schedule.next_sessions(late, NOW, 1)[0]
    assert (first["starts_at"], first["ends_at"]) == ("2026-11-07T21:00:00+00:00", "2026-11-08T00:00:00+00:00")
    playing = datetime(2026, 11, 7, 23, 30, tzinfo=UTC)
    assert schedule.next_sessions(late, playing, 1)[0]["on"] == "2026-11-07", "not yet ended"
    over = datetime(2026, 11, 8, 0, 0, tzinfo=UTC)
    assert schedule.next_sessions(late, over, 1)[0]["on"] == "2026-11-14"


def test_a_daylight_saving_change_keeps_the_local_time():
    """Europe/Brussels leaves summer time on the last Sunday of October, 2026-10-25: 20:00 is 18:00 UTC before it and
    19:00 UTC from that day on."""
    weekly = schedule.parse(
        {"every_weeks": 1, "first": "2026-10-18", "start": "20:00", "end": "23:00", "time_zone": "Europe/Brussels"},
        datetime(2026, 10, 1, tzinfo=UTC),
    )
    sessions = schedule.next_sessions(weekly, datetime(2026, 10, 1, tzinfo=UTC), 3)
    assert [(s["starts_at"], s["ends_at"]) for s in sessions] == [
        ("2026-10-18T18:00:00+00:00", "2026-10-18T21:00:00+00:00"),
        ("2026-10-25T19:00:00+00:00", "2026-10-25T22:00:00+00:00"),
        ("2026-11-01T19:00:00+00:00", "2026-11-01T22:00:00+00:00"),
    ]


def test_sessions_before_the_first_date_there_are_none():
    early = datetime(2026, 1, 1, tzinfo=UTC)
    assert schedule.next_sessions(_rule(), early, 1)[0]["on"] == "2026-11-07"


# ----- changing the next session -----


def test_skipping_the_next_session():
    skipped = schedule.change_next(_rule(), NOW, skip=True)
    assert skipped["changes"] == [{"on": "2026-11-07", "to": None}]
    assert [s["on"] for s in schedule.next_sessions(skipped, NOW, 2)] == ["2026-11-21", "2026-12-05"]
    twice = schedule.change_next(skipped, NOW, skip=True)
    assert twice["changes"] == [{"on": "2026-11-07", "to": None}, {"on": "2026-11-21", "to": None}]


def test_moving_the_next_session_keeps_its_length():
    moved = schedule.change_next(_rule(), NOW, to="2026-11-08T18:30")
    assert moved["changes"] == [{"on": "2026-11-07", "to": "2026-11-08T18:30"}]
    first = schedule.next_sessions(moved, NOW, 1)[0]
    assert (first["starts_at"], first["ends_at"], first["moved"]) == (
        "2026-11-08T17:30:00+00:00",
        "2026-11-08T19:30:00+00:00",
        True,
    )
    again = schedule.change_next(moved, NOW, to="2026-11-07T20:00")
    assert again["changes"] == [], "moved back to its own time: no change"


def test_the_next_session_is_the_next_not_yet_started():
    playing = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)
    assert schedule.change_next(_rule(), playing, skip=True)["changes"] == [{"on": "2026-11-21", "to": None}]


def test_moving_to_the_past_or_a_bad_time_is_refused():
    for wrong in ("2026-11-01T12:00", "2026-10-30T20:00", "2026-11-08", "tomorrow", "2026-11-08T18:30:00"):
        with pytest.raises(PlayError):
            schedule.change_next(_rule(), NOW, to=wrong)


def test_resetting_drops_the_change_of_the_next_session():
    moved = schedule.change_next(_rule(), NOW, to="2026-11-08T18:30")
    assert schedule.change_next(moved, NOW, reset=True)["changes"] == []
    skipped = schedule.change_next(schedule.change_next(_rule(), NOW, skip=True), NOW, skip=True)
    once = schedule.change_next(skipped, NOW, reset=True)
    assert once["changes"] == [{"on": "2026-11-07", "to": None}], "the skip nearest the next session first"
    assert schedule.change_next(once, NOW, reset=True)["changes"] == []
    later = _rule(changes=[{"on": "2026-12-05", "to": None}])
    assert schedule.change_next(later, NOW, reset=True) == later, "a later change isn't the next session's"
