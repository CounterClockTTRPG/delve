"""The ruleset interface: what the game asks of a ruleset, such as a pack's (spec §10, DEL-307).

A campaign plays one ruleset, named by its `ruleset` id; `delve.rules.catalog` is the one list of the rulesets the
installed packs bring, and makes each from its pack. The play services read the campaign's own through
`CampaignContext.ruleset`.
"""

from __future__ import annotations

from typing import Any, Protocol

from delve.domain.reference import ReferenceHit, RulesetReference
from delve.rules.classic.encounters import Encounters
from delve.rules.classic.rulebook import Rulebook
from delve.rules.classic.tables import RuleTables
from delve.rules.classic.treasure import Treasure

__all__ = ["NO_LOOKUPS", "ReferenceHit", "Ruleset"]


class Ruleset(Protocol):
    id: str
    title: str
    reference: RulesetReference | None
    """The ruleset's own lookups (over its pack's data or `pack.db`); None for one without."""
    tables: RuleTables
    """The ruleset's numbers for the classic engine: saves, survival, reaction, surprise, encounter checks."""
    notice: str
    """What the ruleset's licence asks a product to say of it, shown with its book; "" for none."""
    prompt: str
    """What the DM is told of the ruleset, in Markdown, under its procedure's The Ruleset: its books, and how its checks
    and entries read."""
    encounters: Encounters | None
    """The ruleset's own way of determining a random encounter; None for the engine's tiered tables."""
    treasure: Treasure | None
    """The ruleset's treasure types and generator; None for one without."""

    @property
    def rulebook(self) -> Rulebook | None:
        """The book the Rulesets area reads; None for a ruleset (or a reference) that can't be browsed."""
        ...

    def kinds(self) -> tuple[str, ...]: ...

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        """The entries of `kind` that match `query`, at most `limit`. An unknown kind raises `ValueError`."""
        ...

    def merchant_catalogue(self) -> tuple[Any, ...]:
        """Every magic item a merchant could stock, priced; empty for a ruleset without merchants."""
        ...


class NoLookups:
    """The lookups of a ruleset without any (the fake, or a pack's whose `pack.db` isn't built): every one finds
    nothing."""

    def monster(self, name: str) -> list[dict]:
        return []

    def spell(self, name: str, caster: str = "") -> list[dict]:
        return []

    def item(self, name: str, item_type: str = "", max_rarity: int = 100, limit: int = 20) -> list[dict]:
        return []

    def char_class(self, name: str) -> dict | None:
        return None

    def class_levels(self, name: str) -> list[dict]:
        return []

    def race(self, name: str) -> dict | None:
        return None

    def ability(self, ability: str, score: str) -> dict:
        return {"error": f"No ability table for '{ability}' in this ruleset."}

    def proficiency(self, name: str = "", group: str = "", ability: str = "") -> list[dict]:
        return []

    def turning_undead(self) -> list[dict]:
        return []

    def rules_search(self, query: str, source: str = "", limit: int = 5) -> list[dict]:
        return []

    def rules_section(self, source: str, section: str) -> list[dict]:
        return []

    def encounter_tables(self) -> dict:
        return {}

    def osric_magic_items(self) -> dict:
        return {}


NO_LOOKUPS: RulesetReference = NoLookups()
