"""Migration 0024 (cloud storage, DEL-110): it adds `backup_items` and a module's `library_*` columns to a database
made at 0023, whose modules keep their rows with no library entry. Downgrading drops what it added."""

import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _columns, _downgrade, _tables, db_revision

NOW = "2026-10-26T04:00:00+00:00"
LIBRARY = {"library_key", "library_version", "library_hash", "library_origin", "library_author"}


def test_migration_0024_adds_backup_items_and_library_columns(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0023_image_jobs")
    with sqlite3.connect(config.db_path) as db:
        db.execute(
            "INSERT INTO modules (id, title, metadata, created_at, updated_at) VALUES ('mod_1', 'Crypt', '{}', ?, ?)",
            (NOW, NOW),
        )

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        module = storage.modules.get("mod_1")
        assert module.title == "Crypt" and module.library_key is None and module.library_origin is None
        assert storage.backup_items.list() == []
    finally:
        storage.close()

    _downgrade(config, "0023_image_jobs")
    with sqlite3.connect(config.db_path) as db:
        assert "backup_items" not in _tables(db)
        assert not LIBRARY & _columns(db, "modules")
        assert db.execute("SELECT title FROM modules").fetchall() == [("Crypt",)]
