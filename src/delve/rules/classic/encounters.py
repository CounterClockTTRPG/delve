"""A ruleset's own way of determining a random encounter, once the check says one comes (`checks.encounter_check`):
OSRIC's goes by its dungeon matrix, its terrains' categories and its towns. A ruleset without one has the engine's
tiered tables (`RulesetReference.encounter_tables`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from delve.dice import Dice, Roll


@dataclass(frozen=True)
class Encounter:
    result: str
    """What is met: "Giant Ant, Worker", "Bandits"."""
    tier: str = ""
    """Where on the tables it came from: "monster level 2", "forest: Animal"."""
    category: str = ""
    monster: str = ""
    """The bestiary's slug, when the result is one of its monsters."""
    number: str = ""
    """How many: the dice of a wandering group, "1d6"."""
    note: str = ""
    rolls: tuple[Roll, ...] = ()


class Encounters(Protocol):
    def determine(
        self, dice: Dice, *, terrain: str, party_level: int, dungeon_level: int, occasion: str
    ) -> Encounter | None:
        """The encounter that comes in `terrain`; None for a terrain the ruleset has no table for."""
        ...
