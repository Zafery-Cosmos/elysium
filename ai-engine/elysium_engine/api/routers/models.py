"""Provider/model listing, configuration and connectivity tests.

``GET /models`` merges the curated catalog with user-configured rows and
reports ``configured``/``custom`` status.  Configured **local** providers are
live-probed on every listing (short timeout) so the response shows the models
actually installed on the machine; remote reachability is only probed on
demand (``?probe=1``) because it performs network calls.

``PUT /models/providers/{name}`` configures a known provider,
``POST /models/providers`` registers a custom OpenAI-compatible server, and
``POST /models/providers/{name}/test`` runs a live connectivity probe.
API keys go to the OS keychain — never the database, never echoed back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_login_manager, get_registry, get_session
from elysium_engine.api.schemas import (
    CustomProviderIn,
    LoginCodeIn,
    LoginIn,
    LoginOut,
    ModelOut,
    ModelsOut,
    ProviderConfigIn,
    ProviderOut,
    ProviderTestOut,
)
from elysium_engine.db.models import ProviderRecord
from elysium_engine.db.repository import ProviderRepository
from elysium_engine.providers.base import ModelInfo, ProviderError
from elysium_engine.providers.cli_login import CliLoginManager
from elysium_engine.providers.registry import (
    KNOWN_PROVIDERS,
    ProviderRegistry,
    ProviderSpec,
    is_known_provider,
    model_tier,
    spec_for,
)

router = APIRouter()


def _models_out(models: Sequence[ModelInfo]) -> list[ModelOut]:
    return [
        ModelOut(
            id=m.id,
            display_name=m.display_name or m.id,
            release_date=m.release_date,
            context_window=m.context_window,
            input_cost_per_mtok=m.input_cost_per_mtok,
            output_cost_per_mtok=m.output_cost_per_mtok,
            cost_tier=m.cost_tier,
            tier=model_tier(m.id),
        )
        for m in models
    ]


def _provider_out(
    spec: ProviderSpec,
    configured: bool,
    reachable: bool | None,
    models: Sequence[ModelInfo] | None = None,
) -> ProviderOut:
    return ProviderOut(
        name=spec.name,
        kind=spec.kind,
        base_url=spec.base_url,
        default_model=spec.default_model,
        is_local=spec.is_local,
        configured=configured,
        custom=not is_known_provider(spec.name),
        reachable=reachable,
        models=_models_out(models if models is not None else spec.models),
    )


def _merged_specs(session: Session) -> list[tuple[ProviderSpec, bool]]:
    """(spec, saved_in_db) for every known + user-configured provider."""
    records = {r.name: r for r in ProviderRepository(session).list()}
    merged: list[tuple[ProviderSpec, bool]] = []
    for name, spec in KNOWN_PROVIDERS.items():
        record = records.pop(name, None)
        merged.append((spec_for(record), True) if record is not None else (spec, False))
    for record in records.values():  # custom OpenAI-compatible servers
        merged.append((spec_for(record), True))
    return merged


def _spec_or_404(session: Session, name: str) -> ProviderSpec:
    record = ProviderRepository(session).get_by_name(name)
    if record is not None:
        return spec_for(record)
    known = KNOWN_PROVIDERS.get(name)
    if known is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Provider not found.")
    return known


@router.get("/models", response_model=ModelsOut)
async def list_models(
    probe: bool = False,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> ModelsOut:
    providers: list[ProviderOut] = []
    for spec, saved in _merged_specs(session):
        # A provider is routable only once explicitly saved by the user
        # (and, for known remote providers, holding a key in the keychain).
        configured = saved and registry.is_configured(spec)
        reachable: bool | None = None
        models: Sequence[ModelInfo] | None = None
        if configured and spec.is_local:
            # Local servers: list the models that are ACTUALLY installed.
            models, reachable = await registry.discover_local_models(spec)
        elif probe and configured:
            reachable, _ = await registry.probe(spec)
        providers.append(_provider_out(spec, configured, reachable, models))
    return ModelsOut(providers=providers)


@router.put("/models/providers/{name}", response_model=ProviderOut)
def configure_provider(
    name: str,
    body: ProviderConfigIn,
    request: Request,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> ProviderOut:
    known = KNOWN_PROVIDERS.get(name)
    existing = ProviderRepository(session).get_by_name(name)

    base_url = body.base_url or (
        existing.base_url if existing else known.base_url if known else ""
    )
    default_model = body.default_model or (
        existing.default_model if existing else known.default_model if known else ""
    )
    if body.is_local is not None:
        is_local = body.is_local
    elif existing is not None:
        is_local = existing.is_local
    else:
        is_local = known.is_local if known else False

    record: ProviderRecord = ProviderRepository(session).upsert(
        name, base_url=base_url, default_model=default_model, is_local=is_local
    )
    if body.api_key:
        request.app.state.secret_store.set(name, body.api_key)

    spec = spec_for(record)
    return _provider_out(spec, registry.is_configured(spec), None)


@router.post(
    "/models/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED
)
def register_custom_provider(
    body: CustomProviderIn,
    request: Request,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> ProviderOut:
    if is_known_provider(body.name):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"'{body.name}' is a built-in provider. "
            f"Configure it via PUT /models/providers/{body.name}.",
        )
    if ProviderRepository(session).get_by_name(body.name) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A provider named '{body.name}' already exists.",
        )
    record = ProviderRepository(session).upsert(
        body.name,
        base_url=body.base_url,
        default_model=body.default_model,
        is_local=False,
    )
    if body.api_key:
        request.app.state.secret_store.set(body.name, body.api_key)
    spec = spec_for(record)
    return _provider_out(spec, registry.is_configured(spec), None)


def _cli_spec_or_422(name: str) -> ProviderSpec:
    known = KNOWN_PROVIDERS.get(name)
    if known is None or known.kind != "cli":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{name}' does not use a CLI sign-in.",
        )
    return known


async def _login_out(
    name: str, registry: ProviderRegistry, manager: CliLoginManager
) -> LoginOut:
    """Current sign-in state: live session first, else the CLI's own auth status."""
    session = manager.get(name)
    if session is not None and not session.finished:
        return LoginOut(
            state="pending",
            reachable=False,
            auth_url=session.auth_url,
            device_code=session.device_code,
            accepts_input=session.accepts_input,
        )
    signed_in, detail = await registry.cli_status(name)
    if signed_in:
        manager.cancel(name)
        return LoginOut(state="signed_in", reachable=True)
    # A finished session that did not sign in carries the CLI's own message.
    failure = session.error if session is not None else None
    return LoginOut(state="failed", reachable=False, detail=failure or detail)


