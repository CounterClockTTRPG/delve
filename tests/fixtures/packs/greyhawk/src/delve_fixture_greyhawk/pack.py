"""The test double of the private Greyhawk pack (DEL-307): its code with a tiny wiki and lore facts (`data/`, made from
`tests/fixtures/reference`), the Common Year calendar and the region map, so core tests can play a Greyhawk campaign."""

from __future__ import annotations

from importlib import resources

from delve.domain.world import Calendar, Month, WorldMapSource
from delve.setting.wiki import WikiPack, WikiSetting

# Each kind and the wiki's typed tables that hold it, in the order the DM is shown the kinds.
KINDS: dict[str, tuple[str, ...]] = {
    "place": ("settlements", "locations"),
    "realm": ("realms",),
    "deity": ("deities",),
    "character": ("characters",),
    "organization": ("organizations",),
    "creature": ("creatures",),
    "item": ("items",),
    "plane": ("planes",),
    "holiday": ("holidays",),
    "building": ("buildings",),
    "archfiend": ("archfiends",),
}
TABLES = (
    "characters",
    "settlements",
    "deities",
    "creatures",
    "realms",
    "archfiends",
    "locations",
    "organizations",
    "creators",
    "items",
    "planes",
    "holidays",
    "buildings",
)
"""The wiki's typed tables in ttrpg2's order, the order a page's kind is looked for (`creators` is no kind's)."""


def _months(names: tuple[str, ...], season: str, weather_season: str, days: int = 28) -> tuple[Month, ...]:
    return tuple(Month(name, days, season, weather_season) for name in names)


def _festival(name: str, season: str, weather_season: str, days: int = 7) -> tuple[Month, ...]:
    return (Month(name, days, season, weather_season, festival=True),)


GREYHAWK_CALENDAR = Calendar(
    id="common-year",
    era="CY",
    months=(
        *_festival("Needfest", "Midwinter", "winter"),
        *_months(("Fireseek",), "Winter", "winter"),
        *_months(("Readying", "Coldeven"), "Spring", "spring"),
        *_festival("Growfest", "Spring", "spring"),
        *_months(("Planting", "Flocktime", "Wealsun"), "Low summer", "summer"),
        *_festival("Richfest", "Midsummer", "summer"),
        *_months(("Reaping", "Goodmonth", "Harvester"), "High summer", "summer"),
        *_festival("Brewfest", "Autumn", "autumn"),
        *_months(("Patchwall", "Ready'reat"), "Autumn", "autumn"),
        *_months(("Sunsebb",), "Winter", "winter"),
    ),
    default_start=(576, 99),
)
"""The Common Year: twelve months of 28 days and four festival weeks of 7, 364 days. A campaign starts on 1 Planting
576 CY (day 99 of the year) unless it is given another date. A date reads "4 Planting 576 CY", a festival day
"Richfest, day 4, 576 CY"."""

REGION_MAP = WorldMapSource(
    "greyhawk-region",
    "Greyhawk region",
    resources.files("delve_fixture_greyhawk").joinpath("greyhawk-region.map").read_text("utf-8"),
)
"""ttrpg2's hand-made Greyhawk region map, the setting's one built-in map: no structured Flanaess map exists."""


class GreyhawkSetting(WikiSetting):
    """Greyhawk over the pack's wiki."""

    id = "greyhawk"
    title = "Greyhawk"
    world = "oerth"
    KINDS = KINDS
    CALENDAR = GREYHAWK_CALENDAR
    MAPS = (REGION_MAP,)


PACK = WikiPack(GreyhawkSetting, "gh_", ("greyhawk.sql.gz", "lore_facts.sql.gz"), TABLES)
