"""Join requests (DEL-204 part B): `join_requests`, an account's request to join a public table, with its status, its
short thread of messages (JSON), when it was decided and the seat an accept made. One pending request per account and
table (a partial unique index). A request goes with its campaign and with its account; its seat is cleared if that
seat ever went.

Revision ID: 0031_join_requests
Revises: 0030_account_identities
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0031_join_requests"
down_revision = "0030_account_identities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "join_requests",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("campaign_id", sa.Text, sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Text, sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("messages", sa.JSON, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("decided_at", sa.Text, nullable=True),
        sa.Column("seat_id", sa.Text, sa.ForeignKey("seats.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_join_requests_campaign", "join_requests", ["campaign_id"])
    op.create_index("ix_join_requests_account", "join_requests", ["account_id"])
    op.create_index(
        "uq_join_requests_one_pending",
        "join_requests",
        ["campaign_id", "account_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    for index in ("uq_join_requests_one_pending", "ix_join_requests_account", "ix_join_requests_campaign"):
        op.drop_index(index, table_name="join_requests")
    op.drop_table("join_requests")
