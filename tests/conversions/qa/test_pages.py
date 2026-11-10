"""`delve qa pages` (thorough conversion Task 3): the PDF's pages as `p-NNN.png` and their text layer as `ocr-NNN.txt`."""

from pathlib import Path

import pytest
from PIL import Image

from delve.__main__ import main
from tests.fixtures.pdfs import picture_page, text_page, write_pdf


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_pdf(
        tmp_path / "book.pdf",
        [
            text_page(["1. THE HALL", "Dusty benches line the walls of this long hall."]),
            picture_page(),
            text_page(["2. THE KITCHEN", "A cold hearth and a rusty pot."]),
        ],
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_pages_renders_and_reads_text(folder: Path) -> None:
    assert main(["qa", "pages", "book.pdf", "pages", "--dpi", "150"]) == 0
    for n in (1, 2, 3):
        with Image.open(folder / "pages" / f"p-00{n}.png") as image:
            assert image.width == round(612 * 150 / 72)
    assert "Dusty benches line the walls" in (folder / "pages" / "ocr-001.txt").read_text()
    assert (folder / "pages" / "ocr-002.txt").read_text() == ""  # a picture, and OCR is off in tests
    assert "rusty pot" in (folder / "pages" / "ocr-003.txt").read_text()


def test_pages_renders_a_range_at_another_dpi(folder: Path) -> None:
    assert main(["qa", "pages", "book.pdf", "scan", "--dpi", "200", "--first", "2", "--last", "2"]) == 0
    assert sorted(p.name for p in (folder / "scan").iterdir()) == ["ocr-002.txt", "p-002.png"]
    with Image.open(folder / "scan" / "p-002.png") as image:
        assert image.width == round(612 * 200 / 72)


def test_pages_refuses_a_range_the_book_lacks(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["qa", "pages", "book.pdf", "pages", "--first", "2", "--last", "9"]) == 1
    assert "pages 1 to 3" in capsys.readouterr().err
