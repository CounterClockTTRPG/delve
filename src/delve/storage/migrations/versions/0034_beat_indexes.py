"""Indexes on `story.beat_id` and `dm_log.beat_id` (DEL-164): deleting a beat, as deleting or restoring a campaign
deletes every beat, cascades into both tables, and without an index each beat scanned them whole while holding the
write lock (4.16 s for a campaign; 0.81 s with these). dm_log's `(campaign_id, beat_id)` serves no lookup by
`beat_id` alone.

Revision ID: 0034_beat_indexes
Revises: 0033_owner_seat_name
Create Date: 2026-10-27
"""

from alembic import op

revision = "0034_beat_indexes"
down_revision = "0033_owner_seat_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_story_beat", "story", ["beat_id"])
    op.create_index("ix_dm_log_beat", "dm_log", ["beat_id"])


def downgrade() -> None:
    op.drop_index("ix_dm_log_beat", table_name="dm_log")
    op.drop_index("ix_story_beat", table_name="story")
