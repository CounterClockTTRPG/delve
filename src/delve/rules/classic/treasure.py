"""Treasure as the engine and the play services see it: a hoard's coins, gems, art and magic, and the `Treasure` a
ruleset rolls them with."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from delve.dice import Dice, Roll

__all__ = ["COINS", "ArtObject", "Check", "Gem", "MagicItem", "Treasure", "TreasureResult", "TreasureTypeError"]

COINS = ("pp", "gp", "ep", "sp", "cp")


class TreasureTypeError(ValueError):
    """A treasure line that isn't one group of type letters. `groups` lists the groups of a line that has several
    (a bestiary splits lair and individual treasure that way), so the caller can pick one."""

    def __init__(self, message: str, groups: list[dict[str, Any]] | None = None) -> None:
        self.groups = groups or []
        super().__init__(message)


@dataclass(frozen=True)
class Gem:
    name: str
    value_gp: int
    tier: str
    note: str = ""
    """The variance roll's change, such as "double" or "+1 tier"."""


@dataclass(frozen=True)
class ArtObject:
    name: str
    value_gp: int


@dataclass(frozen=True)
class MagicItem:
    category: str
    """The table it comes from: "Potion/Oil", "Scroll", "Ring", "Misc Magic — Jewelry", "Weapon"…"""
    name: str


@dataclass(frozen=True)
class Check:
    """One percentage chance of the treasure-type table: the column of a type, rolled on a d100, present on
    `roll <= chance`."""

    type: str
    column: str
    chance: int
    roll: int
    success: bool


@dataclass(frozen=True)
class TreasureResult:
    types: tuple[str, ...]
    """The type letters rolled, in order: "Qx2 S" is ("Q", "Q", "S")."""
    coins: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COINS, 0))
    gems: tuple[Gem, ...] = ()
    art: tuple[ArtObject, ...] = ()
    magic: tuple[MagicItem, ...] = ()
    checks: tuple[Check, ...] = ()
    rolls: tuple[Roll, ...] = ()


class Treasure(Protocol):
    """A ruleset's treasure: its type letters, which of them are a lair's hoard, and the generator."""

    def lair_codes(self, codes: list[str]) -> list[str]:
        """Those of `codes` that are a lair's hoard, rolled only where the creatures live."""
        ...

    lair_name: str
    """The lair types as a refusal names them ("types A-I")."""
    individual_name: str
    """The types individuals carry, as a refusal names them ("types J-Z")."""
    no_hoard: tuple[str, ...]
    """How the intelligence of a creature that keeps no hoard starts ("animal", "semi")."""

    def parse_types(self, spec: str) -> dict[str, Any]:
        """A treasure line as `{"groups": [{"label", "codes"}…]}`."""
        ...

    def generate(self, dice: Dice, types: str, *, source: str | None = None) -> TreasureResult:
        """The hoard of a line of types; raises `TreasureTypeError` for one that isn't one group of types."""
        ...
