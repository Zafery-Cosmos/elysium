"""task graph reshape (ADR-005)

Replaces the early ``tasks`` stub (parent_id / assigned_agent_id) with the real
task-graph shape: conversation link, owning agent_role, Kanban status +
order_index, JSON dependency edges and a result_summary. The stub was never
written to (no repository writers, no API), so this rebuilds the table.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("tasks")
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("agent_role", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tasks_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_tasks_conversation_id"), ["conversation_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tasks_conversation_id"))
        batch_op.drop_index(batch_op.f("ix_tasks_project_id"))
    op.drop_table("tasks")
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("parent_id", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_agent_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tasks_project_id"), ["project_id"], unique=False
        )
