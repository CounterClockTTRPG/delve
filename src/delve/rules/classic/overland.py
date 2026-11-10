"""Overland movement by mode: the terrain and route shares of a day's pace (plateau 6), and the routing rules of each mode.

The rates are shares of a mode's base pace in miles a day, which the caller works out from the party and the
ruleset's `TravelRates`: 2 × the slowest movement rate on foot, 2 × the mount's on horseback, a cart's miles a day, a
river boat's speed × its hours (± the current) and a ship's. `mode_rules` builds the routing rules of a mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from delve.maps.geo.routing import Mode, ModeRules

__all__ = ["CART_LAND", "LAND_RATES", "MILES_TO_KM", "ROUTE_RATES", "TravelRates", "mode_rules"]

MILES_TO_KM = 1.609344

LAND_RATES: dict[str, float] = {
    "plains": 1.0,
    "urban": 1.0,
    "forest": 1 / 2,
    "hills": 1 / 2,
    "desert": 1 / 2,
    "arctic": 1 / 2,
    "swamp": 1 / 3,
    "jungle": 1 / 3,
    "mountain": 1 / 3,
    "impassable": 0.0,
    "sea": 0.0,
    "lake": 0.0,
}
"""A day's pace off-road in each terrain, as a share of the road's (plateau 6's `TERRAIN_RATES`)."""

ROUTE_RATES: dict[str, float] = {"road": 1.0, "track": 1 / 1.2, "trail": 1 / 1.5}
"""A route's pace by its kind (plateau 6's surface multipliers)."""

CART_LAND: dict[str, float] = {
    terrain: 0.0 if terrain in ("mountain", "swamp", "jungle", "impassable") else rate / 2
    for terrain, rate in LAND_RATES.items()
}
"""A cart off the road: half the pace, and no way through mountains, swamp or jungle."""


@dataclass(frozen=True)
class TravelRates:
    """A ruleset's speeds for the modes of travel; the caller works a day's base pace out from them and the party."""

    horse_mv: int
    """A riding horse's movement rate, for `horse` without a mount of the party's own."""
    cart_miles_per_day: int
    """A cart's miles a day."""
    river_boat_mph: float
    """A river boat's miles an hour in still water."""
    river_current_mph: float
    river_hours: int
    """Hours afloat a day."""
    ship_mph: float
    """A cog or a coaster's miles an hour."""
    ship_hours: int
    """Hours under sail a day."""


def mode_rules(mode: Mode | str, rates: TravelRates, *, flies: bool = False) -> ModeRules:
    """The routing rules of `mode`. A river boat's base pace is its still-water speed, so downstream and upstream are
    the current added and taken off; a flyer (`flies`) crosses everything at its own pace."""
    if mode == "river":
        still = rates.river_boat_mph
        return ModeRules(
            mode,
            {},
            {},
            "river",
            downstream=(still + rates.river_current_mph) / still,
            upstream=(still - rates.river_current_mph) / still,
            lake=1.0,
            flies=flies,
        )
    if mode == "ship":
        return ModeRules(mode, {}, {}, "sea", flies=flies)
    if mode not in ("foot", "horse", "cart"):
        raise ValueError(f"unknown mode {mode!r}")
    land = CART_LAND if mode == "cart" else LAND_RATES
    return ModeRules(mode, dict(land), dict(ROUTE_RATES), "none", flies=flies)
