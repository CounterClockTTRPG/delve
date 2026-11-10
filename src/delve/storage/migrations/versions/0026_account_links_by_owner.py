"""Account links keep whether an owner made them (DEL-150): `account_links.by_owner`, 0 for the links already made,
so an unused one for an owner's or an organiser's account stops working (an owner makes a new one).

Revision ID: 0026_account_links_by_owner
Revises: 0025_module_categories_banners
Create Date: 2026-10-26
"""

from alembic import op

revision = "0026_account_links_by_owner"
down_revision = "0025_module_categories_banners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE account_links ADD COLUMN by_owner BOOLEAN NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE account_links DROP COLUMN by_owner")
