"""Admin dashboard: connections, plan quotas, token usage, reliability, agent actions.

One read-only endpoint, ``GET /admin/overview``, so the page loads in a single
round trip.  Usage comes from the ``usage`` table (one row per model call);
quotas from the latest ``rate_limit_event`` a CLI provider reported.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from elysium_engine import __version__
from elysium_engine.api.deps import get_registry, get_session
from elysium_engine.api.routers.models import _merged_specs
from elysium_engine.api.schemas import AccountOut
from elysium_engine.costing import (
    billing_for,
    current_rate,
    fetch_ecb_rate,
    history as fx_history,
    set_rate,
)
from elysium_engine.db.models import Event, UsageRecord
from elysium_engine.providers.health import LEDGER
from elysium_engine.providers.quota import assess as assess_quota, latest_quotas
from elysium_engine.providers.registry import KNOWN_PROVIDERS, ProviderRegistry

router = APIRouter()


class ProviderStatus(BaseModel):
    name: str
    kind: str  # anthropic | openai | cli
    default_model: str
    # CLI providers: signed in with the user's own account? None for API-key providers.
    signed_in: bool | None = None
    detail: str | None = None
    # CLI providers: is the vendor CLI installed on this computer at all?
    installed: bool = True
    # Whose session it is (CLI providers): lets the user verify "Connecté".
    account: AccountOut | None = None
    # api (per token) | subscription (personal CLI plan) | local
    billing: str = "api"
    # not_installed | not_authenticated | authenticated | available | unavailable |
    # auth_error | quota_exhausted | unknown  (see providers/health.py)
    health: str = "unknown"
    health_detail: str | None = None


class UsageTotals(BaseModel):
    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    # USD figures, split by how they are known — never summed into one blob.
    cost_reported_usd: float = 0.0  # vendor-reported (CLI)
    cost_estimated_usd: float = 0.0  # catalog rate x tokens
    cost_usd: float = 0.0  # reported + estimated
    # EUR with the rate stored on each row at call time (see fx on the overview).
    cost_eur: float = 0.0
    # Calls whose cost could not be known (e.g. subscription without a figure):
    # unknown is not zero.
    unknown_cost_calls: int = 0
    avg_duration_ms: int = 0  # successful calls only


class UsageGroup(UsageTotals):
    key: str
    last_used: datetime | None = None


class UsageDay(BaseModel):
    day: str
    provider: str
    calls: int
    input_tokens: int
    output_tokens: int


class QuotaWindow(BaseModel):
    name: str  # five_hour | seven_day | ...
    utilization: float | None = None  # 0..1
    resets_at: float | None = None  # epoch seconds
    state: str = "unknown"  # ok | stale | exhausted | unknown


class Quota(BaseModel):
    provider: str
    # subscription (CLI plan windows). API providers have no quota data and are
    # billed per token: they are never shown as "quota available".
    kind: str = "subscription"
    state: str = "unknown"  # unknown | stale | exhausted | ok
    observed_at: float | None = None  # epoch seconds of the last reading
    windows: list[QuotaWindow] = []


class FxInfo(BaseModel):
    base: str = "USD"
    quote: str = "EUR"
    rate: float
    source: str  # user | ecb | default
    as_of: str
    is_default: bool  # True = built-in fallback, not a live rate


class ErrorRow(BaseModel):
    at: datetime
    provider: str
    model: str
    agent: str | None
    message: str | None


class ActionRow(BaseModel):
    at: datetime
    agent: str | None
    tool: str | None
    status: str | None


class EngineInfo(BaseModel):
    version: str
    uptime_s: int


class PreviewRow(BaseModel):
    project_id: str
    framework: str | None
    state: str
    port: int | None
    url: str | None
    started_at: str | None
    error: str | None


class PreviewSummary(BaseModel):
    active: int
    items: list[PreviewRow]


class AdminOverview(BaseModel):
    days: int
    engine: EngineInfo
    fx: FxInfo
    previews: PreviewSummary
    by_billing: list[UsageGroup] = []
    providers: list[ProviderStatus]
    totals: UsageTotals
    by_provider: list[UsageGroup]
    by_model: list[UsageGroup]
    by_agent: list[UsageGroup]
    by_day: list[UsageDay]
    quotas: list[Quota]
    recent_errors: list[ErrorRow]
    recent_actions: list[ActionRow]


def _agg_columns() -> list[Any]:
    """calls, errors, tokens in/out, cost, avg duration — shared by every grouping."""
    def cost_sum(kind: str) -> Any:
        return func.coalesce(
            func.sum(case((UsageRecord.cost_kind == kind, UsageRecord.cost_usd), else_=0.0)), 0.0
        )

    return [
        func.count(UsageRecord.id),
        func.coalesce(func.sum(case((UsageRecord.status == "error", 1), else_=0)), 0),
        func.coalesce(func.sum(UsageRecord.input_tokens), 0),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        func.coalesce(
            func.sum(UsageRecord.cache_read_tokens + UsageRecord.cache_write_tokens), 0
        ),
        cost_sum("reported"),
        cost_sum("estimated"),
        func.coalesce(func.sum(UsageRecord.cost_eur), 0.0),
        func.coalesce(
            func.sum(
                case(((UsageRecord.status == "ok") & (UsageRecord.cost_kind == "none"), 1), else_=0)
            ),
            0,
        ),
        # Average over successful calls only: a call that failed fast must not
        # drag the latency figure down.
        func.coalesce(func.avg(case((UsageRecord.status == "ok", UsageRecord.duration_ms))), 0),
    ]


_AGG_WIDTH = 10


def _totals(row: Any) -> dict[str, Any]:
    calls, errors, tokens_in, tokens_out, cache, reported, estimated, eur, unknown, avg_ms = row
    return {
        "calls": int(calls or 0),
        "errors": int(errors or 0),
        "input_tokens": int(tokens_in or 0),
        "output_tokens": int(tokens_out or 0),
        "cache_tokens": int(cache or 0),
        "cost_reported_usd": round(float(reported or 0.0), 6),
        "cost_estimated_usd": round(float(estimated or 0.0), 6),
        "cost_usd": round(float(reported or 0.0) + float(estimated or 0.0), 6),
        "cost_eur": round(float(eur or 0.0), 6),
        "unknown_cost_calls": int(unknown or 0),
        "avg_duration_ms": int(avg_ms or 0),
    }


def _groups(session: Session, since: datetime, *keys: Any) -> list[UsageGroup]:
    stmt = (
        select(*keys, *_agg_columns(), func.max(UsageRecord.created_at))
        .where(UsageRecord.created_at >= since)
        .group_by(*keys)
        .order_by(desc(func.count(UsageRecord.id)))
        .limit(50)
    )
    out: list[UsageGroup] = []
    for row in session.execute(stmt).all():
        width = len(keys)
        label = " · ".join(str(k) if k is not None else "—" for k in row[:width])
        out.append(
            UsageGroup(key=label, last_used=row[-1], **_totals(row[width : width + _AGG_WIDTH]))
        )
    return out


async def _provider_statuses(
    session: Session, registry: ProviderRegistry
) -> list[ProviderStatus]:
    configured = [
        spec for spec, saved in _merged_specs(session) if saved and registry.is_configured(spec)
    ]
    # Subscription providers (Claude Code / Codex) are ALWAYS listed, even before the
    # first sign-in, so they can be connected at any time — not only at onboarding.
    listed = {spec.name for spec in configured}
    configured += [
        spec for spec in KNOWN_PROVIDERS.values() if spec.kind == "cli" and spec.name not in listed
    ]
    cli = [spec for spec in configured if spec.kind == "cli"]
    results = await asyncio.gather(*(registry.cli_state(spec.name) for spec in cli))
    auth = {spec.name: result for spec, result in zip(cli, results, strict=True)}
    out: list[ProviderStatus] = []
    for spec in configured:
        signed_in, detail, account = auth.get(spec.name, (None, None, None))
        installed = registry.is_configured(spec) if spec.kind == "cli" else True
        if spec.kind == "cli":
            # Keep the routing ledger in step with what the user sees here.
            LEDGER.set_cli(spec.name, installed, bool(signed_in), detail)
        state = registry.health(spec)
        out.append(
            ProviderStatus(
                name=spec.name,
                kind=spec.kind,
                default_model=spec.default_model,
                signed_in=signed_in,
                detail=detail,
                installed=installed,
                account=AccountOut(**account) if account else None,
                billing=billing_for(spec.name),
                health=state.state,
                health_detail=state.detail,
            )
        )
    return out


class FxIn(BaseModel):
    rate: float


class FxOut(BaseModel):
    current: FxInfo
    history: list[dict[str, Any]]


def _fx_out(request: Request) -> FxOut:
    sf = request.app.state.session_factory
    fx = current_rate(sf)
    return FxOut(
        current=FxInfo(rate=fx.rate, source=fx.source, as_of=fx.as_of, is_default=fx.is_default),
        history=fx_history(sf),
    )


@router.get("/admin/fx", response_model=FxOut)
def get_fx(request: Request) -> FxOut:
    """Current USD->EUR rate and its history (every change is a new dated row)."""
    return _fx_out(request)


@router.put("/admin/fx", response_model=FxOut)
def put_fx(body: FxIn, request: Request) -> FxOut:
    try:
        set_rate(request.app.state.session_factory, body.rate, "user")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _fx_out(request)


@router.post("/admin/fx/refresh", response_model=FxOut)
async def refresh_fx(request: Request) -> FxOut:
    """Fetch the ECB reference rate (explicit user action: this is a network call)."""
    try:
        rate, as_of = await asyncio.to_thread(fetch_ecb_rate)
        set_rate(request.app.state.session_factory, rate, "ecb", as_of)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(502, str(exc)) from exc
    return _fx_out(request)


@router.get("/admin/overview", response_model=AdminOverview)
async def admin_overview(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    session: Session = Depends(get_session),
    registry: ProviderRegistry = Depends(get_registry),
) -> AdminOverview:
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    providers = await _provider_statuses(session, registry)

    totals_row = session.execute(
        select(*_agg_columns()).where(UsageRecord.created_at >= since)
    ).one()

    day = func.date(UsageRecord.created_at)
    day_rows = session.execute(
        select(
            day,
            UsageRecord.provider,
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        )
        .where(UsageRecord.created_at >= since)
        .group_by(day, UsageRecord.provider)
        .order_by(day)
    ).all()

    error_rows = session.scalars(
        select(UsageRecord)
        .where(UsageRecord.status == "error")
        .order_by(desc(UsageRecord.id))
        .limit(10)
    ).all()

    action_rows = session.scalars(
        select(Event).where(Event.type == "action_request").order_by(desc(Event.id)).limit(20)
    ).all()

    # One entry per subscription provider — "unknown" when it never reported,
    # "stale" when the reading is old or its window has reset, "exhausted" when
    # the plan is used up.  Missing data is never shown as available quota.
    readings = latest_quotas()
    quotas = []
    for status_row in providers:
        if status_row.kind != "cli":
            continue
        assessed = assess_quota(readings.get(status_row.name))
        quotas.append(
            Quota(
                provider=status_row.name,
                state=assessed["state"],
                observed_at=assessed["observed_at"],
                windows=[QuotaWindow(**w) for w in assessed["windows"]],
            )
        )

    fx = current_rate(request.app.state.session_factory)
    billing_groups = _groups(session, since, UsageRecord.billing)

    started_at: float = getattr(request.app.state, "started_at", time.time())
    return AdminOverview(
        days=days,
        fx=FxInfo(rate=fx.rate, source=fx.source, as_of=fx.as_of, is_default=fx.is_default),
        by_billing=billing_groups,
        engine=EngineInfo(version=__version__, uptime_s=int(time.time() - started_at)),
        previews=PreviewSummary(**request.app.state.previews.summary()),
        providers=providers,
        totals=UsageTotals(**_totals(totals_row)),
        by_provider=_groups(session, since, UsageRecord.provider),
        by_model=_groups(session, since, UsageRecord.provider, UsageRecord.model),
        by_agent=_groups(session, since, UsageRecord.agent_name),
        by_day=[
            UsageDay(
                day=str(d),
                provider=p,
                calls=int(c),
                input_tokens=int(i),
                output_tokens=int(o),
            )
            for d, p, c, i, o in day_rows
        ],
        quotas=quotas,
        recent_errors=[
            ErrorRow(
                at=r.created_at,
                provider=r.provider,
                model=r.model,
                agent=r.agent_name,
                message=r.error,
            )
            for r in error_rows
        ],
        recent_actions=[
            ActionRow(
                at=e.created_at,
                agent=e.agent_name,
                tool=(e.payload or {}).get("tool"),
                status=(e.payload or {}).get("status"),
            )
            for e in action_rows
        ],
    )
