"""`delve qa mapcheck`, `rotate` and `tile` (thorough conversion Task 3): a traced map parsed, validated, its doors
mended and drawn as SVG and PNG with no browser; a scan turned and cut with a numbered grid."""

import shutil
from pathlib import Path

import pytest
from PIL import Image

from delve.__main__ import main
from delve.conversions.qa.mapcheck import fix_doors
from tests.fixtures import SAMPLES

APART = """map "Two rooms" {
  grid {
    cell 32 px
    bounds 20 x 10
  }
  renderer "classic-bw"
}
room "r1" { rect 1,1 4 x 4 }
room "r2" { rect 7,1 4 x 4 }
room "r3" { rect 11,1 4 x 4 }
door between room.r2 and room.r3 { type wooden }
door between room.r1 and room.r2 { type secret }
"""


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "maps").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_mapcheck_renders_png_without_browser(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copy(SAMPLES / "crypt.dmap", folder / "maps" / "crypt.dmap")
    assert main(["qa", "mapcheck", "maps/crypt.dmap"]) == 0
    out = capsys.readouterr().out
    assert "rooms 3" in out and "drawn: crypt.svg, crypt.png" in out
    assert (folder / "maps" / "crypt.svg").read_text().startswith("<svg")
    with Image.open(folder / "maps" / "crypt.png") as image:
        assert image.format == "PNG" and image.width == 1200
        assert len(image.convert("L").getcolors(65536) or []) > 2  # drawn, not blank


def test_mapcheck_reports_errors_with_exit_1(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (folder / "maps" / "apart.dmap").write_text(APART)
    assert main(["qa", "mapcheck", "maps/apart.dmap"]) == 1
    assert "they don't meet" in capsys.readouterr().out
    assert not (folder / "maps" / "apart.png").exists()


def test_mapcheck_fix_doors_moves_doors_between_rooms_that_dont_meet(
    folder: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (folder / "maps" / "apart.dmap").write_text(APART)
    assert main(["qa", "mapcheck", "maps/apart.dmap", "--fix-doors"]) == 0
    out = capsys.readouterr().out
    assert "door: r1-r2" in out and "r2-r3" not in out
    source = (folder / "maps" / "apart.dmap").read_text()
    assert "door at 6.0,3.0 { connects room.r1, room.r2 type secret }" in source
    assert "door between room.r2 and room.r3 { type wooden }" in source
    assert (folder / "maps" / "apart.png").exists()


def test_fix_doors_leaves_a_map_that_doesnt_parse() -> None:
    assert fix_doors("map {") == ("map {", [])


def test_rotate_and_tile(folder: Path) -> None:
    Image.new("RGB", (300, 200), "white").save(folder / "scan.png")
    assert main(["qa", "rotate", "scan.png", "rot.png", "90"]) == 0
    with Image.open(folder / "rot.png") as image:
        assert image.size == (200, 300)
    assert main(["qa", "tile", "rot.png", "tile.png", "0", "0", "4", "6", "50", "0", "0", "100"]) == 0
    with Image.open(folder / "tile.png") as image:
        assert image.size == (67, 100)
        red, green, _ = image.getpixel((0, 50))
        assert red > 200 and red - green > 80  # column 0's red line
