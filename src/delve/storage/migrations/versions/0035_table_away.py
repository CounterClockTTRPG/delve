"""The seats away mid-session (DEL-224): `table_sessions.away`, by seat id, `{"at", "part"}`, empty for every table
until a seat steps away or the host marks one away.

Revision ID: 0035_table_away
Revises: 0034_beat_indexes
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_table_away"
down_revision = "0034_beat_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("table_sessions") as batch:
        batch.add_column(sa.Column("away", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("table_sessions") as batch:
        batch.drop_column("away")
