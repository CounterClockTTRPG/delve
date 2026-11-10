"""The one list of the settings Delve knows (settings plan Task 1). The web registry and the DM's `CampaignContext` are
both made from it, so a campaign's setting is the same setting wherever it is read."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from delve.domain.backends import ProviderCapabilities, Registry
from delve.domain.campaigns import MissingPack
from delve.setting.aun import AunSetting
from delve.setting.fake import FakeSetting
from delve.setting.setting import Setting

if TYPE_CHECKING:
    from delve.packs.loader import LoadedPack


@dataclass(frozen=True)
class SettingEntry:
    """One setting: its id and title, and how to make it. `make`'s argument holds the lore fact categories other
    settings claim, which this one must leave out. `fact_categories` are the lore fact categories that are this
    setting's own; a `development` setting is titled as one."""

    id: str
    title: str
    make: Callable[[frozenset[str]], Setting]
    fact_categories: frozenset[str] = frozenset()
    development: bool = False
    preferred: bool = False
    """Its pack says a new campaign takes it."""


def known() -> tuple[SettingEntry, ...]:
    """The in-tree settings: Delve's own, Aun, which reads its own files, and the fake one for development."""
    return (
        SettingEntry("aun", "Aun", lambda exclude: AunSetting()),
        SettingEntry("fake-setting", "Fake setting", lambda exclude: FakeSetting(), frozenset({"fake"}), development=True),
    )


CATALOG: tuple[SettingEntry, ...] = known()
"""The in-tree settings."""


def catalog(packs: Sequence[LoadedPack]) -> tuple[SettingEntry, ...]:
    """The settings of the installed packs, with the lore fact categories their manifests name, and the in-tree ones
    whose id no pack provides: by title, the development ones last."""
    from_packs = tuple(
        SettingEntry(
            p.manifest.id,
            p.manifest.title,
            lambda exclude, p=p: p.entry.setting(p.root, exclude),  # type: ignore[union-attr]
            p.manifest.fact_categories,
            preferred=p.manifest.preferred,
        )
        for p in packs
        if p.manifest.kind == "setting"
    )
    taken = {e.id for e in from_packs}
    entries = (*(e for e in known() if e.id not in taken), *from_packs)
    return tuple(sorted(entries, key=lambda e: (e.development, e.title.casefold())))


def entry(setting_id: str | None, catalog: Sequence[SettingEntry] = CATALOG) -> SettingEntry | None:
    """The entry of `setting_id`; None for no setting or one Delve doesn't know."""
    return next((e for e in catalog if setting_id and e.id == setting_id), None)


def claimed_elsewhere(setting_id: str, catalog: Sequence[SettingEntry] = CATALOG) -> frozenset[str]:
    """The lore fact categories the other settings claim."""
    return frozenset().union(*(e.fact_categories for e in catalog if e.id != setting_id))


def make_setting(setting_id: str | None, catalog: Sequence[SettingEntry] = CATALOG) -> Setting | None:
    """The setting `setting_id`; None for no setting. `MissingPack` for an id that isn't in the catalog."""
    if not setting_id:
        return None
    found = entry(setting_id, catalog)
    if found is None:
        raise MissingPack("setting", setting_id)
    return found.make(claimed_elsewhere(found.id, catalog))


def register_settings(registry: Registry[Setting], catalog: Sequence[SettingEntry] = CATALOG) -> None:
    """Every setting of the catalog in `registry`, a development one titled as such."""
    for e in catalog:
        title = f"{e.title} (development)" if e.development else e.title
        registry.register(
            ProviderCapabilities(e.id, title, frozenset()),
            lambda e=e: e.make(claimed_elsewhere(e.id, catalog)),
        )
