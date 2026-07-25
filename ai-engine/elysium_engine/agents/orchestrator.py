"""Sequential multi-agent orchestrator for EXPERT / "analyse" execution.

Executes the persisted task graph a `plan` turn produced (AI_SYSTEM.md §4):
one agent's call completes before the next starts (true parallel execution is
future work — the loop below is written so parallelizing it later only means
replacing the `for` with a scheduler over the same ready-task computation).

Every step is an event on the append-only event log (ADR-005): the frontend's
Team Activity panel renders these, never raw model output. Spend is tracked by
folding a `{provider, model, input_tokens, output_tokens, cost_eur}` payload
into the `decision` event emitted on each successful task (`kind:
"task_completed"`), so it is visible for free and query-able via
:func:`provider_spend_so_far` without a dedicated ledger table.

Two sub-modes (product requirement): "analyse" (this module — read/reason/
discuss, a written summary, no file writes) and "complet" (full execution incl.
writes). "complet" is explicitly OUT OF SCOPE here: :func:`run_expert_complete`
is a stub that raises :class:`ExpertCompleteNotAvailableError` without
touching the database, and the API layer turns that into a 501.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.agents.base import Agent, EventLog
from elysium_engine.agents.project_manager import PM_AGENT_NAME
from elysium_engine.app_settings import AppSettings
from elysium_engine.db.models import AgentRecord, ProviderRecord, Task
from elysium_engine.db.repository import AgentRepository, ProviderRepository, TaskRepository
from elysium_engine.providers.base import ModelInfo, ProviderError
from elysium_engine.providers.registry import (
    ProviderCallConfig,
    ProviderRegistry,
    spec_for,
)
from elysium_engine.routing import (
    ModelOption,
    NoModelAvailableError,
    TaskClass,
    select_model,
)

log = logging.getLogger(__name__)

# Runnable statuses: a fresh "todo" task, or one left "in_progress" by a run
# that crashed mid-call (safe to retry — no partial side effects happen before
# the task is marked done/blocked).
_RUNNABLE_STATUSES = ("todo", "in_progress")

# v1 summary length (spec: "truncating to the last few hundred chars is fine").
_SUMMARY_TAIL_CHARS = 400

# How much of the task's own prompt we budget context tokens for routing.
_EST_CONTEXT_TOKENS = 4_000


class OrchestratorError(RuntimeError):
    """Base class for orchestration-level (not per-task) failures."""


class TaskGraphCycleError(OrchestratorError):
    """The task graph has a dependency cycle among its unresolved tasks."""

    def __init__(self, task_ids: list[str]) -> None:
        self.task_ids = task_ids
        super().__init__(f"Cycle detected in task graph involving tasks: {task_ids}")


class ExpertCompleteNotAvailableError(OrchestratorError):
    """The "complet" expert sub-mode (full execution incl. writes) isn't built yet."""


# --------------------------------------------------------------- Task 2: model

# Coarse role -> routing task-class mapping (documented per the product spec:
# "pick something sensible and documented"). Mirrors AI_SYSTEM.md §6 loosely:
# - the PM arbitrates/frames the whole run -> "architecture" (top tier first).
# - architect/backend/frontend/database/devops are feature-level build work ->
#   "code" (prefers "balanced", then "powerful", then "fast").
# - qa/security are reviewers, not code generators -> "general" (prefers
#   "balanced", then "fast", then "powerful" — rarely needs the top tier).
# Unknown/custom agents default to "general".
ROLE_TASK_CLASS: dict[str, TaskClass] = {
    PM_AGENT_NAME: "architecture",
    "architect": "code",
    "backend": "code",
    "frontend": "code",
    "database": "code",
    "devops": "code",
    "security": "general",
    "qa": "general",
}


