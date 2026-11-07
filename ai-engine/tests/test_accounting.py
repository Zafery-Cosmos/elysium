"""Accounting: currency, estimated vs reported, billing mode, cache, idempotence, quotas."""

from __future__ import annotations

import time

import httpx
import pytest
from sqlalchemy import func, select

from elysium_engine import costing
from elysium_engine.db.models import UsageRecord
from elysium_engine.providers import quota
from elysium_engine.usage import record_usage


# ------------------------------------------------------------------ fx rate


def test_default_rate_is_clearly_labelled_not_live(app) -> None:  # type: ignore[no-untyped-def]
    quote = costing.current_rate(app.state.session_factory)
    assert quote.is_default and quote.source == "default" and quote.rate == costing.DEFAULT_USD_EUR


def test_rate_changes_are_historised_never_overwritten(app) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    costing.set_rate(sf, 0.90, "user", "2026-11-01")
    costing.set_rate(sf, 0.85, "ecb", "2026-11-07")
    current = costing.current_rate(sf)
    assert (current.rate, current.source, current.as_of) == (0.85, "ecb", "2026-11-07")
    rows = costing.history(sf)
    assert [r["rate"] for r in rows] == [0.85, 0.90]  # newest first, both kept
    with pytest.raises(ValueError):
        costing.set_rate(sf, 0.0, "user")
    with pytest.raises(ValueError):
        costing.set_rate(sf, 50.0, "user")


def test_ecb_rate_parsing_and_failure() -> None:
    ok = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"date": "2026-11-06", "rates": {"EUR": 0.8612}})
        )
    )
    assert costing.fetch_ecb_rate(ok) == (0.8612, "2026-11-06")
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(RuntimeError):
        costing.fetch_ecb_rate(bad)
    junk = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"x": 1})))
    with pytest.raises(RuntimeError):
        costing.fetch_ecb_rate(junk)


async def test_fx_endpoints(auth_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    body = (await auth_client.get("/admin/fx")).json()
    assert body["current"]["is_default"] is True and body["history"] == []
    body = (await auth_client.put("/admin/fx", json={"rate": 0.9})).json()
    assert body["current"]["source"] == "user" and body["current"]["rate"] == 0.9
    assert (await auth_client.put("/admin/fx", json={"rate": -1})).status_code == 422

    monkeypatch.setattr("elysium_engine.api.routers.admin.fetch_ecb_rate", lambda: (0.87, "2026-11-07"))
    body = (await auth_client.post("/admin/fx/refresh")).json()
    assert body["current"]["source"] == "ecb" and len(body["history"]) == 2

    def boom() -> tuple[float, str]:
        raise RuntimeError("offline")

    monkeypatch.setattr("elysium_engine.api.routers.admin.fetch_ecb_rate", boom)
    assert (await auth_client.post("/admin/fx/refresh")).status_code == 502


# -------------------------------------------------- estimated / reported / unknown


def test_api_call_is_estimated_from_catalog_rates() -> None:
    quote = costing.FxQuote(0.5, "user", "2026-11-07")
    rates = costing.model_rates("openai", "gpt-6-luna")
    assert rates is not None
    figures = costing.figures_for(
        "openai", "gpt-6-luna", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}, quote
    )
    assert figures.billing == "api" and figures.kind == "estimated"
    assert figures.cost_usd == pytest.approx(rates[0] + rates[1])
    assert figures.cost_eur == pytest.approx((rates[0] + rates[1]) * 0.5) and figures.fx_rate == 0.5


def test_subscription_without_a_figure_is_unknown_not_zero() -> None:
    quote = costing.FxQuote(0.9, "user", "2026-11-07")
    figures = costing.figures_for("codex", "default", {"input_tokens": 500, "output_tokens": 5}, quote)
    assert (figures.billing, figures.kind) == ("subscription", "none")
    assert figures.cost_usd is None and figures.cost_eur is None


def test_vendor_reported_cost_is_kept_as_reported() -> None:
    quote = costing.FxQuote(0.9, "user", "2026-11-07")
    figures = costing.figures_for("claude-code", "default", {"cost_usd": 0.02}, quote)
    assert (figures.billing, figures.kind, figures.cost_usd) == ("subscription", "reported", 0.02)
    assert figures.cost_eur == pytest.approx(0.018)


def test_local_model_is_free_and_says_so() -> None:
    quote = costing.FxQuote(0.9, "user", "2026-11-07")
    figures = costing.figures_for("ollama", "llama3", {"input_tokens": 10_000}, quote)
    assert (figures.billing, figures.kind, figures.cost_usd) == ("local", "estimated", 0.0)


def test_cache_tokens_are_priced_with_documented_factors() -> None:
    rates = (10.0, 0.0, "anthropic")  # $10 / Mtok input, Anthropic: input excludes cache
    cost = costing.estimate_cost_usd(
        rates, input_tokens=1_000_000, output_tokens=0, cache_read=1_000_000, cache_write=1_000_000
    )
    assert cost == pytest.approx(10 + 10 * 0.1 + 10 * 1.25)
    rates = (10.0, 0.0, "openai")  # OpenAI: prompt_tokens INCLUDES the cached part
    cost = costing.estimate_cost_usd(rates, input_tokens=1_000_000, output_tokens=0, cache_read=400_000)
    assert cost == pytest.approx(0.6 * 10 + 0.4 * 10 * 0.5)


