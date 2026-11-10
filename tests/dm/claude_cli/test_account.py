"""The Claude account's usage from the CLI's `rate_limit_event`, kept for the host's play header."""

import json

import pytest

from delve.dm.claude_cli import account
from delve.dm.claude_cli.provider import _stream_answer
from delve.dm.claude_cli.stream import parse_line

# As `claude -p --output-format stream-json` sent it on 2026-10-24.
EVENT = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "resetsAt": 1792834200,
        "rateLimitType": "five_hour",
        "overageStatus": "rejected",
        "isUsingOverage": False,
        "unifiedWindows": {
            "seven_day": {"utilization": 0.41, "resetsAt": 1793232000, "status": "allowed"},
            "five_hour": {"utilization": 0.82, "resetsAt": 1792834200, "status": "allowed"},
        },
    },
    "session_id": "fcbae564",
}


@pytest.fixture(autouse=True)
def fresh():
    account.reset()
    yield
    account.reset()


def test_the_windows_soonest_reset_first():
    assert account.usage(EVENT["rate_limit_info"], at="2026-10-24T07:40:00Z") == {
        "at": "2026-10-24T07:40:00Z",
        "status": "allowed",
        "windows": [
            {"name": "five_hour", "utilization": 0.82, "resets_at": "2026-10-24T09:30:00Z"},
            {"name": "seven_day", "utilization": 0.41, "resets_at": "2026-10-29T00:00:00Z"},
        ],
    }


def test_without_unified_windows_the_events_own_window_with_its_share_unknown():
    shown = account.usage({"status": "allowed_warning", "resetsAt": 1792834200, "rateLimitType": "five_hour"})
    assert shown is not None
    assert shown["windows"] == [{"name": "five_hour", "utilization": None, "resets_at": "2026-10-24T09:30:00Z"}]
    assert account.usage({"status": "allowed"}) is None
    assert account.usage(None) is None


def test_noted_usage_is_kept_in_the_data_dir_across_a_restart(tmp_path):
    account.configure(tmp_path)
    assert account.latest() is None
    assert account.note(EVENT) is True
    assert account.note({"type": "result"}) is False
    kept = json.loads((tmp_path / account.FILE).read_text())
    assert kept["windows"][0]["utilization"] == 0.82

    account.reset()
    account.configure(tmp_path)
    assert account.latest() == kept


def test_every_reader_of_the_stream_notes_it():
    assert parse_line(EVENT) == []
    assert account.latest()["windows"][0]["name"] == "five_hour"

    account.reset()
    lines = "\n".join(json.dumps(obj) for obj in (EVENT, {"type": "result", "result": "ok", "usage": {}}))
    assert _stream_answer(lines)[0] == "ok"
    assert account.latest() is not None
