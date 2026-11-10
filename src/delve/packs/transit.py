"""How a pack travels: built into one `.delvepack` file, then checked against its manifest and installed in one rename."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from delve.packs.manifest import MANIFEST_NAME, PackError, PackManifest

__all__ = ["PackError", "build_pack", "install_pack", "pack_folders", "rebuild_pack", "remove_pack"]

CHECKSUMS_NAME = "MANIFEST"
_LEFT_OUT_FILES = frozenset({"pack.db"})

_CHECK = """
import importlib, sys
from pathlib import Path
root, kind, entry = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
sys.path.insert(0, str(root / "src"))
module, _, attr = entry.partition(":")
pack = getattr(importlib.import_module(module), attr)
if not callable(getattr(pack, kind, None)):
    sys.exit(f"entry '{entry}' is not a {kind} pack: it has no '{kind}'")
build = getattr(pack, "build", None)
if build is not None:
    build(root, root / "pack.db")
"""


def _left_out(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if any(part.startswith(".") for part in parts):
        return True
    if parts[0] == "tests" or "__pycache__" in parts:
        return True
    return (len(parts) == 1 and parts[0] in _LEFT_OUT_FILES) or relative.suffix == ".pyc"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_pack(folder: Path, out_dir: Path) -> Path:
    """Write `<id>-<version>.delvepack` into `out_dir` from the pack in `folder` and return its path. It holds every
    file of the folder except `tests/`, `pack.db`, `__pycache__/`, `*.pyc` and dot-files; `pack.toml` comes first and
    `MANIFEST` lists the SHA-256 of every other file."""
    manifest = PackManifest.read(folder)
    files: dict[str, bytes] = {}
    for path in sorted(folder.rglob("*")):
        relative = PurePosixPath(path.relative_to(folder).as_posix())
        if _left_out(relative):
            continue
        if path.is_symlink():
            raise PackError(f"{relative} is a symlink")
        if path.is_file():
            files[str(relative)] = path.read_bytes()
    checksums = "".join(f"{_digest(data)}  {name}\n" for name, data in files.items())
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{manifest.id}-{manifest.version}.delvepack"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, files.pop(MANIFEST_NAME))
        archive.writestr(CHECKSUMS_NAME, checksums)
        for name, data in files.items():
            archive.writestr(name, data)
    return target


def install_pack(source: Path | str, packs_dir: Path) -> PackManifest:
    """Install the pack in `source` into `packs_dir`, replacing a pack of the same id, and return its manifest. The
    source is a `.delvepack` file, a pack folder, or a git URL, which may end in `#<folder>` for a pack in a repo of
    several. The pack is checked and built in a folder beside the others first; on any failure that folder is
    deleted and the installed pack stays."""
    if isinstance(source, str) and ("://" in source or source.startswith("git@")):
        return _install_from_git(source, packs_dir)
    return _install_local(Path(source), packs_dir)


def _install_from_git(url: str, packs_dir: Path) -> PackManifest:
    url, _, subfolder = url.partition("#")
    with tempfile.TemporaryDirectory(prefix="delve-pack-") as temp:
        clone = Path(temp) / "clone"
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(clone)], check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as error:
            raise PackError(f"git could not clone {url}: {_last_line(error.stderr)}") from error
        except FileNotFoundError:
            raise PackError("git is not installed") from None
        folder = clone / subfolder if subfolder else clone
        if not folder.resolve().is_relative_to(clone.resolve()) or not folder.is_dir():
            raise PackError(f"{url} has no folder '{subfolder}'")
        return _install_local(folder, packs_dir)


def _install_local(source: Path, packs_dir: Path) -> PackManifest:
    if source.is_dir():
        with tempfile.TemporaryDirectory(prefix="delve-pack-") as temp:
            return _install_file(build_pack(source, Path(temp)), packs_dir)
    if not source.is_file():
        raise PackError(f"{source} is not a .delvepack file or a pack folder")
    return _install_file(source, packs_dir)


def _install_file(archive_path: Path, packs_dir: Path) -> PackManifest:
    packs_dir.mkdir(parents=True, exist_ok=True)
    incoming = Path(tempfile.mkdtemp(prefix=".incoming-", dir=packs_dir))
    old: Path | None = None
    try:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                _extract(archive, incoming)
        except zipfile.BadZipFile as error:
            raise PackError(f"{archive_path.name} is not a .delvepack file: {error}") from error
        manifest = PackManifest.read(incoming)
        # Name the folder after the pack now that its id is known.
        named = packs_dir / f".incoming-{manifest.id}-{incoming.name.removeprefix('.incoming-')}"
        incoming = incoming.rename(named)
        _check_in_subprocess(incoming, manifest)
        final = packs_dir / manifest.id
        if final.exists():
            old = packs_dir / f".old-{manifest.id}"
            shutil.rmtree(old, ignore_errors=True)
            os.replace(final, old)
        try:
            os.replace(incoming, final)
        except OSError:
            if old is not None:
                os.replace(old, final)
                old = None
            raise
        return manifest
    finally:
        shutil.rmtree(incoming, ignore_errors=True)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)


def _extract(archive: zipfile.ZipFile, target: Path) -> None:
    """Unpack `archive` into `target`, refusing a path that leaves it, a symlink, a file `MANIFEST` does not list and
    a file whose SHA-256 differs from `MANIFEST`'s."""
    entries = [info for info in archive.infolist() if not info.is_dir()]
    names = [info.filename for info in entries]
    for info in entries:
        _check_name(info)
    if len(set(names)) != len(names):
        raise PackError("a file appears twice in the pack")
    if CHECKSUMS_NAME not in names:
        raise PackError(f"no {CHECKSUMS_NAME} in the pack")
    listed = _read_checksums(archive.read(CHECKSUMS_NAME).decode("utf-8", "replace"))
    for name in names:
        if name != CHECKSUMS_NAME and name not in listed:
            raise PackError(f"{name} is not in {CHECKSUMS_NAME}")
    for name in listed:
        if name not in names:
            raise PackError(f"{name} is listed in {CHECKSUMS_NAME} but missing")
    for info in entries:
        if info.filename == CHECKSUMS_NAME:
            continue
        data = archive.read(info)
        if _digest(data) != listed[info.filename]:
            raise PackError(f"{info.filename} does not match its checksum in {CHECKSUMS_NAME}")
        path = target / info.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _check_name(info: zipfile.ZipInfo) -> None:
    name = info.filename
    path = PurePosixPath(name)
    if "\\" in name or path.is_absolute() or ".." in path.parts or (len(name) > 1 and name[1] == ":"):
        raise PackError(f"{name} is outside the pack")
    if stat.S_ISLNK(info.external_attr >> 16):
        raise PackError(f"{name} is a symlink")


