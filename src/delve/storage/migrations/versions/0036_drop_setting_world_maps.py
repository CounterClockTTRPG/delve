"""Drop `setting_world_maps` (DEL-22): the plateau 7 pointer from a setting to a module's world map. Since settings
decision 8 a setting keeps maps of its own (`setting_maps`), and every start copied the pointers into them and deleted
them (`adopt_pointers`), so the table is empty on every install that started since. A downgrade makes it again,
empty.

Revision ID: 0036_drop_setting_world_maps
Revises: 0035_table_away
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0036_drop_setting_world_maps"
down_revision = "0035_table_away"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("setting_world_maps")


def downgrade() -> None:
    op.create_table(
        "setting_world_maps",
        sa.Column("setting", sa.Text(), primary_key=True),
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
