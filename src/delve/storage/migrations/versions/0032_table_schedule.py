"""The table's schedule (DEL-204 part C): a campaign's `schedule`, JSON, null for none: the rule it plays by (every N
weeks from a first date, a start and an end in a time zone) and the host's changes to single sessions.

A plain `ALTER TABLE … ADD COLUMN`, null for an existing campaign: a batch would copy and drop the table, and the drop
would cascade.

Revision ID: 0032_table_schedule
Revises: 0031_join_requests
Create Date: 2026-10-27
"""

from alembic import op

revision = "0032_table_schedule"
down_revision = "0031_join_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE campaigns ADD COLUMN schedule JSON")


def downgrade() -> None:
    op.execute("ALTER TABLE campaigns DROP COLUMN schedule")
