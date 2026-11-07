"""accounting: idempotent usage rows, cache tokens, EUR + fx history, quota readings

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USAGE_COLUMNS = (
    sa.Column("request_id", sa.String(length=40), nullable=True),
    sa.Column("billing", sa.String(length=12), nullable=False, server_default="api"),
    sa.Column("cost_kind", sa.String(length=10), nullable=False, server_default="none"),
    sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("cost_eur", sa.Float(), nullable=True),
    sa.Column("fx_rate", sa.Float(), nullable=True),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    # ``init_db`` may already have added everything (additive upgrade at startup).
    if "usage" in tables:
        have = {c["name"] for c in inspector.get_columns("usage")}
        with op.batch_alter_table("usage", schema=None) as batch:
            for column in _USAGE_COLUMNS:
                if column.name not in have:
                    batch.add_column(column)
        indexes = {i["name"] for i in inspector.get_indexes("usage")}
        if "ix_usage_request_id" not in indexes:
            op.create_index("ix_usage_request_id", "usage", ["request_id"], unique=True)
    if "fx_rates" not in tables:
        op.create_table(
            "fx_rates",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("base", sa.String(length=3), nullable=False),
            sa.Column("quote", sa.String(length=3), nullable=False),
            sa.Column("rate", sa.Float(), nullable=False),
            sa.Column("source", sa.String(length=60), nullable=False),
            sa.Column("as_of", sa.String(length=10), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_fx_rates_created_at", "fx_rates", ["created_at"])
    if "quota_readings" not in tables:
        op.create_table(
            "quota_readings",
            sa.Column("provider", sa.String(length=100), nullable=False),
            sa.Column("window", sa.String(length=40), nullable=False),
            sa.Column("utilization", sa.Float(), nullable=False),
            sa.Column("resets_at", sa.Float(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
            sa.Column("observed_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("provider", "window"),
        )


def downgrade() -> None:
    op.drop_table("quota_readings")
    op.drop_index("ix_fx_rates_created_at", table_name="fx_rates")
    op.drop_table("fx_rates")
    op.drop_index("ix_usage_request_id", table_name="usage")
    with op.batch_alter_table("usage", schema=None) as batch:
        for column in _USAGE_COLUMNS:
            batch.drop_column(column.name)
