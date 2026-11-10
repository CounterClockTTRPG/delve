"""The job folder of a thorough conversion (thorough conversion Task 4): what it holds at the start, and `state.json`,
Delve's record of the finished stages and pieces."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from delve.conversions.thorough.workspace import Workspace, install_qa, qa_path, qa_wrapper
from tests.fixtures.pdfs import text_page, write_pdf


def _workspace(tmp_path) -> Workspace:
    pdf = write_pdf(tmp_path / "upload.pdf", [text_page(["# The Caves", "## 1. Entrance"])])
    return Workspace.create("cnv_000000000001", tmp_path / "data", pdf, options={"mode": "ready", "title": "Caves"})


def test_the_folder_holds_the_book_the_qa_wrapper_and_the_reference(tmp_path):
    ws = _workspace(tmp_path)

    assert ws.root == tmp_path / "data" / "conversions" / "cnv_000000000001"
    assert (ws.root / "book.pdf").read_bytes() == (tmp_path / "upload.pdf").read_bytes()
    assert not (ws.root / "qa").exists(), "the wrapper is outside the folder, where no agent can change it"
    assert qa_path(tmp_path / "data").stat().st_mode & 0o777 == 0o755
    ref = sorted(p.name for p in (ws.root / "ref").iterdir())
    assert "dsl.md" in ref and "dsl-map.md" in ref
    assert len([name for name in ref if name.endswith(".dmap")]) == 3
    assert (ws.root / "doubts").is_dir()
    state = ws.state()
    assert (state.stages, state.pieces, state.paused, state.options) == (
        {},
        {},
        None,
        {"mode": "ready", "title": "Caves"},
    )


def test_state_records_pieces_stages_and_the_pause(tmp_path):
    ws = _workspace(tmp_path)

    ws.failed("clean-1", "claude stopped", cost=0.5)
    ws.done("clean-1", 1.25, ["clean/house.md"])
    ws.failed("trace-house", "Missing: maps/house.dmap")
    ws.skipped("trace-house", "Skipped")
    ws.began("clean-2")
    ws.began("trace-ship")
    ws.done("clean-2", 0.25, [])
    ws.stage_done("reading")
    ws.pause("Delve stopped")

    assert ws.is_done("clean-1") and ws.is_done("trace-house") and not ws.is_done("trace-ship")
    assert ws.is_stage_done("reading") and not ws.is_stage_done("cleaning")
    stored = json.loads((ws.root / "state.json").read_text())
    assert stored == {
        "stages": {"reading": "done"},
        "pieces": {
            "clean-1": {
                "status": "done",
                "attempts": 2,
                "cost_usd": 1.75,
                "outputs": ["clean/house.md"],
                "error": None,
                "tokens": None,
            },
            "clean-2": {
                "status": "done",
                "attempts": 1,
                "cost_usd": 0.25,
                "outputs": [],
                "error": None,
                "tokens": None,
            },
            "trace-house": {
                "status": "skipped",
                "attempts": 1,
                "cost_usd": None,
                "outputs": [],
                "error": "Skipped",
                "tokens": None,
            },
        },
        "paused": {"reason": "Delve stopped", "resets_at": None},
        "options": {"mode": "ready", "title": "Caves"},
        "stopped": [],
        "running": ["trace-ship"],
    }
    ws.resumed()
    assert ws.state().paused is None
    assert not (ws.root / "state.json.partial").exists(), "written beside it and renamed over it"


def test_remove_deletes_the_folder(tmp_path):
    ws = _workspace(tmp_path)
    ws.remove()
    assert not ws.root.exists() and not ws.exists()


def test_qa_wrapper_runs_delve_qa(tmp_path):
    """The wrapper is `<data dir>/bin/qa`, outside every job folder (review finding 1), and run from the folder."""
    ws = _workspace(tmp_path)
    planted = ws.root / "delve"
    planted.mkdir()
    (planted / "__init__.py").write_text("")
    (planted / "__main__.py").write_text("print('PLANTED')\n")
    qa = qa_path(tmp_path / "data")
    assert qa == tmp_path / "data" / "bin" / "qa" and not qa.is_relative_to(ws.root)

    ran = subprocess.run([str(qa), "--help"], check=False, cwd=ws.root, capture_output=True, text=True, timeout=60)

    said = ran.stdout + ran.stderr
    assert "PLANTED" not in said, "a delve/ written into the folder is never run in Delve's place"
    assert "usage: delve" in said and "qa" in said
    assert qa_wrapper("/opt/py thon").splitlines() == ["#!/bin/sh", "exec '/opt/py thon' -I -m delve qa \"$@\""]
    assert os.access(qa, os.X_OK)


def test_install_qa_points_the_wrapper_at_this_delve(tmp_path):
    """U1: a job made by one install (another worktree, an older venv) and run by another runs this one's tools; each
    agent session's runner installs the wrapper again, unchanged when it is right."""
    qa = qa_path(tmp_path / "data")
    qa.parent.mkdir(parents=True)
    qa.write_text(qa_wrapper("/gone/venv/bin/python"), "utf-8")
    qa.chmod(0o644)

    assert install_qa(tmp_path / "data") == qa
    assert qa.read_text("utf-8") == qa_wrapper() and os.access(qa, os.X_OK)


def test_resume_drops_the_wrapper_an_older_folder_holds(tmp_path):
    """A folder made before the wrapper moved out has a `./qa` of its own; the resume removes it and installs
    `<data dir>/bin/qa` for this Delve."""
    ws = _workspace(tmp_path)
    (ws.root / "qa").write_text(qa_wrapper("/gone/venv/bin/python"), "utf-8")
    qa_path(tmp_path / "data").unlink()

    ws.resumed()

    assert not (ws.root / "qa").exists()
    assert qa_path(tmp_path / "data").read_text("utf-8") == qa_wrapper()


def test_the_pictures_are_page_numbers_or_objects_with_their_page(tmp_path):
    ws = _workspace(tmp_path)
    maps = [{"name": "hommlet", "title": "Map 2: Village of Hommlet", "page": 131}, {"title": "no page"}]
    ws.write_json("parts.json", {"parts": [], "pictures": [130, *maps, "3", True]})

    assert ws.pictures() == [130, 131], "as the sort of the Temple of Elemental Evil wrote them, like its maps"


def test_a_json_file_is_written_whole_or_not_at_all(tmp_path, monkeypatch):
    """A write that stops halfway (Delve stopping, a full disk) leaves the file as it was, not half of it."""
    ws = _workspace(tmp_path)
    ws.write_json("entities.json", {"entities": {"npcs": [{"id": "ned"}]}})
    write_text = Path.write_text

    def half(path, text, *args, **kwargs):
        write_text(path, text[: len(text) // 2], *args, **kwargs)
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "write_text", half)
    with pytest.raises(OSError):
        ws.write_json("entities.json", {"entities": {"npcs": [{"id": "ned"}, {"id": "the-bosun"}]}})
    monkeypatch.undo()

    assert ws.read_json("entities.json") == {"entities": {"npcs": [{"id": "ned"}]}}
