"""Optional PostgreSQL database chosen from the app.

The connection URL holds a password, so it lives in the OS keychain. A server
that cannot be reached at startup must not lock the user out of the app: the
engine then opens the local SQLite database and reports why.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Engine, Integer, create_engine, func, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from elysium_engine.config import Settings, default_db_url
from elysium_engine.db.models import Base
from elysium_engine.db.session import init_db
from elysium_engine.secrets import SecretStore

log = logging.getLogger(__name__)

SECRET_NAME = "database:url"
_DRIVERS = ("postgres", "postgresql", "postgresql+psycopg")
_CONNECT_TIMEOUT_S = 5
_BATCH = 500


class DatabaseConfigError(ValueError):
    """The URL is invalid, the server unreachable, or the target not usable."""


def normalize_url(raw: str) -> str:
    """A valid PostgreSQL URL using the driver Elysium ships, or an error."""
    try:
        url = make_url(raw.strip())
    except ArgumentError as exc:
        raise DatabaseConfigError("This is not a valid database URL.") from exc
    if url.drivername not in _DRIVERS:
        raise DatabaseConfigError("Only postgresql:// URLs are supported.")
    if not url.host or not url.database:
        raise DatabaseConfigError("The URL must name a host and a database.")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def describe(url_text: str) -> str:
    """Where the data lives, safe to display: never the password."""
    url: URL = make_url(url_text)
    if url.get_backend_name() == "sqlite":
        return url.database or ""
    port = f":{url.port}" if url.port else ""
    return f"{url.username or ''}@{url.host}{port}/{url.database}"


def _connect(url: str) -> Engine:
    return create_engine(url, connect_args={"connect_timeout": _CONNECT_TIMEOUT_S})


def _explain(exc: Exception) -> str:
    # Driver messages can quote connection details; keep only their first line,
    # with the password of the URL never part of what is shown.
    original = getattr(exc, "orig", None) or exc
    return str(original).strip().splitlines()[0][:300] if str(original).strip() else type(exc).__name__


def check_connection(url: str) -> str:
    """The server's version, or :class:`DatabaseConfigError` saying why not."""
    try:
        engine = _connect(url)
    except ModuleNotFoundError as exc:
        raise DatabaseConfigError("The PostgreSQL driver is not installed.") from exc
    try:
        with engine.connect() as connection:
            return str(connection.execute(text("SHOW server_version")).scalar())
    except SQLAlchemyError as exc:
        raise DatabaseConfigError(f"Connection failed: {_explain(exc)}") from exc
    finally:
        engine.dispose()


def resolve_db_url(settings: Settings, store: SecretStore) -> tuple[str, str | None]:
    """(URL to open, why the configured server was not used).

    An explicit ``ELYSIUM_DB_URL`` always wins over the app's own setting.
    """
    if settings.db_url != default_db_url(settings.data_dir):
        return settings.db_url, None
    stored = store.get(SECRET_NAME)
    if not stored:
        return settings.db_url, None
    try:
        check_connection(stored)
    except DatabaseConfigError as exc:
        log.warning("configured PostgreSQL unavailable, using SQLite: %s", exc)
        return settings.db_url, str(exc)
    return stored, None


def _is_empty(engine: Engine) -> bool:
    with engine.connect() as connection:
        return not any(
            connection.execute(select(func.count()).select_from(table)).scalar()
            for table in Base.metadata.sorted_tables
        )


def prepare(url: str, source: Engine | None) -> int:
    """Create the schema on the target, then copy ``source`` into it when asked.

    A target that already holds data is never written to: merging two histories
    could only corrupt one of them. Returns the number of rows copied.
    """
    target = _connect(url)
    try:
        init_db(target)
        if source is None:
            return 0
        if not _is_empty(target):
            raise DatabaseConfigError("This database already holds data: nothing was copied.")
        return _copy(source, target)
    except SQLAlchemyError as exc:
        raise DatabaseConfigError(f"The database could not be prepared: {_explain(exc)}") from exc
    finally:
        target.dispose()


def _copy(source: Engine, target: Engine) -> int:
    copied = 0
    existing = set(inspect(source).get_table_names())
    with source.connect() as reader, target.begin() as writer:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                continue
            batch: list[dict[str, Any]] = []
            for row in reader.execute(select(table)).mappings():
                batch.append(dict(row))
                if len(batch) >= _BATCH:
                    writer.execute(table.insert(), batch)
                    copied += len(batch)
                    batch = []
            if batch:
                writer.execute(table.insert(), batch)
                copied += len(batch)
            _advance_sequence(writer, table)
    return copied


def _advance_sequence(connection: Any, table: Any) -> None:
    """Rows were inserted with their ids: the next automatic id must follow them."""
    keys = list(table.primary_key.columns)
    if len(keys) != 1 or not isinstance(keys[0].type, Integer):
        return
    name = keys[0].name
    sequence = connection.execute(
        select(func.pg_get_serial_sequence(table.name, name))
    ).scalar()
    if sequence is None:  # a fixed-id table, such as the settings row
        return
    highest = connection.execute(select(func.max(keys[0]))).scalar()
    if highest is not None:
        connection.execute(select(func.setval(sequence, highest)))
