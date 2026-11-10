"""The one list of the rulesets an install has, as `delve.setting.catalog` is of the settings: the ones its packs bring
(DEL-307), for Delve has none built in. The web registry and each campaign's `CampaignContext.ruleset` are both made
from it, so a campaign's ruleset is the same wherever it is read; the rest of Delve asks the campaign's ruleset, never
one by name.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from delve.domain.backends import ProviderCapabilities, Registry
from delve.domain.campaigns import MissingPack
from delve.rules.fake import FakeRuleset
from delve.rules.ruleset import Ruleset

if TYPE_CHECKING:
    from delve.packs.loader import LoadedPack


@dataclass(frozen=True)
class RulesetEntry:
    """One ruleset: its id and title, the package that holds it, and how to make it; `preferred` when its pack says a
    new campaign takes it."""

    id: str
    title: str
    package: str
    make: Callable[[], Ruleset]
    preferred: bool = False


CATALOG: tuple[RulesetEntry, ...] = ()
"""The rulesets of an install with no packs: none."""


def catalog(packs: Sequence[LoadedPack]) -> tuple[RulesetEntry, ...]:
    """The rulesets of the installed packs."""
    return tuple(
        RulesetEntry(
            p.manifest.id,
            p.manifest.title,
            p.manifest.package,
            lambda p=p: p.entry.ruleset(p.root),  # type: ignore[union-attr]
            p.manifest.preferred,
        )
        for p in packs
        if p.manifest.kind == "ruleset"
    )


def entry(ruleset_id: str | None, catalog: Sequence[RulesetEntry] | None = None) -> RulesetEntry | None:
    """The entry of `ruleset_id`; None for one Delve doesn't know."""
    return next((e for e in (CATALOG if catalog is None else catalog) if ruleset_id and e.id == ruleset_id), None)


def make_ruleset(ruleset_id: str | None, catalog: Sequence[RulesetEntry] | None = None) -> Ruleset:
    """The ruleset `ruleset_id`; the fake one for no id or the fake's own. `MissingPack` for an id that isn't in the
    catalog."""
    if not ruleset_id or ruleset_id == FakeRuleset.id:
        return FakeRuleset()
    found = entry(ruleset_id, catalog)
    if found is None:
        raise MissingPack("ruleset", ruleset_id)
    return found.make()


def register_rulesets(registry: Registry[Ruleset], catalog: Sequence[RulesetEntry] | None = None) -> None:
    """Every ruleset of the catalog in `registry`, and the fake one, titled as being for development (as the other
    layers' fakes are: offered only when nothing else is)."""
    for e in CATALOG if catalog is None else catalog:
        registry.register(ProviderCapabilities(e.id, e.title, frozenset()), lambda e=e: e.make())
    registry.register(
        ProviderCapabilities(FakeRuleset.id, f"{FakeRuleset.title} (development)", frozenset(), development=True),
        FakeRuleset,
    )
