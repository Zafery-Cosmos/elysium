"""Shared fixtures: a fresh app + temp SQLite DB per test. No real LLM calls."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from elysium_engine.api.app import create_app
from elysium_engine.config import Settings
from elysium_engine.providers.base import Chunk

TEST_TOKEN = "test-token-123"


@pytest.fixture(autouse=True)
def _reset_process_wide_state():  # type: ignore[no-untyped-def]
    """Provider health and quota readings are process-wide: isolate every test."""
    from elysium_engine.providers import quota
    from elysium_engine.providers.health import LEDGER

    LEDGER.reset()
    quota.reset()
    yield
    LEDGER.reset()
    quota.reset()


@pytest.fixture
def settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        token=TEST_TOKEN,
        data_dir=tmp_path,
        db_url=f"sqlite:///{tmp_path}/test.db",
    )


@pytest.fixture
def app(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    # NEVER touch the developer's real OS keychain from tests: before this, tests
    # wrote "fake-key" entries into the real keychain (and could have overwritten a
    # genuine key saved by the user's Elysium).
    from elysium_engine.secrets import InMemorySecretStore

    monkeypatch.setattr("elysium_engine.api.app.build_secret_store", InMemorySecretStore)
    return create_app(settings)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Unauthenticated client (for auth tests)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client with a valid bearer token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as c:
        yield c


async def collect(chunks: AsyncIterator[Chunk]) -> list[Chunk]:
    return [chunk async for chunk in chunks]
