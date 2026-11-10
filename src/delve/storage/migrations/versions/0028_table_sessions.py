"""The table's session state (DEL-199): `table_sessions`, one row per campaign, gone with it: gathering, playing or on
a break, the host's choices for the absent PCs and the raised hands. A campaign without a row gets its state from the
pregame's rule (`delve.play.table_session`), so no row is made here. No other table changes.

Revision ID: 0028_table_sessions
Revises: 0027_account_sign_ups
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_table_sessions"
down_revision = "0027_account_sign_ups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "table_sessions",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("since", sa.Text(), nullable=True),
        sa.Column("absent", sa.JSON(), nullable=False),
        sa.Column("hands", sa.JSON(), nullable=False),
        sa.Column("break_at", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("table_sessions")
