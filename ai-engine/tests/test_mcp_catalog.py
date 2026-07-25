"""The static MCP marketplace catalog: shape, coverage and the HTTP surface."""

from __future__ import annotations

from httpx import AsyncClient

from elysium_engine.mcp.catalog import (
    CATALOG,
    CATALOG_BY_ID,
    CATEGORIES,
    categories,
)

VALID_TRANSPORTS = {"stdio", "http"}


def test_catalog_has_at_least_80_servers() -> None:
    assert len(CATALOG) >= 80


def test_catalog_ids_are_unique() -> None:
    ids = [entry.catalog_id for entry in CATALOG]
    assert len(ids) == len(set(ids))
    assert set(CATALOG_BY_ID) == set(ids)


def test_every_entry_is_fully_populated_and_well_typed() -> None:
    known_categories = set(CATEGORIES)
    for entry in CATALOG:
        assert entry.catalog_id and isinstance(entry.catalog_id, str)
        assert entry.name and isinstance(entry.name, str)
        assert entry.description and isinstance(entry.description, str)
        assert entry.install_hint and isinstance(entry.install_hint, str)
        assert entry.permissions_note and isinstance(entry.permissions_note, str)
        assert entry.transport in VALID_TRANSPORTS, entry.catalog_id
        assert entry.category in known_categories, entry.catalog_id
        assert isinstance(entry.official, bool)


def test_categories_helper_returns_ordered_french_list() -> None:
    assert categories() == list(CATEGORIES)
    # Every declared category is actually used by at least one entry.
    used = {entry.category for entry in CATALOG}
    assert used == set(CATEGORIES)


def test_expected_servers_present_across_groups() -> None:
    expected = {
        "filesystem", "s3", "github", "gitlab", "terraform", "postgres",
        "snowflake", "bigquery", "brave-search", "firecrawl", "tavily",
        "aws", "gcp", "azure", "vercel", "slack", "discord", "twilio",
        "notion", "airtable", "stripe", "shopify", "salesforce",
        "huggingface", "pinecone", "qdrant", "weaviate", "time", "maps",
    }
    assert expected <= set(CATALOG_BY_ID)


async def test_catalog_endpoint_serves_all_entries(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/mcp/catalog")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(CATALOG)
    assert all(item["installed"] is False for item in body)


async def test_categories_endpoint(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/mcp/categories")
    assert response.status_code == 200
    assert response.json() == list(CATEGORIES)


def test_config_schema_populated_for_common_servers() -> None:
    # github -> GITHUB_TOKEN (secret), postgres -> DATABASE_URL, filesystem -> ROOT_PATH.
    gh = {f.key: f for f in CATALOG_BY_ID["github"].config_schema}
    assert gh["GITHUB_TOKEN"].type == "secret" and gh["GITHUB_TOKEN"].required
    pg = {f.key: f for f in CATALOG_BY_ID["postgres"].config_schema}
    assert "DATABASE_URL" in pg and pg["DATABASE_URL"].type == "string"
    fs = {f.key: f for f in CATALOG_BY_ID["filesystem"].config_schema}
    assert "ROOT_PATH" in fs
    # At least ~30 servers carry a config schema; the rest are empty.
    with_schema = [e for e in CATALOG if e.config_schema]
    assert len(with_schema) >= 30
    # Every field is well-typed.
    for entry in CATALOG:
        for field in entry.config_schema:
            assert field.key and field.label
            assert field.type in {"string", "secret", "number"}
            assert isinstance(field.required, bool)


async def test_catalog_endpoint_includes_config_schema(auth_client: AsyncClient) -> None:
    body = (await auth_client.get("/mcp/catalog")).json()
    by_id = {e["catalog_id"]: e for e in body}
    gh_fields = {f["key"]: f for f in by_id["github"]["config_schema"]}
    assert gh_fields["GITHUB_TOKEN"]["type"] == "secret"
    # Servers without a schema expose an empty list, not null.
    assert by_id["everything"]["config_schema"] == []


async def test_mcp_config_round_trip_and_secret_store(auth_client: AsyncClient, app) -> None:  # type: ignore[no-untyped-def]
    # Install GitHub (has GITHUB_TOKEN secret + no other fields).
    r = await auth_client.post("/mcp/servers", json={"catalog_id": "github"})
    assert r.status_code == 201
    server = r.json()
    server_id = server["id"]
    assert server["config"] == {}
    assert {f["key"] for f in server["config_schema"]} == {"GITHUB_TOKEN"}

    # PATCH: a secret field + a plain field. Secret must not persist to the DB.
    r = await auth_client.patch(
        f"/mcp/servers/{server_id}",
        json={"config": {"GITHUB_TOKEN": "ghp_secret", "note": "team repo"}, "enabled": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    # Non-secret round-trips through the DB config; the secret is stripped.
    assert body["config"] == {"note": "team repo"}
    assert "ghp_secret" not in r.text

    # The secret lives in the secret store, keyed by server id + field key.
    store = app.state.secret_store
    assert store.get(f"mcp:{server_id}:GITHUB_TOKEN") == "ghp_secret"

    # GET confirms the persisted (non-secret) config survives.
    listed = (await auth_client.get("/mcp/servers")).json()
    assert listed[0]["config"] == {"note": "team repo"}


async def test_mcp_patch_name_and_command(auth_client: AsyncClient) -> None:
    r = await auth_client.post(
        "/mcp/servers",
        json={"name": "My tool", "url_or_command": "npx -y x", "transport": "stdio"},
    )
    server_id = r.json()["id"]
    r = await auth_client.patch(
        f"/mcp/servers/{server_id}",
        json={"name": "Renamed", "url_or_command": "npx -y y"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renamed"
    assert body["url_or_command"] == "npx -y y"
    assert body["config_schema"] == []  # custom server: no schema
