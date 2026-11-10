"""The two catalogs of an install, made once from its packs: the rulesets and the settings a campaign can name."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from delve.config import Config
from delve.packs.loader import LoadedPack, load_packs
from delve.rules import catalog as rulesets
from delve.setting import catalog as settings


@dataclass(frozen=True)
class Catalogs:
    rulesets: tuple[rulesets.RulesetEntry, ...]
    settings: tuple[settings.SettingEntry, ...]
    packs: tuple[LoadedPack, ...] = ()
    """The packs the catalogs were made from, for what else a pack brings (its house rules)."""

    @classmethod
    def of(cls, packs: Sequence[LoadedPack]) -> Catalogs:
        """The catalogs of `packs` beside the in-tree settings."""
        return cls(rulesets.catalog(packs), settings.catalog(packs), tuple(packs))

    @classmethod
    def installed(cls, config: Config) -> Catalogs:
        """The catalogs of the packs installed in `config`'s data directory (loaded once per folder)."""
        packs, _ = load_packs(config.packs_dir)
        return cls.of(packs)


IN_TREE = Catalogs.of(())
"""The catalogs of an install with no packs: what is built into Delve."""
