"""The ruleset and the settings core tests play: OSRIC (`packs/osric`), and the test doubles of the private Greyhawk
and Forgotten Realms packs (`tests/fixtures/packs`, tiny wikis), installed as packs once per test process, never
imported.

Delve has no ruleset built in and only Aun as a setting (DEL-307), so a test that plays a campaign plays OSRIC, in
Greyhawk or the Realms when it names them: through `osric_catalogs()` over OSRIC's own lookups, or through
`over(reference)`, OSRIC's tables with a stand-in reference (`PlayReference`) in place of its lookups, which is what a
test of the play services needs to say what the lookups find.
"""

from __future__ import annotations

import atexit
import functools
import shutil
import tempfile
from pathlib import Path
from typing import Any

from delve.domain.reference import RulesetReference
from delve.packs import loader
from delve.packs.catalogs import Catalogs
from delve.packs.transit import install_pack
from delve.rules.catalog import RulesetEntry

OSRIC = Path(__file__).resolve().parents[2] / "packs" / "osric"
SETTING_PACKS = tuple((Path(__file__).resolve().parent / "packs" / name) for name in ("greyhawk", "forgotten-realms"))
"""The test doubles of the private setting packs."""
RULESET = "osric"
"""The ruleset id of the campaigns core tests play."""


@functools.cache
def osric_packs_dir() -> Path:
    """A packs folder with `packs/osric` and the setting doubles installed, made once per process and removed at its
    end."""
    folder = Path(tempfile.mkdtemp(prefix="osric-packs-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    for pack in (OSRIC, *SETTING_PACKS):
        install_pack(pack, folder)
    return folder


def install_test_packs(packs_dir: Path) -> None:
    """OSRIC and the setting doubles as `packs_dir` (a test's data dir's `packs`, which must not exist yet): a link to
    `osric_packs_dir`, where they were installed and built once, so the loader loads them once (a second copy would
    import their packages anew, and classes already held would no longer be theirs). A test must not change them."""
    packs_dir.parent.mkdir(parents=True, exist_ok=True)
    packs_dir.symlink_to(osric_packs_dir())


def setting(setting_id: str = "greyhawk", exclude: frozenset[str] | None = None) -> Any:
    """The setting `setting_id` of `osric_catalogs` (Greyhawk's double by default), leaving out `exclude`, else the
    fact categories the other settings claim."""
    from delve.setting.catalog import claimed_elsewhere, entry

    settings = osric_catalogs().settings
    found = entry(setting_id, settings)
    assert found is not None, setting_id
    return found.make(claimed_elsewhere(setting_id, settings) if exclude is None else exclude)


def osric_packs() -> tuple[loader.LoadedPack, ...]:
    """The loaded packs of `osric_packs_dir`: OSRIC and the setting doubles."""
    packs, skipped = loader.load_packs(osric_packs_dir())
    assert not skipped, skipped
    return packs


def osric() -> Any:
    """OSRIC's ruleset, made by its pack: for its tables (`osric().tables`) where a test needs a ruleset's numbers."""
    pack = _osric_pack()
    return pack.entry.ruleset(pack.root)  # type: ignore[union-attr]


def _osric_pack() -> loader.LoadedPack:
    return next(p for p in osric_packs() if p.manifest.id == RULESET)


def osric_catalogs() -> Catalogs:
    """The catalogs of OSRIC over its own lookups, with Greyhawk and the Realms (the doubles) and Aun."""
    return Catalogs.of(osric_packs())


class Over:
    """OSRIC's ruleset with `reference` in place of its lookups: its tables, prompt and treasure, and the engine's
    tiered encounter tables (`encounters` None), which read `reference` as the lookups do."""

    encounters = None

    def __init__(self, osric: Any, reference: RulesetReference | None) -> None:
        self._osric = osric
        self.reference = reference

    def __getattr__(self, name: str) -> Any:
        return getattr(self._osric, name)


def over(reference: Any) -> Catalogs:
    """The catalogs of OSRIC with `reference` (a stand-in of the lookups) in place of its own, with the settings of
    `osric_catalogs`."""
    pack = _osric_pack()
    entry = RulesetEntry(
        pack.manifest.id,
        pack.manifest.title,
        pack.manifest.package,
        lambda: Over(pack.entry.ruleset(pack.root), reference),  # type: ignore[union-attr]
    )
    catalogs = osric_catalogs()
    return Catalogs((entry,), catalogs.settings, catalogs.packs)
