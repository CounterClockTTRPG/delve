"""A ruleset's book as the Rulesets area reads it (rulesets plan Task 5): its sections, their rows, filters and
entries, and a search across them."""

from __future__ import annotations

from typing import Protocol

from delve.domain.reference import Entry, Facet, RowsPage, Section


class Rulebook(Protocol):
    def sections(self) -> list[Section]:
        """The book's sections, in its order."""
        ...

    def columns(self, section: str) -> tuple[str, ...]:
        """The columns of a list section's rows, beside the name; none for a table or an unknown section."""
        ...

    def facets(self, section: str) -> list[Facet]: ...

    def rows(self, section: str, filters: dict[str, str], offset: int, limit: int) -> RowsPage: ...

    def entry(self, section: str, id: str) -> Entry | None: ...

    def table(self, section: str) -> list[dict]: ...

    def search(self, q: str, limit: int) -> list[tuple[str, str, str]]:
        """`(section, id, name)` of the entries whose name matches `q`, ranked as `rank` does."""
        ...


def rank(q: str, hit: tuple[str, str, str]) -> tuple:
    """The store's order for names: the exact name first, then names starting with `q`, then the rest, by name."""
    section, id, name = hit
    lowered, text = name.lower(), q.lower()
    return (0 if lowered == text else 1 if lowered.startswith(text) else 2, lowered, section, id)
