"""Database upgrades: an existing install keeps its data and gains new columns.

Two paths exist and both are tested:
* ``upgrade_schema`` (runs at every engine start, additive, SQLite/Postgres), and
* the Alembic chain (PostgreSQL deployments, non-additive changes).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from elysium_engine.db.migrate import upgrade_schema
from elysium_engine.db.models import Base

ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

# `usage` exactly as Elysium 1.0.1 created it (migration 0008).
OLD_USAGE_DDL = """
CREATE TABLE usage (
    id INTEGER NOT NULL, created_at DATETIME NOT NULL, provider VARCHAR(100) NOT NULL,
    model VARCHAR(200) NOT NULL, agent_name VARCHAR(100), project_id VARCHAR(32),
    conversation_id VARCHAR(32), input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
    cost_usd FLOAT, duration_ms INTEGER NOT NULL, status VARCHAR(10) NOT NULL, error TEXT,
    PRIMARY KEY (id)
)
"""


@pytest.fixture
def old_db(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    with engine.begin() as conn:
        conn.execute(text(OLD_USAGE_DDL))
        conn.execute(text("CREATE INDEX ix_usage_created_at ON usage (created_at)"))
        conn.execute(
            text(
                "INSERT INTO usage (created_at, provider, model, input_tokens, output_tokens, cost_usd,"
                " duration_ms, status) VALUES ('2026-11-01 10:00:00', 'claude-code', 'default', 100, 20,"
                " 0.01, 900, 'ok')"
            )
        )
    yield engine
    engine.dispose()


def test_existing_database_gets_new_columns_and_keeps_its_rows(old_db) -> None:  # type: ignore[no-untyped-def]
    changes = upgrade_schema(old_db)
    cols = {c["name"] for c in inspect(old_db).get_columns("usage")}
    assert {"request_id", "billing", "cost_kind", "cache_read_tokens", "cost_eur", "fx_rate"} <= cols
    assert "usage.request_id" in changes
    with old_db.connect() as conn:
        row = conn.execute(text("SELECT provider, input_tokens, cost_usd, billing, cache_read_tokens FROM usage")).one()
    assert tuple(row) == ("claude-code", 100, 0.01, "api", 0)  # data intact, defaults applied
    tables = set(inspect(old_db).get_table_names())
    assert {"fx_rates", "quota_readings", "preview_sessions"} <= tables  # new tables created too


def test_upgrade_is_idempotent_and_adds_the_unique_index(old_db) -> None:  # type: ignore[no-untyped-def]
    upgrade_schema(old_db)
    assert upgrade_schema(old_db) == []  # second run changes nothing
    insert = text("INSERT INTO usage (created_at, provider, model, input_tokens, output_tokens, duration_ms, status, request_id)"
                  " VALUES ('2026-11-02', 'p', 'm', 0, 0, 0, 'ok', :rid)")
    with old_db.begin() as conn:
        conn.execute(insert, {"rid": "same"})
    with pytest.raises(IntegrityError), old_db.begin() as conn:
        conn.execute(insert, {"rid": "same"})  # idempotency is enforced by the database itself
    with old_db.begin() as conn:  # many rows without a request id (old rows) are fine
        conn.execute(insert, {"rid": None})
        conn.execute(insert, {"rid": None})


def test_fresh_install_and_upgraded_install_end_up_identical(old_db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    upgrade_schema(old_db)
    fresh = create_engine(f"sqlite:///{tmp_path}/fresh.db")
    upgrade_schema(fresh)
    for table in Base.metadata.sorted_tables:
        old_cols = {c["name"] for c in inspect(old_db).get_columns(table.name)}
        new_cols = {c["name"] for c in inspect(fresh).get_columns(table.name)}
        assert old_cols == new_cols, table.name
    fresh.dispose()


def test_a_failed_upgrade_step_loses_nothing(old_db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from elysium_engine.db import migrate

    real = migrate._default_sql
    calls = {"n": 0}

    def flaky(column):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("power cut")
        return real(column)

    monkeypatch.setattr(migrate, "_default_sql", flaky)
    with pytest.raises(RuntimeError):
        upgrade_schema(old_db)
    with old_db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM usage")).scalar() == 1  # row survived
    monkeypatch.setattr(migrate, "_default_sql", real)
    upgrade_schema(old_db)  # simply run again: it resumes where it stopped
    assert "cost_eur" in {c["name"] for c in inspect(old_db).get_columns("usage")}


def _alembic(tmp_path: Path, monkeypatch) -> Config:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ELYSIUM_DB_URL", f"sqlite:///{tmp_path}/chain.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


def test_alembic_chain_runs_from_empty_to_head_and_back(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = _alembic(tmp_path, monkeypatch)
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{tmp_path}/chain.db")
    insp = inspect(engine)
    assert {t.name for t in Base.metadata.sorted_tables} <= set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        have = {c["name"] for c in insp.get_columns(table.name)}
        want = {c.name for c in table.columns}
        assert want <= have, f"{table.name}: migration chain misses {want - have}"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0011"
    command.downgrade(cfg, "0008")  # 0011, 0010 and 0009 are reversible
    assert "fx_rates" not in inspect(engine).get_table_names()
    command.upgrade(cfg, "head")
    assert "fx_rates" in inspect(engine).get_table_names()
    engine.dispose()


def test_alembic_upgrade_over_a_database_already_upgraded_at_startup(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """``init_db`` may have created everything first; the migrations must not choke on that."""
    cfg = _alembic(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path}/chain.db")
    upgrade_schema(engine)
    command.upgrade(cfg, "head")
    engine.dispose()
