"""The world (plan 6 Task 2): a campaign's start date, weather and world position; its factions, clocks, quests, own
lore facts, possessions, world maps, merchants and generated images. An existing campaign keeps its day; its start
date, weather and position stay empty until play first needs them.

Revision ID: 0013_world
Revises: 0012_translations
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_world"
down_revision = "0012_translations"
branch_labels = None
depends_on = None

TABLES = (
    "factions",
    "clocks",
    "quests",
    "campaign_facts",
    "possessions",
    "world_maps",
    "merchants",
    "campaign_images",
)


def _campaign() -> sa.Column:
    return sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    # Plain ALTER TABLE, not a batch: a batch copies and drops the table, and dropping it would cascade.
    for column in ("start_date", "weather", "world"):
        op.add_column("campaign_state", sa.Column(column, sa.JSON(), nullable=True))

    op.create_table(
        "factions",
        _campaign(),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("alignment", sa.Text(), nullable=False, server_default=""),
        sa.Column("goals", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("known", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("strength", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("reputation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("campaign_id", "id"),
    )
    op.create_table(
        "clocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _campaign(),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("faction_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("days_remaining", sa.Integer(), nullable=True),
        sa.Column("segments", sa.Integer(), nullable=True),
        sa.Column("filled", sa.Integer(), nullable=True),
        sa.Column("on_complete", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_day", sa.Integer(), nullable=False),
        sa.Column("done_day", sa.Integer(), nullable=True),
    )
    op.create_index("ix_clocks_campaign", "clocks", ["campaign_id"])
    op.create_table(
        "quests",
        _campaign(),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("giver", sa.Text(), nullable=False, server_default=""),
        sa.Column("scope", sa.Text(), nullable=False, server_default="local"),
        sa.Column("stakes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("known", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_day", sa.Integer(), nullable=True),
        sa.Column("ended_day", sa.Integer(), nullable=True),
        sa.Column("related", sa.JSON(), nullable=False),
        sa.Column("log", sa.JSON(), nullable=False),
        sa.Column("notes_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("campaign_id", "id"),
    )
    op.create_table(
        "campaign_facts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _campaign(),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
        sa.Column("day", sa.Integer(), nullable=False),
    )
    op.create_index("ix_campaign_facts_campaign", "campaign_facts", ["campaign_id"])
    op.create_table(
        "possessions",
        _campaign(),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("location", sa.Text(), nullable=False, server_default=""),
        sa.Column("value_gp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes_md", sa.Text(), nullable=False, server_default=""),
        sa.Column("inventory", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("portrait", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("campaign_id", "id"),
    )
    op.create_table(
        "world_maps",
        _campaign(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("dsl", sa.Text(), nullable=False),
        sa.Column("revealed", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("campaign_id", "name"),
    )
    op.create_table(
        "merchants",
        _campaign(),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("npc_id", sa.Text(), sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("settlement", sa.Text(), nullable=False),
        sa.Column("cost", sa.Text(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("rolled_day", sa.Integer(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("sold", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("campaign_id", "id"),
    )
    op.create_table(
        "campaign_images",
        sa.Column("id", sa.Text(), primary_key=True),
        _campaign(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("blob", sa.Text(), nullable=True),
        sa.Column("mime", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("backend", sa.Text(), nullable=False, server_default=""),
        sa.Column("audience", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_campaign_images_campaign", "campaign_images", ["campaign_id"])
    op.create_index("ix_campaign_images_status", "campaign_images", ["status"])


def downgrade() -> None:
    op.drop_index("ix_campaign_images_status", table_name="campaign_images")
    op.drop_index("ix_campaign_images_campaign", table_name="campaign_images")
    op.drop_index("ix_campaign_facts_campaign", table_name="campaign_facts")
    op.drop_index("ix_clocks_campaign", table_name="clocks")
    for table in reversed(TABLES):
        op.drop_table(table)
    for column in ("world", "weather", "start_date"):
        op.execute(f"ALTER TABLE campaign_state DROP COLUMN {column}")
