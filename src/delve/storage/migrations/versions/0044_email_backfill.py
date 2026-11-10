"""Email (DEL-314): an account linked to Google before email came, with no address of its own (none confirmed, none
waiting), gets the address Google verified, confirmed, as linking gives it now. An identity keeps an address only
when Google said it was verified, so an empty one fills nothing. Plain UPDATE: accounts are referenced by seats, so
no table is rebuilt. Downgrading takes nothing back: the address is the account's now.

Revision ID: 0044_email_backfill
Revises: 0043_email
Create Date: 2026-10-30
"""

from alembic import op

revision = "0044_email_backfill"
down_revision = "0043_email"
branch_labels = None
depends_on = None

_GOOGLE = "FROM account_identities ai WHERE ai.account_id = accounts.id AND ai.provider = 'google' AND ai.email != ''"


def upgrade() -> None:
    op.execute(
        f"UPDATE accounts SET email = (SELECT ai.email {_GOOGLE} ORDER BY ai.linked_at LIMIT 1) "
        f"WHERE email IS NULL AND email_pending IS NULL AND EXISTS (SELECT 1 {_GOOGLE})"
    )


def downgrade() -> None:
    pass
