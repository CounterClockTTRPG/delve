"""The geo world map (plan 7): its model, its grid, its GeoJSON documents, and plateau 6's maps converted."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
