"""Engine and session factory construction."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.models import Base


def create_db_engine(db_url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if db_url.startswith("sqlite"):
        # The engine serves async endpoints and background agent tasks from
        # multiple threads; SQLite's default same-thread check must be off.
        connect_args["check_same_thread"] = False
    engine = create_engine(db_url, connect_args=connect_args)
    if db_url.startswith("sqlite"):
        # SQLite ignores declared foreign keys unless each connection asks for them.
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Bootstrap the schema on a fresh database.

    ``upgrade_schema`` is idempotent: it creates missing tables and adds the
    columns / indexes that newer versions introduced, so an existing database
    keeps working (and keeps its data) after an update.  Alembic remains the
    tool for PostgreSQL deployments and non-additive changes.
    """
    from elysium_engine.db.migrate import upgrade_schema

    upgrade_schema(engine)
