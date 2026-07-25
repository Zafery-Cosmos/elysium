"""mcp servers table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("catalog_id", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("url_or_command", sa.Text(), nullable=False),
        sa.Column("transport", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("mcp_servers", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_mcp_servers_catalog_id"), ["catalog_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_mcp_servers_catalog_id"))
    op.drop_table("mcp_servers")
