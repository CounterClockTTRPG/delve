"""dmap CLI integration."""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from delve.maps.dsl.cli import main
from tests.fixtures import SAMPLES



def test_renderers_command(capsys):
    rc = main(["renderers"])
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert "classic-bw" in out
    assert "floorplan" in out


def test_render_to_file(tmp_path):
    out = tmp_path / "crypt.svg"
    rc = main(["render", str(SAMPLES / "crypt.dmap"), "-o", str(out)])
    assert rc == 0
    text = out.read_text()
    assert text.startswith("<svg")
    assert "Entry Hall" in text


def test_render_to_stdout(capsys):
    rc = main(["render", str(SAMPLES / "cottage.dmap"), "-o", "-"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("<svg")


def test_render_from_stdin(monkeypatch, capsys):
    src = (SAMPLES / "cottage.dmap").read_text()
    monkeypatch.setattr("sys.stdin", io.StringIO(src))
    rc = main(["render", "-", "-o", "-"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("<svg")


def test_render_uses_override_renderer(tmp_path):
    out = tmp_path / "c.svg"
    rc = main([
        "render", str(SAMPLES / "cottage.dmap"),
        "-o", str(out),
        "--renderer", "classic-bw",
    ])
    assert rc == 0
    assert out.read_text().startswith("<svg")


def test_render_missing_file(capsys):
    rc = main(["render", "/nope/missing.dmap", "-o", "-"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "No such file" in err or "missing" in err.lower()


def test_render_bad_input_returns_one(tmp_path, capsys):
    bad = tmp_path / "bad.dmap"
    bad.write_text('map "X" {')  # truncated
    rc = main(["render", str(bad), "-o", "-"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "parse error" in err


def test_validate_command_clean_sample(capsys):
    rc = main(["validate", str(SAMPLES / "crypt.dmap")])
    assert rc == 0


def test_unknown_renderer_exits_one(tmp_path, capsys):
    rc = main([
        "render", str(SAMPLES / "crypt.dmap"),
        "-o", "-",
        "--renderer", "no-such",
    ])
    err = capsys.readouterr().err
    assert rc == 1
    assert "unknown renderer" in err


def _map_with_a_file_include(folder: Path, include: str = "lib.dmap") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "lib.dmap").write_text('feature_def "disk_thing" { shape circle radius 0.5 }\n')
    path = folder / "main.dmap"
    path.write_text(f'include "{include}"\nmap "T" {{ grid {{ bounds 5 x 5 }} }}\nroom "r" {{ rect 0,0 4 x 4 }}\n')
    return path


def test_cli_reads_includes_under_the_inputs_folder(tmp_path, capsys):
    """The command line opts in to file includes (DEL-154): under the
    input's own folder by default, under --include-root when given."""
    path = _map_with_a_file_include(tmp_path / "maps")
    assert main(["validate", str(path)]) == 0
    assert main(["render", str(path), "-o", str(tmp_path / "out.svg")]) == 0
    outside = _map_with_a_file_include(tmp_path / "maps" / "sub", "../lib.dmap")
    assert main(["validate", str(outside)]) == 1
    assert "outside the include root" in capsys.readouterr().err
    assert main(["validate", str(outside), "--include-root", str(tmp_path / "maps")]) == 0


def test_cli_reads_includes_from_stdin_under_the_working_directory(tmp_path, monkeypatch):
    path = _map_with_a_file_include(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO(path.read_text()))
    assert main(["validate", "-"]) == 0
