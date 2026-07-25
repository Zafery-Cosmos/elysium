"""mcp server config column

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Non-secret configuration values; secrets stay in the OS keychain.
    with op.batch_alter_table("mcp_servers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "config",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("mcp_servers", schema=None) as batch_op:
        batch_op.drop_column("config")
