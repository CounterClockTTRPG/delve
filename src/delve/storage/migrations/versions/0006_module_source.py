"""The module source: the working copy's texts, entities, keys and attachments, and the copy each revision pins.

Revision ID: 0006_module_source
Revises: 0005_beats_story
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_module_source"
down_revision = "0005_beats_story"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_sources",
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    with op.batch_alter_table("module_revisions") as batch:
        batch.add_column(sa.Column("source", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("module_revisions") as batch:
        batch.drop_column("source")
    op.drop_table("module_sources")
