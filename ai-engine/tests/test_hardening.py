"""Non-regression tests for defects confirmed during the 2026-11 audit."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import Boolean, Column
from sqlalchemy.exc import IntegrityError

from elysium_engine.api.app import create_app
from elysium_engine.api.routers import conversations
from elysium_engine.app_settings import AppSettings, load_settings
from elysium_engine.config import Settings
from elysium_engine.db.migrate import _default_sql, _for_dialect
from elysium_engine.db.models import Message
from elysium_engine.db.repository import AppSettingsRepository


def test_empty_token_is_refused_at_startup(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(token="", data_dir=tmp_path)


async def test_blank_bearer_never_matches(client: AsyncClient) -> None:
    for header in ("Bearer", "Bearer ", "Bearer    "):
        response = await client.get("/projects", headers={"Authorization": header})
        assert response.status_code == 401


async def test_every_route_but_health_requires_the_token(
    app: FastAPI, client: AsyncClient
) -> None:
    """Walks the real route table, so a router mounted later cannot be forgotten."""
    paths = app.openapi()["paths"]
    assert len(paths) > 30
    unprotected = []
    for path, operations in paths.items():
        url = path.replace("{", "").replace("}", "")
        for method in operations:
            response = await client.request(method.upper(), url)
            if response.status_code != 401:
                unprotected.append(f"{method} {path}")
    assert unprotected == ["get /health"]


async def test_openapi_inventory_is_not_served(client: AsyncClient) -> None:
    assert (await client.get("/openapi.json")).status_code == 404


async def test_foreign_host_header_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DNS rebinding: the page's own domain arrives as Host."""
    from elysium_engine.secrets import InMemorySecretStore

    monkeypatch.setattr("elysium_engine.api.app.build_secret_store", InMemorySecretStore)
    app = create_app(Settings(token="t", data_dir=tmp_path, db_url=f"sqlite:///{tmp_path}/h.db"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
        assert (await c.get("/health")).status_code == 200
        assert (await c.get("/health", headers={"Host": "evil.example"})).status_code == 400


async def test_concurrent_posts_start_a_single_run(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow_refresh(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0.1)

    monkeypatch.setattr(conversations, "refresh_cli", slow_refresh)
    project = (await auth_client.post("/projects", json={"name": "p"})).json()["id"]
    cid = (await auth_client.post(f"/projects/{project}/conversations", json={})).json()["id"]
    url = f"/conversations/{cid}/messages"
    first, second = await asyncio.gather(
        auth_client.post(url, json={"content": "a"}), auth_client.post(url, json={"content": "b"})
    )
    assert sorted((first.status_code, second.status_code)) == [202, 409]
    stored = (await auth_client.get(url)).json()
    assert sum(1 for m in stored if m["role"] == "user") == 1


async def test_failed_setup_releases_the_conversation(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    async def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cli check failed")

    monkeypatch.setattr(conversations, "refresh_cli", boom)
    project = (await auth_client.post("/projects", json={"name": "p"})).json()["id"]
    cid = (await auth_client.post(f"/projects/{project}/conversations", json={})).json()["id"]
    with pytest.raises(RuntimeError):
        await auth_client.post(f"/conversations/{cid}/messages", json={"content": "a"})
    assert cid not in app.state.starting_runs


def test_unknown_stored_key_falls_back_and_keeps_the_rest() -> None:
    loaded = load_settings({"general": {"bogus": 1, "language": "en"}})
    assert loaded.general.language == "en"


def test_invalid_stored_value_falls_back_to_default() -> None:
    loaded = load_settings({"ai": {"max_retries": 999}, "general": {"language": "es"}})
    assert loaded.ai.max_retries == AppSettings().ai.max_retries
    assert loaded.general.language == "es"


async def test_settings_survive_a_stale_row(auth_client: AsyncClient, app: FastAPI) -> None:
    with app.state.session_factory() as session:
        AppSettingsRepository(session).save({"general": {"bogus": 1}})
    assert (await auth_client.get("/settings")).status_code == 200


async def test_custom_validator_error_is_a_422(auth_client: AsyncClient) -> None:
    response = await auth_client.patch(
        "/settings", json={"ai": {"expert_budgets": {"openai": -1}}}
    )
    assert response.status_code == 422


def test_nan_budget_is_refused() -> None:
    with pytest.raises(ValidationError):
        AppSettings.model_validate({"ai": {"expert_budgets": {"openai": float("nan")}}})


def test_sqlite_enforces_foreign_keys(app: FastAPI) -> None:
    with app.state.session_factory() as session:
        session.add(Message(conversation_id="missing", role="user", content="x"))
        with pytest.raises(IntegrityError):
            session.commit()


async def test_provider_name_cannot_reach_another_secret_namespace(
    auth_client: AsyncClient, app: FastAPI
) -> None:
    app.state.secret_store.set("mcp:abc:TOKEN", "secret")
    response = await auth_client.put("/models/providers/mcp:abc:TOKEN", json={"api_key": "x"})
    assert response.status_code == 422
    assert app.state.secret_store.get("mcp:abc:TOKEN") == "secret"


async def test_provider_url_must_be_http(auth_client: AsyncClient) -> None:
    response = await auth_client.put(
        "/models/providers/openai", json={"base_url": "file:///etc/passwd"}
    )
    assert response.status_code == 422


async def test_import_refuses_the_data_directory(
    auth_client: AsyncClient, settings: Settings
) -> None:
    project = (await auth_client.post("/projects", json={"name": "p"})).json()["id"]
    response = await auth_client.post(
        f"/projects/{project}/import-folder", json={"path": str(settings.data_dir)}
    )
    assert response.status_code == 400


async def test_dependency_cycle_is_refused(auth_client: AsyncClient) -> None:
    project = (await auth_client.post("/projects", json={"name": "p"})).json()["id"]
    url = f"/projects/{project}/tasks"
    a = (await auth_client.post(url, json={"title": "a", "agent_role": "architect"})).json()["id"]
    b = (
        await auth_client.post(
            url, json={"title": "b", "agent_role": "architect", "depends_on": [a]}
        )
    ).json()["id"]
    c = (
        await auth_client.post(
            url, json={"title": "c", "agent_role": "architect", "depends_on": [b]}
        )
    ).json()["id"]
    assert (await auth_client.patch(f"/tasks/{a}", json={"depends_on": [c]})).status_code == 422
    assert (await auth_client.patch(f"/tasks/{c}", json={"depends_on": [a]})).status_code == 200


async def test_message_size_is_bounded(auth_client: AsyncClient) -> None:
    project = (await auth_client.post("/projects", json={"name": "p"})).json()["id"]
    cid = (await auth_client.post(f"/projects/{project}/conversations", json={})).json()["id"]
    response = await auth_client.post(
        f"/conversations/{cid}/messages", json={"content": "x" * 2_000_001}
    )
    assert response.status_code == 422


def test_boolean_default_is_valid_postgres_sql() -> None:
    column: Column[bool] = Column("flag", Boolean, default=True)
    assert _for_dialect(_default_sql(column), column, "postgresql") == "TRUE"
    assert _for_dialect(_default_sql(column), column, "sqlite") == "1"
