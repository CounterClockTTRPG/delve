"""Every DM tool as the DM is sent it (its name, description and argument schema) and how the host treats it (whether
it changes state, what players may see), frozen (DEL-383). A 3.5-scoped tool is added beside these, never by changing
them. Regenerate with `DELVE_REGOLDEN=1` only for a change that is meant to, and say why in the commit."""

from __future__ import annotations

import json
from pathlib import Path

from delve.dm.tools.host import all_specs
from tests.fixtures.snapshot import assert_snapshot

SNAPSHOTS = Path(__file__).parent / "snapshots"


def test_the_tool_specs_are_frozen():
    specs = [
        {
            "name": spec.name,
            "description": spec.description,
            "schema": spec.params,
            "mutates": spec.mutates,
            "player_visible": spec.player_visible,
            "dm_only_keys": list(spec.dm_only_keys),
            "areas": None if spec.areas is None else list(spec.areas),
        }
        for spec in all_specs()
    ]
    text = json.dumps(specs, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    assert_snapshot(SNAPSHOTS / "tool_specs.json", text)
