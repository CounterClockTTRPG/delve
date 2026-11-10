"""Module text: the working copy's text, keys and entities, their snapshot in each revision, and a full-text index of
each revision's sections.

Revision ID: 0004_module_text
Revises: 0003_play_state
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_module_text"
down_revision = "0003_play_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_texts",
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("text", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    with op.batch_alter_table("module_revisions") as batch:
        batch.add_column(sa.Column("text", sa.JSON(), nullable=True))
    # One row per paragraph of a revision's sections (ttrpg2 `module_ref`'s chunks). A virtual table has no foreign
    # keys: deleting a module deletes its rows.
    op.execute(
        "CREATE VIRTUAL TABLE module_text_index USING fts5("
        "module_id UNINDEXED, revision UNINDEXED, anchor UNINDEXED, position UNINDEXED, heading_path, body)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE module_text_index")
    with op.batch_alter_table("module_revisions") as batch:
        batch.drop_column("text")
    op.drop_table("module_texts")
