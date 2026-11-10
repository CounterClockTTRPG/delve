"""`delve qa keys` and `delve qa textcheck` (thorough conversion Task 3): the book's entries by a part's key pattern, and
each cleaned text's sections checked against them, with no Greyhawk constant left."""

import json
from pathlib import Path

import pytest

from delve.__main__ import main
from delve.conversions.qa.textcheck import book_keys, check_text, read_parts

HALL = "Dusty benches line the walls of this long hall, and a faded banner hangs above the cold fireplace."
KITCHEN = "A cold hearth and a rusty pot; rats scurry under the table when the door opens."
CELLAR = "Barrels of spoiled wine stand along the damp walls; one hides a smuggler's ladder going down."
DECK = "The ship's deck is slick with rain and the rigging creaks above the empty wheel."
CABIN = "The captain's cabin holds a chart table, a locked sea chest and a lantern still burning."


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "ocr-001.txt").write_text(f"THE HOUSE\n\n1. THE HALL\n{HALL}\n\n2. KITCHEN\n{KITCHEN}\n")
    (pages / "ocr-002.txt").write_text(f"l3. CELLAR\n{CELLAR}\n")  # the text layer read 13 as l3
    (pages / "ocr-003.txt").write_text(f"THE SHIP\n\n1. DECK\n{DECK}\n\n2, 3. CABIN\n{CABIN}\n")
    (pages / "ocr-004.txt").write_text("W501. A ROOM\nIt is empty.\n\nPl08 and P109. TWIN ROOMS\nAs W501.\n")
    parts = [
        {"id": "house", "title": "The House", "pages": [1, 2], "key_pattern": r"^\d+[a-z]?"},
        {"id": "ship", "title": "The Ship", "pages": [3, 3], "key_pattern": r"^\d+[a-z]?"},
        {"id": "front", "title": "Introduction", "pages": [1, 1], "key_pattern": None},
    ]
    (tmp_path / "parts.json").write_text(json.dumps({"parts": parts, "pictures": []}))
    (tmp_path / "clean").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_keys_by_pattern(folder: Path) -> None:
    numbers = book_keys(folder / "pages", r"^\d+[a-z]?", first=1, last=2)
    assert list(numbers) == ["1", "2", "13"]
    assert numbers["13"] == [(2, f"l3. CELLAR\n{CELLAR}")]
    assert HALL in numbers["1"][0][1] and KITCHEN not in numbers["1"][0][1]
    both = book_keys(folder / "pages", r"^\d+[a-z]?", first=1, last=3)
    assert [page for page, _ in both["1"]] == [1, 3]
    letters = book_keys(folder / "pages", r"^[WPZ][0-9B]\d\d[a-e]?")
    assert list(letters) == ["W501", "P108"]
    # Another part's key ends an entry: without it, W501 runs on into the P rooms.
    assert "TWIN" in book_keys(folder / "pages", r"^W\d\d\d")["W501"][0][1]
    stopped = book_keys(folder / "pages", r"^W\d\d\d", stops=[r"^P\d\d\d"])
    assert stopped == {"W501": [(4, "W501. A ROOM\nIt is empty.")]}


def test_keys_command_prints_json(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["qa", "keys", "pages", "--pattern", r"^\d+[a-z]?", "--first", "3", "--last", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"1", "2"}
    assert out["1"]["page"] == 3 and DECK in out["1"]["text"]


def test_keys_command_writes_big_output_to_a_file(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """U1: a part's entries ran to 64 KB, which the CLI keeps outside the folder, where the agent may not read it."""
    assert (
        main(["qa", "keys", "pages", "--pattern", r"^\d+[a-z]?", "--first", "3", "--last", "3", "--out", "k.json"]) == 0
    )
    said = capsys.readouterr().out.splitlines()
    assert json.loads((folder / "k.json").read_text())["1"]["page"] == 3
    assert said == ["1: page 3, 17 words", "2: page 3, 19 words", "2 keys written to k.json"]
    assert main(["qa", "keys", "pages", "--pattern", r"^\d+", "--out", "../k.json"]) == 2
    assert not (folder.parent / "k.json").exists()


def test_textcheck_flags_missing_and_foreign(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (folder / "clean" / "house.md").write_text(
        "# The House\n\n"
        f"## 1. The Hall {{#1}}\n\n> {HALL}\n\n"
        f"## 13. Cellar {{#13}}\n\n{CABIN} {DECK} {KITCHEN}\n\n"
        "## 2 Kitchen\n\nA heading without its full stop.\n\n"
        "## 4. Attic {#attic}\n\nA wrong anchor.\n\n"
        "## The grounds\n\nAn unkeyed heading is fine.\n"
    )
    (folder / "clean" / "ship.md").write_text(
        f"# The Ship\n\n## 1. Deck {{#1}}\n\n{DECK}\n\n## 2. Cabin {{#2}}\n\n{CABIN}\n"
    )
    assert main(["qa", "textcheck", "parts.json", "clean/house.md", "clean/ship.md"]) == 1
    out = capsys.readouterr().out
    house, ship = out.split("== ship.md")
    assert "== house.md: 2 keys" in house
    assert "in the book, not here: 2" in house
    assert "13 (page 2): covers" in house
    assert "heading form: ## 2 Kitchen" in house
    assert "heading form: ## 4. Attic {#attic}" in house
    assert "grounds" not in house
    assert "1 (page" not in house  # the hall is the book's text
    # The ship's rooms 1 and 2 are checked against the ship's page, not the house's.
    assert ship.strip() == ": 2 keys"


def test_textcheck_passes_a_clean_text(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (folder / "clean" / "ship.md").write_text(f"## 1. Deck {{#1}}\n\n{DECK}\n\n## 2. Cabin {{#2}}\n\n{CABIN}\n")
    assert main(["qa", "textcheck", "parts.json", "clean/ship.md"]) == 0
    assert capsys.readouterr().out == "== ship.md: 2 keys\n"


def test_textcheck_letter_keys_and_ranges(folder: Path) -> None:
    parts = read_parts(folder / "parts.json") + read_parts_list(folder)
    text = "## W501. A room {#w501}\n\nIt is empty.\n\n## P108-P109. Twin rooms {#p108-p109}\n\nAnd as W501.\n"
    report = check_text("tower.md", text, parts, folder / "pages")
    assert report.keys == 2 and not report.flagged


def read_parts_list(folder: Path):
    """A `parts.json` may also be the bare list of parts."""
    path = folder / "letters.json"
    path.write_text(json.dumps([{"id": "tower", "pages": [4, 4], "key_pattern": r"^[WPZ][0-9B]\d\d[a-e]?"}]))
    return read_parts(path)
