"""A campaign's portrait style as in Preferences (DEL-252): portraitgen's style is now chosen in Preferences, for PCs
and for NPCs, and a campaign's `portrait_style` of null follows it. A campaign stored every play setting whenever one
changed, so its `illustrated`, the old default, says nothing about a choice: it becomes null. Another style was
chosen, and stays.

Revision ID: 0038_portrait_style_as_preferences
Revises: 0037_observers
Create Date: 2026-10-28
"""

from alembic import op

revision = "0038_portrait_style_as_preferences"
down_revision = "0037_observers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE play_settings SET raw = json_set(raw, '$.portrait_style', json('null')) "
        "WHERE json_extract(raw, '$.portrait_style') = 'illustrated'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE play_settings SET raw = json_set(raw, '$.portrait_style', 'illustrated') "
        "WHERE json_type(raw, '$.portrait_style') IN ('null') OR json_type(raw, '$.portrait_style') IS NULL"
    )
