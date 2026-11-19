"""Snapshot files that freeze what OSRIC and 2e store and send (DEL-383): a test compares its text with the file, and
`DELVE_REGOLDEN=1` writes the file instead. A regenerated snapshot is reviewed, and the commit says why it changed."""

from __future__ import annotations

import difflib
import os
from pathlib import Path


def assert_snapshot(path: Path, actual: str) -> None:
    """`actual` equals the text of `path`; with `DELVE_REGOLDEN=1`, write it there and pass."""
    if os.environ.get("DELVE_REGOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return
    if not path.exists():
        raise AssertionError(f"no snapshot {path}; make it with DELVE_REGOLDEN=1 and review it")
    expected = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True), actual.splitlines(keepends=True), str(path), "actual", n=2
            )
        )
        raise AssertionError(f"{path.name} changed (DELVE_REGOLDEN=1 to accept, after review):\n{diff[:6000]}")
