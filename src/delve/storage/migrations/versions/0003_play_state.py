"""Play state: character sheets and state, the campaign state, the dice log, events, sessions, notes, combats and
house rules.

Revision ID: 0003_play_state
Revises: 0002_modules_campaigns
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_play_state"
down_revision = "0002_modules_campaigns"
branch_labels = None
depends_on = None


def _campaign_fk() -> sa.Column:
    return sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch:
        batch.add_column(sa.Column("kind", sa.Text(), nullable=False, server_default="pc"))
        batch.add_column(sa.Column("sheet", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("state", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("order", sa.Integer(), nullable=True))
    # The characters of plateau 1 are PCs; their marching order is the order they were made in.
    op.execute(
        'UPDATE characters SET "order" = (SELECT COUNT(*) FROM characters AS earlier'
        " WHERE earlier.campaign_id = characters.campaign_id AND earlier.rowid < characters.rowid)"
    )

    op.create_table(
        "campaign_state",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("session", sa.Integer(), nullable=False),
        sa.Column("coin", sa.JSON(), nullable=False),
        sa.Column("loot", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "rolls",
        sa.Column("id", sa.Text(), primary_key=True),
        _campaign_fk(),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("beat", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("combat_round", sa.Integer(), nullable=True),
        sa.Column("notation", sa.Text(), nullable=False),
        sa.Column("faces", sa.JSON(), nullable=False),
        sa.Column("kept", sa.JSON(), nullable=False),
        sa.Column("modifier", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
        sa.UniqueConstraint("campaign_id", "key", name="uq_rolls_campaign_key"),
    )
    op.create_index("ix_rolls_campaign_beat", "rolls", ["campaign_id", "beat"])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _campaign_fk(),
        sa.Column("session", sa.Integer(), nullable=False),
        sa.Column("beat", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("at", sa.Text(), nullable=False),
    )
    op.create_index("ix_events_campaign_id", "events", ["campaign_id", "id"])
    op.create_table(
        "sessions",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("ended_at", sa.Text(), nullable=True),
        sa.Column("recap_md", sa.Text(), nullable=True),
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.Text(), primary_key=True),
        _campaign_fk(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("related_to", sa.Text(), nullable=False, server_default=""),
        sa.Column("revealed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("map_name", sa.Text(), nullable=True),
        sa.Column("node", sa.Text(), nullable=True),
        sa.Column("session", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_notes_campaign_kind", "notes", ["campaign_id", "kind"])
    op.create_table(
        "combats",
        sa.Column("id", sa.Text(), primary_key=True),
        _campaign_fk(),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "uq_combats_one_live", "combats", ["campaign_id"], unique=True, sqlite_where=sa.text("phase != 'ended'")
    )
    op.create_table(
        "house_rules",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("phases", sa.JSON(), nullable=False),
        sa.Column("ruleset", sa.Text(), nullable=True),
        sa.Column("setting", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_house_rules_kind_subject_title", "house_rules", ["kind", "subject", "title"])
    op.create_table(
        "house_rules_bundles",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "house_rules_bundle_rules",
        sa.Column(
            "bundle_id", sa.Text(), sa.ForeignKey("house_rules_bundles.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("rule_id", sa.Text(), sa.ForeignKey("house_rules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "house_rules_campaign_bundles",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "bundle_id", sa.Text(), sa.ForeignKey("house_rules_bundles.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.create_table(
        "house_rules_campaign_rules",
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("rule_id", sa.Text(), sa.ForeignKey("house_rules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "house_rules_campaign_rules",
        "house_rules_campaign_bundles",
        "house_rules_bundle_rules",
        "house_rules_bundles",
        "house_rules",
        "combats",
        "notes",
        "sessions",
        "events",
        "rolls",
        "campaign_state",
    ):
        op.drop_table(table)
    with op.batch_alter_table("characters") as batch:
        for column in ("order", "state", "sheet", "kind"):
            batch.drop_column(column)
