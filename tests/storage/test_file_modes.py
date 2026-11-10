"""The data directory is 0700 and the database's files 0600 (DEL-154, audit finding 13): Delve makes them so, and
tightens what an older Delve, or a hand-made copy, left readable by others."""

import os
import sqlite3
import stat

import pytest

from delve.config import Config, private_data_dir
from delve.storage import database_copies, migrate, open_storage


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def loose_umask():
    old = os.umask(0o002)
    yield
    os.umask(old)


def test_a_new_data_dir_and_database_are_private(tmp_path, loose_umask):
    config = Config(data_dir=tmp_path / "new")
    storage = open_storage(config)
    try:
        storage.settings.save({"language": "nl"})  # a write, so the WAL and its index exist
        assert mode(config.data_dir) == 0o700
        for name in ("delve.db", "delve.db-wal", "delve.db-shm"):
            assert (config.data_dir / name).exists(), name
            assert mode(config.data_dir / name) == 0o600, name
    finally:
        storage.close()


def test_a_loose_data_dir_is_tightened_at_start(tmp_path, loose_umask):
    config = Config(data_dir=tmp_path)
    migrate(config)
    with sqlite3.connect(config.db_path) as db:  # leaves a WAL behind, as a running Delve does
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS t (x)")
    copies = ["delve.db.pre-0026", "delve.db.before-stonehell", "reference.db.pre-voice-20261025"]
    for name in copies:
        (tmp_path / name).write_bytes(b"an old copy")
    (tmp_path / "reference.db").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("not the database's")
    tmp_path.chmod(0o775)
    for path in tmp_path.iterdir():
        path.chmod(0o664)

    open_storage(config).close()
    assert mode(tmp_path) == 0o700
    for name in ("delve.db", "delve.db-wal", "delve.db-shm", "reference.db", *copies):
        if (tmp_path / name).exists():
            assert mode(tmp_path / name) == 0o600, name
    assert all((tmp_path / name).read_bytes() == b"an old copy" for name in copies)  # tightened, never removed
    assert mode(tmp_path / "notes.txt") == 0o664  # not a file of the database


def test_migrate_tightens_too(tmp_path):
    config = Config(data_dir=tmp_path)
    migrate(config)
    tmp_path.chmod(0o755)
    config.db_path.chmod(0o644)
    migrate(config)
    assert (mode(tmp_path), mode(config.db_path)) == (0o700, 0o600)


def test_a_symlink_among_the_copies_is_left_alone(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_bytes(b"x")
    target.chmod(0o644)
    data = tmp_path / "data"
    data.mkdir()
    (data / "delve.db.old").symlink_to(target)
    open_storage(Config(data_dir=data)).close()
    assert mode(target) == 0o644


def test_private_data_dir_makes_and_tightens(tmp_path, loose_umask):
    private_data_dir(tmp_path / "a" / "b")
    assert mode(tmp_path / "a" / "b") == 0o700
    (tmp_path / "a" / "b").chmod(0o777)
    private_data_dir(tmp_path / "a" / "b")
    assert mode(tmp_path / "a" / "b") == 0o700


def test_database_copies_lists_the_old_copies_only(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    for name in ("delve.db.pre-0026", "delve.db.before-stonehell", "reference.db.pre-voice", "delve.dbx", "token"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "reference.db").write_bytes(b"")
    assert [p.name for p in database_copies(config)] == [
        "delve.db.before-stonehell",
        "delve.db.pre-0026",
        "reference.db.pre-voice",
    ]
    assert database_copies(Config(data_dir=tmp_path / "missing")) == []
