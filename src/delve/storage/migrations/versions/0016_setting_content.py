"""The setting's content (settings plan Task 2): a setting's added and overridden pages, its facts, the DM's
proposals and the setting's own world maps, over the shipped setting, which stays read-only. No other table changes.

Revision ID: 0016_setting_content
Revises: 0015_costs
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_setting_content"
down_revision = "0015_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setting_pages",
        sa.Column("setting", sa.Text(), nullable=False),
        sa.Column("title_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("dm_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("setting", "title_key"),
    )
    op.create_table(
        "setting_facts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("setting", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("dm_only", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("setting", sa.Text(), nullable=False),
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("page_kind", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("dm_only", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_proposals_setting_status", "proposals", ["setting", "status"])
    op.create_index("ix_proposals_campaign_id", "proposals", ["campaign_id"])
    op.create_table(
        "setting_maps",
        sa.Column("setting", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("geo", sa.JSON(), nullable=False),
        sa.Column("picture", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reading", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("setting", "name"),
    )


def downgrade() -> None:
    op.drop_table("setting_maps")
    op.drop_index("ix_proposals_campaign_id", "proposals")
    op.drop_index("ix_proposals_setting_status", "proposals")
    op.drop_table("proposals")
    op.drop_table("setting_facts")
    op.drop_table("setting_pages")
