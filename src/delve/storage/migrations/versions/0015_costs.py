"""Costs (faithful modules Task 26, G2): what a conversion's Claude calls cost, summed as it goes. An existing job's
cost is unknown (null).

Revision ID: 0015_costs
Revises: 0014_maps
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_costs"
down_revision = "0014_maps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ALTER TABLE, not a batch, as in 0014: a batch copies and drops the table.
    op.add_column("conversions", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.execute("ALTER TABLE conversions DROP COLUMN cost_usd")
