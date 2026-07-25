"""Provider/model listing and configuration.

``GET /models`` merges the built-in catalog with user-configured rows and
reports ``configured`` status.  ``reachable`` is only probed when the client
asks (``?probe=1``) because it performs live network calls; it is ``null``
otherwise.  ``PUT /models/providers/{name}`` stores the API key in the OS
keychain — the key never touches the database and is never echoed back.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from elysium_engine.api.deps import get_registry, get_session
from elysium_engine.api.schemas import ModelOut, ModelsOut, ProviderConfigIn, ProviderOut
from elysium_engine.db.models import ProviderRecord
from elysium_engine.db.repository import ProviderRepository
from elysium_engine.providers.registry import (
    KNOWN_PROVIDERS,
    ProviderRegistry,
    ProviderSpec,
    model_tier,
    spec_for,
)

router = APIRouter()


def _models_out(spec: ProviderSpec) -> list[ModelOut]:
    return [
        ModelOut(
            id=m.id,
            context_window=m.context_window,
            input_cost_per_mtok=m.input_cost_per_mtok,
            output_cost_per_mtok=m.output_cost_per_mtok,
            tier=model_tier(m.id),
        )
        for m in spec.models
    ]


def _provider_out(
    spec: ProviderSpec, configured: bool, reachable: bool | None
) -> ProviderOut:
    return ProviderOut(
        name=spec.name,
        kind=spec.kind,
        base_url=spec.base_url,
        default_model=spec.default_model,
        is_local=spec.is_local,
        configured=configured,
        reachable=reachable,
        models=_models_out(spec),
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


@router.get("/models", response_model=ModelsOut)
async def list_models(
    probe: bool = False,
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> ModelsOut:
    providers: list[ProviderOut] = []
    for spec, saved in _merged_specs(session):
        # A provider is routable only once explicitly saved by the user
        # (and, for remote providers, holding a key in the keychain).
        configured = saved and registry.is_configured(spec)
        reachable: bool | None = None
        if probe and configured:
            provider = registry.build(spec)
            if provider is not None:
                reachable = await provider.is_reachable()
        providers.append(_provider_out(spec, configured, reachable))
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
