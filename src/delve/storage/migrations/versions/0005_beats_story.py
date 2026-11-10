"""Beats, the story, the DM log, the DM's resumable conversation per campaign, and the campaign's play settings.

Revision ID: 0005_beats_story
Revises: 0004_module_text
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_beats_story"
down_revision = "0004_module_text"
branch_labels = None
depends_on = None


def _campaign_fk() -> sa.Column:
    return sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "beats",
        sa.Column("id", sa.Text(), primary_key=True),
        _campaign_fk(),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("submissions", sa.JSON(), nullable=False),
        sa.Column("opened_at", sa.Text(), nullable=False),
        sa.Column("closed_at", sa.Text(), nullable=True),
        sa.UniqueConstraint("campaign_id", "number", name="uq_beats_campaign_number"),
    )
    op.create_index(
        "uq_beats_one_current",
        "beats",
        ["campaign_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('open', 'running')"),
    )
    op.create_table(
        "story",
        sa.Column("id", sa.Text(), primary_key=True),
        _campaign_fk(),
        sa.Column("beat_id", sa.Text(), sa.ForeignKey("beats.id", ondelete="CASCADE"), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
        sa.UniqueConstraint("campaign_id", "seq", name="uq_story_campaign_seq"),
    )
    op.create_table(
        "dm_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _campaign_fk(),
        sa.Column("beat_id", sa.Text(), sa.ForeignKey("beats.id", ondelete="CASCADE"), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
    )
    op.create_index("ix_dm_log_campaign_beat", "dm_log", ["campaign_id", "beat_id"])
    op.create_table(
        "dm_sessions",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("context_tokens", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "play_settings",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    for table in ("play_settings", "dm_sessions", "dm_log", "story", "beats"):
        op.drop_table(table)
