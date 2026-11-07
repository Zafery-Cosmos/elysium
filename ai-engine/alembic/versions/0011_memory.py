"""project memory: remembered items, scanned folder, file graph

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())  # init_db may have made them
    if "memory_items" not in tables:
        op.create_table(
            "memory_items",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("project_id", sa.String(length=32), nullable=False),
            sa.Column("tier", sa.String(length=8), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source", sa.String(length=10), nullable=False),
            sa.Column("source_ref", sa.String(length=80), nullable=True),
            sa.Column("pinned", sa.Boolean(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_memory_items_project_id", "memory_items", ["project_id"])
        op.create_index("ix_memory_items_project_tier", "memory_items", ["project_id", "tier"])
        op.create_index("ix_memory_items_source_ref", "memory_items", ["project_id", "source_ref"], unique=True)
    if "memory_folders" not in tables:
        op.create_table(
            "memory_folders",
            sa.Column("project_id", sa.String(length=32), nullable=False),
            sa.Column("root_path", sa.Text(), nullable=False),
            sa.Column("last_scan_at", sa.DateTime(), nullable=True),
            sa.Column("last_scan", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("project_id"),
        )
    if "memory_files" not in tables:
        op.create_table(
            "memory_files",
            sa.Column("project_id", sa.String(length=32), nullable=False),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("language", sa.String(length=30), nullable=True),
            sa.Column("size", sa.Integer(), nullable=False),
            sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
            sa.Column("sha1", sa.String(length=40), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("symbols", sa.JSON(), nullable=False),
            sa.Column("imports", sa.JSON(), nullable=False),
            sa.Column("external", sa.JSON(), nullable=False),
            sa.Column("scanned_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("project_id", "path"),
        )


def downgrade() -> None:
    op.drop_table("memory_files")
    op.drop_table("memory_folders")
    op.drop_table("memory_items")
