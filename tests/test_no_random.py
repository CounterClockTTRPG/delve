"""Every roll goes through `Dice`: no module but `delve.dice` may import `random`."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "delve"
IMPORTS_RANDOM = re.compile(r"^\s*(import\s+random\b|from\s+random\s+import\b)", re.MULTILINE)


def test_no_random_import_outside_dice():
    importing = sorted(
        path.relative_to(SRC).as_posix() for path in SRC.rglob("*.py") if IMPORTS_RANDOM.search(path.read_text())
    )
    assert importing == ["dice.py"]
