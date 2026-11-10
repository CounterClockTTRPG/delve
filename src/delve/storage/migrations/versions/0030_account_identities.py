"""Outside identities accounts log in with (DEL-206): `account_identities`, a provider's `sub` per account, one per
provider per account.

Revision ID: 0030_account_identities
Revises: 0029_table_listing
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_account_identities"
down_revision = "0029_table_listing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_identities",
        sa.Column("provider", sa.Text, primary_key=True),
        sa.Column("subject", sa.Text, primary_key=True),
        sa.Column("account_id", sa.Text, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("linked_at", sa.Text, nullable=False),
    )
    op.create_index(
        "ix_account_identities_account_provider", "account_identities", ["account_id", "provider"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_account_identities_account_provider", table_name="account_identities")
    op.drop_table("account_identities")
