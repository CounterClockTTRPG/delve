"""Translations (plan 4 Task 7, spec §7.7): a story entry's text in one language other than English, as far as it has
been translated, and whether it is still `translating`, `done` or `failed`. The entry itself stays English.

Revision ID: 0012_translations
Revises: 0011_story_audience
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_translations"
down_revision = "0011_story_audience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "translations",
        sa.Column("entry_id", sa.Text(), sa.ForeignKey("story.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("entry_id", "language"),
    )


def downgrade() -> None:
    op.drop_table("translations")
