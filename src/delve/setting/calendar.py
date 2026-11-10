"""The in-tree calendar: Aun's Reckoning (DEL-351); a setting pack brings its own. A campaign keeps its day and its
start date; the date, the month and the season are derived from them, never set by hand."""

from __future__ import annotations

from delve.domain.world import Calendar, Month


def _months(names: tuple[str, ...], season: str, weather_season: str, days: int = 28) -> tuple[Month, ...]:
    return tuple(Month(name, days, season, weather_season) for name in names)


def _festival(name: str, season: str, weather_season: str, days: int = 7) -> tuple[Month, ...]:
    return (Month(name, days, season, weather_season, festival=True),)


RECKONING_CALENDAR = Calendar(
    id="reckoning",
    era="RY",
    months=(
        *_festival("Hollow Days", "Midwinter", "winter", days=5),
        *_months(("Vormas", "Velith"), "Winter", "winter", days=30),
        *_months(("Isaine", "Ashen", "Marrah"), "Spring", "spring", days=30),
        *_months(("Aurelmas", "Karsk", "Fennick"), "Summer", "summer", days=30),
        *_months(("Hollin", "Oruun", "Seremark"), "Autumn", "autumn", days=30),
        Month("Nameless Month", 30, "Winter", "winter"),
    ),
    default_start=(1188, 66),
)
"""Aun's Reckoning (DEL-351): years counted from the Unmaking, twelve months of 30 days named for the great gods
(Nhul's, the last, is the Nameless Month) and the five Hollow Days that open the year, 365 days. A campaign starts on
1 Isaine 1188 RY (day 66 of the year), Isaine's Morning, unless it is given another date. A date reads
"4 Isaine 1188 RY", a Hollow Day "Hollow Days, day 2, 1188 RY"."""
