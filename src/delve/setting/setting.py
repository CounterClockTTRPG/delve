"""The setting interface: places, deities, factions and lore of a world such as Aun (spec §10)."""

from __future__ import annotations

from typing import Protocol

from delve.domain.reference import LoreFact, ReferenceHit, SettingPage
from delve.domain.world import Calendar, WorldMapSource


class Setting(Protocol):
    """The same shape as `Ruleset`, with the setting's own kinds (Aun's `place`, `deity`, `character`…), and the
    world around them: its calendar, its world maps, its wiki and its lore facts."""

    id: str
    title: str
    world: str
    """The world it is on, as a ruleset's encounter entries tag theirs ("toril"); "" when it names none."""

    def kinds(self) -> tuple[str, ...]: ...

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        """The entries of `kind` that match `query`, at most `limit`. An unknown kind raises `ValueError`."""
        ...

    def calendar(self) -> Calendar:
        """The calendar the setting's campaigns count their days in."""
        ...

    def world_maps(self) -> tuple[WorldMapSource, ...]:
        """The world maps a campaign in the setting starts with."""
        ...

    def search(self, query: str, limit: int = 10) -> list[ReferenceHit]:
        """Full-text search of the setting's pages, best first, each with a snippet."""
        ...

    def page(self, title: str) -> SettingPage | None:
        """The page titled `title` (any case, following redirects), or None."""
        ...

    def lore_facts(self, n: int, category: str = "", seed: int | None = None) -> list[LoreFact]:
        """Up to `n` of the setting's "Did you know" facts, drawn at random; of `category` when given. The same
        `seed` gives the same draw."""
        ...
