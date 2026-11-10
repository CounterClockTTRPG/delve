"""Migration 0020 (players and tavern Task B1): it adds `accounts`, `account_links` and `seats.account_id` to a
database made at 0019, whose seats keep their rows, their tokens and their characters, so a seat cookie and the owner
token made before it keep working. Downgrading drops what it added."""

import hashlib
import sqlite3

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient

from delve.config import Config
from delve.domain.accounts import Profile
from delve.storage import MIGRATIONS, open_storage
from delve.storage.sqlite.engine import create_sqlite_engine
from delve.web.app import create_app
from tests.storage.test_migrations import HEAD, _columns, _downgrade, _tables, db_revision
from tests.web.conftest import BASE_URL, INDEX_HTML, make_registries

SEAT_TOKEN = "an-old-seat-token-from-plateau-4"
OWNER_TOKEN = "0123456789abcdef0123456789abcdef0123456789abcdef"
NOW = "2026-10-23T20:00:00+00:00"
ACCOUNT_COLUMNS = {
    "id", "username", "password_hash", "created_at", "disabled_at", "organiser", "owner", "external_id", "display_name",
    "pronouns", "avatar_emblem", "avatar_sha", "colour", "language", "about", "host_note", "time_zone", "pending",
    "request_note", "reset_asked_at", "email", "email_pending", "mail_host", "mail_board",
}  # fmt: skip
LINK_COLUMNS = {"token_hash", "account_id", "kind", "created_at", "expires_at", "used_at", "by_owner"}
TABLES = {"accounts", "account_links"}


def _upgrade_to(config: Config, revision: str) -> None:
    engine = create_sqlite_engine(config.db_path)
    try:
        with engine.begin() as connection:
            alembic_config = AlembicConfig()
            alembic_config.set_main_option("script_location", str(MIGRATIONS))
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, revision)
    finally:
        engine.dispose()


def _a_0019_table(config: Config) -> None:
    """A database made at 0019 with a campaign, the owner's seat, a player's seat with a token, and the player's PC."""
    config.data_dir.mkdir(parents=True)
    _upgrade_to(config, "0019_campaign_maps")
    assert db_revision(config) == "0019_campaign_maps"
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
            "INSERT INTO seats (id, campaign_id, name, language, role, organiser, owner, joined_at) "
            "VALUES ('seat_host', 'cmp_1', 'Host', 'en', 'host', 1, 1, ?)",
            (NOW,),
        )
        db.execute(
            "INSERT INTO seats (id, campaign_id, name, language, role, token_hash, joined_at) "
            "VALUES ('seat_ana', 'cmp_1', 'Ana', 'nl', 'player', ?, ?)",
            (hashlib.sha256(SEAT_TOKEN.encode()).hexdigest(), NOW),
        )
        db.execute(
            "INSERT INTO characters (id, campaign_id, name, created_at, kind, controller_id) "
            "VALUES ('chr_mira', 'cmp_1', 'Mira', ?, 'pc', 'seat_ana')",
            (NOW,),
        )
    config.token_path.write_text(OWNER_TOKEN + "\n")
    config.token_path.chmod(0o600)


def test_old_seat_tokens_still_find_their_seats(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    _a_0019_table(config)

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        ana = storage.seats.by_token_hash(hashlib.sha256(SEAT_TOKEN.encode()).hexdigest())
        assert ana is not None and (ana.id, ana.name, ana.language, ana.role) == ("seat_ana", "Ana", "nl", "player")
        assert ana.account_id is None and ana.left_at is None and ana.joined_at == NOW
        assert storage.seats.controlled("seat_ana") == ["chr_mira"], "the seat still plays its PC"
        host = storage.seats.owner_seat("cmp_1")
        assert host is not None and host.id == "seat_host" and host.account_id is None
        assert [seat.id for seat in storage.seats.list("cmp_1")] == ["seat_host", "seat_ana"]
        assert storage.accounts.list() == []

        static = tmp_path / "static"
        static.mkdir()
        (static / "index.html").write_text(INDEX_HTML)
        app = create_app(config, storage, make_registries(), static_dir=static)
        with TestClient(app, base_url=BASE_URL) as lan:
            lan.cookies.set("delve_seat", SEAT_TOKEN)
            me = lan.get("/api/me")
            assert me.status_code == 200, me.text
            assert me.json()["principal"]["id"] == "seat:seat_ana"
            assert me.json()["seat"]["id"] == "seat_ana" and me.json()["seat"]["campaign_name"] == "Tuesday"
        with TestClient(app, base_url=BASE_URL) as lan:
            assert lan.get("/api/modules").status_code == 401
            owner = lan.get("/api/modules", headers={"Authorization": f"Bearer {OWNER_TOKEN}"})
            assert owner.status_code == 200, owner.text
            assert [module["id"] for module in owner.json()] == ["mod_1"]
            me = lan.get("/api/me", headers={"Authorization": f"Bearer {OWNER_TOKEN}"})
            assert me.json()["principal"]["id"] == "owner"
        assert config.token_path.read_text().strip() == OWNER_TOKEN, "the owner token is kept, not made anew"
    finally:
        storage.close()

    with sqlite3.connect(config.db_path) as db:
        assert TABLES <= _tables(db)
        assert _columns(db, "accounts") == ACCOUNT_COLUMNS
        assert _columns(db, "account_links") == LINK_COLUMNS
        assert "account_id" in _columns(db, "seats")
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(seats)")}
        assert keys == {("campaigns", "campaign_id", "CASCADE"), ("accounts", "account_id", "SET NULL")}
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(account_links)")}
        assert keys == {("accounts", "account_id", "CASCADE")}
        keys = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(characters)")}
        assert ("seats", "controller_id", "SET NULL") in keys, "seats wasn't rebuilt under the characters"
        indexes = {row[1]: (row[2], row[4]) for row in db.execute("PRAGMA index_list(seats)")}
        assert indexes["uq_seats_account_live"] == (1, 1), "unique and partial"
        assert db.execute("SELECT controller_id FROM characters").fetchall() == [("seat_ana",)]


def test_downgrade_drops_accounts(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    _a_0019_table(config)
    storage = open_storage(config)
    try:
        storage.accounts.create("ana", Profile("Ana"))
    finally:
        storage.close()

    _downgrade(config, "0019_campaign_maps")
    assert db_revision(config) == "0019_campaign_maps"
    with sqlite3.connect(config.db_path) as db:
        assert not TABLES & _tables(db)
        assert "account_id" not in _columns(db, "seats")
        assert "uq_seats_account_live" not in {row[1] for row in db.execute("PRAGMA index_list(seats)")}
        assert db.execute("SELECT id FROM seats ORDER BY rowid").fetchall() == [("seat_host",), ("seat_ana",)]
        assert db.execute("SELECT controller_id FROM characters").fetchall() == [("seat_ana",)]
