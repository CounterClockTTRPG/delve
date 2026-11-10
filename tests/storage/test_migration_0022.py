"""Migration 0022 (table voice and fixes Task 0): it adds the campaign's voice and initiative mode, a character's
departure, a conversion's comments and closed questions, the fight's rounds (`combat_rounds`) and the fix-it comments
(`module_comments`) to a database made at 0021, whose campaigns, characters, fights and conversions keep their rows
and get the defaults that keep them working as before. Downgrading drops what it added."""

import json
import sqlite3

from delve.config import Config
from delve.rules.classic import combat as rules
from delve.storage import open_storage
from tests.storage.test_migration_0020 import _upgrade_to
from tests.storage.test_migrations import HEAD, _columns, _downgrade, _tables, db_revision

NOW = "2026-10-24T20:00:00+00:00"
TABLES = {"combat_rounds", "module_comments"}
# A fight of 0021 in its second round, its mage casting Sleep (the per-round `casting` of before ongoing actions).
FIGHT = {
    "phase": "round",
    "round": 2,
    "order": [],
    "current": 0,
    "combatants": {
        "chr_mira": {"id": "chr_mira", "name": "Mira", "side": "party", "character_id": "chr_mira", "hp": 4,
                     "hp_max": 6, "conditions": ["casting"], "casting": "Sleep"},
        "mon_1": {"id": "mon_1", "name": "Goblin", "side": "enemy", "hp": 5, "hp_max": 5},
    },
    "declared": {"chr_mira": {"spell": "Sleep"}},
}  # fmt: skip
QUESTIONS = {"questions": [{"id": "q1", "text": "How deep?", "default": "Two levels", "answer": None}], "remarks": []}


def _a_0021_table(config: Config) -> None:
    """A database made at 0021: a module, a campaign with a PC in a live fight, and a finished conversion with a
    question."""
    config.data_dir.mkdir(parents=True)
    _upgrade_to(config, "0021_login_sessions")
    assert db_revision(config) == "0021_login_sessions"
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
        db.execute(
            'INSERT INTO characters (id, campaign_id, name, created_at, kind, "order") '
            "VALUES ('chr_mira', 'cmp_1', 'Mira', ?, 'pc', 0)",
            (NOW,),
        )
        db.execute(
            "INSERT INTO combats (id, campaign_id, phase, state, created_at, updated_at) "
            "VALUES ('cbt_1', 'cmp_1', 'round', ?, ?, ?)",
            (json.dumps(FIGHT), NOW, NOW),
        )
        db.execute(
            "INSERT INTO conversions (id, kind, title, mode, status, step, done, total, module_id, warnings, "
            "created_at, updated_at, questions) "
            "VALUES ('cnv_1', 'pdf', 'Crypt', 'ready', 'done', 'maps', 9, 9, 'mod_1', '[]', ?, ?, ?)",
            (NOW, NOW, json.dumps(QUESTIONS)),
        )


def test_existing_campaign_gets_the_defaults(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    _a_0021_table(config)

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        campaign = storage.campaigns.get("cmp_1")
        assert (campaign.name, campaign.join_token, campaign.status) == ("Tuesday", "join-me", "in_progress")
        assert (campaign.voice, campaign.initiative) == ("allowed", "combatant")
        mira = storage.characters.get("chr_mira")
        assert (mira.name, mira.order, mira.departure, mira.departed_at) == ("Mira", 0, None, None)
        assert storage.characters.set_departure("chr_mira", "retired").departure == "retired"
        assert storage.campaigns.set_voice("cmp_1", "off").voice == "off"
    finally:
        storage.close()


def test_existing_fight_and_conversion_keep_working(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    _a_0021_table(config)

    storage = open_storage(config)
    try:
        live = storage.combats.live("cmp_1")
        assert live is not None and live[0] == "cbt_1"
        fight = rules.from_json(live[1])
        assert fight.round == 2 and fight.combatants["chr_mira"].casting == "Sleep"
        assert storage.combat_rounds.list("cbt_1") == [], "no round of an old fight is recorded"
        conversion = storage.conversions.get("cnv_1")
        assert (conversion.questions, conversion.comments, conversion.closed) == (QUESTIONS, "", [])
        assert storage.conversions.set_closed("cnv_1", ["question:q1"]).closed == ["question:q1"]
        assert storage.module_comments.list("mod_1") == []
    finally:
        storage.close()

    with sqlite3.connect(config.db_path) as db:
        assert TABLES <= _tables(db)
        assert {"voice", "initiative"} <= _columns(db, "campaigns")
        assert {"departure", "departed_at"} <= _columns(db, "characters")
        assert {"comments", "closed"} <= _columns(db, "conversions")
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(combat_rounds)")}
        assert keys == {("combats", "combat_id", "CASCADE"), ("campaigns", "campaign_id", "CASCADE")}
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(module_comments)")}
        assert keys == {("modules", "module_id", "CASCADE"), ("conversions", "conversion_id", "SET NULL")}
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(characters)")}
        assert ("seats", "controller_id", "SET NULL") in keys, "characters wasn't rebuilt"
        assert db.execute("SELECT count(*) FROM combats").fetchone() == (1,), "no table was rebuilt under the fight"


def test_downgrade_drops_what_0022_added(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    _a_0021_table(config)
    storage = open_storage(config)
    try:
        storage.module_comments.create("mod_1", "exit X is not yet in place, fix it")
    finally:
        storage.close()

    _downgrade(config, "0021_login_sessions")
    assert db_revision(config) == "0021_login_sessions"
    with sqlite3.connect(config.db_path) as db:
        assert not TABLES & _tables(db)
        assert not {"voice", "initiative"} & _columns(db, "campaigns")
        assert not {"departure", "departed_at"} & _columns(db, "characters")
        assert not {"comments", "closed"} & _columns(db, "conversions")
        assert db.execute("SELECT id FROM campaigns").fetchall() == [("cmp_1",)]
        assert db.execute("SELECT id FROM characters").fetchall() == [("chr_mira",)]
        assert db.execute("SELECT id FROM combats").fetchall() == [("cbt_1",)]
