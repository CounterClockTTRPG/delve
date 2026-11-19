"""SRD 3.5's entry as a pack: the ruleset, made from the pack's own package."""

from __future__ import annotations

from pathlib import Path

from delve_srd35.ruleset import Srd35Ruleset


class Pack:
    def ruleset(self, root: Path) -> Srd35Ruleset:
        return Srd35Ruleset()


PACK = Pack()
