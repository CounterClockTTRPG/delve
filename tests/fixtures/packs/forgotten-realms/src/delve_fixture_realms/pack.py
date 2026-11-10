"""The test double of the private Forgotten Realms pack (DEL-307): its code with a tiny wiki (`data/`, made from
`tests/fixtures/reference`) and the Calendar of Harptos."""

from __future__ import annotations

from delve.domain.world import Calendar, Month
from delve.setting.wiki import WikiPack, WikiSetting

# Each kind and the wiki's typed tables that hold it, in the order the DM is shown the kinds: Greyhawk's, less the
# kinds the Realms wiki has no infobox for (holidays, archfiends).
KINDS: dict[str, tuple[str, ...]] = {
    "place": ("settlements", "locations"),
    "realm": ("realms",),
    "deity": ("deities",),
    "character": ("characters",),
    "organization": ("organizations",),
    "creature": ("creatures",),
    "item": ("items",),
    "plane": ("planes",),
    "building": ("buildings",),
}
TABLES = (
    "characters",
    "settlements",
    "deities",
    "creatures",
    "realms",
    "locations",
    "organizations",
    "items",
    "planes",
    "buildings",
)
"""The wiki's typed tables in the order a page's kind is looked for."""


def _festival(name: str, season: str, weather_season: str) -> Month:
    return Month(name, 1, season, weather_season, festival=True)


HARPTOS_CALENDAR = Calendar(
    id="harptos",
    era="DR",
    months=(
        Month("Hammer", 30, "Winter", "winter"),
        _festival("Midwinter", "Midwinter", "winter"),
        Month("Alturiak", 30, "Winter", "winter"),
        Month("Ches", 30, "Spring", "spring"),
        Month("Tarsakh", 30, "Spring", "spring"),
        _festival("Greengrass", "Spring", "spring"),
        Month("Mirtul", 30, "Spring", "spring"),
        Month("Kythorn", 30, "Summer", "summer"),
        Month("Flamerule", 30, "Summer", "summer"),
        _festival("Midsummer", "Midsummer", "summer"),
        Month("Eleasis", 30, "Summer", "summer"),
        Month("Eleint", 30, "Autumn", "autumn"),
        _festival("Highharvestide", "Autumn", "autumn"),
        Month("Marpenoth", 30, "Autumn", "autumn"),
        Month("Uktar", 30, "Autumn", "autumn"),
        _festival("Feast of the Moon", "Autumn", "autumn"),
        Month("Nightal", 30, "Winter", "winter"),
    ),
    default_start=(1340, 123),
)
"""The Calendar of Harptos (Dale Reckoning): twelve months of three tendays and five festival days between them, 365
days. Shieldmeet, the day after Midsummer every fourth year, is left out: a `Calendar` has a year of fixed length. A
campaign starts on 1 Mirtul 1340 DR (day 123 of the year), the year of Ruins of Adventure, unless it is given another
date. A date reads "1 Mirtul 1340 DR", a festival day "Midsummer, 1340 DR"."""


class RealmsSetting(WikiSetting):
    """The Forgotten Realms over the pack's wiki."""

    id = "forgotten-realms"
    title = "Forgotten Realms"
    world = "toril"
    KINDS = KINDS
    CALENDAR = HARPTOS_CALENDAR


PACK = WikiPack(RealmsSetting, "fr_", ("lore_facts.sql.gz", "forgotten_realms.sql.gz"), TABLES)
