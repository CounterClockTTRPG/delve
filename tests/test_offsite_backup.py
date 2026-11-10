"""The nightly off-site copy of Delve's code and database (scripts/offsite_backup.py)."""

from __future__ import annotations

import asyncio
import gzip
import importlib.util
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

from delve.cloud.connections import StoreConfig, save_store

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "offsite_backup.py"
_spec = importlib.util.spec_from_file_location("offsite_backup", SCRIPT)
offsite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offsite)


def a_repo(path: Path) -> Path:
    path.mkdir()
    run = lambda *args: subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    run("init", "-q", "-b", "master")
    (path / "README.md").write_text("Delve\n")
    run("add", "README.md")
    run("-c", "user.name=t", "-c", "user.email=t@x", "commit", "-q", "-m", "first")
    return path


def a_database(data_dir: Path) -> None:
    data_dir.mkdir(exist_ok=True)
    db = sqlite3.connect(data_dir / "delve.db")
    db.execute("CREATE TABLE campaigns (name TEXT)")
    db.execute("INSERT INTO campaigns VALUES ('Puppets')")
    db.commit()
    db.close()


def test_copies_the_code_and_the_database_and_keeps_thirty_days(tmp_path):
    repo, data_dir, store = a_repo(tmp_path / "repo"), tmp_path / "data", tmp_path / "store"
    a_database(data_dir)
    store.mkdir()
    save_store(data_dir, "backup", StoreConfig("local", root=str(store)), keep_secret=False)
    old = store / "offsite" / "code" / "delve-2026-09-01.bundle"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    kept = store / "offsite" / "code" / "delve-2026-10-20.bundle"
    kept.write_bytes(b"kept")
    own = store / "inst_x" / "index.json"  # one of Delve's own backups: never touched
    own.parent.mkdir()
    own.write_text("{}")

    assert asyncio.run(offsite.run(data_dir, repo, 30, date(2026, 10, 27))) == 0

    bundle = store / "offsite" / "code" / "delve-2026-10-27.bundle"
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bundle), str(clone)], check=True, capture_output=True)
    assert (clone / "README.md").read_text() == "Delve\n"
    copied = tmp_path / "copied.db"
    copied.write_bytes(gzip.decompress((store / "offsite" / "db" / "delve-2026-10-27.db.gz").read_bytes()))
    assert sqlite3.connect(copied).execute("SELECT name FROM campaigns").fetchall() == [("Puppets",)]
    assert not old.exists() and kept.exists() and own.exists()


def test_copies_the_packs_repository_and_lists_the_installed_packs(tmp_path):
    """DEL-307: the private packs repository is bundled as Delve's is, and the install's packs are listed so they can
    be installed again; their pack.db is never copied."""
    import json

    repo, packs_repo, data_dir, store = (
        a_repo(tmp_path / "repo"),
        a_repo(tmp_path / "packs"),
        tmp_path / "data",
        tmp_path / "store",
    )
    a_database(data_dir)
    osric = data_dir / "packs" / "osric"
    osric.mkdir(parents=True)
    (osric / "pack.toml").write_text('id = "osric"\nkind = "ruleset"\ntitle = "OSRIC 3.0"\nversion = "1.0.0"\n')
    (osric / "pack.db").write_bytes(b"built")
    store.mkdir()
    save_store(data_dir, "backup", StoreConfig("local", root=str(store)), keep_secret=False)

    assert asyncio.run(offsite.run(data_dir, repo, 30, date(2026, 11, 1), packs_repo)) == 0

    assert (store / "offsite" / "code" / "delve-2026-11-01.packs.bundle").is_file()
    listed = json.loads((store / "offsite" / "packs" / "delve-2026-11-01.packs.json").read_text())
    assert listed == [{"id": "osric", "kind": "ruleset", "title": "OSRIC 3.0", "version": "1.0.0"}]
    assert not list(store.rglob("pack.db"))


def test_without_a_backup_store_nothing_is_copied(tmp_path):
    repo, data_dir = a_repo(tmp_path / "repo"), tmp_path / "data"
    a_database(data_dir)
    assert asyncio.run(offsite.run(data_dir, repo, 30, date(2026, 10, 27))) == 1


def test_stale_reads_the_date_in_the_name():
    names = ["offsite/db/delve-2026-09-26.db.gz", "offsite/db/delve-2026-09-27.db.gz", "offsite/notes.txt"]
    assert offsite.stale(names, date(2026, 10, 27), 30) == ["offsite/db/delve-2026-09-26.db.gz"]
