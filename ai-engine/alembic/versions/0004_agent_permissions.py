"""agent permission profile columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Least-privilege permission profile per agent (AI_SYSTEM.md §1). Server
    # defaults backfill existing rows to the most restrictive profile.
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "filesystem",
                sa.String(length=20),
                nullable=False,
                server_default="none",
            )
        )
        batch_op.add_column(
            sa.Column(
                "shell", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(
            sa.Column(
                "network", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_column("network")
        batch_op.drop_column("shell")
        batch_op.drop_column("filesystem")
