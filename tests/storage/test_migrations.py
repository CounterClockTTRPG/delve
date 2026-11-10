import sqlite3

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from delve.config import Config
from delve.domain.world import CampaignWorldMap, WorldPosition
from delve.storage import MIGRATIONS, MigrationBrokeReferences, SchemaTooNewError, migrate, open_storage
from delve.storage.sqlite.engine import create_sqlite_engine

HEAD = "0044_email_backfill"


def db_revision(config: Config) -> str | None:
    with sqlite3.connect(config.db_path) as db:
        row = db.execute("SELECT version_num FROM alembic_version").fetchone()
    return row[0] if row else None


def test_fresh_db_is_at_head(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    assert db_revision(config) == HEAD


def test_migrate_returns_head(tmp_path):
    config = Config(data_dir=tmp_path / "new")
    assert migrate(config) == HEAD
    assert db_revision(config) == HEAD


def test_reopen_is_idempotent(tmp_path):
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    storage.settings.save({"language": "nl"})
    storage.close()
    assert migrate(config) == HEAD
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        assert storage.settings.load() == {"language": "nl"}
    finally:
        storage.close()


def test_older_schema_is_upgraded(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            if table != "alembic_version":
                db.execute(f"DROP TABLE IF EXISTS {table}")  # an FTS5 table drops its shadow tables
        db.execute("DELETE FROM alembic_version")
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        assert storage.settings.load() == {}
    finally:
        storage.close()


def test_newer_schema_refused(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        db.execute("UPDATE alembic_version SET version_num = '9999_future'")
    with pytest.raises(SchemaTooNewError) as caught:
        open_storage(config)
    assert caught.value.db_revision == "9999_future" and caught.value.code_head == HEAD
    assert "9999_future" in str(caught.value) and HEAD in str(caught.value)
    with pytest.raises(SchemaTooNewError):
        migrate(config)
    assert db_revision(config) == "9999_future"


def test_migration_0001_to_0002_keeps_settings(tmp_path):
    config = Config(data_dir=tmp_path)
    engine = create_sqlite_engine(config.db_path)
    try:
        with engine.begin() as connection:
            alembic_config = AlembicConfig()
            alembic_config.set_main_option("script_location", str(MIGRATIONS))
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "0001_settings")
    finally:
        engine.dispose()
    assert db_revision(config) == "0001_settings"
    with sqlite3.connect(config.db_path) as db:
        db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('app', ?, '2026-10-17T00:00:00+00:00')",
            ('{"language": "nl", "choices": {"dm": {"provider": "fake"}}}',),
        )

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        assert storage.settings.load() == {"language": "nl", "choices": {"dm": {"provider": "fake"}}}
        module = storage.modules.create("After the upgrade")
        assert storage.modules.get(module.id) == module
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "settings",
        "modules",
        "module_maps",
        "module_revisions",
        "campaigns",
        "characters",
        "map_states",
        "blobs",
        "module_blobs",
    } <= tables


PLAY_TABLES = {
    "campaign_state",
    "rolls",
    "events",
    "sessions",
    "notes",
    "combats",
    "house_rules",
    "house_rules_bundles",
    "house_rules_bundle_rules",
    "house_rules_campaign_bundles",
    "house_rules_campaign_rules",
}


def test_migration_0002_to_0003_keeps_characters_as_pcs_in_order(tmp_path):
    config = Config(data_dir=tmp_path)
    engine = create_sqlite_engine(config.db_path)
    try:
        with engine.begin() as connection:
            alembic_config = AlembicConfig()
            alembic_config.set_main_option("script_location", str(MIGRATIONS))
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "0002_modules_campaigns")
    finally:
        engine.dispose()
    with sqlite3.connect(config.db_path) as db:
        now = "2026-10-17T00:00:00+00:00"
        db.execute("INSERT INTO modules VALUES ('mod_000000000001', 'Crypt', '{}', ?, ?)", (now, now))
        db.execute("INSERT INTO module_revisions VALUES ('mod_000000000001', 1, 'Crypt', '{}', '[]', ?)", (now,))
        for campaign in ("cmp_000000000001", "cmp_000000000002"):
            db.execute("INSERT INTO campaigns VALUES (?, 'Tuesday', 'mod_000000000001', 1, ?)", (campaign, now))
        db.executemany(
            "INSERT INTO characters VALUES (?, ?, ?, ?)",
            [
                ("chr_00000000000a", "cmp_000000000001", "Mira", now),
                ("chr_00000000000b", "cmp_000000000002", "Anselm", now),
                ("chr_00000000000c", "cmp_000000000001", "Brother Anselm", now),
            ],
        )

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        mira, anselm = storage.characters.list("cmp_000000000001")
        assert (mira.name, mira.kind, mira.order, mira.sheet.label, mira.state.hp) == ("Mira", "pc", 0, "Mira", 0)
        assert (anselm.name, anselm.order) == ("Brother Anselm", 1)
        assert storage.characters.list("cmp_000000000002")[0].order == 0
        assert storage.characters.create("cmp_000000000001", "Pip").order == 2
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert PLAY_TABLES <= tables


