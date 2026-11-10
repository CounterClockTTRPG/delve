"""A small in-memory setting for tests and development."""

from __future__ import annotations

from delve.domain.reference import LoreFact, ReferenceHit, SettingPage
from delve.domain.world import PLAIN_CALENDAR, Calendar, WorldMapSource

KINDS = ("place", "deity", "faction")

SAMPLE_HITS: dict[str, list[ReferenceHit]] = {
    "place": [
        ReferenceHit("place", "hommlet", "Hommlet", "A quiet village in the Viscounty of Verbobonc."),
        ReferenceHit("place", "verbobonc", "Verbobonc", "A city on the Velverdyva, seat of the Viscount."),
    ],
    "deity": [
        ReferenceHit("deity", "st-cuthbert", "St. Cuthbert", "God of common sense, wisdom and zeal."),
    ],
    "faction": [
        ReferenceHit("faction", "circle-of-eight", "Circle of Eight", "Mages who keep the balance of the Flanaess."),
    ],
}

LORE_FACTS = (
    LoreFact(1, "Hommlet's inn is the Welcome Wench.", "fake", "fake-setting"),
    LoreFact(2, "St. Cuthbert's holy symbol is a starburst.", "fake", "fake-setting"),
)


class FakeSetting:
    """A setting holding a dict of hits for the kinds place, deity and faction; `lookup` and `search` match the query
    case-insensitively in the title, and a hit's text is its page. It counts its days on the plain calendar and has
    no world map."""

    id = "fake-setting"
    title = "Fake setting"
    world = ""

    def __init__(self, hits: dict[str, list[ReferenceHit]] | None = None) -> None:
        self._hits = {kind: list((SAMPLE_HITS if hits is None else hits).get(kind, [])) for kind in KINDS}

    def kinds(self) -> tuple[str, ...]:
        return KINDS

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        if kind not in self._hits:
            raise ValueError(f"unknown kind '{kind}'; kinds: {', '.join(KINDS)}")
        needle = query.casefold()
        return [hit for hit in self._hits[kind] if needle in hit.title.casefold()][:limit]

    def calendar(self) -> Calendar:
        return PLAIN_CALENDAR

    def world_maps(self) -> tuple[WorldMapSource, ...]:
        return ()

    def search(self, query: str, limit: int = 10) -> list[ReferenceHit]:
        return [hit for kind in KINDS for hit in self.lookup(kind, query, limit)][:limit]

    def page(self, title: str) -> SettingPage | None:
        hits = [hit for kind in KINDS for hit in self._hits[kind] if hit.title.casefold() == title.casefold()]
        return SettingPage(hits[0].title, hits[0].kind, {}, hits[0].text, ()) if hits else None

    def lore_facts(self, n: int, category: str = "", seed: int | None = None) -> list[LoreFact]:
        return [fact for fact in LORE_FACTS if category in ("", fact.category)][:n]
