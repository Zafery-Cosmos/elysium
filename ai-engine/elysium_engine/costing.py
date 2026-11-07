"""Cost accounting: currency, billing mode, estimated vs reported, cache tokens.

Rules (see docs/ARCHITECTURE.md, "Accounting"):

* Catalog prices and CLI-reported costs are **USD**.  Budgets and displays that
  need euros use an explicit, *dated and stored* USD->EUR rate (``fx_rates``);
  every usage row keeps the rate it was converted with, so history never shifts.
* A cost is ``reported`` (a vendor figure), ``estimated`` (catalog rate x tokens)
  or ``none`` (unknown) — never presented as the same thing.
* ``billing`` says who pays: ``api`` (per token), ``subscription`` (a personal
  CLI plan: the API-equivalent figure is informative, nothing is charged per
  call) or ``local``.  A zero cost on a subscription is **not** "unlimited": it
  is bounded by the plan's quota windows (see ``quota.py``).
* Cache tokens are recorded apart and priced with documented factors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.models import FxRate

log = logging.getLogger(__name__)

# Built-in fallback only: clearly labelled "default", never shown as a live rate.
DEFAULT_USD_EUR = 0.92
ECB_URL = "https://api.frankfurter.app/latest"

# Price of cached input relative to the normal input rate (published vendor
# ratios; estimates, flagged as such).
CACHE_FACTORS: dict[str, tuple[float, float]] = {
    "anthropic": (0.1, 1.25),  # (read, write)
    "openai": (0.5, 1.0),
}


@dataclass(frozen=True, slots=True)
class FxQuote:
    rate: float
    source: str
    as_of: str

    @property
    def is_default(self) -> bool:
        return self.source == "default"


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def current_rate(session_factory: sessionmaker[Session]) -> FxQuote:
    """Latest stored USD->EUR rate, or the labelled built-in default."""
    try:
        with session_factory() as session:
            row = session.query(FxRate).order_by(FxRate.id.desc()).first()
            if row is not None:
                return FxQuote(row.rate, row.source, row.as_of)
    except Exception:  # accounting must never break a chat
        log.exception("could not read the fx rate")
    return FxQuote(DEFAULT_USD_EUR, "default", _today())


def set_rate(
    session_factory: sessionmaker[Session], rate: float, source: str, as_of: str | None = None
) -> FxQuote:
    """Append a new rate (history is never overwritten)."""
    if not 0.2 <= rate <= 5.0:
        raise ValueError("USD->EUR rate must be between 0.2 and 5.0")
    when = as_of or _today()
    with session_factory() as session:
        session.add(FxRate(rate=float(rate), source=source[:60], as_of=when))
        session.commit()
    return FxQuote(float(rate), source, when)


def history(session_factory: sessionmaker[Session], limit: int = 20) -> list[dict[str, Any]]:
    with session_factory() as session:
        rows = session.query(FxRate).order_by(FxRate.id.desc()).limit(limit).all()
        return [
            {"rate": r.rate, "source": r.source, "as_of": r.as_of, "created_at": r.created_at.isoformat()}
            for r in rows
        ]


def fetch_ecb_rate(client: httpx.Client | None = None) -> tuple[float, str]:
    """USD->EUR from the ECB reference rates (frankfurter.app). Explicit user action only."""
    owns = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        response = client.get(ECB_URL, params={"from": "USD", "to": "EUR"})
        response.raise_for_status()
        body = response.json()
        return float(body["rates"]["EUR"]), str(body["date"])
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Could not fetch the exchange rate: {exc}") from exc
    finally:
        if owns:
            client.close()


def billing_for(provider_name: str) -> str:
    """``api`` | ``subscription`` | ``local`` for a provider name."""
    from elysium_engine.providers.registry import KNOWN_PROVIDERS

    spec = KNOWN_PROVIDERS.get(provider_name)
    if spec is None:
        return "api"
    if spec.kind == "cli":
        return "subscription"
    return "local" if spec.is_local else "api"


def model_rates(provider_name: str, model: str) -> tuple[float, float, str] | None:
    """``(input_usd_per_mtok, output_usd_per_mtok, kind)`` from the catalog, if known."""
    from elysium_engine.providers.registry import KNOWN_PROVIDERS

    spec = KNOWN_PROVIDERS.get(provider_name)
    if spec is None:
        return None
    for info in spec.models:
        if info.id == model:
            return info.input_cost_per_mtok, info.output_cost_per_mtok, spec.kind
    return None


def estimate_cost_usd(
    rates: tuple[float, float, str],
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
) -> float:
    """Catalog-rate estimate, cache tokens priced with ``CACHE_FACTORS``.

    Anthropic's ``input_tokens`` excludes cached tokens; for the others it includes
    them, so the cached part is carved out of the normal input first.
    """
    input_rate, output_rate, kind = rates
    read_f, write_f = CACHE_FACTORS.get(kind, (1.0, 1.0))
    uncached = input_tokens if kind == "anthropic" else max(0, input_tokens - cache_read - cache_write)
    total = (
        uncached * input_rate
        + cache_read * input_rate * read_f
        + cache_write * input_rate * write_f
        + output_tokens * output_rate
    )
    return total / 1_000_000


@dataclass(frozen=True, slots=True)
class CostFigures:
    billing: str
    kind: str  # reported | estimated | none
    cost_usd: float | None
    cost_eur: float | None
    fx_rate: float | None


def figures_for(
    provider_name: str,
    model: str,
    usage: dict[str, Any],
    quote: FxQuote,
) -> CostFigures:
    """Decide how a call's cost is described. ``status`` errors have no cost."""
    billing = billing_for(provider_name)
    reported = usage.get("cost_usd")
    cost: float | None
    kind: str
    if isinstance(reported, (int, float)):
        cost, kind = float(reported), "reported"
    else:
        rates = model_rates(provider_name, model)
        has_price = rates is not None and (rates[0] > 0 or rates[1] > 0)
        if billing == "local":
            cost, kind = 0.0, "estimated"
        elif rates is not None and has_price and billing == "api":
            cost = estimate_cost_usd(
                rates,
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read=int(usage.get("cache_read_tokens") or 0),
                cache_write=int(usage.get("cache_write_tokens") or 0),
            )
            kind = "estimated"
        else:
            cost, kind = None, "none"  # unknown is unknown, not zero
    eur = round(cost * quote.rate, 8) if cost is not None else None
    return CostFigures(billing, kind, cost, eur, quote.rate if cost is not None else None)
