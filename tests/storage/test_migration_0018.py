"""Migration 0018 (carry-the-party-on plan Task 1): it adds `campaign_histories` and `campaign_carries` to a 0017
database, its campaigns as they were, and downgrading drops them."""

import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migrations import HEAD, _columns, _downgrade, _tables, db_revision

HISTORY_COLUMNS = {
    "campaign_id", "dm_md", "table_md", "status", "error", "edited", "conversion_id", "cost_usd", "created_at",
    "updated_at",
}  # fmt: skip
CARRY_COLUMNS = {"id", "from_campaign_id", "to_campaign_id", "character_ids", "carried_at"}
TABLES = {"campaign_histories", "campaign_carries"}


def test_0018_upgrade_and_downgrade(tmp_path):
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
    finally:
        storage.close()
    _downgrade(config, "0017_novels")
    with sqlite3.connect(config.db_path) as db:
        assert not TABLES & _tables(db)

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        assert storage.campaigns.get(campaign.id).name == "Tuesday"
        assert storage.histories.get(campaign.id) is None and storage.histories.writing() == []
        assert storage.carries.origin(campaign.id) is None and storage.carries.onward(campaign.id) == []
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert TABLES <= _tables(db)
        assert _columns(db, "campaign_histories") == HISTORY_COLUMNS
        assert _columns(db, "campaign_carries") == CARRY_COLUMNS
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(campaign_histories)")}
        assert keys == {("campaigns", "campaign_id", "CASCADE")}
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(campaign_carries)")}
        assert keys == {("campaigns", "from_campaign_id", "SET NULL"), ("campaigns", "to_campaign_id", "CASCADE")}
        indexed = {row[1] for row in db.execute("PRAGMA index_list(campaign_carries)")}
        assert "ix_campaign_carries_from_campaign_id" in indexed

    _downgrade(config, "0017_novels")
    with sqlite3.connect(config.db_path) as db:
        assert not TABLES & _tables(db)
        assert db.execute("SELECT name FROM campaigns").fetchall() == [("Tuesday",)]
