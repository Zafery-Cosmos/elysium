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
