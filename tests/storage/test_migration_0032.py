"""Migration 0032 (the table's schedule, DEL-204 part C): it adds a campaign's `schedule` to a database made at 0031,
whose campaigns keep their rows and have none. Downgrading drops the column."""

import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _columns, _downgrade, db_revision

NOW = "2026-10-27T15:00:00+00:00"
RULE = {"every_weeks": 1, "first": "2026-11-03", "start": "19:30", "end": "22:30", "time_zone": "Europe/Riga"}


def test_migration_0032_adds_the_schedule(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0031_join_requests")
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
            "INSERT INTO campaigns (id, name, module_id, revision, created_at, join_token, visibility) "
            "VALUES ('cmp_1', 'Tuesday', 'mod_1', 1, ?, 'join-me', 'public')",
            (NOW,),
        )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        campaign = storage.campaigns.get("cmp_1")
        assert (campaign.schedule, campaign.visibility) == (None, "public")
        rule = {**RULE, "changes": []}
        assert storage.campaigns.set_schedule("cmp_1", rule).schedule == rule
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert "schedule" in _columns(db, "campaigns")

    _downgrade(config, "0031_join_requests")
    with sqlite3.connect(config.db_path) as db:
        assert "schedule" not in _columns(db, "campaigns")
        assert db.execute("SELECT name, visibility FROM campaigns").fetchall() == [("Tuesday", "public")]
