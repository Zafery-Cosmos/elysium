"""Bearer-token enforcement: everything except /health requires the token."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import TEST_TOKEN


async def test_health_is_open(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


async def test_missing_token_rejected(client: AsyncClient) -> None:
    for route in ("/projects", "/models", "/agents"):
        response = await client.get(route)
        assert response.status_code == 401, route
        assert response.headers["www-authenticate"] == "Bearer"


async def test_wrong_token_rejected(client: AsyncClient) -> None:
    response = await client.get("/projects", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


async def test_wrong_scheme_rejected(client: AsyncClient) -> None:
    response = await client.get("/projects", headers={"Authorization": f"Basic {TEST_TOKEN}"})
    assert response.status_code == 401


async def test_valid_token_accepted(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/projects")
    assert response.status_code == 200
    assert response.json() == []
