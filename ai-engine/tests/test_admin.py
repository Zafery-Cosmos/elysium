"""Admin dashboard: usage aggregation, errors, plan quotas."""

from __future__ import annotations

import json

import pytest

from elysium_engine.providers import quota
from elysium_engine.providers.claude_code import ClaudeCodeProvider
from elysium_engine.usage import record_usage
from tests.conftest import collect


@pytest.fixture(autouse=True)
def _clean_quota():  # type: ignore[no-untyped-def]
    quota.reset()
    yield
    quota.reset()


async def test_overview_is_empty_on_a_fresh_install(auth_client) -> None:  # type: ignore[no-untyped-def]
    body = (await auth_client.get("/admin/overview")).json()
    assert body["totals"]["calls"] == 0
    assert body["providers"] == [] and body["by_day"] == [] and body["quotas"] == []
    assert body["engine"]["version"]


async def test_overview_aggregates_calls_and_errors(auth_client, app) -> None:  # type: ignore[no-untyped-def]
    sf = app.state.session_factory
    record_usage(
        sf,
        provider="claude-code",
        model="default",
        agent_name="Project Manager",
        conversation_id=None,
        usage={"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.01},
        duration_ms=1000,
    )
    record_usage(
        sf,
        provider="openai",
        model="gpt-5.5",
        agent_name="Project Manager",
        conversation_id=None,
        usage={},
        duration_ms=500,
        status="error",
        error="boom",
    )

    body = (await auth_client.get("/admin/overview?days=7")).json()
    assert body["days"] == 7
    totals = body["totals"]
    assert (totals["calls"], totals["errors"]) == (2, 1)
    assert (totals["input_tokens"], totals["output_tokens"]) == (100, 20)
    assert totals["cost_usd"] == 0.01 and totals["avg_duration_ms"] == 750

    by_provider = {g["key"]: g for g in body["by_provider"]}
    assert by_provider["claude-code"]["calls"] == 1 and by_provider["openai"]["errors"] == 1
    assert {g["key"] for g in body["by_model"]} == {"claude-code · default", "openai · gpt-5.5"}
    assert body["by_agent"][0]["key"] == "Project Manager"
    assert sum(d["calls"] for d in body["by_day"]) == 2
    assert body["recent_errors"][0]["message"] == "boom"


async def test_call_for_an_unknown_conversation_is_still_recorded(auth_client, app) -> None:  # type: ignore[no-untyped-def]
    # Usage history must survive the deletion of the conversation it came from.
    record_usage(
        app.state.session_factory,
        provider="codex",
        model="default",
        agent_name=None,
        conversation_id="gone",
        usage={"input_tokens": 5, "output_tokens": 1},
        duration_ms=10,
    )
    body = (await auth_client.get("/admin/overview")).json()
    assert body["totals"]["calls"] == 1 and body["by_agent"][0]["key"] == "—"


async def test_plan_quota_is_captured_from_the_claude_stream(auth_client) -> None:  # type: ignore[no-untyped-def]
    lines = [
        json.dumps(
            {
                "type": "rate_limit_event",
                "rate_limit_info": {
                    "unifiedWindows": {
                        "five_hour": {"utilization": 0.51, "resetsAt": 1794052800, "status": "allowed"},
                        "seven_day": {"utilization": 0.66, "resetsAt": 1794600000},
                    }
                },
            }
        ),
        json.dumps({"type": "result", "is_error": False, "usage": {}, "stop_reason": "end_turn"}),
    ]

    async def runner(argv, stdin, cwd):  # type: ignore[no-untyped-def]
        for line in lines:
            yield line

    provider = ClaudeCodeProvider(runner=runner, binary="claude")
    await collect(provider.chat([{"role": "user", "content": "hi"}]))

    body = (await auth_client.get("/admin/overview")).json()
    [reading] = body["quotas"]
    assert reading["provider"] == "claude-code"
    windows = {w["name"]: w for w in reading["windows"]}
    assert windows["five_hour"]["utilization"] == 0.51
    assert windows["five_hour"]["resets_at"] == 1794052800
    assert windows["seven_day"]["utilization"] == 0.66


async def test_days_is_validated(auth_client) -> None:  # type: ignore[no-untyped-def]
    assert (await auth_client.get("/admin/overview?days=0")).status_code == 422
    assert (await auth_client.get("/admin/overview?days=9999")).status_code == 422


async def test_overview_requires_the_token(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/admin/overview")).status_code in (401, 403)
