"""The owner's seat takes the owner account's name: a table's owner seat was made as "Host" whatever the owner was
called, so the table, Find a table and the story said "Host". Those still called "Host" are named after the install's
first live owner account; nothing changes while there is none.

Revision ID: 0033_owner_seat_name
Revises: 0032_table_schedule
Create Date: 2026-10-27
"""

from alembic import op

revision = "0033_owner_seat_name"
down_revision = "0032_table_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE seats SET name = (
            SELECT display_name FROM accounts
            WHERE owner = 1 AND disabled_at IS NULL AND trim(display_name) != '' ORDER BY rowid LIMIT 1
        )
        WHERE owner = 1 AND name = 'Host' AND account_id IS NULL
          AND EXISTS (SELECT 1 FROM accounts WHERE owner = 1 AND disabled_at IS NULL AND trim(display_name) != '')
        """
    )


def downgrade() -> None:
    pass  # the old name was only ever the default; a renamed seat keeps its name
