"""per-call usage log (admin dashboard)

One row per model call: provider, model, agent, tokens, API-equivalent cost,
duration and status. No foreign keys on purpose — usage history outlives the
conversations and projects it came from.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``init_db`` may already have created the table on SQLite (create_all).
    if "usage" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "usage",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("agent_name", sa.String(length=100), nullable=True),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("usage", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_usage_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_usage_provider"), ["provider"], unique=False)
        batch_op.create_index(batch_op.f("ix_usage_project_id"), ["project_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("usage", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_usage_project_id"))
        batch_op.drop_index(batch_op.f("ix_usage_provider"))
        batch_op.drop_index(batch_op.f("ix_usage_created_at"))
    op.drop_table("usage")
