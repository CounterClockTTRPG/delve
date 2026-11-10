import hashlib
import sqlite3
import threading
import time
from itertools import count
from pathlib import Path
from unittest import mock

import pytest

from delve.config import Config
from delve.storage import open_storage
from tests.storage.contract import CONTRACT, run_contract_suite


def test_open_creates_data_dir_and_db(tmp_path):
    config = Config(data_dir=tmp_path / "not" / "there")
    storage = open_storage(config)
    try:
        assert config.data_dir.is_dir() and config.db_path.is_file()
    finally:
        storage.close()


def test_wal_enabled(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_foreign_keys_on(tmp_path):
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        with storage.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    finally:
        storage.close()


def test_synchronous_normal(tmp_path):
    """WAL with synchronous=NORMAL (DEL-165): one fsync per checkpoint, not per commit."""
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        with storage.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 1
    finally:
        storage.close()


def test_settings_survive_reopen(tmp_path):
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    storage.settings.save({"language": "nl"})
    storage.close()
    storage = open_storage(config)
    try:
        assert storage.settings.load() == {"language": "nl"}
    finally:
        storage.close()


def test_the_conversion_queue_switch_survives_a_restart(tmp_path):
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    storage.conversions.set_queue_paused(True)
    storage.close()
    storage = open_storage(config)
    try:
        assert storage.conversions.queue_paused() is True
    finally:
        storage.close()


def test_contract_suite_sqlite(tmp_path):
    n = count()
    run_contract_suite(lambda: open_storage(Config(data_dir=tmp_path / f"db{next(n)}")))


@pytest.mark.parametrize("check", CONTRACT, ids=lambda check: check.__name__)
def test_contract_check_sqlite(tmp_path, check):
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        check(storage)
    finally:
        storage.close()


def test_blob_stored_under_data_dir(tmp_path):
    data = b"a map image"
    sha = hashlib.sha256(data).hexdigest()
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        storage.blobs.put(data, "image/png")
    finally:
        storage.close()
    path = tmp_path / "blobs" / sha[:2] / sha
    assert path.read_bytes() == data
    assert [p.name for p in path.parent.iterdir()] == [sha]


def test_failed_blob_write_leaves_no_file(tmp_path):
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        with mock.patch("os.replace", side_effect=OSError("disk full")), pytest.raises(OSError):
            storage.blobs.put(b"half a bundle", "application/zip")
    finally:
        storage.close()
    assert [p for p in (tmp_path / "blobs").rglob("*") if p.is_file()] == []


def test_put_file_never_reads_the_whole_file(tmp_path):
    data = b"%PDF-1.4 " + bytes(range(256)) * 20_000
    book = tmp_path / "book.pdf"
    book.write_bytes(data)
    storage = open_storage(Config(data_dir=tmp_path / "data"))
    try:
        with (
            mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read whole")),
            mock.patch("delve.storage.sqlite.blobs.CHUNK", 4096),
        ):
            sha = storage.blobs.put_file(book, "application/pdf")
        assert storage.blobs.get(sha) == data
    finally:
        storage.close()
    path = tmp_path / "data" / "blobs" / sha[:2] / sha
    assert sha == hashlib.sha256(data).hexdigest()
    assert [p.name for p in path.parent.iterdir()] == [sha]
    assert [p.name for p in (tmp_path / "data" / "blobs").iterdir()] == [sha[:2]], "no temporary file is left"


def test_failed_put_file_leaves_no_file_and_no_blob(tmp_path):
    book = tmp_path / "book.pdf"
    book.write_bytes(b"%PDF-1.4 half a book")
    storage = open_storage(Config(data_dir=tmp_path / "data"))
    try:
        with mock.patch("os.replace", side_effect=OSError("disk full")), pytest.raises(OSError):
            storage.blobs.put_file(book, "application/pdf")
        assert not storage.blobs.exists(hashlib.sha256(book.read_bytes()).hexdigest())
    finally:
        storage.close()
    assert [p for p in (tmp_path / "data" / "blobs").rglob("*") if p.is_file()] == []


def test_busy_timeout_on_every_connection(tmp_path):
    """A second writer waits up to 5 s for the lock instead of failing at once with "database is locked"."""
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        with storage.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
    finally:
        storage.close()


def test_transactions_that_check_then_write_take_turns(tmp_path):
    """`transaction()` takes the write lock as it begins (`BEGIN IMMEDIATE`), so a second one waits for the first to
    commit before it reads: two that each read a count and write it one higher end at two. Deferred, as pysqlite begins
    by default, both read 0 and the second either loses the first's write or fails on its stale snapshot."""
    storage = open_storage(Config(data_dir=tmp_path))
    storage.settings.save({"count": 0})
    first_read = threading.Event()
    failures: list[BaseException] = []

    def bump(signal: bool) -> None:
        try:
            with storage.transaction():
                count = storage.settings.load()["count"]
                if signal:
                    first_read.set()
                    time.sleep(0.2)  # the other one tries to begin meanwhile
                storage.settings.save({"count": count + 1})
        except BaseException as failure:  # noqa: BLE001 - reported below
            failures.append(failure)

    try:
        first = threading.Thread(target=bump, args=(True,))
        first.start()
        assert first_read.wait(5)
        second = threading.Thread(target=bump, args=(False,))
        second.start()
        first.join()
        second.join()
        assert failures == []
        assert storage.settings.load()["count"] == 2
    finally:
        storage.close()
