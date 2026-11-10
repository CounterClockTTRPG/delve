"""Histories and carries (carry-the-party-on plan Task 1): a campaign's history, the DM's and the table's texts, gone
with its campaign; and the link from the campaign a party was carried on from to the one it went into, kept when the
old campaign is deleted. No other table changes.

Revision ID: 0018_histories
Revises: 0017_novels
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_histories"
down_revision = "0017_novels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_histories",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("dm_md", sa.Text(), nullable=False),
        sa.Column("table_md", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("conversion_id", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "campaign_carries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("from_campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "to_campaign_id",
            sa.Text(),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("character_ids", sa.JSON(), nullable=False),
        sa.Column("carried_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_campaign_carries_from_campaign_id", "campaign_carries", ["from_campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_campaign_carries_from_campaign_id", "campaign_carries")
    op.drop_table("campaign_carries")
    op.drop_table("campaign_histories")
