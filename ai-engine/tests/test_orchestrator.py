"""Sequential multi-agent orchestrator ("analyse" expert sub-mode).

End-to-end runs go through the REAL provider build path (ProviderRegistry ->
OpenAICompatProvider) with an httpx.MockTransport standing in for the network —
the same faithful pattern as test_providers.py. No real LLM/network call ever
happens anywhere in this file.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from elysium_engine.agents.base import Agent, EventLog
from elysium_engine.agents.orchestrator import (
    ExpertCompleteNotAvailableError,
    TaskGraphCycleError,
    _topological_order,
    estimate_cost,
    provider_spend_so_far,
    resolve_agent_model,
    run_expert_analysis,
    run_expert_complete,
)
from elysium_engine.app_settings import default_settings
from elysium_engine.db.repository import (
    AgentRepository,
    ConversationRepository,
    EventRepository,
    ProviderRepository,
    TaskRepository,
)
from elysium_engine.providers.base import ModelInfo
from elysium_engine.routing import ModelOption, NoModelAvailableError

# --------------------------------------------------------------- pure functions


def _model_info(id_: str, in_cost: float, out_cost: float) -> ModelInfo:
    return ModelInfo(
        id=id_, context_window=100_000, input_cost_per_mtok=in_cost, output_cost_per_mtok=out_cost
    )


def _agent(name: str = "backend", model_ref: str = "auto") -> Agent:
    return Agent(name=name, role=name.capitalize(), model_ref=model_ref, system_prompt="p")


def test_estimate_cost_uses_catalog_mtok_rates() -> None:
    info = _model_info("m", 2.0, 6.0)
    assert estimate_cost(info, 500_000, 100_000) == pytest.approx(500_000 / 1e6 * 2.0 + 100_000 / 1e6 * 6.0)


def test_provider_spend_so_far_sums_matching_provider_only() -> None:
    events = [
        {"payload": {"provider": "openai", "cost_eur": 1.0}},
        {"payload": {"provider": "deepseek", "cost_eur": 5.0}},
        {"payload": {"provider": "openai", "cost_eur": 0.5}},
        {"payload": {"kind": "task_skipped"}},  # no cost_eur -> ignored
    ]
    assert provider_spend_so_far(events, "openai") == pytest.approx(1.5)
    assert provider_spend_so_far(events, "deepseek") == pytest.approx(5.0)
    assert provider_spend_so_far(events, "mistral") == 0.0


def test_resolve_agent_model_explicit_ref_used_verbatim() -> None:
    provider, model = resolve_agent_model(_agent(model_ref="openai:gpt-4o-mini"), available=[])
    assert (provider, model) == ("openai", "gpt-4o-mini")


def test_resolve_agent_model_invalid_explicit_ref_raises() -> None:
    with pytest.raises(NoModelAvailableError):
        resolve_agent_model(_agent(model_ref="not-a-valid-ref"), available=[])


def test_resolve_agent_model_auto_routes_via_options() -> None:
    options = [
        ModelOption(
            provider="openai", model="gpt-4o-mini", tier="balanced",
            context_window=128_000, input_cost=0.15, output_cost=0.6,
        )
    ]
    provider, _model = resolve_agent_model(_agent(model_ref="auto"), available=options)
    assert provider == "openai"


def test_resolve_agent_model_auto_no_provider_raises() -> None:
    with pytest.raises(NoModelAvailableError):
        resolve_agent_model(_agent(model_ref="auto"), available=[])


# --------------------------------------------------------- dependency ordering


async def _create_project(auth_client: AsyncClient, name: str = "Demo") -> str:
    r = await auth_client.post("/projects", json={"name": name, "description": "d"})
    assert r.status_code == 201
    return r.json()["id"]


async def test_topological_order_respects_dependencies(app: FastAPI, auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client, "Order")
    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        a = repo.create(project_id, "A", "architect")
        b = repo.create(project_id, "B", "backend", depends_on=[a.id])
        c = repo.create(project_id, "C", "qa", depends_on=[b.id])
        tasks = repo.list_by_project(project_id)
        order = _topological_order(tasks)
    assert [t.id for t in order] == [a.id, b.id, c.id]


async def test_topological_order_detects_cycle(app: FastAPI, auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client, "Cycle")
    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        a = repo.create(project_id, "A", "architect")
        b = repo.create(project_id, "B", "backend")
        c = repo.create(project_id, "C", "qa")
        # Wire a genuine cycle after the fact: A <- C <- B <- A.
        repo.update(a, depends_on=[c.id])
        repo.update(b, depends_on=[a.id])
        repo.update(c, depends_on=[b.id])
        tasks = repo.list_by_project(project_id)
        with pytest.raises(TaskGraphCycleError) as exc_info:
            _topological_order(tasks)
    assert {a.id, b.id, c.id} == set(exc_info.value.task_ids)


# --------------------------------------------------------------------- fixtures


def _openai_style_response(prompt_tokens: int = 1000, completion_tokens: int = 500) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"index": 0, "message": {"content": "Looks good."}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


def _mock_chat_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _configure_provider(
    app: FastAPI, name: str, base_url: str, default_model: str
) -> None:
    with app.state.session_factory() as session:
        ProviderRepository(session).upsert(
            name, base_url=base_url, default_model=default_model, is_local=False
        )
        session.commit()
    app.state.secret_store.set(name, "fake-key")


def _pin_agent_model(app: FastAPI, project_id: str, role: str, model_ref: str) -> None:
    with app.state.session_factory() as session:
        record = AgentRepository(session).get_by_role_or_name(project_id, role)
        assert record is not None
        record.model_ref = model_ref
        session.commit()


async def _run_orchestrator(app: FastAPI, project_id: str, **settings_overrides: object) -> str:
    """Create a conversation, run the orchestrator against it, return its id."""
    with app.state.session_factory() as session:
        conversation = ConversationRepository(session).create(project_id)
        conversation_id = conversation.id

    settings = default_settings()
    settings.ai.streaming = False
    for key, value in settings_overrides.items():
        setattr(settings.ai, key, value)

    event_log = EventLog(app.state.session_factory, app.state.event_bus)
    await run_expert_analysis(
        session_factory=app.state.session_factory,
        registry=app.state.registry,
        event_log=event_log,
        project_id=project_id,
        conversation_id=conversation_id,
        app_settings=settings,
    )
    return conversation_id


# ------------------------------------------------------------------ end to end


async def test_orchestrator_no_task_graph_emits_clear_error(
    app: FastAPI, auth_client: AsyncClient
) -> None:
    project_id = await _create_project(auth_client, "Empty")
    conversation_id = await _run_orchestrator(app, project_id)
    with app.state.session_factory() as session:
        events = EventRepository(session).list_for_conversation(conversation_id)
    assert len(events) == 1
    assert events[0].type == "error"
    assert "plan" in events[0].payload["message"].lower()


async def test_orchestrator_happy_path_two_providers(app: FastAPI, auth_client: AsyncClient) -> None:
    app.state.registry.chat_client = _mock_chat_client(lambda r: _openai_style_response())
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-5-mini")
    _configure_provider(app, "deepseek", "https://api.deepseek.com/v1", "deepseek-v4")

    project_id = await _create_project(auth_client, "Happy")
    _pin_agent_model(app, project_id, "architect", "openai:gpt-5-mini")
    _pin_agent_model(app, project_id, "backend", "deepseek:deepseek-v4")

    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        t1 = repo.create(project_id, "Design", "architect")
        t2 = repo.create(project_id, "Build", "backend", depends_on=[t1.id])

    conversation_id = await _run_orchestrator(app, project_id)

    with app.state.session_factory() as session:
        tasks = {t.id: t for t in TaskRepository(session).list_by_project(project_id)}
        events = EventRepository(session).list_for_conversation(conversation_id)

    assert tasks[t1.id].status == "done"
    assert tasks[t2.id].status == "done"
    assert tasks[t1.id].result_summary
    assert tasks[t2.id].result_summary

    done_events = [e for e in events if e.type == "done"]
    assert len(done_events) == 1
    summary = done_events[0].payload
    assert summary["tasks_completed"] == 2
    assert summary["tasks_blocked"] == 0
    assert summary["stopped_for_budget"] is False
    assert set(summary["spend_by_provider"]) == {"openai", "deepseek"}
    assert all(v > 0 for v in summary["spend_by_provider"].values())

    completed_payloads = [
        e.payload for e in events if e.type == "decision" and e.payload.get("kind") == "task_completed"
    ]
    assert {p["provider"] for p in completed_payloads} == {"openai", "deepseek"}


async def test_orchestrator_budget_exhaustion_stops_run(app: FastAPI, auth_client: AsyncClient) -> None:
    # One 1000/500-token call on gpt-5-mini ($0.25/$2.0 per Mtok) costs 0.00125.
    app.state.registry.chat_client = _mock_chat_client(lambda r: _openai_style_response())
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-5-mini")

    project_id = await _create_project(auth_client, "Budget")
    _pin_agent_model(app, project_id, "architect", "openai:gpt-5-mini")

    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        # Three independent tasks (no deps) on the SAME provider; cap allows
        # exactly two calls (2*0.00125=0.0025) before the third is blocked.
        t1 = repo.create(project_id, "One", "architect")
        t2 = repo.create(project_id, "Two", "architect")
        t3 = repo.create(project_id, "Three", "architect")

    conversation_id = await _run_orchestrator(app, project_id, expert_budgets={"openai": 0.002})

    with app.state.session_factory() as session:
        tasks = {t.id: t for t in TaskRepository(session).list_by_project(project_id)}
        events = EventRepository(session).list_for_conversation(conversation_id)

    assert tasks[t1.id].status == "done"
    assert tasks[t2.id].status == "done"
    # The stop point: task 3 is NEVER TOUCHED — still "todo", not blocked/done.
    assert tasks[t3.id].status == "todo"
    assert tasks[t3.id].result_summary is None

    budget_errors = [
        e for e in events if e.type == "error" and e.payload.get("kind") == "budget_exhausted"
    ]
    assert len(budget_errors) == 1

    done_events = [e for e in events if e.type == "done"]
    summary = done_events[0].payload
    assert summary["stopped_for_budget"] is True
    assert summary["tasks_completed"] == 2
    assert summary["tasks_not_started"] == 1


async def test_orchestrator_falls_back_to_affordable_provider(
    app: FastAPI, auth_client: AsyncClient
) -> None:
    app.state.registry.chat_client = _mock_chat_client(lambda r: _openai_style_response())
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-5-mini")
    _configure_provider(app, "deepseek", "https://api.deepseek.com/v1", "deepseek-v4")

    project_id = await _create_project(auth_client, "Fallback")
    # Both tasks route to openai; its budget is exhausted by the first call
    # (0.00125 > 0.001), so the second task must fall back to deepseek.
    _pin_agent_model(app, project_id, "architect", "openai:gpt-5-mini")

    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        t1 = repo.create(project_id, "One", "architect")
        t2 = repo.create(project_id, "Two", "architect")

    conversation_id = await _run_orchestrator(app, project_id, expert_budgets={"openai": 0.001})

    with app.state.session_factory() as session:
        tasks = {t.id: t for t in TaskRepository(session).list_by_project(project_id)}
        events = EventRepository(session).list_for_conversation(conversation_id)

    assert tasks[t1.id].status == "done"
    assert tasks[t2.id].status == "done"  # completed via fallback, not blocked

    completed = {
        e.payload["task_id"]: e.payload["provider"]
        for e in events
        if e.type == "decision" and e.payload.get("kind") == "task_completed"
    }
    assert completed[t1.id] == "openai"
    assert completed[t2.id] == "deepseek"  # fell back, not stuck/blocked on openai

    done_events = [e for e in events if e.type == "done"]
    assert done_events[0].payload["stopped_for_budget"] is False


async def test_orchestrator_one_task_provider_error_blocks_only_that_task(
    app: FastAPI, auth_client: AsyncClient
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    app.state.registry.chat_client = _mock_chat_client(handler)
    _configure_provider(app, "openai", "https://api.openai.com/v1", "gpt-5-mini")

    project_id = await _create_project(auth_client, "PartialFail")
    _pin_agent_model(app, project_id, "architect", "openai:gpt-5-mini")
    _pin_agent_model(app, project_id, "qa", "openai:gpt-5-mini")

    with app.state.session_factory() as session:
        repo = TaskRepository(session)
        # Independent tasks (no deps) so the second is not skipped for unmet
        # dependencies — only for the first task's own provider error.
        t1 = repo.create(project_id, "Fails", "architect")
        t2 = repo.create(project_id, "Independent", "qa")

    conversation_id = await _run_orchestrator(app, project_id)

    with app.state.session_factory() as session:
        tasks = {t.id: t for t in TaskRepository(session).list_by_project(project_id)}
        events = EventRepository(session).list_for_conversation(conversation_id)

    assert tasks[t1.id].status == "blocked"
    assert tasks[t2.id].status == "blocked"  # same failing provider, but NOT skipped
    done_events = [e for e in events if e.type == "done"]
    assert done_events[0].payload["tasks_blocked"] == 2
    assert done_events[0].payload["stopped_for_budget"] is False


async def test_run_expert_complete_rejects_without_mutation(
    app: FastAPI, auth_client: AsyncClient
) -> None:
    project_id = await _create_project(auth_client, "Complet")
    with app.state.session_factory() as session:
        TaskRepository(session).create(project_id, "Task", "architect")

    with pytest.raises(ExpertCompleteNotAvailableError):
        await run_expert_complete(project_id=project_id)

    with app.state.session_factory() as session:
        tasks = TaskRepository(session).list_by_project(project_id)
    assert tasks[0].status == "todo"  # untouched


# ------------------------------------------------------------------- API layer


async def test_message_expert_complete_returns_501_no_mutation(auth_client: AsyncClient) -> None:
    project_a = await _create_project(auth_client, "API-A")
    conv = (
        await auth_client.post(f"/projects/{project_a}/conversations", json={})
    ).json()["id"]
    r = await auth_client.post(
        f"/conversations/{conv}/messages",
        json={"content": "go", "execution": "expert", "expert_submode": "complet"},
    )
    assert r.status_code == 501
    history = (await auth_client.get(f"/conversations/{conv}/messages")).json()
    assert history == []  # no user message was ever persisted


async def test_message_expert_requires_submode(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client, "API-B")
    conv = (
        await auth_client.post(f"/projects/{project_id}/conversations", json={})
    ).json()["id"]
    r = await auth_client.post(
        f"/conversations/{conv}/messages", json={"content": "go", "execution": "expert"}
    )
    assert r.status_code == 422


async def test_message_expert_bad_submode_422(auth_client: AsyncClient) -> None:
    project_id = await _create_project(auth_client, "API-C")
    conv = (
        await auth_client.post(f"/projects/{project_id}/conversations", json={})
    ).json()["id"]
    r = await auth_client.post(
        f"/conversations/{conv}/messages",
        json={"content": "go", "execution": "expert", "expert_submode": "ultra"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- settings


async def test_expert_budgets_round_trip_and_partial_patch(auth_client: AsyncClient) -> None:
    r = await auth_client.patch(
        "/settings", json={"ai": {"expert_budgets": {"openai": 5.0, "deepseek": 2.0}}}
    )
    assert r.status_code == 200
    assert r.json()["ai"]["expert_budgets"] == {"openai": 5.0, "deepseek": 2.0}

    # Patching one provider's cap leaves the other intact; null = unlimited.
    r = await auth_client.patch(
        "/settings", json={"ai": {"expert_budgets": {"openai": None, "deepseek": 2.0}}}
    )
    assert r.status_code == 200
    assert r.json()["ai"]["expert_budgets"] == {"openai": None, "deepseek": 2.0}

    fetched = await auth_client.get("/settings")
    assert fetched.json()["ai"]["expert_budgets"] == {"openai": None, "deepseek": 2.0}
