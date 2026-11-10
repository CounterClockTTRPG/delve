"""Maps (plan 7 Task 1): a world map's GeoJSON document, base picture, status, what the party knows of it and the
reading of its picture; the party's journey; a campaign's status; a conversion's target, result and questions; a
translated answer; the pictures' tiles; and which module's map is a setting's on this install. An existing world map
is `ready` with no `geo`, converted from its `dsl` on first read; an existing campaign is `in_progress`.

Revision ID: 0014_maps
Revises: 0013_world
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_maps"
down_revision = "0013_world"
branch_labels = None
depends_on = None


def _columns() -> dict[str, tuple[sa.Column, ...]]:
    """The new columns by table, made afresh on each call: a column joins the one table it is added to."""
    return {
        "world_maps": (
            sa.Column("geo", sa.JSON(), nullable=True),
            sa.Column("picture", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="ready"),
            sa.Column("knowledge", sa.JSON(), nullable=True),
            sa.Column("reading", sa.JSON(), nullable=True),
        ),
        "campaign_state": (sa.Column("journey", sa.JSON(), nullable=True),),
        "campaigns": (sa.Column("status", sa.Text(), nullable=False, server_default="in_progress"),),
        "conversions": (
            sa.Column("target", sa.JSON(), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("questions", sa.JSON(), nullable=True),
        ),
        "translations": (sa.Column("answer", sa.Text(), nullable=True),),
    }


def upgrade() -> None:
    # Plain ALTER TABLE, not a batch: a batch copies and drops the table, and dropping it would cascade.
    for table, columns in _columns().items():
        for column in columns:
            op.add_column(table, column)

    op.create_table(
        "world_pictures",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("max_zoom", sa.Integer(), nullable=False),
        sa.Column("tiles", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "setting_world_maps",
        sa.Column("setting", sa.Text(), primary_key=True),
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("setting_world_maps")
    op.drop_table("world_pictures")
    for table, columns in reversed(_columns().items()):
        for column in reversed(columns):
            op.execute(f"ALTER TABLE {table} DROP COLUMN {column.name}")