@router.post("/models/providers/{name}/login", response_model=LoginOut)
async def start_cli_login(
    name: str,
    body: LoginIn | None = None,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
    manager: CliLoginManager = Depends(get_login_manager),
) -> LoginOut:
    """Sign in a CLI-backed provider (Claude Code / Codex) with the user's own account.

    Saves the provider (so it becomes routable), then — unless already signed
    in — starts the vendor CLI's login and returns the link / device code it
    printed.  The browser opens by itself on this machine; when it cannot be
    used (another device, another person), open ``auth_url`` elsewhere and send
    the resulting code back with ``POST .../login/code``.  The UI then polls
    ``GET .../login`` until ``state`` leaves ``pending``.
    """
    known = _cli_spec_or_422(name)
    mode = body.mode if body is not None else "browser"
    if ProviderRepository(session).get_by_name(name) is None:
        ProviderRepository(session).upsert(
            name, base_url=known.base_url, default_model=known.default_model, is_local=False
        )
    if not registry.is_configured(known):
        return LoginOut(
            state="not_installed",
            reachable=False,
            detail=f"The '{name}' command-line tool is not installed on this computer.",
        )
    signed_in, _ = await registry.cli_status(name)
    if signed_in:
        return LoginOut(state="signed_in", reachable=True)
    try:
        argv = registry.cli_login_argv(name, mode)
        live = manager.start(name, argv, device=(mode == "device"))
    except ProviderError as exc:
        return LoginOut(state="failed", reachable=False, detail=str(exc))
    # Give the CLI a moment to print its link / code before answering.
    for _ in range(50):
        wanted = live.device_code if live.device else live.auth_url
        if live.finished or wanted is not None:
            break
        await asyncio.sleep(0.1)
    return await _login_out(name, registry, manager)


@router.get("/models/providers/{name}/login", response_model=LoginOut)
async def get_cli_login(
    name: str,
    registry: ProviderRegistry = Depends(get_registry),
    manager: CliLoginManager = Depends(get_login_manager),
) -> LoginOut:
    _cli_spec_or_422(name)
    return await _login_out(name, registry, manager)


@router.post("/models/providers/{name}/login/code", response_model=LoginOut)
async def submit_cli_login_code(
    name: str,
    body: LoginCodeIn,
    registry: ProviderRegistry = Depends(get_registry),
    manager: CliLoginManager = Depends(get_login_manager),
) -> LoginOut:
    """Finish a pending sign-in with a pasted code or redirect address.

    Accepts the code shown by the vendor, or the full redirect address
    (``http://127.0.0.1:<port>/...?code=...``) from a browser that was not on
    this machine.  The CLI validates it; no token passes through Elysium.
    """
    _cli_spec_or_422(name)
    live = manager.get(name)
    if live is None or live.finished:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="No sign-in is in progress. Start one first.",
        )
    try:
        await asyncio.to_thread(live.submit, body.code)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    # The CLI validates the code within seconds: wait for its verdict.
    for _ in range(120):
        if live.finished:
            break
        await asyncio.sleep(0.1)
    return await _login_out(name, registry, manager)


@router.delete("/models/providers/{name}/login", status_code=status.HTTP_204_NO_CONTENT)
def cancel_cli_login(
    name: str,
    manager: CliLoginManager = Depends(get_login_manager),
) -> None:
    _cli_spec_or_422(name)
    manager.cancel(name)


@router.post("/models/providers/{name}/test", response_model=ProviderTestOut)
async def test_provider(
    name: str,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> ProviderTestOut:
    spec = _spec_or_404(session, name)
    reachable, detail = await registry.probe(spec)
    return ProviderTestOut(reachable=reachable, detail=detail)
