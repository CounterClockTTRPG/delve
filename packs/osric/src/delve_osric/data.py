"""OSRIC's tables, read once from the package's `data/*.json`."""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

CLASSES = ("assassin", "cleric", "druid", "fighter", "illusionist", "magic-user", "monk", "paladin", "ranger", "thief")
"""OSRIC's ten classes, as `classes.json` keys them."""


@cache
def load(name: str) -> Any:
    """`data/<name>.json`; the monsters by the names players say (`monster_names.json`, DEL-325), each keeping the
    guide's index name as `index_name` ("Bear, greater, polar" is "Polar bear")."""
    data = json.loads(resources.files("delve_osric").joinpath("data", f"{name}.json").read_text("utf-8"))
    if name == "monsters":
        names = own(load("monster_names"))
        data = {
            **data,
            "monsters": [
                {**m, "name": names[m["name"]], "index_name": m["name"]} if m["name"] in names else m
                for m in data["monsters"]
            ],
        }
    return data


def own(table: dict[str, Any]) -> dict[str, Any]:
    """A table without its `_source` and other notes."""
    return {key: value for key, value in table.items() if not key.startswith("_")}