def test_migration_0003_downgrades(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    engine = create_sqlite_engine(config.db_path)
    try:
        with engine.begin() as connection:
            alembic_config = AlembicConfig()
            alembic_config.set_main_option("script_location", str(MIGRATIONS))
            alembic_config.attributes["connection"] = connection
            command.downgrade(alembic_config, "0002_modules_campaigns")
    finally:
        engine.dispose()
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in db.execute("PRAGMA table_info(characters)")}
    assert not PLAY_TABLES & tables
    assert columns == {"id", "campaign_id", "name", "created_at"}


def _downgrade(config: Config, revision: str) -> None:
    engine = create_sqlite_engine(config.db_path)
    try:
        with engine.begin() as connection:
            alembic_config = AlembicConfig()
            alembic_config.set_main_option("script_location", str(MIGRATIONS))
            alembic_config.attributes["connection"] = connection
            command.downgrade(alembic_config, revision)
    finally:
        engine.dispose()


def test_migration_0004_downgrades(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    _downgrade(config, "0003_play_state")
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in db.execute("PRAGMA table_info(module_revisions)")}
    assert not {"module_texts", "module_text_index"} & tables
    assert "text" not in columns


TABLE_TABLES = {"beats", "story", "dm_log", "dm_sessions", "play_settings"}


def test_migration_0005_adds_and_downgrades_beats_story(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert TABLE_TABLES <= tables
    _downgrade(config, "0004_module_text")
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not TABLE_TABLES & tables and PLAY_TABLES <= tables and "module_texts" in tables


def test_migration_0006_adds_and_downgrades_module_sources(tmp_path):
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in db.execute("PRAGMA table_info(module_revisions)")}
    assert "module_sources" in tables and "source" in columns
    _downgrade(config, "0005_beats_story")
    with sqlite3.connect(config.db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in db.execute("PRAGMA table_info(module_revisions)")}
    assert "module_sources" not in tables and "source" not in columns and "text" in columns


def test_migration_0007_gives_existing_campaigns_adnd2e_in_greyhawk(tmp_path):
    """Campaigns made before 0007 played AD&D 2e in Greyhawk implicitly; the migration says so."""
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    _downgrade(config, "0005_beats_story")
    with sqlite3.connect(config.db_path) as db:
        assert {row[1] for row in db.execute("PRAGMA table_info(campaigns)")} == {
            "id",
            "name",
            "module_id",
            "revision",
            "created_at",
        }
        now = "2026-10-17T00:00:00+00:00"
        db.execute("INSERT INTO modules VALUES ('mod_000000000001', 'Crypt', '{}', ?, ?)", (now, now))
        db.execute(
            "INSERT INTO module_revisions (module_id, number, title, metadata, maps, created_at) "
            "VALUES ('mod_000000000001', 1, 'Crypt', '{}', '[]', ?)",
            (now,),
        )
        db.execute("INSERT INTO campaigns VALUES ('cmp_000000000001', 'Tuesday', 'mod_000000000001', 1, ?)", (now,))
        db.execute(
            "INSERT INTO characters (id, campaign_id, name, kind, sheet, state, created_at) "
            "VALUES ('chr_00000000000a', 'cmp_000000000001', 'Mira', 'pc', '{}', '{}', ?)",
            (now,),
        )

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        old = storage.campaigns.get("cmp_000000000001")
        assert (old.ruleset, old.setting) == ("adnd2e", "greyhawk")
        assert [c.name for c in storage.characters.list(old.id)] == ["Mira"], "the campaign keeps its characters"
        new = storage.campaigns.create("Friday", "mod_000000000001", 1, setting="", ruleset="adnd2e")
        assert (storage.campaigns.get(new.id).ruleset, storage.campaigns.get(new.id).setting) == ("adnd2e", "")
    finally:
        storage.close()


