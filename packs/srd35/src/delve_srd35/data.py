"""SRD 3.5's data, read once from the package's `data/*.json` (made by `scripts/extract.py`)."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any


@cache
def load(name: str) -> Any:
    return json.loads(resources.files("delve_srd35").joinpath("data", f"{name}.json").read_text("utf-8"))
