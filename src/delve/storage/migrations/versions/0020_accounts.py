"""Accounts (players and tavern Task B1): `accounts` with their profiles and rights (`organiser`, and `owner`, the
human's ruling of 2026-10-24), the one-time `account_links` that set or reset a password, and `seats.account_id`, with
one live seat per account and campaign. Seats made before keep their rows and tokens, with no account.

Revision ID: 0020_accounts
Revises: 0019_campaign_maps
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_accounts"
down_revision = "0019_campaign_maps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("disabled_at", sa.Text(), nullable=True),
        sa.Column("organiser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("external_id", sa.Text(), nullable=True, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("pronouns", sa.Text(), nullable=False, server_default=""),
        sa.Column("avatar_emblem", sa.Text(), nullable=True),
        sa.Column("avatar_sha", sa.Text(), nullable=True),
        sa.Column("colour", sa.Text(), nullable=False, server_default="teal"),
        sa.Column("language", sa.Text(), nullable=False, server_default="en"),
        sa.Column("about", sa.Text(), nullable=False, server_default=""),
        sa.Column("host_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("time_zone", sa.Text(), nullable=True),
    )
    op.create_table(
        "account_links",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_account_links_account_id", "account_links", ["account_id"])
    # Plain ALTER TABLE, not a batch: a batch copies and drops `seats`, and dropping it would cascade.
    op.execute("ALTER TABLE seats ADD COLUMN account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL")
    op.execute(
        "CREATE UNIQUE INDEX uq_seats_account_live ON seats (campaign_id, account_id) "
        "WHERE account_id IS NOT NULL AND left_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_seats_account_live", table_name="seats")
    op.execute("ALTER TABLE seats DROP COLUMN account_id")
    op.drop_index("ix_account_links_account_id", table_name="account_links")
    op.drop_table("account_links")
    op.drop_table("accounts")
