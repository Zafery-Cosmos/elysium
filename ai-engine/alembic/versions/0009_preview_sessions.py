"""live preview sessions

One row per project: chosen folder, detected framework, trust decision and the
last known server state (port, url, pid). Reconciled at every engine start.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``init_db`` may already have created the table on SQLite (create_all).
    if "preview_sessions" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "preview_sessions",
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("subdir", sa.String(length=300), nullable=True),
        sa.Column("framework", sa.String(length=30), nullable=True),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=100), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
    )


def downgrade() -> None:
    op.drop_table("preview_sessions")
