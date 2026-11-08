"""file_changes: edits proposed by agents, written only once a human accepts them

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # upgrade_schema may already have created it at engine start.
    if sa.inspect(op.get_bind()).has_table("file_changes"):
        return
    op.create_table(
        "file_changes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=True),
        sa.Column("task_id", sa.String(32), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("base_content", sa.Text(), nullable=True),
        sa.Column("base_sha256", sa.String(64), nullable=True),
        sa.Column("new_content", sa.Text(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_file_changes_project_status", "file_changes", ["project_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_file_changes_project_status", table_name="file_changes")
    op.drop_table("file_changes")
