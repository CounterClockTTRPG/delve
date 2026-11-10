"""Cloud storage (DEL-110): `backup_items`, what the backup store last got of each module, campaign and setting, by
its bundle's hash; and a module's place in the shared library (`library_*`), NULL until it is published or downloaded.

Plain `CREATE TABLE` and `ALTER TABLE … ADD COLUMN`s: a batch would copy and drop `modules`.

Revision ID: 0024_cloud_storage
Revises: 0023_image_jobs
Create Date: 2026-10-26
"""

from alembic import op

revision = "0024_cloud_storage"
down_revision = "0023_image_jobs"
branch_labels = None
depends_on = None

LIBRARY = (
    ("library_key", "TEXT"),
    ("library_version", "INTEGER"),
    ("library_hash", "TEXT"),
    ("library_origin", "TEXT"),
    ("library_author", "TEXT"),
)


def upgrade() -> None:
    op.execute(
        "CREATE TABLE backup_items (kind TEXT NOT NULL, item_id TEXT NOT NULL, hash TEXT NOT NULL,"
        " size INTEGER NOT NULL, backed_up_at TEXT NOT NULL, PRIMARY KEY (kind, item_id))"
    )
    for column, type_ in LIBRARY:
        op.execute(f"ALTER TABLE modules ADD COLUMN {column} {type_}")


def downgrade() -> None:
    for column, _ in reversed(LIBRARY):
        op.execute(f"ALTER TABLE modules DROP COLUMN {column}")
    op.execute("DROP TABLE backup_items")
