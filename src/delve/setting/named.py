"""A setting that is only a name, for one whose materials aren't in yet (a pack's that isn't installed yet, as one was until DEL-38):
modules and campaigns can name it, and it has no pages, kinds, lore or world map, and counts its days on the plain
calendar."""

from __future__ import annotations

from delve.domain.reference import LoreFact, ReferenceHit, SettingPage
from delve.domain.world import PLAIN_CALENDAR, Calendar, WorldMapSource


class NamedSetting:
    """A setting with an id and a title and nothing else: every lookup finds nothing."""

    def __init__(self, setting_id: str, title: str) -> None:
        self.id = setting_id
        self.title = title
        self.world = ""

    def kinds(self) -> tuple[str, ...]:
        return ()

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        raise ValueError(f"unknown kind '{kind}'; {self.title} has no kinds yet")

    def calendar(self) -> Calendar:
        return PLAIN_CALENDAR

    def world_maps(self) -> tuple[WorldMapSource, ...]:
        return ()

    def search(self, query: str, limit: int = 10) -> list[ReferenceHit]:
        return []

    def page(self, title: str) -> SettingPage | None:
        return None

    def lore_facts(self, n: int, category: str = "", seed: int | None = None) -> list[LoreFact]:
        return []