def _read_checksums(text: str) -> dict[str, str]:
    listed: dict[str, str] = {}
    for line in text.splitlines():
        digest, separator, name = line.partition("  ")
        if not line.strip():
            continue
        if not separator or len(digest) != 64:
            raise PackError(f"{CHECKSUMS_NAME} has a line that is not '<sha256>  <path>': {line!r}")
        if name in listed:
            raise PackError(f"{name} is listed twice in {CHECKSUMS_NAME}")
        listed[name] = digest
    return listed


def _check_in_subprocess(root: Path, manifest: PackManifest) -> None:
    """Import the pack's entry in a fresh interpreter, check it is the kind the manifest says and run its `build`,
    so a broken pack never enters this process. The last line of the interpreter's stderr is the failure."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-I", "-c", _CHECK, str(root), manifest.kind, manifest.entry],
        cwd=root,
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PackError(f"{manifest.id}: {_last_line(result.stderr) or f'exited with {result.returncode}'}")


def _last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def pack_folders(packs_dir: Path) -> dict[str, Path]:
    """The installed packs' ids and their folders; a folder without a readable manifest, and dot-folders, are left out."""
    found: dict[str, Path] = {}
    if packs_dir.is_dir():
        for folder in sorted(p for p in packs_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
            try:
                found.setdefault(PackManifest.read(folder).id, folder)
            except PackError:
                continue
    return found


def remove_pack(pack_id: str, packs_dir: Path) -> None:
    """Delete the installed pack with this id, `pack.db` and all."""
    folder = pack_folders(packs_dir).get(pack_id)
    if folder is None:
        raise PackError(f"no pack '{pack_id}' is installed")
    shutil.rmtree(folder)


def rebuild_pack(pack_id: str, packs_dir: Path) -> None:
    """Run the installed pack's `build` again, in place."""
    folder = pack_folders(packs_dir).get(pack_id)
    if folder is None:
        raise PackError(f"no pack '{pack_id}' is installed")
    _check_in_subprocess(folder, PackManifest.read(folder))
