"""A player's request for a new password (DEL-268): `accounts.reset_asked_at`, when they asked from the login page,
until a reset link is made or the request is dismissed. A plain ALTER TABLE: accounts are referenced by seats.

Revision ID: 0039_password_help
Revises: 0038_portrait_style_as_preferences
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0039_password_help"
down_revision = "0038_portrait_style_as_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("reset_asked_at", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "reset_asked_at")