def resolve_agent_model(
    agent: Agent,
    available: Sequence[ModelOption],
    est_context_tokens: int = _EST_CONTEXT_TOKENS,
    budget: float | None = None,
) -> tuple[str, str]:
    """Resolve an agent's ``model_ref`` to a concrete ``(provider, model_id)``.

    ``model_ref == "auto"`` routes via :func:`routing.select_model` using the
    coarse role -> task-class mapping above (pure — reuses the existing
    routing logic, no I/O). An explicit ``"provider:model_id"`` ref is used
    **verbatim** (the operator's pin overrides routing entirely; it is not
    checked against ``available`` here — a missing/unconfigured provider
    surfaces later when the caller tries to actually build it).

    Raises :class:`routing.NoModelAvailableError` when ``model_ref == "auto"``
    and no provider is available at all.
    """
    if agent.model_ref != "auto":
        provider_name, sep, model_id = agent.model_ref.partition(":")
        if not sep or not provider_name or not model_id:
            raise NoModelAvailableError(
                f"Agent '{agent.name}' has an invalid model_ref "
                f"'{agent.model_ref}' (expected \"provider:model_id\")."
            )
        return provider_name, model_id

    task_class = ROLE_TASK_CLASS.get(agent.name, "general")
    choice = select_model(task_class, est_context_tokens, budget, available)
    return choice.provider, choice.model


# --------------------------------------------------------------- Task 3: spend


def estimate_cost(model_info: ModelInfo, input_tokens: int, output_tokens: int) -> float:
    """Cost of one call, from the catalog's USD/Mtok rates (pure).

    Mirrors the existing ``ai.cost_guard_eur`` simplification already in this
    codebase: catalog costs are USD/Mtok and are compared directly against
    EUR-labelled budgets with no FX conversion (no exchange-rate source
    exists anywhere in the engine yet).
    """
    input_mtok = input_tokens / 1_000_000
    output_mtok = output_tokens / 1_000_000
    return model_info.input_cost_per_mtok * input_mtok + model_info.output_cost_per_mtok * output_mtok


def provider_spend_so_far(events: Sequence[Mapping[str, Any]], provider: str) -> float:
    """Sum ``cost_eur`` across ``events`` whose payload names ``provider`` (pure).

    ``events`` is any sequence of ``{"payload": {...}}``-shaped mappings — the
    in-memory per-run ledger this module builds, or rows read back from the
    persisted event log (both carry ``provider``/``cost_eur`` in the payload of
    the ``task_completed`` decision events emitted below).
    """
    total = 0.0
    for event in events:
        payload = event.get("payload") or {}
        if payload.get("provider") == provider and payload.get("cost_eur") is not None:
            total += float(payload["cost_eur"])
    return total


