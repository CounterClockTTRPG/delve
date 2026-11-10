"""Settings: one JSON value per key.

Revision ID: 0001_settings
Revises:
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_settings"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("settings")
