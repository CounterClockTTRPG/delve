"""Migration 0038 (DEL-252): a campaign's stored portrait style `illustrated`, the old default every saved play setting
carried, becomes null, as in Preferences; a style a host chose stays. Downgrading gives null back as `illustrated`."""

import json
import sqlite3

from delve.config import Config
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _downgrade, db_revision

NOW = "2026-10-28T11:00:00+00:00"


def _style(db, campaign_id):
    raw = db.execute("SELECT raw FROM play_settings WHERE campaign_id = ?", (campaign_id,)).fetchone()[0]
    return json.loads(raw).get("portrait_style", "missing")


def test_migration_0038_makes_the_old_default_as_in_preferences(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    _upgrade_to(config, "0037_observers")
    with sqlite3.connect(config.db_path) as db:
        db.execute("INSERT INTO modules (id, title, metadata, created_at, updated_at) VALUES ('mod_1', 'C', '{}', ?, ?)",
                   (NOW, NOW))
        db.execute("INSERT INTO module_revisions (module_id, number, title, metadata, maps, created_at) "
                   "VALUES ('mod_1', 1, 'C', '{}', '[]', ?)", (NOW,))
        for cid, style in (("cmp_1", "illustrated"), ("cmp_2", "inkwash")):
            db.execute("INSERT INTO campaigns (id, name, module_id, revision, created_at, join_token) "
                       "VALUES (?, ?, 'mod_1', 1, ?, ?)", (cid, cid, NOW, f"join-{cid}"))
            db.execute("INSERT INTO play_settings (campaign_id, raw, updated_at) VALUES (?, ?, ?)",
                       (cid, json.dumps({"tone": "classic", "portrait_style": style}), NOW))
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert (_style(db, "cmp_1"), _style(db, "cmp_2")) == (None, "inkwash")
        assert json.loads(db.execute("SELECT raw FROM play_settings WHERE campaign_id = 'cmp_1'").fetchone()[0])[
            "tone"
        ] == "classic", "the rest is kept"
    _downgrade(config, "0037_observers")
    with sqlite3.connect(config.db_path) as db:
        assert (_style(db, "cmp_1"), _style(db, "cmp_2")) == ("illustrated", "inkwash")
