"""agent enabled + custom columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows are the built-in roster: enabled, not custom.
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )
        batch_op.add_column(
            sa.Column(
                "custom", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_column("custom")
        batch_op.drop_column("enabled")
