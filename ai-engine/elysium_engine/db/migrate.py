"""Additive schema upgrade for existing databases, applied at every start.

``create_all`` only creates *missing tables*: a database made by an older
Elysium would never receive a column added later, and every INSERT touching it
would fail.  :func:`upgrade_schema` closes that gap for the changes Elysium makes
(new tables, new nullable / defaulted columns, new indexes).  It never drops,
renames or rewrites anything, so a failed or interrupted run loses no data and
can simply be run again.  Alembic (``ai-engine/alembic``) remains the tool for
PostgreSQL deployments and for any non-additive change.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Boolean, Column, Engine, inspect, text
from sqlalchemy.schema import CreateIndex

from elysium_engine.db.models import Base

log = logging.getLogger(__name__)


def _for_dialect(default: str | None, column: Column[Any], dialect_name: str) -> str | None:
    """PostgreSQL refuses an integer default on a BOOLEAN column."""
    if dialect_name == "postgresql" and isinstance(column.type, Boolean) and default in ("0", "1"):
        return "TRUE" if default == "1" else "FALSE"
    return default


def _default_sql(column: Column[Any]) -> str | None:
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg  # type: ignore[union-attr]
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def upgrade_schema(engine: Engine) -> list[str]:
    """Create missing tables/columns/indexes; returns a log of what was added."""
    Base.metadata.create_all(engine)
    changes: list[str] = []
    inspector = inspect(engine)
    dialect = engine.dialect
    for table in Base.metadata.sorted_tables:
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(dialect)}'
            default = _for_dialect(_default_sql(column), column, dialect.name)
            if default is not None:
                ddl += f" DEFAULT {default}"
            # NOT NULL is only safe with a default; otherwise add it nullable.
            if not column.nullable and default is not None:
                ddl += " NOT NULL"
            with engine.begin() as conn:
                conn.execute(text(ddl))
            changes.append(f"{table.name}.{column.name}")
            log.info("schema upgrade: added column %s.%s", table.name, column.name)
        present = {i["name"] for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in present:
                continue
            try:
                with engine.begin() as conn:
                    conn.execute(CreateIndex(index))
                changes.append(f"index {index.name}")
            except Exception:  # an index is an optimisation: never block startup
                log.exception("could not create index %s", index.name)
    return changes
