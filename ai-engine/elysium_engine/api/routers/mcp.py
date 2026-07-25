"""MCP marketplace routes — v0: catalog + persisted configuration only.

``GET /mcp/catalog`` serves the curated marketplace, ``/mcp/servers`` manages
what the user installed (a row in ``mcp_servers`` per server).  Explicitly out
of scope for this phase: the **runtime MCP client** — nothing here spawns a
process or opens a connection; enabling a server only flips a persisted flag.
When the runtime lands (later phase) every MCP tool call will still go
through the Rust permission broker (ADR-003).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_session
from elysium_engine.api.schemas import (
    McpCatalogEntryOut,
    McpConfigFieldOut,
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
)
from elysium_engine.db.models import McpServer
from elysium_engine.db.repository import McpServerRepository
from elysium_engine.mcp.catalog import (
    CATALOG,
    CATALOG_BY_ID,
    ConfigField,
    McpCatalogEntry,
    categories,
)
from elysium_engine.secrets import SecretStore

router = APIRouter()


def _secret_key(server_id: str, field_key: str) -> str:
    """Keychain key for a server's secret config field."""
    return f"mcp:{server_id}:{field_key}"


def _config_schema_out(schema: tuple[ConfigField, ...]) -> list[McpConfigFieldOut]:
    return [
        McpConfigFieldOut(key=f.key, label=f.label, type=f.type, required=f.required)
        for f in schema
    ]


def _catalog_entry_out(entry: McpCatalogEntry, installed: bool) -> McpCatalogEntryOut:
    return McpCatalogEntryOut(
        catalog_id=entry.catalog_id,
        name=entry.name,
        description=entry.description,
        transport=entry.transport,
        install_hint=entry.install_hint,
        category=entry.category,
        permissions_note=entry.permissions_note,
        official=entry.official,
        installed=installed,
        config_schema=_config_schema_out(entry.config_schema),
    )


def _schema_for(server: McpServer) -> tuple[ConfigField, ...]:
    if server.catalog_id and server.catalog_id in CATALOG_BY_ID:
        return CATALOG_BY_ID[server.catalog_id].config_schema
    return ()


def _server_out(server: McpServer) -> McpServerOut:
    schema = _schema_for(server)
    return McpServerOut(
        id=server.id,
        catalog_id=server.catalog_id,
        name=server.name,
        description=server.description,
        url_or_command=server.url_or_command,
        transport=server.transport,
        enabled=server.enabled,
        config=dict(server.config),  # secrets are never stored here
        config_schema=_config_schema_out(schema),
        created_at=server.created_at,
    )


@router.get("/mcp/categories", response_model=list[str])
def list_categories() -> list[str]:
    return categories()


def _get_or_404(session: Session, server_id: str) -> McpServer:
    server = McpServerRepository(session).get(server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="MCP server not found.")
    return server


@router.get("/mcp/catalog", response_model=list[McpCatalogEntryOut])
def list_catalog(session: Session = Depends(get_session)) -> list[McpCatalogEntryOut]:
    installed_ids = {
        s.catalog_id for s in McpServerRepository(session).list() if s.catalog_id
    }
    return [
        _catalog_entry_out(entry, entry.catalog_id in installed_ids)
        for entry in CATALOG
    ]


@router.get("/mcp/servers", response_model=list[McpServerOut])
def list_servers(session: Session = Depends(get_session)) -> list[McpServerOut]:
    return [_server_out(s) for s in McpServerRepository(session).list()]


@router.post(
    "/mcp/servers", response_model=McpServerOut, status_code=status.HTTP_201_CREATED
)
def install_server(
    body: McpServerCreate, session: Session = Depends(get_session)
) -> McpServerOut:
    repo = McpServerRepository(session)
    if body.catalog_id is not None:
        entry = CATALOG_BY_ID.get(body.catalog_id)
        if entry is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="Unknown catalog entry."
            )
        if repo.get_by_catalog_id(entry.catalog_id) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"'{entry.name}' is already installed.",
            )
        server = repo.create(
            catalog_id=entry.catalog_id,
            name=entry.name,
            description=entry.description,
            url_or_command=entry.install_hint,
            transport=entry.transport,
        )
        return _server_out(server)

    # Custom server: name/url_or_command/transport enforced by the schema.
    assert body.name and body.url_or_command and body.transport
    server = repo.create(
        name=body.name,
        url_or_command=body.url_or_command,
        transport=body.transport,
    )
    return _server_out(server)


def _split_config(
    server: McpServer, incoming: dict[str, object], secret_store: SecretStore
) -> dict[str, object]:
    """Route secret fields to the keychain; return the non-secret config to persist.

    ``type: "secret"`` fields (per the server's ``config_schema``) are stored in
    the OS keychain keyed by server id + field key and stripped from the result,
    so secrets never land in the DB. Non-secret values are merged into the
    existing config.
    """
    secret_keys = {f.key for f in _schema_for(server) if f.type == "secret"}
    persisted: dict[str, object] = dict(server.config)
    for key, value in incoming.items():
        if key in secret_keys:
            secret_store.set(_secret_key(server.id, key), str(value))
            persisted.pop(key, None)  # never keep a secret in the DB
        else:
            persisted[key] = value
    return persisted


@router.patch("/mcp/servers/{server_id}", response_model=McpServerOut)
def update_server(
    server_id: str,
    body: McpServerUpdate,
    request: Request,
    session: Session = Depends(get_session),
) -> McpServerOut:
    server = _get_or_404(session, server_id)
    config = None
    if body.config is not None:
        config = _split_config(server, body.config, request.app.state.secret_store)
    updated = McpServerRepository(session).update(
        server,
        enabled=body.enabled,
        name=body.name,
        url_or_command=body.url_or_command,
        config=config,
    )
    return _server_out(updated)


@router.delete("/mcp/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: str, session: Session = Depends(get_session)) -> Response:
    server = _get_or_404(session, server_id)
    McpServerRepository(session).delete(server)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
