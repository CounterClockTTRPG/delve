"""A campaign's own maps (campaign maps, 2026-10-23): dungeon maps made for one campaign and never part of its module,
gone with the campaign. No other table changes.

Revision ID: 0019_campaign_maps
Revises: 0018_histories
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_campaign_maps"
down_revision = "0018_histories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_maps",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("campaign_id", "name"),
    )


def downgrade() -> None:
    op.drop_table("campaign_maps")
