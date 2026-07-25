"""MCP marketplace routes — v0: catalog + persisted configuration only.

``GET /mcp/catalog`` serves the curated marketplace, ``/mcp/servers`` manages
what the user installed (a row in ``mcp_servers`` per server).  Explicitly out
of scope for this phase: the **runtime MCP client** — nothing here spawns a
process or opens a connection; enabling a server only flips a persisted flag.
When the runtime lands (later phase) every MCP tool call will still go
through the Rust permission broker (ADR-003).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_session
from elysium_engine.api.schemas import (
    McpCatalogEntryOut,
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
)
from elysium_engine.db.models import McpServer
from elysium_engine.db.repository import McpServerRepository
from elysium_engine.mcp.catalog import CATALOG, CATALOG_BY_ID, categories

router = APIRouter()


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
        McpCatalogEntryOut(
            catalog_id=entry.catalog_id,
            name=entry.name,
            description=entry.description,
            transport=entry.transport,
            install_hint=entry.install_hint,
            category=entry.category,
            permissions_note=entry.permissions_note,
            official=entry.official,
            installed=entry.catalog_id in installed_ids,
        )
        for entry in CATALOG
    ]


@router.get("/mcp/servers", response_model=list[McpServerOut])
def list_servers(session: Session = Depends(get_session)) -> list[McpServerOut]:
    return [McpServerOut.model_validate(s) for s in McpServerRepository(session).list()]


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
        return McpServerOut.model_validate(server)

    # Custom server: name/url_or_command/transport enforced by the schema.
    assert body.name and body.url_or_command and body.transport
    server = repo.create(
        name=body.name,
        url_or_command=body.url_or_command,
        transport=body.transport,
    )
    return McpServerOut.model_validate(server)


@router.patch("/mcp/servers/{server_id}", response_model=McpServerOut)
def update_server(
    server_id: str, body: McpServerUpdate, session: Session = Depends(get_session)
) -> McpServerOut:
    server = _get_or_404(session, server_id)
    updated = McpServerRepository(session).set_enabled(server, body.enabled)
    return McpServerOut.model_validate(updated)


@router.delete("/mcp/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: str, session: Session = Depends(get_session)) -> Response:
    server = _get_or_404(session, server_id)
    McpServerRepository(session).delete(server)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
