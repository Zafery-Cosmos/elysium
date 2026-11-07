"""Provider health/routing and a more reliable "analyse" run."""

from __future__ import annotations

import httpx
import pytest

from elysium_engine.agents.orchestrator import (
    _build_task_prompt,
    _unusable_reason,
    summarize_result,
)
from elysium_engine.costing import set_rate
from elysium_engine.db.models import ProviderRecord
from elysium_engine.db.repository import EventRepository, TaskRepository
from elysium_engine.providers import quota
from elysium_engine.providers.health import LEDGER, classify_error, refresh_cli
from elysium_engine.providers.registry import KNOWN_PROVIDERS
from tests.test_orchestrator import (
    _configure_provider,
    _create_project,
    _mock_chat_client,
    _openai_style_response,
    _pin_agent_model,
    _run_orchestrator,
)


def _events(app, conversation_id):  # type: ignore[no-untyped-def]
    with app.state.session_factory() as session:
        return list(EventRepository(session).list_for_conversation(conversation_id))


# ------------------------------------------------------------------ classification


@pytest.mark.parametrize(
    ("message", "state"),
    [
        ("HTTP 401: invalid x-api-key", "auth_error"),
        ("Incorrect API key provided", "auth_error"),
        ("claude-code: Not signed in", "auth_error"),
        ("HTTP 429: rate limit reached", "quota_exhausted"),
        ("You exceeded your current quota", "quota_exhausted"),
        ("insufficient_quota", "quota_exhausted"),
        ("timed out after 300s", "unavailable"),
        ("ConnectError: All connection attempts failed", "unavailable"),
    ],
)
def test_error_messages_map_to_health_states(message: str, state: str) -> None:
    assert classify_error(message) == state


def test_api_provider_states(app) -> None:  # type: ignore[no-untyped-def]
    reg = app.state.registry
    spec = KNOWN_PROVIDERS["openai"]
    assert reg.health(spec).state == "not_authenticated"  # no key saved
    app.state.secret_store.set("openai", "k")
    assert reg.health(spec).state == "authenticated" and reg.health(spec).usable
    LEDGER.note_ok("openai")
    assert reg.health(spec).state == "available"
    LEDGER.note_error("openai", "HTTP 401 unauthorized")
    assert reg.health(spec).state == "auth_error" and not reg.health(spec).usable
    LEDGER.note_error("openai", "429 too many requests")
    assert reg.health(spec).state == "quota_exhausted"


def test_error_states_expire(app) -> None:  # type: ignore[no-untyped-def]
    app.state.secret_store.set("openai", "k")
    LEDGER.note_error("openai", "connection refused")
    health = LEDGER.health("openai", kind="openai", configured=True, now=_now() + 3600)
    assert health.state == "authenticated"  # an old failure no longer decides anything


def _now() -> float:
    import time

    return time.time()


async def test_installed_cli_is_not_a_signed_in_cli(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    reg = app.state.registry
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: "x")
    spec = KNOWN_PROVIDERS["claude-code"]
    assert reg.health(spec).state == "unknown"  # never checked: not assumed usable-by-default info

    async def signed_out(name):  # type: ignore[no-untyped-def]
        return False, "Not signed in", None

    monkeypatch.setattr(reg, "cli_state", signed_out)
    await refresh_cli(reg, ("claude-code",))
    assert reg.health(spec).state == "not_authenticated" and not reg.health(spec).usable

    with app.state.session_factory() as s:
        record = ProviderRecord(name="claude-code", base_url="", default_model="default", is_local=False)
        s.add(record)
        s.commit()
        assert reg.available_options([record]) == []  # not routed to while signed out

    async def signed_in(name):  # type: ignore[no-untyped-def]
        return True, None, {"email": "me@example.com"}

    monkeypatch.setattr(reg, "cli_state", signed_in)
    LEDGER.reset()
    await refresh_cli(reg, ("claude-code",))
    assert reg.health(spec).state == "authenticated"
    assert reg.available_options([record])  # now routable


async def test_cli_check_that_hangs_is_cut_off(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    reg = app.state.registry
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: "x")
    monkeypatch.setattr("elysium_engine.providers.health.CLI_CHECK_TIMEOUT_S", 0.2)

    async def hang(name):  # type: ignore[no-untyped-def]
        await asyncio.sleep(30)

    monkeypatch.setattr(reg, "cli_state", hang)
    await refresh_cli(reg, ("codex",))
    assert reg.health(KNOWN_PROVIDERS["codex"]).state == "unavailable"


