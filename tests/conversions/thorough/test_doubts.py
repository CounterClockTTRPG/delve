"""A thorough conversion's doubts gathered from `doubts/` (thorough conversion Task 6)."""

import json

from delve.conversions.thorough.doubts import UNREADABLE, gather
from delve.conversions.thorough.workspace import Workspace
from tests.fixtures.pdfs import text_page, write_pdf


def _workspace(tmp_path) -> Workspace:
    pdf = write_pdf(tmp_path / "upload.pdf", [text_page(["# The Caves", "## 1. Entrance"])])
    return Workspace.create("cnv_000000000001", tmp_path / "data", pdf, options={"mode": "ready", "title": "Caves"})


def _write(ws: Workspace, name: str, text: str) -> None:
    path = ws.root / "doubts" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


def test_the_doubts_come_in_the_stages_order_each_with_its_piece(tmp_path):
    ws = _workspace(tmp_path)
    for name in ("describe", "trace-house", "clean-2", "clean-1.skipped", "sort"):
        _write(ws, name, json.dumps([{"part": "house", "pages": [3], "kind": "missing-room", "text": name}]))

    assert [(d["piece"], d["text"]) for d in gather(ws)] == [
        ("sort", "sort"),
        ("clean-1", "clean-1.skipped"),
        ("clean-2", "clean-2"),
        ("trace-house", "trace-house"),
        ("describe", "describe"),
    ]


def test_a_doubt_is_kept_in_shape_and_never_lost(tmp_path):
    """An unknown kind is `other`, a page that isn't a number is dropped, a missing part is the piece's, and a file
    that isn't a list of doubts is one doubt itself."""
    ws = _workspace(tmp_path)
    _write(ws, "clean-1", json.dumps([{"pages": [2, "3", True, 4], "kind": "guessed", "text": None}]))
    _write(ws, "trace-house", "{not json")

    assert gather(ws) == [
        {"piece": "clean-1", "part": "clean-1", "pages": [2, 4], "kind": "other", "text": ""},
        {"piece": "trace-house", "part": "trace-house", "pages": [], "kind": "other", "text": UNREADABLE},
    ]


def test_no_doubts_folder_is_no_doubts(tmp_path):
    assert gather(_workspace(tmp_path)) == []
