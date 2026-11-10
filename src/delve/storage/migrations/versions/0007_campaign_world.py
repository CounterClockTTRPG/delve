"""A campaign's ruleset and setting (spec §10). Campaigns made before it played AD&D 2e in Greyhawk implicitly, and
keep doing so.

Revision ID: 0007_campaign_world
Revises: 0006_module_source
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_campaign_world"
down_revision = "0006_module_source"
branch_labels = None
depends_on = None


# Plain ALTER TABLE, not a batch: a batch copies and drops `campaigns`, and with foreign keys on, dropping it would
# delete every row that cascades from a campaign.
def upgrade() -> None:
    op.add_column("campaigns", sa.Column("ruleset", sa.Text(), nullable=False, server_default="adnd2e"))
    op.add_column("campaigns", sa.Column("setting", sa.Text(), nullable=True))
    op.execute("UPDATE campaigns SET setting = 'greyhawk'")


def downgrade() -> None:
    op.execute("ALTER TABLE campaigns DROP COLUMN setting")
    op.execute("ALTER TABLE campaigns DROP COLUMN ruleset")
