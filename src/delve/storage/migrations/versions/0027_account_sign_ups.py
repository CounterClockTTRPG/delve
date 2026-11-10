"""Sign-ups wait for approval (DEL-156): `accounts.pending`, 0 for every account already made, and
`accounts.request_note`, what the person who signed up told the approver.

Plain `ALTER TABLE … ADD COLUMN`s: a batch would copy and drop `accounts`.

Revision ID: 0027_account_sign_ups
Revises: 0026_account_links_by_owner
Create Date: 2026-10-26
"""

from alembic import op

revision = "0027_account_sign_ups"
down_revision = "0026_account_links_by_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE accounts ADD COLUMN pending BOOLEAN NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE accounts ADD COLUMN request_note TEXT NOT NULL DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE accounts DROP COLUMN request_note")
    op.execute("ALTER TABLE accounts DROP COLUMN pending")
