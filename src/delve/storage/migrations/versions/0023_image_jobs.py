"""A painting's job at its provider (DEL-138): `provider_job`, the id of assetgen's job, which the next start follows
rather than sending a copy, and `queue`, the painting's place in the provider's queue while it waits there.

Plain `ALTER TABLE … ADD COLUMN`s, both NULL for an existing row: a batch would copy and drop the table.

Revision ID: 0023_image_jobs
Revises: 0022_table_voice_and_fixes
Create Date: 2026-10-26
"""

from alembic import op

revision = "0023_image_jobs"
down_revision = "0022_table_voice_and_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE campaign_images ADD COLUMN provider_job TEXT")
    op.execute("ALTER TABLE campaign_images ADD COLUMN queue INTEGER")


def downgrade() -> None:
    for column in ("queue", "provider_job"):
        op.execute(f"ALTER TABLE campaign_images DROP COLUMN {column}")
