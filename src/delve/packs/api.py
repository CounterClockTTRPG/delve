"""What a pack's entry object offers Delve; the pack's code needs nothing of Delve beyond these protocols."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from delve.rules.ruleset import Ruleset
from delve.setting.setting import Setting

PACK_API = 1
"""The pack API this Delve reads; a pack's `delve_api` must equal it."""


class RulesetPack(Protocol):
    """A ruleset pack's entry: `ruleset` makes the ruleset from the pack folder. An entry may also have
    `build(root, db)`, which writes the pack's database at install time."""

    def ruleset(self, root: Path) -> Ruleset: ...


class SettingPack(Protocol):
    """A setting pack's entry: `setting` makes the setting from the pack folder, leaving out the fact categories in
    `exclude`. An entry may also have `build(root, db)`, which writes the pack's database at install time."""

    def setting(self, root: Path, exclude: frozenset[str]) -> Setting: ...


PACK_IMPORTS = (
    "delve.domain",
    "delve.dice",
    "delve.rules.classic",
    "delve.rules.ruleset",
    "delve.setting.setting",
    "delve.setting.wiki",
    "delve.setting.calendar",
    "delve.packs.api",
    "delve.packs.store",
)
"""The core modules a pack may import, each with what is under it; `tests/packs/test_pack_imports.py` holds every pack to it."""
