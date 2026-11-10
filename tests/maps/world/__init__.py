"""The world-map language (plan 6 Task 7). ttrpg2 had no tests for it, so its four real maps are the fixtures."""

from pathlib import Path

DATA = Path(__file__).parent / "data"


def read(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8")


INCLUDES = {"sulm-akar-buildings.map": read("sulm-akar-buildings.map")}
"""The fragment wastes-of-cynidicea includes."""
