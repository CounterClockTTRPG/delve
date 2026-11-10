"""Migration 0031 (join requests, DEL-204 part B): it adds `join_requests` to a database made at 0030, whose campaigns
and accounts keep their rows and have no requests yet. A request goes with its campaign and its account; the seat an
accept made is kept as a plain reference, cleared if that seat ever went. Downgrading drops it."""

import sqlite3

from delve.config import Config
from delve.domain.accounts import Profile
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _columns, _downgrade, _tables, db_revision

NOW = "2026-10-27T15:00:00+00:00"


def test_migration_0031_adds_the_join_requests(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0030_account_identities")
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
        ana = storage.accounts.create("ana", Profile("Ana"))
        assert storage.join_requests.of_campaign(campaign.id) == []
        storage.join_requests.create(campaign.id, ana.id, (), NOW)
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert _columns(db, "join_requests") == {
            "id",
            "campaign_id",
            "account_id",
            "status",
            "messages",
            "created_at",
            "decided_at",
            "seat_id",
            "role",  # 0037
        }
        cascades = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(join_requests)")}
        assert cascades == {
            ("campaigns", "campaign_id", "CASCADE"),
            ("accounts", "account_id", "CASCADE"),
            ("seats", "seat_id", "SET NULL"),
        }

    _downgrade(config, "0030_account_identities")
    with sqlite3.connect(config.db_path) as db:
        assert "join_requests" not in _tables(db)
        assert db.execute("SELECT name FROM campaigns").fetchall() == [("Tuesday",)]
