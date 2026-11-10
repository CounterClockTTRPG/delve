"""`delve qa` reads and writes only in the job folder (thorough conversion Task 3, review focus 4): an absolute path out,
`..`, and a symlink out are each refused with exit code 2, for every command, before anything is read or written."""

import os
from pathlib import Path

import pytest

from delve.__main__ import main
from delve.conversions.qa.paths import OutsideFolder, inside


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    outside = tmp_path / "data"
    outside.mkdir()
    (outside / "delve.db").write_text("SECRET-XYZZY")
    (outside / "notes.md").write_text("## 1. Out {#1}\n")
    job = outside / "conversions" / "cnv_1"
    job.mkdir(parents=True)
    (job / "parts.json").write_text("[]")
    (job / "clean").mkdir()
    (job / "clean" / "house.md").write_text("## 1. Hall {#1}\n")
    (job / "maps").mkdir()
    os.symlink(outside / "notes.md", job / "clean" / "link.md")
    os.symlink(outside, job / "out")
    monkeypatch.chdir(job)
    return job


OUTSIDE = [
    pytest.param(str(Path.home() / "x.md"), id="absolute"),
    pytest.param("../../delve.db", id="dotdot"),
    pytest.param("clean/link.md", id="symlink-file"),
    pytest.param("out/delve.db", id="symlink-dir"),
]


def commands(bad: str) -> list[list[str]]:
    return [
        ["textcheck", "parts.json", bad],
        ["textcheck", bad, "clean/house.md"],
        ["textcheck", "parts.json", "clean/house.md", "--pages", bad],
        ["keys", bad, "--pattern", r"^\d+"],
        ["pages", bad, "pages"],
        ["pages", "book.pdf", bad],
        ["rotate", bad, "r.png", "90"],
        ["rotate", "in.png", bad, "90"],
        ["tile", bad, "t.png", "0", "0", "2", "2", "10", "0", "0", "100"],
        ["mapcheck", bad],
        ["join", bad, "joined"],
        ["join", "maps", bad],
    ]


@pytest.mark.parametrize("bad", OUTSIDE)
def test_qa_refuses_paths_outside_folder(folder: Path, bad: str, capsys: pytest.CaptureFixture[str]) -> None:
    before = sorted(p.name for p in folder.parent.parent.rglob("*"))
    for argv in commands(bad):
        assert main(["qa", *argv]) == 2, argv
        assert "outside the job folder" in capsys.readouterr().err
    assert sorted(p.name for p in folder.parent.parent.rglob("*")) == before
    assert (folder.parent.parent / "delve.db").read_text() == "SECRET-XYZZY"


def test_mapcheck_refuses_drawing_through_a_symlink_out(folder: Path) -> None:
    """The `.svg` and `.png` beside a map are paths too: a symlink there that points out is refused."""
    (folder / "maps" / "a.dmap").write_text('map "A" {\n  grid {\n    bounds 4 x 4\n  }\n}\n')
    os.symlink(folder.parent.parent / "delve.db", folder / "maps" / "a.png")
    assert main(["qa", "mapcheck", "maps/a.dmap"]) == 2
    assert (folder.parent.parent / "delve.db").read_text() == "SECRET-XYZZY"


def test_inside_resolves_paths_in_the_folder(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    assert inside(tmp_path, "a/../b.md") == (tmp_path / "b.md").resolve()
    assert inside(tmp_path, str(tmp_path / "a")) == (tmp_path / "a").resolve()
    assert inside(tmp_path, ".") == tmp_path.resolve()
    with pytest.raises(OutsideFolder):
        inside(tmp_path / "a", "../b.md")
