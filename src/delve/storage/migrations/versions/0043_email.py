"""Email (DEL-314): an account's address and mail switches (`accounts.email`, `email_pending`, `mail_host`,
`mail_board`), the `email_confirmations` of typed-in addresses, the `mail_outbox` (which keeps no recipient address)
and `board_follows`. Plain ALTER TABLE and new tables: accounts are referenced by seats.

Revision ID: 0043_email
Revises: 0042_board
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "0043_email"
down_revision = "0042_board"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("email", sa.Text(), nullable=True))
    op.add_column("accounts", sa.Column("email_pending", sa.Text(), nullable=True))
    op.add_column("accounts", sa.Column("mail_host", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("accounts", sa.Column("mail_board", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "email_confirmations",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("used_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_email_confirmations_account", "email_confirmations", ["account_id"])
    op.create_table(
        "mail_outbox",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("reply_to", sa.Text(), nullable=True),
        sa.Column("unsubscribe", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_at", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.Text(), nullable=True),
        sa.Column("failed_at", sa.Text(), nullable=True),
        sa.Column("failure", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_mail_outbox_due", "mail_outbox", ["sent_at", "failed_at", "next_at"])
    op.create_table(
        "board_follows",
        sa.Column("account_id", sa.Text(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic_id", sa.Text(), sa.ForeignKey("board_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notified_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("account_id", "topic_id"),
    )


def downgrade() -> None:
    op.drop_table("board_follows")
    op.drop_index("ix_mail_outbox_due", table_name="mail_outbox")
    op.drop_table("mail_outbox")
    op.drop_index("ix_email_confirmations_account", table_name="email_confirmations")
    op.drop_table("email_confirmations")
    op.drop_column("accounts", "mail_board")
    op.drop_column("accounts", "mail_host")
    op.drop_column("accounts", "email_pending")
    op.drop_column("accounts", "email")
