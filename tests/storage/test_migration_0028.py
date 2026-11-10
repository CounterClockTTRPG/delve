"""Migration 0028 (the table's session state, DEL-199): it adds `table_sessions`, one row per campaign, to a database
made at 0027, whose campaigns keep their rows and have no session state yet. Downgrading drops it."""

import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _columns, _downgrade, _tables, db_revision

NOW = "2026-10-27T15:00:00+00:00"


def test_migration_0028_adds_the_table_sessions(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0027_account_sign_ups")
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
        assert storage.table_sessions.get(campaign.id) is None
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert _columns(db, "table_sessions") == {
            "campaign_id",
            "state",
            "since",
            "absent",
            "hands",
            "break_at",
            "updated_at",
            "away",  # 0035
        }
        cascades = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(table_sessions)")}
        assert cascades == {("campaigns", "campaign_id", "CASCADE")}

    _downgrade(config, "0027_account_sign_ups")
    with sqlite3.connect(config.db_path) as db:
        assert "table_sessions" not in _tables(db)
        assert db.execute("SELECT name FROM campaigns").fetchall() == [("Tuesday",)]