# ---------------------------------------------------------------- persistence


def _row(app, **kw):  # type: ignore[no-untyped-def]
    defaults = dict(
        provider="openai", model="gpt-6-luna", agent_name="A", conversation_id=None,
        usage={"input_tokens": 1000, "output_tokens": 500}, duration_ms=10,
    )  # fmt: skip
    return record_usage(app.state.session_factory, **{**defaults, **kw})


def test_writes_are_idempotent_per_request_id(app) -> None:  # type: ignore[no-untyped-def]
    assert _row(app, request_id="abc") is True
    assert _row(app, request_id="abc") is False  # a replay is ignored, not double-counted
    assert _row(app, request_id="def") is True
    with app.state.session_factory() as s:
        assert s.scalar(select(func.count(UsageRecord.id))) == 2


def test_history_keeps_the_rate_it_was_converted_with(app) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    costing.set_rate(sf, 1.0, "user")
    _row(app, request_id="old", usage={"input_tokens": 1_000_000, "output_tokens": 0})
    costing.set_rate(sf, 2.0, "user")
    _row(app, request_id="new", usage={"input_tokens": 1_000_000, "output_tokens": 0})
    with sf() as s:
        old = s.scalar(select(UsageRecord).where(UsageRecord.request_id == "old"))
        new = s.scalar(select(UsageRecord).where(UsageRecord.request_id == "new"))
    assert old.fx_rate == 1.0 and new.fx_rate == 2.0
    assert new.cost_eur == pytest.approx(old.cost_eur * 2)  # same call, newer rate; old row untouched


def test_failed_calls_carry_no_cost(app) -> None:  # type: ignore[no-untyped-def]
    _row(app, request_id="e", status="error", error="boom")
    with app.state.session_factory() as s:
        row = s.scalar(select(UsageRecord))
    assert row.cost_kind == "none" and row.cost_usd is None and row.cost_eur is None


async def test_overview_keeps_reported_estimated_and_unknown_apart(auth_client, app) -> None:  # type: ignore[no-untyped-def]
    _row(app, request_id="1")  # API, estimated
    _row(app, request_id="2", provider="claude-code", model="default", usage={"input_tokens": 9, "cost_usd": 0.5})
    _row(app, request_id="3", provider="codex", model="default", usage={"input_tokens": 9})  # unknown
    _row(app, request_id="4", usage={"input_tokens": 100, "cache_read_tokens": 40, "cache_write_tokens": 10})
    body = (await auth_client.get("/admin/overview")).json()
    totals = body["totals"]
    assert totals["calls"] == 4 and totals["cost_reported_usd"] == 0.5
    assert totals["cost_estimated_usd"] > 0 and totals["unknown_cost_calls"] == 1
    assert totals["cache_tokens"] == 50
    assert totals["cost_usd"] == pytest.approx(totals["cost_reported_usd"] + totals["cost_estimated_usd"])
    by_billing = {g["key"]: g for g in body["by_billing"]}
    assert set(by_billing) == {"api", "subscription"}
    assert by_billing["subscription"]["calls"] == 2 and by_billing["api"]["calls"] == 2
    codex = next(g for g in body["by_provider"] if g["key"] == "codex")
    assert codex["cost_usd"] == 0.0 and codex["unknown_cost_calls"] == 1  # unknown, flagged as such


# --------------------------------------------------------------------- quotas


def test_quota_states_unknown_stale_exhausted_ok() -> None:
    now = 1_000_000.0
    assert quota.assess(None, now)["state"] == "unknown"
    fresh = {"updated_at": now - 60, "windows": {"five_hour": {"utilization": 0.4, "resets_at": now + 3600, "status": "allowed"}}}
    assert quota.assess(fresh, now)["state"] == "ok"
    full = {"updated_at": now - 60, "windows": {"five_hour": {"utilization": 1.0, "resets_at": now + 3600, "status": "rejected"}}}
    assert quota.assess(full, now)["state"] == "exhausted"
    old = {"updated_at": now - 3 * 3600, "windows": {"five_hour": {"utilization": 0.1, "resets_at": now + 3600, "status": "allowed"}}}
    assert quota.assess(old, now)["state"] == "stale"
    moved_on = {"updated_at": now - 60, "windows": {"five_hour": {"utilization": 1.0, "resets_at": now - 5, "status": "rejected"}}}
    assert quota.assess(moved_on, now)["state"] == "stale"  # the window reset since: not "exhausted" anymore


def test_quota_readings_survive_a_restart(app) -> None:  # type: ignore[no-untyped-def]
    quota.configure(app.state.session_factory)
    quota.record_quota("claude-code", {"five_hour": {"utilization": 0.7, "resetsAt": time.time() + 600, "status": "allowed"}})
    quota.reset()  # "restart": memory gone
    assert quota.latest_quotas() == {}
    quota.configure(app.state.session_factory)  # reload from the database
    reading = quota.latest_quotas()["claude-code"]
    assert reading["windows"]["five_hour"]["utilization"] == 0.7
    assert quota.assess(reading)["state"] == "ok"
