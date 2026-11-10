"""The repositories, behind interfaces. The only package that knows SQL."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine

from delve.config import Config, private_data_dir
from delve.storage.interfaces import (
    BlobStore,
    CampaignRepository,
    CampaignStateRepository,
    CharacterRepository,
    EventRepository,
    MapStateRepository,
    ModuleInUse,
    ModuleRepository,
    ModuleSourceRepository,
    ModuleTextRepository,
    RevisionRepository,
    RollRepository,
    SeatRepository,
    SettingsRepository,
    Storage,
)
from delve.storage.sqlite import SqliteStorage
from delve.storage.sqlite.engine import create_sqlite_engine

__all__ = [
    "BlobStore",
    "CampaignRepository",
    "CampaignStateRepository",
    "CharacterRepository",
    "EventRepository",
    "MapStateRepository",
    "MigrationBrokeReferences",
    "ModuleInUse",
    "ModuleRepository",
    "ModuleSourceRepository",
    "ModuleTextRepository",
    "RevisionRepository",
    "RollRepository",
    "SchemaTooNewError",
    "SeatRepository",
    "SettingsRepository",
    "Storage",
    "database_copies",
    "migrate",
    "open_storage",
]

MIGRATIONS = Path(__file__).parent / "migrations"


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer Delve: its schema revision is unknown to this code."""

    def __init__(self, db_revision: str, code_head: str) -> None:
        self.db_revision = db_revision
        self.code_head = code_head
        super().__init__(
            f"The database is at schema revision {db_revision!r}, which this Delve does not know; "
            f"its newest is {code_head!r}. Upgrade Delve to open this database."
        )


class MigrationBrokeReferences(RuntimeError):
    """A migration left rows naming rows that aren't there (`PRAGMA foreign_key_check`); it was rolled back."""

    def __init__(self, broken: list[Any]) -> None:
        self.broken = broken
        tables = sorted({str(row[0]) for row in broken})
        super().__init__(f"A migration left {len(broken)} rows naming rows that aren't there, in {', '.join(tables)}.")


def open_storage(config: Config) -> Storage:
    """Open the SQLite storage in `config.data_dir`, creating it and migrating it to the newest schema.

    Blobs are kept under `<data dir>/blobs/`.
    """
    engine = _open_migrated(config)
    return SqliteStorage(engine, config.data_dir / "blobs")


def migrate(config: Config) -> str:
    """Bring the database up to the newest schema and return that revision."""
    _open_migrated(config).dispose()
    return _script().get_current_head()


DATABASE_FILE_MODE = 0o600
DATABASES = ("delve.db", "reference.db")
"""The databases in the data directory, whose files (the database, its `-wal`, `-shm` and `-journal`, and any copy
named `<database>.<something>`) are kept 0600. So is each installed pack's `pack.db` (`PACK_DATABASE`, in
`<data dir>/packs/<id>/`), with its `-wal`, `-shm` and `-journal`."""

PACK_DATABASE = "pack.db"


def database_copies(config: Config) -> list[Path]:
    """The old copies of the databases in the data directory, by name: `delve.db.pre-0026`, `reference.db.pre-voice`, as
    made by hand before a migration or an import. Each holds everything its database did, so `delve serve` names them
    for the owner to remove; Delve never removes one itself."""
    try:
        paths = sorted(config.data_dir.iterdir())
    except FileNotFoundError:
        return []
    return [p for p in paths if p.name.startswith(tuple(f"{db}." for db in DATABASES)) and p.is_file()]


def _tighten(config: Config) -> None:
    """The data directory 0700 and each file of a database 0600 (DEL-154, audit finding 13): an older Delve left them
    0775 and 0644, as SQLite and `cp` make them. Only regular files this user owns are changed, never a symlink's
    target; and the database is made 0600 before SQLite opens it, since SQLite gives its `-wal` and `-shm` the
    database's own mode."""
    private_data_dir(config.data_dir)
    if not config.db_path.exists():
        os.close(os.open(config.db_path, os.O_WRONLY | os.O_CREAT, DATABASE_FILE_MODE))
    paths = [p for p in config.data_dir.iterdir() if p.name.startswith(DATABASES)]
    paths += config.packs_dir.glob(f"*/{PACK_DATABASE}*") if config.packs_dir.is_dir() else []
    for path in paths:
        info = path.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) != DATABASE_FILE_MODE:
            path.chmod(DATABASE_FILE_MODE)


def _open_migrated(config: Config) -> Engine:
    _tighten(config)
    engine = create_sqlite_engine(config.db_path)
    try:
        _upgrade(engine)
    except BaseException:
        engine.dispose()
        raise
    return engine


def _script() -> ScriptDirectory:
    return ScriptDirectory(str(MIGRATIONS))


def _upgrade(engine: Engine) -> None:
    """Run the migrations to head in one transaction, with foreign keys off.

    On, a migration that rebuilds a table (a batch: copy, drop, rename) cascades the drop into every table that names
    it: 0037's test lost every character that way when `campaigns` was rebuilt. SQLite ignores the pragma inside a
    transaction, so it is set before one begins, and set back after. What foreign keys would have refused, a row
    naming nothing, `PRAGMA foreign_key_check` finds before the commit: such a migration is refused and rolled back.
    Only what the migrations broke counts, not a row an older Delve (or a hand edit) left, so a database with one
    still opens; and a database at head is neither migrated nor checked."""
    script = _script()
    head = script.get_current_head()
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            with connection.begin():
                current = MigrationContext.configure(connection).get_current_revision()
                if current is not None and current not in {s.revision for s in script.walk_revisions()}:
                    raise SchemaTooNewError(current, head)
                if current == head:
                    return
                before = _broken_references(connection)
                alembic_config = AlembicConfig()
                alembic_config.set_main_option("script_location", str(MIGRATIONS))
                alembic_config.attributes["connection"] = connection
                command.upgrade(alembic_config, "head")
                broken = [row for row in _broken_references(connection) if row not in before]
                if broken:
                    raise MigrationBrokeReferences(broken)
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _broken_references(connection: Connection) -> list[tuple[Any, ...]]:
    """The rows naming a row that isn't there: `(table, rowid, parent, constraint)`, as `PRAGMA foreign_key_check`
    lists them."""
    return [tuple(row) for row in connection.exec_driver_sql("PRAGMA foreign_key_check")]
