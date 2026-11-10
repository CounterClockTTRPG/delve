"""Seats (plan 4 Task 1): the people at a campaign's table, with their role, a campaign's join token, and the seat
that plays each character. A campaign made before it was the owner's alone: it gets the owner's seat ("Host", `en`,
the host, no token), which plays its PCs, and a join token.

Revision ID: 0010_seats
Revises: 0009_conversions
Create Date: 2026-10-18
"""

import secrets
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0010_seats"
down_revision = "0009_conversions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seats",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("campaign_id", sa.Text(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("organiser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_hash", sa.Text(), nullable=True, unique=True),
        sa.Column("joined_at", sa.Text(), nullable=False),
        sa.Column("left_at", sa.Text(), nullable=True),
    )
    op.create_index("ix_seats_campaign", "seats", ["campaign_id"])
    op.create_index("uq_seats_one_owner", "seats", ["campaign_id"], unique=True, sqlite_where=sa.text("owner = 1"))
    # Plain ALTER TABLE, not a batch: a batch copies and drops the table, and dropping it would cascade.
    op.add_column("campaigns", sa.Column("join_token", sa.Text(), nullable=True))
    op.execute("ALTER TABLE characters ADD COLUMN controller_id TEXT REFERENCES seats(id) ON DELETE SET NULL")

    connection = op.get_bind()
    now = datetime.now(UTC).isoformat()
    for (campaign_id,) in connection.execute(sa.text("SELECT id FROM campaigns ORDER BY rowid")).all():
        seat_id = f"seat_{secrets.token_hex(6)}"
        connection.execute(
            sa.text(
                "INSERT INTO seats (id, campaign_id, name, language, role, organiser, owner, joined_at) "
                "VALUES (:id, :campaign_id, 'Host', 'en', 'host', 1, 1, :now)"
            ),
            {"id": seat_id, "campaign_id": campaign_id, "now": now},
        )
        connection.execute(
            sa.text("UPDATE campaigns SET join_token = :token WHERE id = :id"),
            {"token": secrets.token_urlsafe(24), "id": campaign_id},
        )
        connection.execute(
            sa.text("UPDATE characters SET controller_id = :seat WHERE campaign_id = :id AND kind = 'pc'"),
            {"seat": seat_id, "id": campaign_id},
        )
    op.create_index("uq_campaigns_join_token", "campaigns", ["join_token"], unique=True)


def downgrade() -> None:
    op.execute("ALTER TABLE characters DROP COLUMN controller_id")
    op.drop_index("uq_campaigns_join_token", table_name="campaigns")
    op.execute("ALTER TABLE campaigns DROP COLUMN join_token")
    op.drop_index("uq_seats_one_owner", table_name="seats")
    op.drop_index("ix_seats_campaign", table_name="seats")
    op.drop_table("seats")
