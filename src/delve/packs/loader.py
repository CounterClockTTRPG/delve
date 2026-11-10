"""Finding the packs an install has: each folder under the packs directory is read, imported and checked."""

from __future__ import annotations

import importlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from delve.packs.api import RulesetPack, SettingPack
from delve.packs.manifest import PackError, PackManifest

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedPack:
    manifest: PackManifest
    root: Path
    entry: RulesetPack | SettingPack


@dataclass(frozen=True)
class Skipped:
    folder: Path
    reason: str


_Result = tuple[tuple[LoadedPack, ...], tuple[Skipped, ...]]
_loaded: dict[Path, _Result] = {}
_imported: dict[str, str] = {}
"""The `src` path each pack package was imported from, so its cached modules can be dropped."""


def reset() -> None:
    """Forget the packs loaded so far, so the next `load_packs` reads the folders again (for tests)."""
    _loaded.clear()
    for package in list(_imported):
        _forget(package)


def _forget(package: str) -> None:
    """Drop a pack package, its submodules and its `src` path, so the next import reads the files again."""
    src = _imported.pop(package)
    for name in [n for n in sys.modules if n == package or n.startswith(package + ".")]:
        del sys.modules[name]
    while src in sys.path:
        sys.path.remove(src)


def load_packs(folder: Path) -> _Result:
    """The packs in `folder`'s sub-folders, in folder-name order, and the folders left out with why. A pack is left
    out, and logged at WARNING, when its manifest is bad, its package is Delve's own, its id is taken by an earlier
    folder, its package is used by an earlier folder, or its entry cannot be imported. Loaded once per folder for the process."""
    key = folder.resolve()
    if key not in _loaded:
        _loaded[key] = _load(key)
    return _loaded[key]


def _load(folder: Path) -> _Result:
    if not folder.is_dir():
        return (), ()
    packs: list[LoadedPack] = []
    skipped: list[Skipped] = []
    seen: dict[str, Path] = {}
    packages: dict[str, Path] = {}
    for root in sorted(p for p in folder.iterdir() if p.is_dir()):
        try:
            pack = _load_one(root, seen, packages)
        except PackError as error:
            log.warning("pack %s skipped: %s", root, error)
            skipped.append(Skipped(root, str(error)))
            continue
        seen[pack.manifest.id] = root
        packages[pack.manifest.package] = root
        packs.append(pack)
    return tuple(packs), tuple(skipped)


def _load_one(root: Path, seen: dict[str, Path], packages: dict[str, Path]) -> LoadedPack:
    manifest = PackManifest.read(root)
    if manifest.package == "delve" or manifest.package in sys.stdlib_module_names:
        raise PackError(f"package '{manifest.package}' is taken")
    if manifest.id in seen:
        raise PackError(f"id '{manifest.id}' is already used by {seen[manifest.id].name}")
    if manifest.package in packages:
        raise PackError(f"package '{manifest.package}' is already used by {packages[manifest.package].name}")
    src = str(root / "src")
    if _imported.get(manifest.package, src) != src:
        _forget(manifest.package)
    _imported[manifest.package] = src
    if src not in sys.path:
        sys.path.insert(0, src)
    importlib.invalidate_caches()
    module_name, _, attr = manifest.entry.partition(":")
    try:
        entry = getattr(importlib.import_module(module_name), attr)
    except ImportError as error:
        raise PackError(f"entry '{manifest.entry}' cannot be imported: {error}") from error
    except AttributeError:
        raise PackError(f"entry '{manifest.entry}' has no '{attr}'") from None
    except Exception as error:  # a pack's own code failing on import must not stop Delve
        raise PackError(f"entry '{manifest.entry}' failed on import: {error!r}") from error
    return LoadedPack(manifest, root, entry)
