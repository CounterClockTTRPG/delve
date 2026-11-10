"""The schema the migrations build is the one `tables.py` describes, and no migration rebuilds a table others name."""

import ast
import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Boolean, Integer

from delve.config import Config
from delve.storage import MIGRATIONS, open_storage
from delve.storage.sqlite.tables import metadata

FTS_TABLE = "module_text_index"
"""The search index, an FTS5 virtual table that `tables.py` doesn't describe (SQLAlchemy can't), with its shadow
tables `module_text_index_data`, `_idx`, `_content`, `_docsize` and `_config`."""

INLINE_REFERENCES = {("seats", "account_id"), ("characters", "controller_id")}
"""Columns added by `ALTER TABLE … ADD COLUMN … REFERENCES … ON DELETE SET NULL` (0010, 0020): SQLAlchemy reads such
a foreign key without its ON DELETE, so it compares unlike `tables.py`'s; `PRAGMA foreign_key_list` shows it is there
(checked below)."""


def _harmless(diff) -> bool:
    """A difference SQLite's reflection makes up, not one between the schemas (each kind explained where it's named)."""
    if isinstance(diff, list):  # alembic groups a column's changes in a list
        return all(_harmless(d) for d in diff)
    kind = diff[0]
    if kind == "modify_type":
        # SQLite has no boolean type: a Boolean column is an INTEGER, whichever of the two a migration named.
        _, _, _, _, _, stored, described = diff
        return isinstance(stored, Integer) and isinstance(described, Boolean)
    if kind in ("add_fk", "remove_fk"):
        constraint = diff[1]
        return {(constraint.table.name, c.name) for c in constraint.columns} <= INLINE_REFERENCES
    return False


def test_the_migrated_schema_is_the_one_tables_py_describes(tmp_path):
    """A fresh database migrated to head against `tables.py`: a column, index or constraint one has and the other
    hasn't (a migration that forgot what the code reads, or the code that forgot an index) fails here."""
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        with storage.engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"include_name": lambda name, kind, _parent: not (kind == "table" and name.startswith(FTS_TABLE))},
            )
            diffs = [d for d in compare_metadata(context, metadata) if not _harmless(d)]
    finally:
        storage.close()
    assert diffs == []
    with sqlite3.connect(tmp_path / "delve.db") as db:
        for table, column in INLINE_REFERENCES:
            keys = {(row[3], row[6]) for row in db.execute(f"PRAGMA foreign_key_list({table})")}
            assert (column, "SET NULL") in keys, (table, column)


REFERENCED = sorted({key.column.table.name for table in metadata.tables.values() for key in table.foreign_keys})
"""The tables other tables name in a foreign key: a batch rebuild drops and makes them again."""

OLD_BATCHES = {
    ("0003_play_state.py", "characters"),
    ("0004_module_text.py", "module_revisions"),
    ("0006_module_source.py", "module_revisions"),
}
"""Batches from before foreign keys were turned off for migrations, each only adding columns, which alembic does with
ALTER TABLE, not a rebuild; the installs have run them."""


def _batches_on_referenced_tables() -> list[tuple[str, str]]:
    found = []
    for path in sorted((MIGRATIONS / "versions").glob("*.py")):
        tree = ast.parse(path.read_text())
        upgrade = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "upgrade")
        for node in ast.walk(upgrade):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr in ("batch_alter_table", "drop_table") and node.args:
                name = node.args[0].value if isinstance(node.args[0], ast.Constant) else ast.unparse(node.args[0])
                if name in REFERENCED:
                    found.append((path.name, name))
    return found


def test_no_migration_rebuilds_or_drops_a_table_others_name():
    """A batch (copy, drop, rename) or a drop of a table that others name in a foreign key. Migrations run with foreign
    keys off now, so a rebuild no longer cascades (0037's test lost every character to one on `campaigns`), but a row
    left naming nothing refuses the migration; use plain `ALTER TABLE` (see 0037) instead."""
    assert REFERENCED and "campaigns" in REFERENCED and "modules" in REFERENCED
    assert [found for found in _batches_on_referenced_tables() if found not in OLD_BATCHES] == []
