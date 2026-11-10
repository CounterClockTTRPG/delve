"""Migration 0025 (module categories and banners, DEL-114 and DEL-123): it adds `module_categories` and a module's
`category_id` and `banner_*` columns to a database made at 0024, whose modules keep their rows with no category and
no banner. Downgrading drops what it added."""

import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _columns, _downgrade, _tables, db_revision

NOW = "2026-10-26T15:00:00+00:00"
ADDED = {"category_id", "banner_blob", "banner_mime", "banner_source", "banner_status", "banner_error", "banner_prompt"}


def test_migration_0025_adds_categories_and_banner_columns(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0024_cloud_storage")
    with sqlite3.connect(config.db_path) as db:
        db.execute(
            "INSERT INTO modules (id, title, metadata, created_at, updated_at) VALUES ('mod_1', 'Crypt', '{}', ?, ?)",
            (NOW, NOW),
        )

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        module = storage.modules.get("mod_1")
        assert module.title == "Crypt" and module.category_id is None and module.banner is None
        assert storage.module_categories.list() == []
    finally:
        storage.close()

    _downgrade(config, "0024_cloud_storage")
    with sqlite3.connect(config.db_path) as db:
        assert "module_categories" not in _tables(db)
        assert not ADDED & _columns(db, "modules")
        assert db.execute("SELECT title FROM modules").fetchall() == [("Crypt",)]