def test_migration_0008_stores_the_dm_audience_as_gm(tmp_path):
    """Plateau 3 stored a DM-only text, section or attachment as `dm`; Delve stores the format's `gm` everywhere
    (docs/data-dictionary.md), in the working text and source and in every revision."""
    import json

    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    _downgrade(config, "0007_campaign_world")
    now = "2026-10-18T00:00:00+00:00"
    text = {"sections": [{"anchor": "a#b", "audience": "dm"}, {"anchor": "a#c", "audience": "player"}], "keys": [],
            "entities": {"npcs": [{"id": "kael", "name": "Kael", "audience": "gm"}]}}  # fmt: skip
    source = {"texts": [{"id": "a", "audience": "dm"}], "attachments": [{"id": "x", "audience": "dm"}]}
    with sqlite3.connect(config.db_path) as db:
        db.execute("INSERT INTO modules VALUES ('mod_000000000001', 'Crypt', '{}', ?, ?)", (now, now))
        db.execute("INSERT INTO module_texts VALUES ('mod_000000000001', ?, ?)", (json.dumps(text), now))
        db.execute("INSERT INTO module_sources VALUES ('mod_000000000001', ?, ?)", (json.dumps(source), now))
        db.execute(
            "INSERT INTO module_revisions (module_id, number, title, metadata, maps, created_at, text, source) "
            "VALUES ('mod_000000000001', 1, 'Crypt', '{}', '[]', ?, ?, ?)",
            (now, json.dumps(text), json.dumps(source)),
        )
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        stored = [db.execute(sql).fetchone()[0] for sql in (
            "SELECT text FROM module_texts", "SELECT source FROM module_sources",
            "SELECT text FROM module_revisions", "SELECT source FROM module_revisions",
        )]  # fmt: skip
    assert all('"dm"' not in raw for raw in stored)
    assert [s["audience"] for s in json.loads(stored[0])["sections"]] == ["gm", "player"]
    assert json.loads(stored[1])["attachments"][0]["audience"] == "gm"


