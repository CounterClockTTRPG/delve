"""OSRIC's entry as a pack: the ruleset, made from the pack's own package."""

from __future__ import annotations

from pathlib import Path

from delve_osric.ruleset import OsricRuleset


class Pack:
    def ruleset(self, root: Path) -> OsricRuleset:
        return OsricRuleset()


PACK = Pack()
