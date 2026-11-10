"""The Claude account's usage, from the `rate_limit_event` every `claude -p` turn sends: each window (the 5-hour one,
the weekly one when it applies) with its share used and its reset, as Guild reads it (`lib/limits.js` accountUsage).

Every reader of the CLI's stream (the DM's resident process, one-shot calls, the thorough conversion's agents) hands
its lines to `note`; the latest usage is kept for the process and in `<data dir>/account.json` once `configure` named
it, so a restart still shows it. The host reads it on the play screen (`GET /api/campaigns/{id}/play/usage`).
"""

from __future__ import annotations

import contextlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILE = "account.json"

_lock = threading.Lock()
_path: Path | None = None
_latest: dict[str, Any] | None = None


def configure(data_dir: Path) -> None:
    """Keep the usage in `data_dir`, and start from what is kept there."""
    global _path, _latest
    with _lock:
        _path, _latest = data_dir / FILE, None
        with contextlib.suppress(OSError, ValueError):
            kept = json.loads(_path.read_text("utf-8"))
            if isinstance(kept, dict) and isinstance(kept.get("windows"), list):
                _latest = kept


def latest() -> dict[str, Any] | None:
    """`{at, status, windows: [{name, utilization (0..1 or None), resets_at}]}`, soonest reset first; None before any."""
    return _latest


def limit_resets_at() -> str | None:
    """When the usage limit ends: the latest reset of the windows that are full (used up, or of a share unknown in a
    usage the limit refused), from the last usage kept; None without such a window (table voice and fixes Task D1)."""
    kept = _latest
    if kept is None:
        return None
    full = [
        w["resets_at"]
        for w in kept.get("windows", [])
        if (w.get("utilization") is None and kept.get("status") == "rejected") or (w.get("utilization") or 0) >= 1
    ]
    return max(full) if full else None


def _iso(epoch: Any) -> str | None:
    if isinstance(epoch, bool) or not isinstance(epoch, int | float) or epoch <= 0:
        return None
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def usage(info: Any, at: str | None = None) -> dict[str, Any] | None:
    """A `rate_limit_info` as the usage shown; None without a window to show."""
    if not isinstance(info, dict):
        return None
    windows = []
    for name, window in (info.get("unifiedWindows") or {}).items():
        resets_at = _iso((window or {}).get("resetsAt"))
        if resets_at:
            share = window.get("utilization")
            utilization = float(share) if isinstance(share, int | float) and not isinstance(share, bool) else None
            windows.append({"name": str(name), "utilization": utilization, "resets_at": resets_at})
    if not windows and info.get("rateLimitType") and _iso(info.get("resetsAt")):
        windows.append({"name": str(info["rateLimitType"]), "utilization": None, "resets_at": _iso(info["resetsAt"])})
    if not windows:
        return None
    windows.sort(key=lambda w: w["resets_at"])
    at = at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {"at": at, "status": str(info.get("status") or ""), "windows": windows}


def note(obj: Any) -> bool:
    """Keep the usage of a stream-json line if it is a `rate_limit_event`; True when it was one."""
    global _latest
    if not isinstance(obj, dict) or obj.get("type") != "rate_limit_event":
        return False
    shown = usage(obj.get("rate_limit_info"))
    if shown is None:
        return True
    with _lock:
        _latest = shown
        if _path is not None:
            with contextlib.suppress(OSError):
                temp = _path.with_suffix(".tmp")
                temp.write_text(json.dumps(shown), "utf-8")
                temp.replace(_path)
    return True


def reset() -> None:
    """For tests: forget the usage and where it is kept."""
    global _path, _latest
    with _lock:
        _path, _latest = None, None
