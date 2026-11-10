"""Voice at the table, the initiative timeline and module fix-ups (table voice and fixes Task 0): a campaign's voice
setting and initiative mode, a character's departure from the party, a conversion's comments and the questions closed
on it, the fight's rounds as the timeline shows them (`combat_rounds`), and the fix-it comments on a module
(`module_comments`).

Every column is a plain `ALTER TABLE … ADD COLUMN` with a default that keeps an existing row working as before (voice
allowed, initiative per combatant, in the party, no comments, nothing closed): a batch would copy and drop the table,
and the drop would cascade.

Revision ID: 0022_table_voice_and_fixes
Revises: 0021_login_sessions
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_table_voice_and_fixes"
down_revision = "0021_login_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE campaigns ADD COLUMN voice TEXT NOT NULL DEFAULT 'allowed'")
    op.execute("ALTER TABLE campaigns ADD COLUMN initiative TEXT NOT NULL DEFAULT 'combatant'")
    op.execute("ALTER TABLE characters ADD COLUMN departure TEXT")
    op.execute("ALTER TABLE characters ADD COLUMN departed_at TEXT")
    op.execute("ALTER TABLE conversions ADD COLUMN comments TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE conversions ADD COLUMN closed JSON")
    op.create_table(
        "combat_rounds",
        sa.Column("combat_id", sa.Text(), sa.ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("beat_id", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=True),
        sa.Column("rolled_at", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.Text(), nullable=True),
        sa.Column("released_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("combat_id", "round"),
    )
    op.create_index("ix_combat_rounds_campaign", "combat_rounds", ["campaign_id", "combat_id"])
    op.create_table(
        "module_comments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("module_id", sa.Text(), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("anchor", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("conversion_id", sa.Text(), sa.ForeignKey("conversions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_module_comments_module_status", "module_comments", ["module_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_module_comments_module_status", table_name="module_comments")
    op.drop_table("module_comments")
    op.drop_index("ix_combat_rounds_campaign", table_name="combat_rounds")
    op.drop_table("combat_rounds")
    for table, column in (
        ("conversions", "closed"),
        ("conversions", "comments"),
        ("characters", "departed_at"),
        ("characters", "departure"),
        ("campaigns", "initiative"),
        ("campaigns", "voice"),
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
