"""Novels (novelization plan Task 1): a campaign or a module told as a story, with its choices, its outline and its
chapters (JSON), saved as they are written. A novel goes with its campaign or its module. No other table changes.

Revision ID: 0017_novels
Revises: 0016_setting_content
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_novels"
down_revision = "0016_setting_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "novels",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True),
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("sessions", sa.JSON(), nullable=True),
        sa.Column("length", sa.Text(), nullable=False),
        sa.Column("tone", sa.Text(), nullable=False),
        sa.Column("custom_tone", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("chapters", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("conversion_id", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("(campaign_id IS NULL) != (module_id IS NULL)", name="ck_novels_one_source"),
    )
    op.create_index("ix_novels_campaign_id", "novels", ["campaign_id"])
    op.create_index("ix_novels_module_id", "novels", ["module_id"])


def downgrade() -> None:
    op.drop_index("ix_novels_module_id", "novels")
    op.drop_index("ix_novels_campaign_id", "novels")
    op.drop_table("novels")
