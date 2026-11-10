"""Story audiences (plan 4 Task 3, spec §7.5): who at the table may see a story entry. Null is everyone; otherwise
`{"characters": [ids]}` or `{"seats": [ids]}` (`delve.play.audience`). An Ask the DM made before it was the owner's
alone: its `ask` and `answer` entries are for the owner's seat.

Revision ID: 0011_story_audience
Revises: 0010_seats
Create Date: 2026-10-18
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0011_story_audience"
down_revision = "0010_seats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE story ADD COLUMN audience JSON")
    connection = op.get_bind()
    owners = connection.execute(sa.text("SELECT campaign_id, id FROM seats WHERE owner = 1")).all()
    for campaign_id, seat_id in owners:
        connection.execute(
            sa.text("UPDATE story SET audience = :audience WHERE campaign_id = :campaign AND kind IN ('ask', 'answer')"),
            {"audience": json.dumps({"seats": [seat_id]}), "campaign": campaign_id},
        )


def downgrade() -> None:
    op.execute("ALTER TABLE story DROP COLUMN audience")
