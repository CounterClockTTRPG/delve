"""The message board (DEL-297): `board_zones`, `board_topics`, `board_posts`, `board_reads` and `board_visits`. New
tables only. A zone's campaign is set null when the campaign goes; topics, posts and read marks follow their zone and
topic. No keys to accounts: an author's id may outlive the account.

Revision ID: 0042_board
Revises: 0041_monster_pictures
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0042_board"
down_revision = "0041_monster_pictures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "board_zones",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("read", sa.Text(), nullable=False),
        sa.Column("write", sa.Text(), nullable=False),
        sa.Column("pictures", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="SET NULL")),
        sa.Column("moderators", sa.JSON(), nullable=False),
        sa.Column("members", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("uq_board_zones_campaign", "board_zones", ["campaign_id"], unique=True)
    op.create_table(
        "board_topics",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("zone_id", sa.Text(), sa.ForeignKey("board_zones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("last_post_at", sa.Text(), nullable=False),
        sa.Column("last_author_id", sa.Text()),
        sa.Column("posts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_board_topics_zone", "board_topics", ["zone_id"])
    op.create_table(
        "board_posts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("topic_id", sa.Text(), sa.ForeignKey("board_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Text()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("edited_at", sa.Text()),
        sa.Column("removed", sa.Text()),
        sa.Column("picture", sa.JSON()),
    )
    op.create_index("ix_board_posts_topic", "board_posts", ["topic_id"])
    op.create_table(
        "board_reads",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("topic_id", sa.Text(), sa.ForeignKey("board_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("account_id", "topic_id"),
    )
    op.create_table(
        "board_visits",
        sa.Column("account_id", sa.Text(), primary_key=True),
        sa.Column("first_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("board_visits")
    op.drop_table("board_reads")
    op.drop_table("board_posts")
    op.drop_table("board_topics")
    op.drop_table("board_zones")
