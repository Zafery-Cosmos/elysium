"""Engine and session factory construction."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.models import Base


def create_db_engine(db_url: str) -> Engine:
    connect_args: dict[str, object] = {}
    if db_url.startswith("sqlite"):
        # The engine serves async endpoints and background agent tasks from
        # multiple threads; SQLite's default same-thread check must be off.
        connect_args["check_same_thread"] = False
    return create_engine(db_url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Bootstrap the schema on a fresh database.

    Alembic (``ai-engine/alembic``) is the source of truth for upgrades on
    existing installs; ``create_all`` is idempotent and only creates missing
    tables, which keeps first-run zero-setup on SQLite.
    """
    Base.metadata.create_all(engine)
