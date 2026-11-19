"""The keys OSRIC and 2e campaigns store for a sheet, a character's state and a fight, frozen (DEL-383).

An additive field that is left out while empty (`OMIT_IF_NONE`) keeps these sets as they are; any other new, renamed or
dropped key changes what existing campaigns store, and fails here. Regenerate with `DELVE_REGOLDEN=1` only for a change
that is meant to, and say why in the commit."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from delve.domain.characters import CharacterState, Sheet
from delve.domain.data import to_dict
from delve.rules.classic import combat as cb
from tests.fixtures.snapshot import assert_snapshot
from tests.rules.classic.test_combat import GARREK, fight_with_goblins

SNAPSHOTS = Path(__file__).parent / "snapshots"


def keys(value: Any, path: str = "") -> list[str]:
    """Every key path in `value`: `a`, `a.b`, and `a[].b` for the dicts inside a list."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            here = f"{path}.{key}" if path else str(key)
            found.append(here)
            found.extend(keys(inner, here))
    elif isinstance(value, list):
        for item in value:
            found.extend(keys(item, f"{path}[]"))
    return sorted(set(found))


def test_the_stored_key_sets_are_frozen():
    fight = fight_with_goblins(GARREK)
    stored = to_dict(fight)
    stored["combatants"] = {"<id>": next(iter(stored["combatants"].values()))}  # ids vary; one combatant's keys
    sets = {
        "sheet": keys(to_dict(Sheet())),
        "sheet_with_attacks": keys(to_dict(GARREK.sheet)),
        "character_state": keys(to_dict(CharacterState())),
        "combat": keys(stored),
        "combatant": keys(to_dict(fight.combatants["chr_garrek"])),
        "start": sorted(cb.start([GARREK])[1]),
    }
    assert_snapshot(SNAPSHOTS / "stored_keys.json", json.dumps(sets, indent=2, sort_keys=True) + "\n")
