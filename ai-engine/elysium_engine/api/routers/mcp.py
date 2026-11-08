"""MCP marketplace routes: catalog, persisted configuration and a live test.

``GET /mcp/catalog`` serves the curated marketplace, ``/mcp/servers`` manages
what the user installed (a row in ``mcp_servers`` per server).  ``POST .../test``
really starts the configured command (a user action behind the session token),
runs the handshake, lists the tools and stops it; agents are offered only what
that test found, and each call they make waits for the user (``mcp.toolbox``).
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_session
from elysium_engine.api.schemas import (
    McpCatalogEntryOut,
    McpConfigFieldOut,
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    McpTestOut,
    McpToolOut,
)
from elysium_engine.mcp import runtime as mcp_runtime
from elysium_engine.mcp.client import McpError
from elysium_engine.mcp.runtime import (
    MANUAL_SECRETS as _MANUAL_SECRETS,
    TOOLS_CACHE,
    launch_for,
    manual_secrets as _manual_secrets,
    public_config,
    schema_for as _schema_for,
    secret_key as _secret_key,
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


def _config_schema_out(
    schema: tuple[ConfigField, ...],
    server_id: str | None = None,
    secret_store: SecretStore | None = None,
) -> list[McpConfigFieldOut]:
    def is_set(field: ConfigField) -> bool:
        if field.type != "secret" or server_id is None or secret_store is None:
            return False
        return secret_store.get(_secret_key(server_id, field.key)) is not None

    return [
        McpConfigFieldOut(
            key=f.key, label=f.label, type=f.type, required=f.required, secret_set=is_set(f)
        )
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


def _server_out(server: McpServer, secret_store: SecretStore | None = None) -> McpServerOut:
    schema = _schema_for(server)
    return McpServerOut(
        id=server.id,
        catalog_id=server.catalog_id,
        name=server.name,
        description=server.description,
        url_or_command=server.url_or_command,
        transport=server.transport,
        enabled=server.enabled,
        # Secrets are never stored here; the bookkeeping entry is internal.
        config=public_config(server),
        config_schema=_config_schema_out(schema, server.id, secret_store),
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
def list_servers(
    request: Request, session: Session = Depends(get_session)
) -> list[McpServerOut]:
    store = request.app.state.secret_store
    return [_server_out(s, store) for s in McpServerRepository(session).list()]


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
    server: McpServer,
    incoming: dict[str, object],
    secret_store: SecretStore,
    manual_secrets: Sequence[str] = (),
) -> dict[str, object]:
    """Route secret fields to the keychain; return the non-secret config to persist.

    ``type: "secret"`` fields (per the server's ``config_schema``) are stored in
    the OS keychain keyed by server id + field key and stripped from the result,
    so secrets never land in the DB. Non-secret values are merged into the
    existing config.
    """
    schema_secrets = {f.key for f in _schema_for(server) if f.type == "secret"}
    secret_keys = schema_secrets | set(manual_secrets)
    persisted: dict[str, object] = dict(server.config)
    for key, value in incoming.items():
        if key in (_MANUAL_SECRETS, TOOLS_CACHE):
            continue
        if key in secret_keys:
            secret_store.set(_secret_key(server.id, key), str(value))
            persisted.pop(key, None)  # never keep a secret in the DB
        else:
            persisted[key] = value
    # Remembered so these secrets are found again at launch and on uninstall.
    known = sorted((set(_manual_secrets(server)) | set(manual_secrets)) - schema_secrets)
    if known:
        persisted[_MANUAL_SECRETS] = known
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
        config = _split_config(
            server, body.config, request.app.state.secret_store, body.secret_keys
        )
    updated = McpServerRepository(session).update(
        server,
        enabled=body.enabled,
        name=body.name,
        url_or_command=body.url_or_command,
        config=config,
    )
    return _server_out(updated, request.app.state.secret_store)


@router.post("/mcp/servers/{server_id}/test", response_model=McpTestOut)
async def test_server_endpoint(
    server_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> McpTestOut:
    """Really start the server, run the MCP handshake and list its tools.

    This is the proof that a configured server works: it launches the command
    with the saved configuration (secrets from the keychain), then stops it.
    """
    server = _get_or_404(session, server_id)
    try:
        spec = launch_for(server, request.app.state.secret_store)
    except McpError as exc:
        return McpTestOut(ok=False, error=str(exc))
    result = await mcp_runtime.probe_server(spec)
    if result.ok:
        # Agents are only offered what this test really found.
        McpServerRepository(session).update(
            server,
            config={
                **server.config,
                TOOLS_CACHE: [{"name": t.name, "description": t.description} for t in result.tools],
            },
        )
    return McpTestOut(
        ok=result.ok,
        tools=[McpToolOut(name=t.name, description=t.description) for t in result.tools],
        server_name=result.server_name,
        server_version=result.server_version,
        error=result.error,
        duration_ms=result.duration_ms,
    )


@router.delete("/mcp/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_server(
    server_id: str, request: Request, session: Session = Depends(get_session)
) -> Response:
    server = _get_or_404(session, server_id)
    names = [f.key for f in _schema_for(server) if f.type == "secret"] + _manual_secrets(server)
    for name in names:  # uninstalling must not leave credentials behind
        request.app.state.secret_store.delete(_secret_key(server.id, name))
    McpServerRepository(session).delete(server)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