def test_migration_0009_adds_conversions_and_drafts(tmp_path):
    """Modules made before 0009 are ready, not drafts; downgrading drops the conversions and the column."""
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    _downgrade(config, "0008_audience_gm")
    with sqlite3.connect(config.db_path) as db:
        assert "draft" not in {row[1] for row in db.execute("PRAGMA table_info(modules)")}
        assert "conversions" not in {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        now = "2026-10-18T00:00:00+00:00"
        db.execute("INSERT INTO modules VALUES ('mod_000000000001', 'Crypt', '{}', ?, ?)", (now, now))
    storage = open_storage(config)
    try:
        assert storage.modules.get("mod_000000000001").draft is False
        assert storage.conversions.list() == []
    finally:
        storage.close()


def test_migration_0010_gives_existing_campaigns_an_owner_seat(tmp_path):
    """A campaign made before 0010 was the owner's alone: it gets their seat as host, with its PCs, and a join token.
    Downgrading drops the seats and both columns."""
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    _downgrade(config, "0009_conversions")
    now = "2026-10-18T00:00:00+00:00"
    with sqlite3.connect(config.db_path) as db:
        assert "seats" not in {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        db.execute("INSERT INTO modules (id, title, metadata, created_at, updated_at) "
                   "VALUES ('mod_000000000001', 'Crypt', '{}', ?, ?)", (now, now))  # fmt: skip
        db.execute(
            "INSERT INTO module_revisions (module_id, number, title, metadata, maps, created_at) "
            "VALUES ('mod_000000000001', 1, 'Crypt', '{}', '[]', ?)",
            (now,),
        )
        for cid in ("cmp_000000000001", "cmp_000000000002"):
            db.execute(
                "INSERT INTO campaigns (id, name, module_id, revision, created_at) "
                "VALUES (?, 'Tuesday', 'mod_000000000001', 1, ?)",
                (cid, now),
            )
        for chr_id, kind in (("chr_00000000000a", "pc"), ("chr_00000000000b", "npc")):
            db.execute(
                "INSERT INTO characters (id, campaign_id, name, kind, sheet, state, created_at) "
                "VALUES (?, 'cmp_000000000001', 'Mira', ?, '{}', '{}', ?)",
                (chr_id, kind, now),
            )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        first, second = storage.campaigns.get("cmp_000000000001"), storage.campaigns.get("cmp_000000000002")
        assert first.join_token and second.join_token and first.join_token != second.join_token
        [seat] = storage.seats.list(first.id)
        assert (seat.name, seat.language, seat.role, seat.owner, seat.organiser) == ("Host", "en", "host", True, True)
        assert seat.id.startswith("seat_") and seat.joined_at and seat.left_at is None
        assert storage.seats.owner_seat(second.id) is not None
        assert storage.characters.get("chr_00000000000a").controller_id == seat.id, "the PC is the owner's"
        assert storage.characters.get("chr_00000000000b").controller_id is None, "an NPC is the DM's"
        assert storage.seats.controlled(seat.id) == ["chr_00000000000a"]
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        token_hashes = db.execute("SELECT token_hash FROM seats").fetchall()
    assert token_hashes == [(None,), (None,)], "the owner's seat has no token: the owner token stands for it"

    _downgrade(config, "0009_conversions")
    with sqlite3.connect(config.db_path) as db:
        assert "seats" not in {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "join_token" not in {row[1] for row in db.execute("PRAGMA table_info(campaigns)")}
        assert "controller_id" not in {row[1] for row in db.execute("PRAGMA table_info(characters)")}
        assert db.execute("SELECT count(*) FROM characters").fetchone() == (2,)


def test_migration_0011_gives_old_questions_to_the_owner(tmp_path):
    """An Ask the DM made before 0011 was the owner's: its `ask` and `answer` are for the owner's seat, and every
    other entry is for everyone. Downgrading drops the column."""
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
        owner = storage.seats.create(campaign.id, "Host", "en", "host", organiser=True, owner=True)
    finally:
        storage.close()
    _downgrade(config, "0010_seats")
    now = "2026-10-18T00:00:00+00:00"
    with sqlite3.connect(config.db_path) as db:
        for seq, kind in enumerate(("player_act", "dm_text", "ask", "answer"), start=1):
            db.execute(
                "INSERT INTO story (id, campaign_id, beat_id, seq, kind, payload, at) VALUES (?, ?, NULL, ?, ?, '{}', ?)",
                (f"sty_{seq:012d}", campaign.id, seq, kind, now),
            )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        entries = storage.story.list(campaign.id)
        assert [(e.kind, e.audience) for e in entries] == [
            ("player_act", None),
            ("dm_text", None),
            ("ask", {"seats": [owner.id]}),
            ("answer", {"seats": [owner.id]}),
        ]
    finally:
        storage.close()

    _downgrade(config, "0010_seats")
    with sqlite3.connect(config.db_path) as db:
        assert "audience" not in {row[1] for row in db.execute("PRAGMA table_info(story)")}
        assert db.execute("SELECT count(*) FROM story").fetchone() == (4,)


WORLD_TABLES = {
    "factions",
    "clocks",
    "quests",
    "campaign_facts",
    "possessions",
    "world_maps",
    "merchants",
    "campaign_images",
}


def test_migration_0013_adds_the_world_and_keeps_the_day(tmp_path):
    """An existing campaign's state keeps its day, hour and coin; its start date, weather and world position are
    empty. Downgrading drops the tables and the columns."""
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
    finally:
        storage.close()
    _downgrade(config, "0012_translations")
    now = "2026-10-18T00:00:00+00:00"
    with sqlite3.connect(config.db_path) as db:
        assert not WORLD_TABLES & {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        db.execute(
            "INSERT INTO campaign_state (campaign_id, day, hour, minute, session, coin, loot, updated_at) "
            'VALUES (?, 41, 14, 30, 3, \'{"pp": 0, "gp": 12, "ep": 0, "sp": 0, "cp": 0}\', \'[]\', ?)',
            (campaign.id, now),
        )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        state = storage.campaign_states.get(campaign.id)
        assert (state.day, state.hour, state.minute, state.session, state.coin["gp"]) == (41, 14, 30, 3, 12)
        assert (state.start_date, state.weather, state.world) == (None, (), None)
        assert storage.factions.list(campaign.id) == [] and storage.campaign_images.painting() == []
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert WORLD_TABLES <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    _downgrade(config, "0012_translations")
    with sqlite3.connect(config.db_path) as db:
        assert not WORLD_TABLES & {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in db.execute("PRAGMA table_info(campaign_state)")}
        assert not {"start_date", "weather", "world"} & columns
        assert db.execute("SELECT day FROM campaign_state").fetchone() == (41,)


MAPS_TABLES = {"world_pictures", "setting_world_maps"}
MAPS_COLUMNS = {
    "world_maps": {"geo", "picture", "status", "knowledge", "reading"},
    "campaign_state": {"journey"},
    "campaigns": {"status"},
    "conversions": {"target", "result", "questions"},
    "translations": {"answer"},
}


def _tables(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def test_migration_0014_keeps_a_campaigns_world_map_and_position(tmp_path):
    """A plateau 6 campaign keeps its world map, its `revealed` and the party's position: the map is `ready` with no
    `geo` (it is converted on first read), the position reads as one in the `.map`'s own units, and the campaign is
    `in_progress`. Downgrading drops the tables and the columns."""
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
    finally:
        storage.close()
    _downgrade(config, "0013_world")
    now = "2026-10-18T00:00:00+00:00"
    with sqlite3.connect(config.db_path) as db:
        assert not MAPS_TABLES & _tables(db)
        for table, columns in MAPS_COLUMNS.items():
            assert not columns & _columns(db, table), table
        db.execute(
            "INSERT INTO world_maps (campaign_id, name, title, source, dsl, revealed, updated_at) "
            "VALUES (?, 'greyhawk-region', 'Greyhawk region', 'setting', 'workspace {}', '[\"castle\"]', ?)",
            (campaign.id, now),
        )
        db.execute(
            "INSERT INTO campaign_state (campaign_id, day, hour, minute, session, coin, loot, updated_at, world) "
            'VALUES (?, 4, 6, 0, 1, \'{"pp": 0, "gp": 0, "ep": 0, "sp": 0, "cp": 0}\', \'[]\', ?, '
            '\'{"map": "greyhawk-region", "x": 12.5, "y": 40.0, "at": "greyhawk"}\')',
            (campaign.id, now),
        )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        world_map = storage.world_maps.get(campaign.id, "greyhawk-region")
        assert (world_map.dsl, world_map.revealed, world_map.status) == ("workspace {}", ("castle",), "ready")
        assert (world_map.geo, world_map.picture, world_map.knowledge, world_map.reading) == (None, None, None, None)
        state = storage.campaign_states.get(campaign.id)
        assert state.world == WorldPosition("greyhawk-region", 12.5, 40.0, at="greyhawk", km=False)
        assert state.journey is None and state.day == 4
        assert storage.campaigns.get(campaign.id).status == "in_progress"
        assert storage.world_pictures.get("0" * 64) is None
    finally:
        storage.close()

    _downgrade(config, "0013_world")
    with sqlite3.connect(config.db_path) as db:
        assert not MAPS_TABLES & _tables(db)
        for table, columns in MAPS_COLUMNS.items():
            assert not columns & _columns(db, table), table
        assert db.execute("SELECT revealed FROM world_maps").fetchone() == ('["castle"]',)
        assert db.execute("SELECT count(*) FROM campaigns").fetchone() == (1,)


def test_migration_0015_keeps_existing_conversions_with_no_cost(tmp_path):
    """A conversion from before 0015 keeps its row, its cost unknown (null); downgrading drops the column."""
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    _downgrade(config, "0014_maps")
    with sqlite3.connect(config.db_path) as db:
        assert "cost_usd" not in _columns(db, "conversions")
        db.execute(
            "INSERT INTO conversions (id, kind, title, mode, status, step, done, total, warnings, created_at, "
            "updated_at) VALUES ('cnv_000000000001', 'pdf', 'The Kobold Caves', 'ready', 'done', 'maps', 1, 1, '[]', "
            "'2026-10-18T00:00:00+00:00', '2026-10-18T00:00:00+00:00')"
        )
    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        kept = storage.conversions.get("cnv_000000000001")
        assert (kept.title, kept.status, kept.cost_usd) == ("The Kobold Caves", "done", None)
    finally:
        storage.close()

    _downgrade(config, "0014_maps")
    with sqlite3.connect(config.db_path) as db:
        assert "cost_usd" not in _columns(db, "conversions")
        assert db.execute("SELECT title FROM conversions").fetchone() == ("The Kobold Caves",)


SETTING_CONTENT_TABLES = {"setting_pages", "setting_facts", "proposals", "setting_maps"}


def test_migration_0016_adds_the_setting_content_and_downgrades(tmp_path):
    """The head has the four tables of the setting's content; downgrading to 0015 drops them, and the campaigns'
    world maps and the setting pointers keep their rows."""
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
        storage.world_maps.put(CampaignWorldMap(campaign.id, "region", "The region", "setting", "workspace {}\n"))
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert SETTING_CONTENT_TABLES <= _tables(db)
        assert {"setting", "title_key", "title", "kind", "fields", "text", "dm_only", "created_at", "updated_at"} == (
            _columns(db, "setting_pages")
        )
        indexed = {row[1] for row in db.execute("PRAGMA index_list(proposals)")}
        assert {"ix_proposals_setting_status", "ix_proposals_campaign_id"} <= indexed

    _downgrade(config, "0015_costs")
    with sqlite3.connect(config.db_path) as db:
        assert not SETTING_CONTENT_TABLES & _tables(db)
        assert db.execute("SELECT name FROM world_maps").fetchall() == [("region",)]
        assert db.execute("SELECT count(*) FROM setting_world_maps").fetchone() == (0,), "made again by 0036's downgrade"

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        assert storage.setting_pages.list("greyhawk") == [] and storage.proposals.list() == []
    finally:
        storage.close()


NOVEL_COLUMNS = {
    "id", "title", "campaign_id", "module_id", "revision", "sessions", "length", "tone", "custom_tone", "language",
    "instructions", "chapters", "status", "error", "conversion_id", "cost_usd", "created_at", "updated_at",
}  # fmt: skip


def test_migration_0017_adds_the_novels_and_downgrades(tmp_path):
    """0017 upgrades a 0016 database with its campaigns as they were and adds the `novels` table, its source columns
    indexed; downgrading to 0016 drops it and keeps the campaigns."""
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
    finally:
        storage.close()
    _downgrade(config, "0016_setting_content")
    with sqlite3.connect(config.db_path) as db:
        assert "novels" not in _tables(db)

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        assert storage.campaigns.get(campaign.id).name == "Tuesday"
        assert storage.novels.for_campaign(campaign.id) == [] and storage.novels.writing() == []
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert _columns(db, "novels") == NOVEL_COLUMNS
        indexed = {row[1] for row in db.execute("PRAGMA index_list(novels)")}
        assert {"ix_novels_campaign_id", "ix_novels_module_id"} <= indexed
        cascades = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(novels)")}
        assert cascades == {("campaigns", "campaign_id", "CASCADE"), ("modules", "module_id", "CASCADE")}

    _downgrade(config, "0016_setting_content")
    with sqlite3.connect(config.db_path) as db:
        assert "novels" not in _tables(db)
        assert db.execute("SELECT name FROM campaigns").fetchall() == [("Tuesday",)]


def test_migration_0019_adds_the_campaign_maps_and_downgrades(tmp_path):
    """0019 upgrades a 0018 database with its campaigns as they were and adds `campaign_maps`, gone with their
    campaign; downgrading to 0018 drops it and keeps the campaigns."""
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
    finally:
        storage.close()
    _downgrade(config, "0018_histories")
    with sqlite3.connect(config.db_path) as db:
        assert "campaign_maps" not in _tables(db)

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        assert storage.campaign_maps.list(campaign.id) == []
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert _columns(db, "campaign_maps") == {
            "campaign_id",
            "name",
            "position",
            "source",
            "created_at",
            "updated_at",
        }
        cascades = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(campaign_maps)")}
        assert cascades == {("campaigns", "campaign_id", "CASCADE")}

    _downgrade(config, "0018_histories")
    with sqlite3.connect(config.db_path) as db:
        assert "campaign_maps" not in _tables(db)
        assert db.execute("SELECT name FROM campaigns").fetchall() == [("Tuesday",)]


def test_migration_0030_adds_the_account_identities_and_downgrades(tmp_path):
    """0030 upgrades a 0029 database with its accounts as they were and adds `account_identities`, gone with their
    account; downgrading to 0029 drops it and keeps the accounts (DEL-206)."""
    from delve.domain.accounts import Identity, Profile

    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        ana = storage.accounts.create("ana", Profile("Ana"))
    finally:
        storage.close()
    _downgrade(config, "0029_table_listing")
    with sqlite3.connect(config.db_path) as db:
        assert "account_identities" not in _tables(db)

    storage = open_storage(config)
    try:
        assert db_revision(config) == HEAD
        storage.account_identities.add(Identity("google", "1083", ana.id, "", "2026-10-27T10:00:00+00:00"))
    finally:
        storage.close()
    with sqlite3.connect(config.db_path) as db:
        assert _columns(db, "account_identities") == {"provider", "subject", "account_id", "email", "linked_at"}
        cascades = {(row[2], row[3], row[6]) for row in db.execute("PRAGMA foreign_key_list(account_identities)")}
        assert cascades == {("accounts", "account_id", "CASCADE")}

    _downgrade(config, "0029_table_listing")
    with sqlite3.connect(config.db_path) as db:
        assert "account_identities" not in _tables(db)
        assert db.execute("SELECT username FROM accounts").fetchall() == [("ana",)]


def test_migration_0033_names_the_owner_seats_after_the_owner(tmp_path):
    """0033 names an owner seat still called "Host" after the first owner account; a renamed one, and a player's
    seat called "Host", keep their names."""
    from delve.domain.accounts import Profile

    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        storage.accounts.create("ana", Profile("Ana"))
        storage.accounts.create("saldek", Profile("Saldek"), owner=True)
    finally:
        storage.close()
    _downgrade(config, "0032_table_schedule")
    now = "2026-10-27T00:00:00+00:00"
    with sqlite3.connect(config.db_path) as db:
        db.execute("INSERT INTO modules (id, title, metadata, created_at, updated_at) "
                   "VALUES ('mod_000000000001', 'Crypt', '{}', ?, ?)", (now, now))  # fmt: skip
        db.execute(
            "INSERT INTO module_revisions (module_id, number, title, metadata, maps, created_at) "
            "VALUES ('mod_000000000001', 1, 'Crypt', '{}', '[]', ?)",
            (now,),
        )
        for cid in ("cmp_000000000001", "cmp_000000000002"):
            db.execute(
                "INSERT INTO campaigns (id, name, module_id, revision, created_at) "
                "VALUES (?, 'Tuesday', 'mod_000000000001', 1, ?)",
                (cid, now),
            )
        for sid, cid, name, owner in (
            ("seat_000000000001", "cmp_000000000001", "Host", 1),
            ("seat_000000000002", "cmp_000000000002", "Raf", 1),
            ("seat_000000000003", "cmp_000000000001", "Host", 0),
        ):
            db.execute(
                "INSERT INTO seats (id, campaign_id, name, language, role, organiser, owner, joined_at) "
                "VALUES (?, ?, ?, 'en', 'host', 1, ?, ?)",
                (sid, cid, name, owner, now),
            )
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        names = dict(db.execute("SELECT id, name FROM seats").fetchall())
    assert names == {"seat_000000000001": "Saldek", "seat_000000000002": "Raf", "seat_000000000003": "Host"}


def test_migration_0034_indexes_the_beat_of_story_and_dm_log(tmp_path):
    """0034 indexes `beat_id` on story and dm_log, which a beat's delete cascades into (DEL-164), and its downgrade
    drops them."""
    config = Config(data_dir=tmp_path)
    open_storage(config).close()

    def indexes() -> set[str]:
        with sqlite3.connect(config.db_path) as db:
            return {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}

    assert {"ix_story_beat", "ix_dm_log_beat"} <= indexes()
    with sqlite3.connect(config.db_path) as db:
        plan = " ".join(row[3] for row in db.execute("EXPLAIN QUERY PLAN DELETE FROM story WHERE beat_id = 'b'"))
    assert "ix_story_beat" in plan, plan
    _downgrade(config, "0033_owner_seat_name")
    assert not {"ix_story_beat", "ix_dm_log_beat"} & indexes()


def test_migration_0035_adds_who_is_away(tmp_path):
    """0035 adds `table_sessions.away`, `{}` for a table stored before it (DEL-224); its downgrade drops it."""
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    _downgrade(config, "0034_beat_indexes")
    now = "2026-10-27T00:00:00+00:00"
    with sqlite3.connect(config.db_path) as db:
        db.execute("INSERT INTO modules (id, title, metadata, created_at, updated_at) "
                   "VALUES ('mod_000000000001', 'Crypt', '{}', ?, ?)", (now, now))  # fmt: skip
        db.execute(
            "INSERT INTO module_revisions (module_id, number, title, metadata, maps, created_at) "
            "VALUES ('mod_000000000001', 1, 'Crypt', '{}', '[]', ?)",
            (now,),
        )
        db.execute(
            "INSERT INTO campaigns (id, name, module_id, revision, created_at) "
            "VALUES ('cmp_000000000001', 'Tuesday', 'mod_000000000001', 1, ?)",
            (now,),
        )
        db.execute(
            "INSERT INTO table_sessions (campaign_id, state, since, absent, hands, break_at, updated_at) "
            "VALUES ('cmp_000000000001', 'playing', ?, '{}', '{}', NULL, ?)",
            (now, now),
        )
    storage = open_storage(config)
    try:
        assert storage.table_sessions.get("cmp_000000000001").away == {}
    finally:
        storage.close()
    _downgrade(config, "0034_beat_indexes")
    with sqlite3.connect(config.db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(table_sessions)")}
    assert "away" not in columns


def test_migration_0036_drops_the_setting_pointers_and_downgrades(tmp_path):
    """The head has no `setting_world_maps` (DEL-22); a downgrade to 0035 makes it again, empty."""
    config = Config(data_dir=tmp_path)
    open_storage(config).close()
    with sqlite3.connect(config.db_path) as db:
        assert "setting_world_maps" not in _tables(db)
    _downgrade(config, "0035_table_away")
    with sqlite3.connect(config.db_path) as db:
        assert _columns(db, "setting_world_maps") == {"setting", "module_id", "name", "updated_at"}
        assert db.execute("SELECT count(*) FROM setting_world_maps").fetchone() == (0,)
    open_storage(config).close()
    assert db_revision(config) == HEAD


def test_migration_0037_adds_who_may_watch(tmp_path):
    """0037 adds `campaigns.observers` (`anyone` for a table from before) and `join_requests.role` (`player`), and
    its downgrade drops both (DEL-215)."""
    config = Config(data_dir=tmp_path)
    storage = open_storage(config)
    try:
        module = storage.modules.create("Crypt")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="adnd2e", setting="greyhawk"
        )
    finally:
        storage.close()
    _downgrade(config, "0036_drop_setting_world_maps")
    storage = open_storage(config)
    try:
        assert storage.campaigns.get(campaign.id).observers == "anyone"
    finally:
        storage.close()
    _downgrade(config, "0036_drop_setting_world_maps")
    with sqlite3.connect(config.db_path) as db:
        assert "observers" not in {row[1] for row in db.execute("PRAGMA table_info(campaigns)")}
        assert "role" not in {row[1] for row in db.execute("PRAGMA table_info(join_requests)")}


def _a_campaign_with_a_character(config: Config) -> tuple[str, str]:
    storage = open_storage(config)
    try:
        module = storage.modules.create("Keep")
        campaign = storage.campaigns.create(
            "Tuesday", module.id, storage.revisions.snapshot(module.id).number, ruleset="osric", setting=""
        )
        character = storage.characters.create(campaign.id, "Ana")
    finally:
        storage.close()
    # A revision behind, so that the next start migrates: a database at head is neither migrated nor checked.
    with sqlite3.connect(config.db_path) as db:
        db.execute("UPDATE alembic_version SET version_num = '0043_email'")
    return campaign.id, character.id


def test_a_migration_that_rebuilds_campaigns_keeps_what_names_them(tmp_path, monkeypatch):
    """Migrations run with foreign keys off: a batch rebuild of `campaigns` (copy, drop, rename) no longer cascades
    the drop into every table that names a campaign, as one did in 0037's test, deleting the characters."""
    config = Config(data_dir=tmp_path)
    campaign_id, character_id = _a_campaign_with_a_character(config)

    def rebuild(alembic_config, _revision):
        operations = Operations(MigrationContext.configure(alembic_config.attributes["connection"]))
        with operations.batch_alter_table("campaigns", recreate="always"):
            pass

    monkeypatch.setattr("delve.storage.command.upgrade", rebuild)
    storage = open_storage(config)
    try:
        assert storage.campaigns.get(campaign_id) is not None
        assert storage.characters.get(character_id) is not None
    finally:
        storage.close()


def test_a_migration_that_leaves_a_broken_reference_is_refused_whole(tmp_path, monkeypatch):
    """With foreign keys off, nothing stops a migration leaving a row that names nothing, so `PRAGMA
    foreign_key_check` looks once it has run: it is refused, rolled back, and the database stays as it was."""
    config = Config(data_dir=tmp_path)
    _a_campaign_with_a_character(config)

    def orphan(alembic_config, _revision):
        alembic_config.attributes["connection"].exec_driver_sql("UPDATE characters SET campaign_id = 'cmp_gone'")

    monkeypatch.setattr("delve.storage.command.upgrade", orphan)
    with pytest.raises(MigrationBrokeReferences, match="characters"):
        open_storage(config)
    with sqlite3.connect(config.db_path) as db:
        assert db.execute("SELECT campaign_id FROM characters").fetchone()[0] != "cmp_gone"


def test_a_broken_reference_from_before_the_migration_doesnt_stop_it(tmp_path):
    """Only what the migrations broke is refused: a row an older Delve or a hand edit left naming nothing stays, and
    the database still opens."""
    config = Config(data_dir=tmp_path)
    _a_campaign_with_a_character(config)
    with sqlite3.connect(config.db_path) as db:  # a plain connection: foreign keys off
        db.execute("UPDATE characters SET campaign_id = 'cmp_gone'")
    open_storage(config).close()
    assert db_revision(config) == HEAD
