"""Snapshots (cloud storage, DEL-110): a module, a campaign or a setting as rows by table, for a backup's bundles, and
the records of what the backup store last got.

Rows come in `rowid` order, the order the repositories list them in, so a restored item lists as it did; `blobs`
rows, which nothing lists, come by sha. A campaign's tables are every table with a `campaign_id` column, found from
the metadata so that a new one is never missed; the module's and the setting's are named. Restore writes in
`metadata.sorted_tables` order, parents first. A dump reads in one SQLite read transaction, so a beat that commits
while a backup packs never reaches the copy halfway.

A campaign's join token is a credential, so it stays out of the dump, and a restored campaign gets a fresh one. Its
seats keep their token hashes, so the restored table keeps its seats.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import ColumnElement, Connection, Integer, Table, delete, select, text
from sqlalchemy.dialects.sqlite import insert

from delve.storage.interfaces import BackupItem, Snapshot, SnapshotKind, SnapshotRefused
from delve.storage.sqlite.campaigns_repo import SqliteCampaignRepository
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.module_texts_repo import drop_index, index_revision
from delve.storage.sqlite.tables import (
    accounts,
    backup_items,
    blobs,
    campaign_carries,
    campaigns,
    house_rules,
    house_rules_bundle_rules,
    house_rules_bundles,
    metadata,
    module_blobs,
    module_categories,
    module_comments,
    module_maps,
    module_revisions,
    module_sources,
    module_texts,
    modules,
    seats,
    setting_facts,
    setting_maps,
    setting_pages,
    story,
    translations,
    world_pictures,
)

MIGRATIONS = Path(__file__).parent.parent / "migrations"
SHA256 = re.compile(r"[0-9a-f]{64}")

MODULE_TABLES = (module_maps, module_revisions, module_texts, module_sources, module_blobs, module_comments)
"""A module's own tables beside `modules`, by `module_id`."""
SETTING_TABLES = (setting_pages, setting_facts, setting_maps)
"""A setting's tables, by `setting`."""
CAMPAIGN_TABLES = tuple(
    table for table in metadata.sorted_tables if "campaign_id" in table.c and table is not campaign_carries
)
"""A campaign's own tables beside `campaigns`: every one with a `campaign_id`. A carry is between two campaigns and
belongs to neither."""
SHARED = (house_rules, house_rules_bundles, house_rules_bundle_rules, world_pictures, module_categories)
"""Rows an item reaches but doesn't own: those already here are kept, and replacing the item leaves them."""
UPSERTED = (modules, module_revisions, campaigns)
"""Rows replaced in place, so that the campaigns playing a module and the carries of a campaign keep theirs."""
LEFT_OUT = {campaigns: ("join_token",)}
"""Columns that never go into a dump: credentials of this install."""
TABLES: dict[SnapshotKind, tuple[Table, ...]] = {
    "module": (modules, *MODULE_TABLES, module_categories, blobs),
    "campaign": (
        campaigns,
        *CAMPAIGN_TABLES,
        translations,
        house_rules_bundles,
        house_rules_bundle_rules,
        house_rules,
        world_pictures,
        blobs,
    ),
    "setting": (*SETTING_TABLES, world_pictures, blobs),
}
"""The tables each kind's dump writes, and the only ones its restore takes."""
FOREIGN = "This copy holds more than its item."


@cache
def _known_heads() -> frozenset[str]:
    return frozenset(script.revision for script in ScriptDirectory(str(MIGRATIONS)).walk_revisions())


def _rows(connection: Connection, table: Table, where: ColumnElement[bool]) -> list[dict[str, Any]]:
    left_out = LEFT_OUT.get(table, ())
    query = select(*(c for c in table.c if c.name not in left_out)).where(where).order_by(text("rowid"))
    return [dict(row) for row in connection.execute(query).mappings()]


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _shas(rows: dict[str, list[dict[str, Any]]]) -> set[str]:
    return {sha for listed in rows.values() for row in listed for s in _strings(row) for sha in SHA256.findall(s)}


def _counter(table: Table) -> str | None:
    """The column of a table numbered by SQLite (`events.id`), if it has one."""
    key = list(table.primary_key.columns)
    return key[0].name if len(key) == 1 and isinstance(key[0].type, Integer) else None


class SqliteSnapshotRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def dump(self, kind: SnapshotKind, item_id: str) -> Snapshot:
        with _one_read(self._db) as connection:
            head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if kind == "module":
                rows = self._module(connection, item_id)
            elif kind == "campaign":
                rows = self._campaign(connection, item_id)
            else:
                rows = self._setting(connection, item_id)
            found = _shas(rows)
            rows["blobs"] = _blob_rows(connection, found)
        rows = {name: table for name, table in rows.items() if table}
        assert set(rows) <= {table.name for table in TABLES[kind]}, "a dump writes a table its restore refuses"
        shas = frozenset(row["sha256"] for row in rows.get("blobs", []))
        return Snapshot(kind=kind, item_id=item_id, head=head, rows=rows, blobs=shas)

    def restore(self, snapshot: Snapshot, *, replace: bool) -> list[str]:
        if snapshot.head not in _known_heads():
            raise SnapshotRefused("A newer Delve made this copy. Upgrade Delve to restore it.")
        _check_own(snapshot)
        warnings: list[str] = []
        with self._db.transaction(), self._db.begin() as connection:
            if snapshot.kind == "campaign":
                (row,) = snapshot.rows["campaigns"]
                pinned = select(module_revisions.c.number).where(
                    module_revisions.c.module_id == row["module_id"], module_revisions.c.number == row["revision"]
                )
                if connection.execute(pinned).first() is None:
                    raise SnapshotRefused("Restore its module first.")
            if self._exists(connection, snapshot.kind, snapshot.item_id):
                if not replace:
                    raise SnapshotRefused("It is on this install already.")
                self._delete(connection, snapshot)
            if snapshot.kind == "module":
                snapshot = _with_category(connection, snapshot)
            missing = {sha for sha in snapshot.blobs if not _present(connection, blobs, blobs.c.sha256 == sha)}
            if missing:
                warnings.append(f"{len(missing)} picture(s) weren't in the copy.")
            kept_bundles = {
                bundle["id"]
                for bundle in snapshot.rows.get("house_rules_bundles", [])
                if _present(connection, house_rules_bundles, house_rules_bundles.c.id == bundle["id"])
            }
            for table in metadata.sorted_tables:
                if table is blobs or table.name not in snapshot.rows:
                    continue
                rows = [{k: v for k, v in row.items() if k in table.c} for row in snapshot.rows[table.name]]
                if table is module_blobs:
                    rows = [row for row in rows if row["sha256"] not in missing]
                elif table is house_rules_bundle_rules:
                    rows = [row for row in rows if row["bundle_id"] not in kept_bundles]
                elif table is seats:
                    rows = [self._seat(connection, row, warnings) for row in rows]
                _insert(connection, table, rows)
            if snapshot.kind == "campaign":
                SqliteCampaignRepository(self._db).new_join_token(snapshot.item_id)
            if snapshot.kind == "module":
                for revision in snapshot.rows.get("module_revisions", []):
                    index_revision(connection, snapshot.item_id, revision["number"], revision.get("text"))
        return warnings

    def item_ids(self, kind: SnapshotKind) -> list[str]:
        with self._db.connect() as connection:
            if kind == "module":
                return sorted(connection.execute(select(modules.c.id)).scalars())
            if kind == "campaign":
                return sorted(connection.execute(select(campaigns.c.id)).scalars())
            found: set[str] = set()
            for table in SETTING_TABLES:
                found.update(connection.execute(select(table.c.setting).distinct()).scalars())
            return sorted(found)

    def title(self, kind: SnapshotKind, item_id: str) -> str:
        if kind == "setting":
            return item_id
        column = modules.c.title if kind == "module" else campaigns.c.name
        with self._db.connect() as connection:
            found = connection.execute(select(column).where(column.table.c.id == item_id)).scalar()
        if found is None:
            raise KeyError(item_id)
        return found

    def _module(self, connection: Connection, id: str) -> dict[str, list[dict[str, Any]]]:
        rows = {"modules": _rows(connection, modules, modules.c.id == id)}
        if not rows["modules"]:
            raise KeyError(id)
        for table in MODULE_TABLES:
            rows[table.name] = _rows(connection, table, table.c.module_id == id)
        # A fix-it comment's job stays on this install.
        rows["module_comments"] = [dict(row, conversion_id=None) for row in rows["module_comments"]]
        # Its category (DEL-114) goes along, a shared row: added where it's missing, never replaced.
        category = rows["modules"][0].get("category_id")
        if category is not None:
            rows["module_categories"] = _rows(connection, module_categories, module_categories.c.id == category)
        return rows

    def _campaign(self, connection: Connection, id: str) -> dict[str, list[dict[str, Any]]]:
        rows = {"campaigns": _rows(connection, campaigns, campaigns.c.id == id)}
        if not rows["campaigns"]:
            raise KeyError(id)
        for table in CAMPAIGN_TABLES:
            rows[table.name] = _rows(connection, table, table.c.campaign_id == id)
        entries = [entry["id"] for entry in rows["story"]]
        rows["translations"] = _rows(connection, translations, translations.c.entry_id.in_(entries))
        bundle_ids = [link["bundle_id"] for link in rows["house_rules_campaign_bundles"]]
        rows["house_rules_bundles"] = _rows(connection, house_rules_bundles, house_rules_bundles.c.id.in_(bundle_ids))
        rows["house_rules_bundle_rules"] = _rows(
            connection, house_rules_bundle_rules, house_rules_bundle_rules.c.bundle_id.in_(bundle_ids)
        )
        rule_ids = {link["rule_id"] for link in rows["house_rules_campaign_rules"]}
        rule_ids.update(link["rule_id"] for link in rows["house_rules_bundle_rules"])
        rows["house_rules"] = _rows(connection, house_rules, house_rules.c.id.in_(rule_ids))
        rows["world_pictures"] = _pictures(connection, rows["world_maps"])
        return rows

    def _setting(self, connection: Connection, setting: str) -> dict[str, list[dict[str, Any]]]:
        rows = {table.name: _rows(connection, table, table.c.setting == setting) for table in SETTING_TABLES}
        rows["world_pictures"] = _pictures(connection, rows["setting_maps"])
        return rows

    def _exists(self, connection: Connection, kind: SnapshotKind, item_id: str) -> bool:
        if kind == "module":
            return _present(connection, modules, modules.c.id == item_id)
        if kind == "campaign":
            return _present(connection, campaigns, campaigns.c.id == item_id)
        return any(_present(connection, table, table.c.setting == item_id) for table in SETTING_TABLES)

    def _delete(self, connection: Connection, snapshot: Snapshot) -> None:
        """Delete the item's rows before its snapshot goes in, but for those `UPSERTED`."""
        id = snapshot.item_id
        if snapshot.kind == "module":
            numbers = [revision["number"] for revision in snapshot.rows.get("module_revisions", [])]
            dropped = (module_revisions.c.module_id == id) & module_revisions.c.number.not_in(numbers)
            played = select(campaigns.c.id).where(
                campaigns.c.module_id == id, campaigns.c.revision.in_(select(module_revisions.c.number).where(dropped))
            )
            if connection.execute(played).first() is not None:
                raise SnapshotRefused("A campaign here plays a revision this copy doesn't have.")
            for table in reversed(MODULE_TABLES):
                if table is not module_revisions:
                    connection.execute(delete(table).where(table.c.module_id == id))
            connection.execute(delete(module_revisions).where(dropped))
            drop_index(connection, id)
        elif snapshot.kind == "campaign":
            entries = select(story.c.id).where(story.c.campaign_id == id)
            connection.execute(delete(translations).where(translations.c.entry_id.in_(entries)))
            for table in reversed(CAMPAIGN_TABLES):
                connection.execute(delete(table).where(table.c.campaign_id == id))
        else:
            for table in SETTING_TABLES:
                connection.execute(delete(table).where(table.c.setting == id))

    def _seat(self, connection: Connection, row: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        account = row.get("account_id")
        if account is None or _present(connection, accounts, accounts.c.id == account):
            return row
        warnings.append(f"{row['name']}'s seat lost its account, which isn't on this install.")
        return dict(row, account_id=None)


@contextmanager
def _one_read(db: Database) -> Iterator[Connection]:
    """A connection whose reads all see one moment of the database. pysqlite begins a transaction only before a write,
    so this begins one, which WAL keeps to the moment of its first read until it ends; in an open transaction (a
    bundle's packing, `bundles.pack`), that one's, so the reads after the dump see the same moment."""
    with db.connect() as connection:
        if not connection.connection.dbapi_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        yield connection


def _check_own(snapshot: Snapshot) -> None:
    """Refuse a snapshot that names a table its kind's dump doesn't write, or a row of another item: a bundle comes
    from a store, so it may be forged. Shared rows (`SHARED`, `blobs`) are only ever added, never replaced."""
    kind, id, rows = snapshot.kind, snapshot.item_id, snapshot.rows
    if not set(rows) <= {table.name for table in TABLES[kind]}:
        raise SnapshotRefused(FOREIGN)

    def owned(name: str, column: str, ids: Iterable[Any]) -> bool:
        allowed = set(ids)
        return all(row.get(column) in allowed for row in rows.get(name, []))

    if kind == "module":
        mine = [row.get("id") for row in rows.get("modules", [])] == [id]
        mine = mine and all(owned(table.name, "module_id", [id]) for table in MODULE_TABLES)
        mine = mine and owned("module_categories", "id", (row.get("category_id") for row in rows.get("modules", [])))
    elif kind == "campaign":
        mine = [row.get("id") for row in rows.get("campaigns", [])] == [id]
        mine = mine and all(owned(table.name, "campaign_id", [id]) for table in CAMPAIGN_TABLES)
        mine = mine and owned("translations", "entry_id", (row.get("id") for row in rows.get("story", [])))
        bundles = (row.get("id") for row in rows.get("house_rules_bundles", []))
        mine = mine and owned("house_rules_bundle_rules", "bundle_id", bundles)
    else:
        mine = all(owned(table.name, "setting", [id]) for table in SETTING_TABLES)
    if not mine:
        raise SnapshotRefused(FOREIGN)


def _with_category(connection: Connection, snapshot: Snapshot) -> Snapshot:
    """A module's copy with its category (DEL-114) matched to this install's: by id, else by name in any case (the
    module takes that one), else added last; a module whose category isn't in the copy gets none."""
    (module,) = snapshot.rows["modules"]
    wanted = module.get("category_id")
    copied = [row for row in snapshot.rows.get("module_categories", []) if row.get("id") == wanted]
    here = connection.execute(select(module_categories)).mappings().all()
    category: str | None = None
    keep: list[dict[str, Any]] = []
    if wanted is not None and any(row["id"] == wanted for row in here):
        category = wanted
    elif copied:
        named = next((row for row in here if row["name"].casefold() == str(copied[0]["name"]).casefold()), None)
        if named is not None:
            category = named["id"]
        else:
            category = wanted
            keep = [dict(copied[0], position=len(here))]
    rows = {**snapshot.rows, "modules": [dict(module, category_id=category)], "module_categories": keep}
    return dataclasses.replace(snapshot, rows=rows)


def _present(connection: Connection, table: Table, where: ColumnElement[bool]) -> bool:
    return connection.execute(select(text("1")).select_from(table).where(where).limit(1)).first() is not None


def _blob_rows(connection: Connection, shas: set[str]) -> list[dict[str, Any]]:
    """The `blobs` rows of those shas that are blobs, without the time they were put, which a restore sets anew."""
    if not shas:
        return []
    query = select(blobs.c.sha256, blobs.c.mime, blobs.c.size).where(blobs.c.sha256.in_(shas)).order_by(blobs.c.sha256)
    return [dict(row) for row in connection.execute(query).mappings()]


def _pictures(connection: Connection, maps: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {row["picture"] for row in maps if row.get("picture")}
    return _rows(connection, world_pictures, world_pictures.c.id.in_(ids)) if ids else []


def _insert(connection: Connection, table: Table, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    counter = _counter(table)
    if counter is not None:
        ids = [row[counter] for row in rows if row.get(counter) is not None]
        if ids and connection.execute(select(table.c[counter]).where(table.c[counter].in_(ids)).limit(1)).first():
            # Taken here by another item: SQLite numbers the rows anew, in their order.
            rows = [{k: v for k, v in row.items() if k != counter} for row in rows]
    statement = insert(table)
    if table in SHARED:
        statement = statement.on_conflict_do_nothing()
    elif table in UPSERTED:
        key = [column.name for column in table.primary_key.columns]
        columns = [name for name in rows[0] if name not in key]
        statement = statement.on_conflict_do_update(
            index_elements=key, set_={name: statement.excluded[name] for name in columns}
        )
    connection.execute(statement, rows)


class SqliteBackupItemRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, kind: SnapshotKind, item_id: str) -> BackupItem | None:
        query = select(backup_items).where(backup_items.c.kind == kind, backup_items.c.item_id == item_id)
        with self._db.connect() as connection:
            row = connection.execute(query).first()
        return None if row is None else BackupItem(**row._mapping)

    def put(self, item: BackupItem) -> None:
        values = {
            "kind": item.kind,
            "item_id": item.item_id,
            "hash": item.hash,
            "size": item.size,
            "backed_up_at": item.backed_up_at,
        }
        upsert = insert(backup_items).values(values)
        upsert = upsert.on_conflict_do_update(
            index_elements=[backup_items.c.kind, backup_items.c.item_id],
            set_={"hash": item.hash, "size": item.size, "backed_up_at": item.backed_up_at},
        )
        with self._db.begin() as connection:
            connection.execute(upsert)

    def list(self) -> list[BackupItem]:
        query = select(backup_items).order_by(backup_items.c.kind, backup_items.c.item_id)
        with self._db.connect() as connection:
            return [BackupItem(**row._mapping) for row in connection.execute(query)]
