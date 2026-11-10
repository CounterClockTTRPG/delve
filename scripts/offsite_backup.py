"""Copy Delve's code and database off this machine each night, into Delve's own backup store (owner, 2026-10-27).

The server holds both Delve's checkout and gitea, so a crash of it would take the code with it. This writes, under
`offsite/` in the store that Preferences set as Delve's backup store (the same container, the same credential):

- `offsite/code/delve-<date>.bundle`: the repository as `git bundle create --all` makes it, every branch and tag with
  its history; `git clone delve-<date>.bundle delve` gives it back anywhere;
- `offsite/db/delve-<date>.db.gz`: a consistent copy of `delve.db` (SQLite's online backup, safe while Delve runs),
  gzipped. Its accounts, campaigns and settings: the data dir's secrets (`token`, `device-secret`, the stores'
  credentials) stay here;
- `offsite/code/delve-<date>.packs.bundle`: the private packs repository (`delve-packs`, beside Delve's checkout, or
  `--packs-repo`), as Delve's is, when there is one;
- `offsite/packs/delve-<date>.packs.json`: the packs the install has (`packs/*/pack.toml`: id, kind, title, version),
  so they can be installed again (`delve pack install`); a pack's `pack.db` is built again on install, never copied.

Copies older than `--keep-days` are deleted. Delve's own backups live under the install's id, and a restore only reads
prefixes that hold an index, so `offsite/` is never mistaken for one. The credential never reaches the log. Run by the
`delve-offsite.timer` user unit; by hand:

    uv run python scripts/offsite_backup.py
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from delve.cloud.connections import load_store, open_store
from delve.cloud.store import StoreError

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "delve"
PREFIX = "offsite/"
KEEP_DAYS = 30
# A night's copy is a few tens of megabytes: time enough for a slow upload.
TIMEOUT = httpx.Timeout(600.0, connect=20.0)

log = logging.getLogger("offsite")


def code_bundle(repo: Path, out: Path) -> Path:
    """The repository at `repo` as one bundle file of every ref, at `out`."""
    subprocess.run(["git", "-C", str(repo), "bundle", "create", str(out), "--all"], check=True, capture_output=True)
    return out


def installed_packs(data_dir: Path) -> list[dict[str, str]]:
    """The packs in `data_dir/packs`, by id: what each `pack.toml` says it is. A folder without a readable manifest is
    left out."""
    packs = []
    for manifest in sorted((data_dir / "packs").glob("*/pack.toml")):
        try:
            raw = tomllib.loads(manifest.read_text("utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        packs.append({key: str(raw.get(key, "")) for key in ("id", "kind", "title", "version")})
    return packs


def database_copy(db: Path, out: Path) -> Path:
    """A consistent copy of the SQLite database `db`, gzipped at `out`, taken while it may be in use."""
    plain = out.with_suffix("")
    source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(plain)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    with plain.open("rb") as raw, gzip.open(out, "wb", compresslevel=6) as packed:
        while chunk := raw.read(1 << 20):
            packed.write(chunk)
    plain.unlink()
    return out


def stale(names: list[str], today: date, keep_days: int) -> list[str]:
    """The copies among `names` (`offsite/…/delve-<YYYY-MM-DD>.…`) older than `keep_days`; names without a date stay."""
    oldest = today - timedelta(days=keep_days)
    old = []
    for name in names:
        stem = name.rsplit("/", 1)[-1].removeprefix("delve-")[:10]
        try:
            when = date.fromisoformat(stem)
        except ValueError:
            continue
        if when < oldest:
            old.append(name)
    return old


async def run(data_dir: Path, repo: Path, keep_days: int, today: date, packs_repo: Path | None = None) -> int:
    config = load_store(data_dir, "backup")
    if config is None:
        log.error("No backup store is set in Preferences: nothing was copied.")
        return 1
    with tempfile.TemporaryDirectory(prefix="delve-offsite-") as scratch:
        work = Path(scratch)
        copies = {
            f"{PREFIX}code/delve-{today.isoformat()}.bundle": code_bundle(repo, work / "delve.bundle"),
            f"{PREFIX}db/delve-{today.isoformat()}.db.gz": database_copy(data_dir / "delve.db", work / "delve.db.gz"),
        }
        if packs_repo is not None and (packs_repo / ".git").exists():
            bundle = code_bundle(packs_repo, work / "packs.bundle")
            copies[f"{PREFIX}code/delve-{today.isoformat()}.packs.bundle"] = bundle
        listed = work / "packs.json"
        listed.write_text(json.dumps(installed_packs(data_dir), indent=2) + "\n")
        copies[f"{PREFIX}packs/delve-{today.isoformat()}.packs.json"] = listed
        store = open_store(config, httpx.AsyncClient(timeout=TIMEOUT))
        try:
            for name, path in copies.items():
                await store.put(name, path.read_bytes())
                log.info("copied %s (%d bytes)", name, path.stat().st_size)
            names = [listed.name for listed in await store.list(PREFIX)]
            for name in stale(names, today, keep_days):
                await store.delete(name)
                log.info("deleted %s", name)
        except StoreError as error:
            log.error("The copy broke off: %s", error)
            return 1
        finally:
            await store.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--keep-days", type=int, default=KEEP_DAYS)
    parser.add_argument("--packs-repo", type=Path, default=ROOT.parent / "delve-packs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return asyncio.run(run(args.data_dir, args.repo, args.keep_days, datetime.now(UTC).date(), args.packs_repo))


if __name__ == "__main__":
    sys.exit(main())
