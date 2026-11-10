"""The kinds of monsters' pictures, for every campaign (DEL-275): `monster_pictures`, by the kind's slug. A new table,
referenced by none.

Revision ID: 0041_monster_pictures
Revises: 0039_password_help
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0041_monster_pictures"
down_revision = "0039_password_help"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monster_pictures",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("blob", sa.Text()),
        sa.Column("mime", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("monster_pictures")
