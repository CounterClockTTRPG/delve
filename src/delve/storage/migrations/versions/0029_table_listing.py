"""The table's listing (DEL-204 part A): a campaign's `visibility` (`private` or `public`), its players' `description`
and its `slots`, the places for players (null: no limit).

Each column is a plain `ALTER TABLE … ADD COLUMN` with a default that keeps an existing campaign as it was (private,
no description, no limit): a batch would copy and drop the table, and the drop would cascade.

Revision ID: 0029_table_listing
Revises: 0028_table_sessions
Create Date: 2026-10-27
"""

from alembic import op

revision = "0029_table_listing"
down_revision = "0028_table_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE campaigns ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")
    op.execute("ALTER TABLE campaigns ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE campaigns ADD COLUMN slots INTEGER")


def downgrade() -> None:
    for column in ("slots", "description", "visibility"):
        op.execute(f"ALTER TABLE campaigns DROP COLUMN {column}")
