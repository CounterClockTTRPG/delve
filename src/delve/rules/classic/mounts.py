"""Mounts: a species' stats from the ruleset's defaults (`RuleTables.mounts`, `(hp_max, ac, mv, thac0, attacks,
morale)` per species, and `mount_fly`), with the caller's over them. An unknown species is any other string; its stats
are the caller's, and it needs `hp_max` and `thac0`.
"""

from __future__ import annotations

from typing import Any

from delve.rules.classic.tables import RuleTables

__all__ = ["UnknownSpecies", "mount_stats", "species_key"]


class UnknownSpecies(ValueError):
    """A species without defaults whose stats lack `hp_max` or `thac0`."""


def species_key(species: str) -> str:
    """The species as the ruleset's mounts key it: lower case, spaces as hyphens ("Riding horse" is `riding-horse`)."""
    return "-".join(species.strip().lower().split())


def mount_stats(species: str, overrides: dict[str, Any], *, rules: RuleTables) -> dict[str, Any]:
    """A mount's stats, `{species, hp, hp_max, ac, mv, fly, thac0, attacks, morale}`: the species' defaults with
    `overrides` over them. `hp` starts at `hp_max` unless given. An unknown species takes `overrides` alone, and
    needs a positive `hp_max` and `thac0` (ttrpg2's rule: AC and MV may be anything, 0 included)."""
    key = species_key(species)
    defaults = rules.mounts.get(key)
    if defaults is None:
        if not all(isinstance(overrides.get(k), int) and overrides[k] > 0 for k in ("hp_max", "thac0")):
            raise UnknownSpecies(key)
        stats: dict[str, Any] = {"species": key}
    else:
        hp_max, ac, mv, thac0, attacks, morale = defaults
        stats = {
            "species": key,
            "hp": hp_max,
            "hp_max": hp_max,
            "ac": ac,
            "mv": mv,
            "fly": rules.mount_fly.get(key, 0),
            "thac0": thac0,
            "attacks": list(attacks),
            "morale": morale,
        }
    stats.update({k: v for k, v in overrides.items() if k != "species"})
    if "hp" not in overrides:
        stats["hp"] = stats["hp_max"]
    return stats
