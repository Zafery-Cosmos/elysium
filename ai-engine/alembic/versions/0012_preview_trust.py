"""preview: trust bound to one manifest, framework override kept apart

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = {
    "framework_override": sa.String(30),
    "trust_digest": sa.String(64),
}


def upgrade() -> None:
    # upgrade_schema may already have added them at engine start.
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("preview_sessions")}
    for name, column_type in _COLUMNS.items():
        if name not in existing:
            op.add_column("preview_sessions", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in _COLUMNS:
        op.drop_column("preview_sessions", name)