def _totals_per_provider(spend_events: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for event in spend_events:
        payload = event.get("payload") or {}
        provider = payload.get("provider")
        cost = payload.get("cost_eur")
        if provider is None or cost is None:
            continue
        totals[provider] = totals.get(provider, 0.0) + float(cost)
    return totals


def _has_headroom(
    provider: str, budgets: Mapping[str, float | None], spend_events: Sequence[Mapping[str, Any]]
) -> bool:
    cap = budgets.get(provider)
    if cap is None:
        return True
    return provider_spend_so_far(spend_events, provider) < cap


def _find_fallback(
    task_class: TaskClass,
    available: Sequence[ModelOption],
    budgets: Mapping[str, float | None],
    spend_events: Sequence[Mapping[str, Any]],
    exclude: str,
) -> ModelOption | None:
    """Reuse routing's fallback chain, restricted to providers with headroom."""
    affordable = [
        option
        for option in available
        if option.provider != exclude and _has_headroom(option.provider, budgets, spend_events)
    ]
    if not affordable:
        return None
    try:
        return select_model(task_class, _EST_CONTEXT_TOKENS, None, affordable)
    except NoModelAvailableError:
        return None


# --------------------------------------------------------- Task 4: task graph


def _topological_order(tasks: Sequence[Task]) -> list[Task]:
    """Kahn's algorithm over runnable tasks; ``done`` tasks satisfy edges as-is.

    Returns a deterministic execution order (ties broken by ``order_index``
    then ``id``).  Raises :class:`TaskGraphCycleError` when one or more
    runnable tasks never reach in-degree 0 — a dependency cycle among them
    (a dependency permanently missing cannot happen here since the API
    validates ``depends_on`` at write time).
    """
    runnable = [t for t in tasks if t.status in _RUNNABLE_STATUSES]
    runnable_ids = {t.id for t in runnable}
    by_id = {t.id: t for t in runnable}
    indegree: dict[str, int] = {t.id: 0 for t in runnable}
    dependents: dict[str, list[str]] = {t.id: [] for t in runnable}
    for t in runnable:
        for dep_id in t.depends_on:
            if dep_id in runnable_ids:
                indegree[t.id] += 1
                dependents[dep_id].append(t.id)

    ready = [t for t in runnable if indegree[t.id] == 0]
    order: list[Task] = []
    seen: set[str] = set()
    while ready:
        ready.sort(key=lambda t: (t.order_index, t.id))
        current = ready.pop(0)
        order.append(current)
        seen.add(current.id)
        for child_id in dependents[current.id]:
            indegree[child_id] -= 1
            if indegree[child_id] == 0:
                ready.append(by_id[child_id])

    stuck = [t.id for t in runnable if t.id not in seen]
    if stuck:
        raise TaskGraphCycleError(stuck)
    return order


def _agent_from_record(record: AgentRecord) -> Agent:
    return Agent(
        name=record.name,
        role=record.role,
        model_ref=record.model_ref,
        system_prompt=record.system_prompt,
        allowed_tools=tuple(record.allowed_tools),
        permissions=tuple(record.permissions),
        filesystem=record.filesystem,  # type: ignore[arg-type]
        shell=record.shell,
        network=record.network,
    )


def _model_info_for(
    provider_records: Sequence[ProviderRecord], provider_name: str, model_id: str
) -> ModelInfo | None:
    for record in provider_records:
        if record.name == provider_name:
            for info in spec_for(record).models:
                if info.id == model_id:
                    return info
    return None


def _build_task_prompt(task: Task, completed: Sequence[Task]) -> str:
    """Simple concatenation (no RAG): the task + prior completed summaries."""
    lines = [
        f"Task: {task.title}",
        f"Description: {task.description.strip() or '(none provided)'}",
    ]
    if completed:
        lines.append("\nContext — prior completed work in this project:")
        for prior in completed:
            summary = (prior.result_summary or "").strip() or "(no summary)"
            lines.append(f"- [{prior.agent_role}] {prior.title}: {summary}")
    lines.append(
        "\nEXECUTION MODE: ANALYSE. Read, reason and discuss only — do not "
        "write or modify any files. Produce a concise, actionable written "
        "summary of your analysis/recommendation for this task."
    )
    return "\n".join(lines)


def _summarize(text: str, limit: int = _SUMMARY_TAIL_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


async def _call_agent(
    provider: Any,
    messages: list[dict[str, str]],
    model_id: str,
    stream: bool,
    event_log: EventLog,
    conversation_id: str,
    agent_name: str,
) -> tuple[str, dict[str, int]]:
    """One provider call, emitting `token` events as they arrive (ProviderError propagates)."""
    parts: list[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    async for chunk in provider.chat(messages, stream=stream, model=model_id):
        if chunk["type"] == "token":
            parts.append(chunk["text"])
            event_log.append(conversation_id, "token", {"text": chunk["text"]}, agent_name)
        elif chunk["type"] == "done":
            usage = {
                "input_tokens": chunk.get("input_tokens") or 0,
                "output_tokens": chunk.get("output_tokens") or 0,
            }
        # tool_call chunks: analyse mode never grants tool/file access, so any
        # tool call a model attempts is simply ignored (no broker request).
    return "".join(parts), usage


async def run_expert_analysis(
    *,
    session_factory: sessionmaker[Session],
    registry: ProviderRegistry,
    event_log: EventLog,
    project_id: str,
    conversation_id: str,
    app_settings: AppSettings,
) -> None:
    """Execute the project's task graph, sequentially, in EXPERT/"analyse" mode.

    Preconditions: a non-empty task graph must already exist (from a `plan`
    turn) — an empty graph emits a clear `error` event and returns without
    touching anything else. A dependency cycle is likewise a hard stop (the
    execution order is undefined otherwise).

    Per task, in dependency order: resolve the owning agent -> resolve its
    model -> check that provider's EXPERT-mode budget headroom (falling back
    to another affordable configured provider, or stopping the *entire* run
    if none has headroom — the only condition that aborts the whole run) ->
    call it -> mark the task done/blocked.

    Asymmetry (per product spec): a provider error on one task only blocks
    that task; the run continues to the next independent task. Budget
    exhaustion (no fallback) is the only thing that stops the whole run, since
    silently degrading spend limits is explicitly not wanted.
    """
    emit = event_log.append

    with session_factory() as session:
        tasks = list(TaskRepository(session).list_by_project(project_id))
        provider_records = list(ProviderRepository(session).list())
        agent_records = list(AgentRepository(session).list_for_project(project_id))
        # Addressable by either "role" (built-ins) or "name" (custom agents),
        # matching AgentRepository.get_by_role_or_name's contract.
        agents_by_ident: dict[str, AgentRecord] = {}
        for record in agent_records:
            agents_by_ident[record.role] = record
            agents_by_ident[record.name] = record

    if not tasks:
        emit(
            conversation_id,
            "error",
            {
                "agent": PM_AGENT_NAME,
                "message": (
                    "No task graph found for this project yet. Run `plan` mode "
                    "first so the Project Manager can generate one, then start "
                    "the expert-mode run again."
                ),
                "recoverable": True,
            },
            PM_AGENT_NAME,
        )
        return

    try:
        order = _topological_order(tasks)
    except TaskGraphCycleError as exc:
        emit(
            conversation_id,
            "error",
            {
                "agent": PM_AGENT_NAME,
                "message": (
                    "The task graph has a dependency cycle and cannot be "
                    f"executed: tasks {exc.task_ids} depend on each other. Fix "
                    "the dependencies on the board and try again."
                ),
                "task_ids": exc.task_ids,
                "recoverable": True,
            },
            PM_AGENT_NAME,
        )
        return

    status_by_id: dict[str, str] = {t.id: t.status for t in tasks}
    completed: list[Task] = [t for t in tasks if t.status == "done"]
    available = registry.available_options(provider_records)
    budgets: Mapping[str, float | None] = app_settings.ai.expert_budgets
    cache = None  # keep prompt-cache/call knobs unset here; provider defaults apply
    call = ProviderCallConfig(
        max_tokens=app_settings.ai.max_response_tokens,
        timeout_s=float(app_settings.ai.request_timeout_s),
        max_retries=app_settings.ai.max_retries,
    )
    stream = app_settings.ai.streaming

    spend_events: list[dict[str, Any]] = []
    tasks_done = 0
    tasks_blocked = 0
    tasks_skipped = 0
    stopped_for_budget = False

    for task in order:
        unmet = [dep for dep in task.depends_on if status_by_id.get(dep) != "done"]
        if unmet:
            tasks_skipped += 1
            emit(
                conversation_id,
                "decision",
                {
                    "agent": PM_AGENT_NAME,
                    "kind": "task_skipped",
                    "task_id": task.id,
                    "reason": f"unmet dependencies: {unmet}",
                },
                PM_AGENT_NAME,
            )
            continue

        record = agents_by_ident.get(task.agent_role)
        if record is None or not record.enabled:
            _mark(session_factory, task.id, "blocked", "No enabled agent for this role.")
            status_by_id[task.id] = "blocked"
            tasks_blocked += 1
            emit(
                conversation_id,
                "error",
                {
                    "agent": PM_AGENT_NAME,
                    "task_id": task.id,
                    "message": f"No enabled agent for role '{task.agent_role}'.",
                    "recoverable": True,
                },
                PM_AGENT_NAME,
            )
            continue

        agent = _agent_from_record(record)

        try:
            provider_name, model_id = resolve_agent_model(agent, available)
        except NoModelAvailableError as exc:
            _mark(session_factory, task.id, "blocked", f"No model available: {exc}")
            status_by_id[task.id] = "blocked"
            tasks_blocked += 1
            emit(
                conversation_id,
                "error",
                {"agent": agent.name, "task_id": task.id, "message": str(exc), "recoverable": True},
                agent.name,
            )
            continue

        task_class = ROLE_TASK_CLASS.get(agent.name, "general")
        if not _has_headroom(provider_name, budgets, spend_events):
            fallback = _find_fallback(task_class, available, budgets, spend_events, provider_name)
            if fallback is None:
                emit(
                    conversation_id,
                    "error",
                    {
                        "agent": PM_AGENT_NAME,
                        "kind": "budget_exhausted",
                        "task_id": task.id,
                        "provider": provider_name,
                        "message": (
                            f"Provider '{provider_name}' has exhausted its expert-mode "
                            "budget and no other configured provider has headroom. "
                            "Stopping the run."
                        ),
                        "recoverable": True,
                    },
                    PM_AGENT_NAME,
                )
                stopped_for_budget = True
                break
            provider_name, model_id = fallback.provider, fallback.model

        model_info = _model_info_for(provider_records, provider_name, model_id)
        provider = registry.resolve(provider_records, provider_name, cache, call)
        if provider is None or model_info is None:
            _mark(session_factory, task.id, "blocked", f"Provider '{provider_name}' not configured.")
            status_by_id[task.id] = "blocked"
            tasks_blocked += 1
            emit(
                conversation_id,
                "error",
                {
                    "agent": agent.name,
                    "task_id": task.id,
                    "message": f"Provider '{provider_name}' is not configured.",
                    "recoverable": True,
                },
                agent.name,
            )
            continue

        _mark(session_factory, task.id, "in_progress", None)
        status_by_id[task.id] = "in_progress"
        emit(conversation_id, "agent_status", {"agent": agent.name, "status": "thinking"}, agent.name)

        prompt = _build_task_prompt(task, completed)
        messages = [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            full_text, usage = await _call_agent(
                provider, messages, model_id, stream, event_log, conversation_id, agent.name
            )
        except ProviderError as exc:
            # Per-task failure: blocks only this task, the run continues.
            _mark(session_factory, task.id, "blocked", f"Provider error: {exc}")
            status_by_id[task.id] = "blocked"
            tasks_blocked += 1
            emit(
                conversation_id,
                "error",
                {"agent": agent.name, "task_id": task.id, "message": str(exc), "recoverable": True},
                agent.name,
            )
            emit(conversation_id, "agent_status", {"agent": agent.name, "status": "idle"}, agent.name)
            continue

        cost = estimate_cost(model_info, usage["input_tokens"], usage["output_tokens"])
        summary = _summarize(full_text)
        updated = _mark(session_factory, task.id, "done", summary)
        status_by_id[task.id] = "done"
        completed.append(updated)
        tasks_done += 1
        spend_payload = {
            "agent": agent.name,
            "kind": "task_completed",
            "task_id": task.id,
            "provider": provider_name,
            "model": model_id,
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cost_eur": cost,
        }
        spend_events.append({"payload": spend_payload})
        emit(conversation_id, "decision", spend_payload, agent.name)
        emit(conversation_id, "agent_status", {"agent": agent.name, "status": "idle"}, agent.name)

    # Tasks never reached because the run stopped for budget exhaustion: they
    # stay "todo" untouched (never marked done or blocked), per spec.
    tasks_not_started = len(order) - (tasks_done + tasks_blocked + tasks_skipped)

    emit(
        conversation_id,
        "done",
        {
            "agent": PM_AGENT_NAME,
            "kind": "expert_analysis_summary",
            "tasks_completed": tasks_done,
            "tasks_blocked": tasks_blocked,
            "tasks_skipped": tasks_skipped,
            "tasks_not_started": tasks_not_started,
            "stopped_for_budget": stopped_for_budget,
            "spend_by_provider": _totals_per_provider(spend_events),
        },
        PM_AGENT_NAME,
    )


def _mark(
    session_factory: sessionmaker[Session],
    task_id: str,
    status: str,
    result_summary: str | None,
) -> Task:
    with session_factory() as session:
        repo = TaskRepository(session)
        task = repo.get(task_id)
        assert task is not None  # loaded from this same project moments ago
        updated = repo.update(task, status=status, result_summary=result_summary)
        session.refresh(updated)
        session.expunge(updated)
        return updated


async def run_expert_complete(**_: Any) -> None:
    """"complet" sub-mode stub: full execution incl. writes. NOT YET AVAILABLE.

    Raises immediately, before any DB read/write, so callers (the API layer)
    can turn this into a clean "not yet available" response with no side
    effects — real file writes are explicitly out of scope for this phase.
    """
    raise ExpertCompleteNotAvailableError(
        "Expert mode 'complet' (full execution including file writes) is not "
        "available yet. Use 'analyse' for now."
    )