def test_exhausted_subscription_quota_blocks_routing(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    reg = app.state.registry
    monkeypatch.setattr("elysium_engine.providers.registry.find_binary", lambda _n: "x")
    LEDGER.set_cli("claude-code", True, True, None)
    quota.record_quota(
        "claude-code",
        {"five_hour": {"utilization": 1.0, "resetsAt": _now() + 3600, "status": "rejected"}},
    )
    assert reg.health(KNOWN_PROVIDERS["claude-code"]).state == "quota_exhausted"


# ------------------------------------------------------ routing: no silent fallback


async def test_unusable_provider_is_replaced_and_the_replacement_is_announced(  # type: ignore[no-untyped-def]
    app, auth_client
) -> None:
    app.state.registry.chat_client = _mock_chat_client(lambda r: _openai_style_response())
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-6-luna")
    _configure_provider(app, "deepseek", "https://api.deepseek.com/v1", "deepseek-flash")
    project_id = await _create_project(auth_client, "Fallback")
    _pin_agent_model(app, project_id, "architect", "openai:gpt-6-luna")
    with app.state.session_factory() as s:
        TaskRepository(s).create(project_id, "work", "architect")
    LEDGER.note_error("openai", "HTTP 401 invalid api key")

    conversation_id = await _run_orchestrator(app, project_id)
    events = _events(app, conversation_id)
    fallback = [e.payload for e in events if e.payload.get("kind") == "provider_fallback"]
    assert fallback and fallback[0]["from"] == "openai" and fallback[0]["to"] == "deepseek"
    assert "auth_error" in fallback[0]["reason"]
    done = [e.payload for e in events if e.payload.get("kind") == "task_completed"]
    assert done and all(p["provider"] == "deepseek" for p in done[:1])


async def test_no_usable_provider_blocks_the_task_explicitly(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    app.state.registry.chat_client = _mock_chat_client(lambda r: _openai_style_response())
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-6-luna")
    project_id = await _create_project(auth_client, "NoFallback")
    _pin_agent_model(app, project_id, "architect", "openai:gpt-6-luna")
    with app.state.session_factory() as s:
        TaskRepository(s).create(project_id, "work", "architect")
    LEDGER.note_error("openai", "HTTP 401 invalid api key")

    conversation_id = await _run_orchestrator(app, project_id)
    events = _events(app, conversation_id)
    unavailable = [e.payload for e in events if e.payload.get("kind") == "provider_unavailable"]
    assert unavailable and unavailable[0]["provider"] == "openai"
    with app.state.session_factory() as s:
        architect = [t for t in TaskRepository(s).list_by_project(project_id) if t.agent_role == "architect"]
    assert architect and all(t.status == "blocked" and "unavailable" in t.result_summary for t in architect)


def test_budget_blocker_is_reported_as_budget(app) -> None:  # type: ignore[no-untyped-def]
    app.state.secret_store.set("openai", "k")
    rec = ProviderRecord(name="openai", base_url="https://api.openai.com/v1", default_model="gpt-6-luna", is_local=False)
    spent = [{"payload": {"provider": "openai", "cost_eur": 2.0}}]
    assert _unusable_reason(app.state.registry, [rec], "openai", {"openai": 1.0}, spent) == (
        "budget",
        "expert-mode budget exhausted",
    )
    assert _unusable_reason(app.state.registry, [rec], "openai", {"openai": 5.0}, spent) is None


# ------------------------------------------------------------- money in the run


async def test_budget_spend_is_converted_to_eur_with_the_stored_rate(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    set_rate(app.state.session_factory, 0.5, "user", "2026-11-07")
    app.state.registry.chat_client = _mock_chat_client(lambda r: _openai_style_response(1_000_000, 0))
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-6-luna")
    project_id = await _create_project(auth_client, "Money")
    _pin_agent_model(app, project_id, "architect", "openai:gpt-6-luna")
    with app.state.session_factory() as s:
        TaskRepository(s).create(project_id, "work", "architect")

    conversation_id = await _run_orchestrator(app, project_id)
    payload = next(e.payload for e in _events(app, conversation_id) if e.payload.get("kind") == "task_completed" and e.payload["provider"] == "openai")
    assert payload["billing"] == "api" and payload["cost_kind"] == "estimated"
    assert payload["fx_rate"] == 0.5
    assert payload["cost_eur"] == pytest.approx(payload["cost_usd"] * 0.5) and payload["cost_eur"] > 0


# ----------------------------------------------------------- reliability of tasks


async def test_one_crashing_agent_does_not_abort_the_run(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("unexpected bug in transport")
        return _openai_style_response()

    app.state.registry.chat_client = _mock_chat_client(handler)
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-6-luna")
    project_id = await _create_project(auth_client, "Crash")
    for role in ("architect", "backend"):
        _pin_agent_model(app, project_id, role, "openai:gpt-6-luna")
    with app.state.session_factory() as s:
        TaskRepository(s).create(project_id, "first", "architect")
        TaskRepository(s).create(project_id, "second", "backend")
    conversation_id = await _run_orchestrator(app, project_id)
    summary = next(e.payload for e in _events(app, conversation_id) if e.payload.get("kind") == "expert_analysis_summary")
    assert summary["tasks_completed"] >= 1 and summary["tasks_blocked"] >= 1


async def test_empty_answer_is_an_incomplete_task(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    empty = httpx.Response(
        200,
        json={"choices": [{"index": 0, "message": {"content": "  "}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 0}},
    )
    app.state.registry.chat_client = _mock_chat_client(lambda r: empty)
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-6-luna")
    project_id = await _create_project(auth_client, "Empty")
    _pin_agent_model(app, project_id, "architect", "openai:gpt-6-luna")
    with app.state.session_factory() as s:
        task = TaskRepository(s).create(project_id, "t", "architect")
        task_id = task.id
    await _run_orchestrator(app, project_id)
    with app.state.session_factory() as s:
        task = TaskRepository(s).get(task_id)
    assert task.status == "blocked" and "empty" in task.result_summary


async def test_dependency_on_a_missing_task_is_blocked_with_a_reason(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    app.state.registry.chat_client = _mock_chat_client(lambda r: _openai_style_response())
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-6-luna")
    project_id = await _create_project(auth_client, "Ghost")
    _pin_agent_model(app, project_id, "backend", "openai:gpt-6-luna")
    with app.state.session_factory() as s:
        repo = TaskRepository(s)
        task = repo.create(project_id, "orphan", "backend")
        repo.update(task, depends_on=["ghost-id"])
        task_id = task.id
    conversation_id = await _run_orchestrator(app, project_id)
    with app.state.session_factory() as s:
        task = TaskRepository(s).get(task_id)
    assert task.status == "blocked" and "unknown task" in task.result_summary
    assert any("do not exist" in e.payload.get("message", "") for e in _events(app, conversation_id))


async def test_failed_dependency_blocks_the_dependent_task(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    def always_fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    app.state.registry.chat_client = _mock_chat_client(always_fail)
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-6-luna")
    project_id = await _create_project(auth_client, "Chain")
    for role in ("architect", "backend"):
        _pin_agent_model(app, project_id, role, "openai:gpt-6-luna")
    with app.state.session_factory() as s:
        repo = TaskRepository(s)
        first = repo.create(project_id, "first", "architect")
        second = repo.create(project_id, "second", "backend", depends_on=[first.id])
        second_id = second.id
    await _run_orchestrator(app, project_id, max_retries=0)
    with app.state.session_factory() as s:
        second = TaskRepository(s).get(second_id)
    assert second.status == "blocked" and "Dependency blocked" in second.result_summary


# ------------------------------------------------------------------- summaries


def test_short_results_are_kept_whole() -> None:
    text = "Use PostgreSQL. Constraint: GDPR."
    assert summarize_result(text) == text


def test_long_results_keep_framing_constraints_and_conclusion() -> None:
    filler = "\n".join(f"detail line {i} about the design of module {i}" for i in range(400))
    text = (
        "# Analysis\nFraming sentence at the very start.\n"
        + filler
        + "\nContraintes: données hébergées en UE uniquement.\nCela vaut pour tous les environnements.\n"
        + filler
        + "\nConclusion: choisir PostgreSQL 16 avec réplication."
    )
    out = summarize_result(text)
    assert len(out) < len(text) / 2
    assert "Framing sentence at the very start" in out  # head
    assert "Contraintes: données hébergées en UE uniquement." in out  # constraint from the middle
    assert "Conclusion: choisir PostgreSQL 16" in out  # tail


class _FakeTask:
    def __init__(self, id, role, title, summary, depends_on=()):  # type: ignore[no-untyped-def]
        self.id, self.agent_role, self.title = id, role, title
        self.result_summary, self.depends_on, self.description = summary, list(depends_on), "d"


def test_prompt_context_is_bounded_and_dependencies_come_first() -> None:
    dep = _FakeTask("dep", "architect", "Design", "KEY-CONSTRAINT " + "x" * 4000)
    noise = [_FakeTask(f"n{i}", "qa", f"Noise {i}", "y" * 3000) for i in range(30)]
    task = _FakeTask("t", "backend", "Build", None, depends_on=["dep"])
    prompt = _build_task_prompt(task, [*noise, dep])  # type: ignore[arg-type]
    assert prompt.index("(dependency)") < prompt.index("Noise")
    assert "KEY-CONSTRAINT" in prompt
    assert len(prompt) < 16_000  # 30 x 3000 chars of other work did not blow the context up
    assert "omitted" in prompt  # and the omission is stated, not silent
