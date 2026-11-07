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

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from elysium_engine import __version__
from elysium_engine.api.deps import get_registry, get_session
from elysium_engine.api.routers.models import _merged_specs
from elysium_engine.db.models import Event, UsageRecord
from elysium_engine.providers.quota import latest_quotas
from elysium_engine.providers.registry import ProviderRegistry

router = APIRouter()


class ProviderStatus(BaseModel):
    name: str
    kind: str  # anthropic | openai | cli
    default_model: str
    # CLI providers: signed in with the user's own account? None for API-key providers.
    signed_in: bool | None = None
    detail: str | None = None


class UsageTotals(BaseModel):
    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    avg_duration_ms: int = 0


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
    utilization: float  # 0..1
    resets_at: int | None = None  # epoch seconds
    status: str | None = None


class Quota(BaseModel):
    provider: str
    windows: list[QuotaWindow]
    updated_at: float  # epoch seconds


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


class AdminOverview(BaseModel):
    days: int
    engine: EngineInfo
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
    return [
        func.count(UsageRecord.id),
        func.coalesce(func.sum(case((UsageRecord.status == "error", 1), else_=0)), 0),
        func.coalesce(func.sum(UsageRecord.input_tokens), 0),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0),
        func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
        func.coalesce(func.avg(UsageRecord.duration_ms), 0),
    ]


def _totals(row: Any) -> dict[str, Any]:
    calls, errors, tokens_in, tokens_out, cost, avg_ms = row
    return {
        "calls": int(calls or 0),
        "errors": int(errors or 0),
        "input_tokens": int(tokens_in or 0),
        "output_tokens": int(tokens_out or 0),
        "cost_usd": round(float(cost or 0.0), 4),
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
            UsageGroup(key=label, last_used=row[-1], **_totals(row[width : width + 6]))
        )
    return out


async def _provider_statuses(
    session: Session, registry: ProviderRegistry
) -> list[ProviderStatus]:
    configured = [
        spec for spec, saved in _merged_specs(session) if saved and registry.is_configured(spec)
    ]
    cli = [spec for spec in configured if spec.kind == "cli"]
    results = await asyncio.gather(*(registry.cli_status(spec.name) for spec in cli))
    auth = {spec.name: result for spec, result in zip(cli, results, strict=True)}
    out: list[ProviderStatus] = []
    for spec in configured:
        signed_in, detail = auth.get(spec.name, (None, None))
        out.append(
            ProviderStatus(
                name=spec.name,
                kind=spec.kind,
                default_model=spec.default_model,
                signed_in=signed_in,
                detail=detail,
            )
        )
    return out


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

    quotas = [
        Quota(
            provider=name,
            updated_at=reading["updated_at"],
            windows=[
                QuotaWindow(name=w, **{k: v for k, v in data.items()})
                for w, data in reading["windows"].items()
            ],
        )
        for name, reading in latest_quotas().items()
    ]

    started_at: float = getattr(request.app.state, "started_at", time.time())
    return AdminOverview(
        days=days,
        engine=EngineInfo(version=__version__, uptime_s=int(time.time() - started_at)),
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
