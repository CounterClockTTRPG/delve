"""Migration 0029 (the table's listing, DEL-204): it adds a campaign's visibility, description and slots to a database
made at 0028, whose campaigns keep their rows and get the defaults that keep them as they were: private, no
description, no limit. Downgrading drops the three columns."""

import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _columns, _downgrade, db_revision

NOW = "2026-10-27T15:00:00+00:00"
LISTING = {"visibility", "description", "slots"}


def test_migration_0029_adds_the_listing(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0028_table_sessions")
    with sqlite3.connect(config.db_path) as db:
        db.execute(
            "INSERT INTO modules (id, title, metadata, created_at, updated_at) VALUES ('mod_1', 'Crypt', '{}', ?, ?)",
            (NOW, NOW),
        )
        db.execute(
            "INSERT INTO module_revisions (module_id, number, title, metadata, maps, created_at) "
            "VALUES ('mod_1', 1, 'Crypt', '{}', '[]', ?)",
            (NOW,),
        )
        db.execute(
            "INSERT INTO campaigns (id, name, module_id, revision, created_at, join_token) "
            "VALUES ('cmp_1', 'Tuesday', 'mod_1', 1, ?, 'join-me')",
            (NOW,),
        )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        campaign = storage.campaigns.get("cmp_1")
        assert (campaign.visibility, campaign.description, campaign.slots) == ("private", "", None)
        assert storage.campaigns.set_listing("cmp_1", "public", "Newcomers welcome.", 5).slots == 5
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert LISTING <= _columns(db, "campaigns")

    _downgrade(config, "0028_table_sessions")
    with sqlite3.connect(config.db_path) as db:
        assert not LISTING & _columns(db, "campaigns")
        assert db.execute("SELECT name, voice FROM campaigns").fetchall() == [("Tuesday", "allowed")]
