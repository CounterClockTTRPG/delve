"""The DM-only audience is stored as the format's `gm` (docs/data-dictionary.md). Plateau 3 stored DM-only texts,
sections and attachments as `dm`, and entity records as `gm`; now every stored audience is `gm` or `player`.

Downgrade leaves the values: the code before this migration read anything but `player` as DM-only.

Revision ID: 0008_audience_gm
Revises: 0007_campaign_world
Create Date: 2026-10-18
"""

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0008_audience_gm"
down_revision = "0007_campaign_world"
branch_labels = None
depends_on = None

# (table, key column, JSON column): the working text and source, and their copies in every revision.
COLUMNS = (
    ("module_texts", "module_id", "text"),
    ("module_sources", "module_id", "source"),
    ("module_revisions", "module_id || '/' || number", "text"),
    ("module_revisions", "module_id || '/' || number", "source"),
)


def _gm(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("gm" if k == "audience" and v == "dm" else _gm(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_gm(v) for v in value]
    return value


def upgrade() -> None:
    connection = op.get_bind()
    for table, key, column in COLUMNS:
        rows = connection.execute(sa.text(f"SELECT {key}, {column} FROM {table} WHERE {column} IS NOT NULL")).all()
        for row_key, raw in rows:
            fixed = json.dumps(_gm(json.loads(raw)))
            if fixed != raw:
                connection.execute(
                    sa.text(f"UPDATE {table} SET {column} = :raw WHERE {key} = :key"), {"raw": fixed, "key": row_key}
                )


def downgrade() -> None:
    pass
