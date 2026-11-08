"""Choosing a PostgreSQL server: validation, fallback and what the API exposes.

Real connections were exercised against a throwaway PostgreSQL 17 cluster; here
the rules that must hold without a server.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from elysium_engine.config import Settings, default_db_url
from elysium_engine.db import external
from elysium_engine.db.external import (
    SECRET_NAME,
    DatabaseConfigError,
    describe,
    normalize_url,
    resolve_db_url,
)
from elysium_engine.secrets import InMemorySecretStore


@pytest.mark.parametrize(
    "raw",
    ["postgres://u:p@h/db", "postgresql://u:p@h:5432/db", " postgresql+psycopg://u:p@h/db "],
)
def test_postgres_urls_use_the_shipped_driver(raw: str) -> None:
    assert normalize_url(raw).startswith("postgresql+psycopg://u:p@h")


@pytest.mark.parametrize(
    "raw", ["mysql://u:p@h/db", "sqlite:///x.db", "nonsense", "postgresql://u:p@h/", "postgresql:///db"]
)
def test_other_urls_are_refused(raw: str) -> None:
    with pytest.raises(DatabaseConfigError):
        normalize_url(raw)


def test_description_never_contains_the_password() -> None:
    shown = describe("postgresql+psycopg://user:hunter2@db.lan:5433/elysium")
    assert shown == "user@db.lan:5433/elysium"


def _settings(data_dir: Path, db_url: str = "") -> Settings:
    return Settings(token="t" * 40, data_dir=data_dir, db_url=db_url)


def test_explicit_environment_url_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemorySecretStore()
    store.set(SECRET_NAME, "postgresql+psycopg://u:p@h/db")
    monkeypatch.setattr(external, "check_connection", lambda url: pytest.fail("must not connect"))
    explicit = f"sqlite:///{tmp_path / 'other.db'}"
    assert resolve_db_url(_settings(tmp_path, explicit), store) == (explicit, None)


def test_saved_server_is_used_when_reachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql+psycopg://u:p@h/db"
    store = InMemorySecretStore()
    store.set(SECRET_NAME, url)
    monkeypatch.setattr(external, "check_connection", lambda _url: "17")
    assert resolve_db_url(_settings(tmp_path), store) == (url, None)


def test_unreachable_server_falls_back_to_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(_url: str) -> str:
        raise DatabaseConfigError("Connection failed: refused")

    store = InMemorySecretStore()
    store.set(SECRET_NAME, "postgresql+psycopg://u:p@h/db")
    monkeypatch.setattr(external, "check_connection", down)
    url, error = resolve_db_url(_settings(tmp_path), store)
    assert url == default_db_url(tmp_path)
    assert error == "Connection failed: refused"


def test_no_saved_server_keeps_local(tmp_path: Path) -> None:
    assert resolve_db_url(_settings(tmp_path), InMemorySecretStore()) == (default_db_url(tmp_path), None)


async def test_status_route(auth_client: AsyncClient) -> None:
    info = (await auth_client.get("/admin/database")).json()
    assert info["backend"] == "sqlite" and info["configured"] is None and info["fallback_error"] is None


async def test_save_stores_in_keychain_without_echoing_it(
    app: FastAPI, auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from elysium_engine.api.routers import database

    monkeypatch.setattr(database, "check_connection", lambda _url: "17")
    monkeypatch.setattr(database, "prepare", lambda _url, _source: 0)
    response = await auth_client.put("/admin/database", json={"url": "postgresql://u:hunter2@h/db"})
    assert response.status_code == 200 and "hunter2" not in response.text
    assert response.json()["restart_required"] is True
    assert app.state.secret_store.get(SECRET_NAME) == "postgresql+psycopg://u:hunter2@h/db"
    info = await auth_client.get("/admin/database")
    assert "hunter2" not in info.text and info.json()["configured"] == "u@h/db"
    assert (await auth_client.delete("/admin/database")).status_code == 204
    assert app.state.secret_store.get(SECRET_NAME) is None


async def test_refused_url_saves_nothing(app: FastAPI, auth_client: AsyncClient) -> None:
    response = await auth_client.put("/admin/database", json={"url": "mysql://u:p@h/db"})
    assert response.status_code == 422
    assert app.state.secret_store.get(SECRET_NAME) is None


async def test_open_url_only_accepts_web_links(auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert (await auth_client.post("/settings/open-url", json={"url": "file:///c:/x"})).status_code == 422
    assert (await auth_client.post("/settings/open-url", json={"url": "calc.exe"})).status_code == 422
    assert (await auth_client.post("/settings/open-url", json={"url": "https://e.org/a"})).status_code == 204
    assert opened == ["https://e.org/a"]


async def test_project_progress(app: FastAPI, auth_client: AsyncClient) -> None:
    from elysium_engine.db.repository import TaskRepository

    project_id = (await auth_client.post("/projects", json={"name": "P", "description": ""})).json()["id"]
    assert (await auth_client.get("/projects")).json()[0]["progress"] is None
    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        repo.create(project_id, "a", "backend", status="done")
        repo.create(project_id, "b", "backend")
    assert (await auth_client.get("/projects")).json()[0]["progress"] == 0.5
