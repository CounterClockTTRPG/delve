"""Module categories (DEL-114) and module banners (DEL-123): `module_categories`, and a module's `category_id` and
`banner_*` columns, NULL for none.

Plain `CREATE TABLE` and `ALTER TABLE … ADD COLUMN`s: a batch would copy and drop `modules`.

Revision ID: 0025_module_categories_banners
Revises: 0024_cloud_storage
Create Date: 2026-10-26
"""

from alembic import op

revision = "0025_module_categories_banners"
down_revision = "0024_cloud_storage"
branch_labels = None
depends_on = None

COLUMNS = ("category_id", "banner_blob", "banner_mime", "banner_source", "banner_status", "banner_error", "banner_prompt")


def upgrade() -> None:
    op.execute("CREATE TABLE module_categories (id TEXT NOT NULL PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL)")
    for column in COLUMNS:
        op.execute(f"ALTER TABLE modules ADD COLUMN {column} TEXT")


def downgrade() -> None:
    for column in reversed(COLUMNS):
        op.execute(f"ALTER TABLE modules DROP COLUMN {column}")
    op.execute("DROP TABLE module_categories")
