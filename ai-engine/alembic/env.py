"""Alembic environment — targets SQLite (default) and PostgreSQL (ADR-001)."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, inspect, pool

from elysium_engine.config import default_data_dir, default_db_url
from elysium_engine.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return os.environ.get("ELYSIUM_DB_URL") or default_db_url(default_data_dir())


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for ALTER TABLE on SQLite
    )
    with context.begin_transaction():
        context.run_migrations()


def _adopt_bootstrapped_database(engine) -> bool:  # type: ignore[no-untyped-def]
    """A database created by ``init_db`` (create_all) has the tables but no
    ``alembic_version``: running 0001..N on it fails ("table already exists").
    Bring it to the current schema additively, then mark it as ``head``."""
    with engine.connect() as probe:
        tables = set(inspect(probe).get_table_names())
    if "alembic_version" in tables or "projects" not in tables:
        return False
    from alembic.script import ScriptDirectory

    from elysium_engine.db.migrate import upgrade_schema

    upgrade_schema(engine)
    script = ScriptDirectory.from_config(config)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.get_context().stamp(script, "head")
    return True


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    if _adopt_bootstrapped_database(engine):
        return
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
