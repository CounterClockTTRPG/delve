"""Conversions (plan 5 Task 4): a row per job that makes a module from a PDF or a request, and `modules.draft`, which
keeps a module from starting a campaign until it is marked ready. Modules made before it are ready.

Revision ID: 0009_conversions
Revises: 0008_audience_gm
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_conversions"
down_revision = "0008_audience_gm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ALTER TABLE, not a batch: a batch copies and drops `modules`, and dropping it would cascade.
    op.add_column("modules", sa.Column("draft", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "conversions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "uq_conversions_one_running", "conversions", ["status"], unique=True, sqlite_where=sa.text("status = 'running'")
    )


def downgrade() -> None:
    op.drop_index("uq_conversions_one_running", table_name="conversions")
    op.drop_table("conversions")
    op.execute("ALTER TABLE modules DROP COLUMN draft")
