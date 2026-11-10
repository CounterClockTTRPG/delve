"""Login sessions (players and tavern Task C1): a browser logged in to an account, known only by its token's SHA-256
hex digest, ended 30 days after its last use.

Revision ID: 0021_login_sessions
Revises: 0020_accounts
Create Date: 2026-10-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_login_sessions"
down_revision = "0020_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.Text(), nullable=False),
        sa.Column("device", sa.Text(), nullable=False, server_default=""),
        sa.Column("address", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_login_sessions_account", "login_sessions", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_login_sessions_account", table_name="login_sessions")
    op.drop_table("login_sessions")
