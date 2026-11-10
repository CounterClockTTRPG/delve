"""Modules with their maps and revisions, campaigns, characters, map states and blobs.

Revision ID: 0002_modules_campaigns
Revises: 0001_settings
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_modules_campaigns"
down_revision = "0001_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "modules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "module_maps",
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "module_revisions",
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("maps", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["module_id", "revision"],
            ["module_revisions.module_id", "module_revisions.number"],
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "characters",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_characters_campaign_id", "characters", ["campaign_id"])
    op.create_table(
        "map_states",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("map_name", sa.Text(), primary_key=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "blobs",
        sa.Column("sha256", sa.Text(), primary_key=True),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "module_blobs",
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.Text(), primary_key=True),
        sa.Column("sha256", sa.Text(), sa.ForeignKey("blobs.sha256", ondelete="RESTRICT"), primary_key=True),
    )


def downgrade() -> None:
    for table in (
        "module_blobs",
        "blobs",
        "map_states",
        "characters",
        "campaigns",
        "module_revisions",
        "module_maps",
        "modules",
    ):
        op.drop_table(table)
