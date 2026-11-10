"""Shared test helpers (named uniquely: several packages' tests run in one
pytest session, so `from conftest import …` would pick up the wrong one)."""
from __future__ import annotations

from tests.fixtures import SAMPLES

SAMPLE = SAMPLES / "scenarios" / "crypt-of-saint-vellis"


def codes(diags) -> list[str]:
    return [d.code for d in diags if d.severity == "error"]


def warn_codes(diags) -> list[str]:
    return [d.code for d in diags if d.severity == "warning"]
