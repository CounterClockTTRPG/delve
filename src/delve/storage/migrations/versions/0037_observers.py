"""Who may watch a table, and what a join request asks to be (DEL-215): `campaigns.observers` (`anyone` for every
table until its host says otherwise, as before) and `join_requests.role` (`player` for every request made before).

Revision ID: 0037_observers
Revises: 0036_drop_setting_world_maps
Create Date: 2026-10-27
"""

from alembic import op

revision = "0037_observers"
down_revision = "0036_drop_setting_world_maps"
branch_labels = None
depends_on = None

# Plain ALTER TABLE, as 0022 does: a batch would copy and drop `campaigns`, and the drop cascades into every table
# that names a campaign.


def upgrade() -> None:
    op.execute("ALTER TABLE campaigns ADD COLUMN observers TEXT NOT NULL DEFAULT 'anyone'")
    op.execute("ALTER TABLE join_requests ADD COLUMN role TEXT NOT NULL DEFAULT 'player'")


def downgrade() -> None:
    op.execute("ALTER TABLE join_requests DROP COLUMN role")
    op.execute("ALTER TABLE campaigns DROP COLUMN observers")
