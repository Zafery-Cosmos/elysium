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

import asyncio
import logging
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.agents.base import Agent, EventLog
from elysium_engine.agents.project_manager import PM_AGENT_NAME
from elysium_engine.app_settings import AppSettings
from elysium_engine.costing import current_rate, figures_for
from elysium_engine.memory.service import build_context, remember_task_result
from elysium_engine.db.models import AgentRecord, ProviderRecord, Task
from elysium_engine.db.repository import AgentRepository, ProviderRepository, TaskRepository
from elysium_engine.providers.base import ModelInfo, ProviderError
from elysium_engine.providers.health import CLI_NAMES, LEDGER, refresh_cli
from elysium_engine.usage import new_request_id, record_usage
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

# A task result up to this size is kept whole; longer ones are condensed by
# `summarize_result` (head + key lines + tail), never cut to the last few chars.
_SUMMARY_FULL_CHARS = 3_000
_SUMMARY_HEAD_CHARS = 1_200
_SUMMARY_TAIL_CHARS = 1_200
_SUMMARY_KEY_CHARS = 1_200
# Budget of prior-work context injected into one task prompt.
_CONTEXT_BUDGET_CHARS = 12_000
_PRIORITY_SHARE_CHARS = 5_000  # ceiling for each *direct dependency*

_KEY_LINE = re.compile(
    r"(?i)^\W*(constraints?|contraintes?|conclusions?|decisions?|décisions?|risks?|risques?|"
    r"recommendations?|recommandations?|to retain|à retenir|assumptions?|hypothèses?|"
    r"requirements?|exigences?|must|doit|decided|décidé)\b"
)

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
    """USD cost of one call from the catalog's USD/Mtok rates (pure, no cache pricing).

    Money handling lives in :mod:`elysium_engine.costing`: the orchestrator
    converts to EUR with the stored, dated rate before comparing with budgets.
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


def _unusable_reason(
    registry: ProviderRegistry,
    records: Sequence[ProviderRecord],
    provider: str,
    budgets: Mapping[str, float | None],
    spend_events: Sequence[Mapping[str, Any]],
) -> tuple[str, str] | None:
    """``("health"|"budget", text)`` when ``provider`` must not be used now, else None."""
    record = next((r for r in records if r.name == provider), None)
    if record is not None:
        state = registry.health(spec_for(record))
        if not state.usable:
            return "health", f"{state.state}" + (f" — {state.detail}" if state.detail else "")
    if not _has_headroom(provider, budgets, spend_events):
        return "budget", "expert-mode budget exhausted"
    return None


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


def summarize_result(text: str) -> str:
    """Condense a task result without losing conclusions or constraints.

    A short answer is kept whole.  A long one keeps its beginning (framing), its
    end (conclusions usually land there) and — from the middle — every line that
    states a constraint / decision / risk / requirement with the lines that
    follow it.  The old behaviour (keep only the last 400 characters) dropped
    all of that.
    """
    text = text.strip()
    if len(text) <= _SUMMARY_FULL_CHARS:
        return text
    head = text[:_SUMMARY_HEAD_CHARS]
    tail = text[-_SUMMARY_TAIL_CHARS:]
    middle_lines = text[_SUMMARY_HEAD_CHARS:-_SUMMARY_TAIL_CHARS].splitlines()
    key: list[str] = []
    used = 0
    index = 0
    while index < len(middle_lines) and used < _SUMMARY_KEY_CHARS:
        line = middle_lines[index].strip()
        if line and _KEY_LINE.match(line):
            block = [line, *[m.strip() for m in middle_lines[index + 1 : index + 4] if m.strip()]]
            chunk = "\n".join(block)
            key.append(chunk)
            used += len(chunk)
            index += len(block)
        else:
            index += 1
    parts = [head, "[… condensed …]"]
    if key:
        parts += ["\n".join(key)[:_SUMMARY_KEY_CHARS], "[…]"]
    parts.append(tail)
    return "\n".join(parts)


def _fit(text: str, limit: int) -> str:
    """Shrink to ``limit`` characters keeping the start and the end."""
    if len(text) <= limit:
        return text
    half = max(1, (limit - 20) // 2)
    return f"{text[:half]}\n[… cut for size …]\n{text[-half:]}"


def _context_lines(task: Task, completed: Sequence[Task]) -> list[str]:
    """Prior work for ``task``, direct dependencies first and in full priority.

    The whole context stays under ``_CONTEXT_BUDGET_CHARS``: dependencies get the
    larger share (they are what this task builds on); other finished tasks are
    squeezed into what remains, oldest first, so nothing silently grows unbounded.
    """
    deps = set(task.depends_on)
    direct = [p for p in completed if p.id in deps]
    others = [p for p in completed if p.id not in deps]
    budget = _CONTEXT_BUDGET_CHARS
    lines: list[str] = []
    for prior in direct:
        summary = _fit((prior.result_summary or "").strip() or "(no summary)", _PRIORITY_SHARE_CHARS)
        budget -= len(summary)
        lines.append(f"- [{prior.agent_role}] {prior.title} (dependency): {summary}")
    for prior in reversed(others):  # most recent first
        room = max(0, min(600, budget))
        if room < 80:
            lines.append("- … (earlier work omitted to keep the context small)")
            break
        summary = _fit((prior.result_summary or "").strip() or "(no summary)", room)
        budget -= len(summary)
        lines.append(f"- [{prior.agent_role}] {prior.title}: {summary}")
    return lines


def _build_task_prompt(task: Task, completed: Sequence[Task]) -> str:
    """The task + prior completed work (bounded, dependencies first). No RAG."""
    lines = [
        f"Task: {task.title}",
        f"Description: {task.description.strip() or '(none provided)'}",
    ]
    context = _context_lines(task, completed)
    if context:
        lines.append("\nContext — prior completed work in this project:")
        lines.extend(context)
    lines.append(
        "\nEXECUTION MODE: ANALYSE. Read, reason and discuss only — do not "
        "write or modify any files. Produce a concise, actionable written "
        "summary of your analysis/recommendation for this task."
    )
    return "\n".join(lines)


async def _call_agent(
    provider: Any,
    messages: list[dict[str, str]],
    model_id: str,
    stream: bool,
    event_log: EventLog,
    conversation_id: str,
    agent_name: str,
    session_factory: sessionmaker[Session] | None = None,
) -> tuple[str, dict[str, int]]:
    """One provider call, emitting `token` events as they arrive (ProviderError propagates).

    Every call is also logged to the usage table (admin dashboard).
    """
    parts: list[str] = []
    usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}
    started = time.monotonic()
    status, error = "ok", None
    request_id = new_request_id()
    try:
        async for chunk in provider.chat(messages, stream=stream, model=model_id):
            if chunk["type"] == "token":
                parts.append(chunk["text"])
                event_log.append(conversation_id, "token", {"text": chunk["text"]}, agent_name)
            elif chunk["type"] == "done":
                usage = {
                    "input_tokens": chunk.get("input_tokens") or 0,
                    "output_tokens": chunk.get("output_tokens") or 0,
                    "cost_usd": chunk.get("cost_usd"),
                    "cache_read_tokens": chunk.get("cache_read_tokens") or 0,
                    "cache_write_tokens": chunk.get("cache_write_tokens") or 0,
                }
            # tool_call chunks: analyse mode never grants tool/file access, so any
            # tool call a model attempts is simply ignored (no broker request).
        LEDGER.note_ok(provider.name)
    except BaseException as exc:
        status, error = "error", str(exc) or type(exc).__name__
        if not isinstance(exc, asyncio.CancelledError):
            LEDGER.note_error(provider.name, error)
        raise
    finally:
        if session_factory is not None:
            record_usage(
                session_factory,
                request_id=request_id,
                provider=provider.name,
                model=model_id,
                agent_name=agent_name,
                conversation_id=conversation_id,
                usage=usage,
                duration_ms=int((time.monotonic() - started) * 1000),
                status=status,
                error=error,
            )
    return "".join(parts), {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_read_tokens": int(usage.get("cache_read_tokens") or 0),
        "cache_write_tokens": int(usage.get("cache_write_tokens") or 0),
        "cost_usd": usage.get("cost_usd"),
    }


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
    # Know whether each subscription CLI is really signed in before routing.
    await refresh_cli(registry, tuple(r.name for r in provider_records if r.name in CLI_NAMES))
    quote = current_rate(session_factory)
    # What the project already knows (decisions, constraints, file map), given to
    # every agent so it need not re-read files or be told things twice.
    with session_factory() as mem_session:
        memory_text = build_context(mem_session, project_id, 1_200)["text"]
    memory_block = f"\n\n# Project memory\n{memory_text}" if memory_text else ""
    available = registry.available_options(
        provider_records, local_only=app_settings.privacy.local_only
    )
    budgets: Mapping[str, float | None] = app_settings.ai.expert_budgets
    cache = None  # keep prompt-cache/call knobs unset here; provider defaults apply
    call = ProviderCallConfig(
        max_tokens=app_settings.ai.max_response_tokens,
        timeout_s=float(app_settings.ai.request_timeout_s),
        max_retries=app_settings.ai.max_retries,
        redact_secrets=app_settings.privacy.redact_secrets_before_send,
        local_only=app_settings.privacy.local_only,
    )
    stream = app_settings.ai.streaming

    spend_events: list[dict[str, Any]] = []
    tasks_done = 0
    tasks_blocked = 0
    tasks_skipped = 0
    stopped_for_budget = False

    for task in order:
        missing = [dep for dep in task.depends_on if dep not in status_by_id]
        if missing:
            # The dependency no longer exists: it can never complete.  Say so
            # (and block) instead of skipping the task silently forever.
            _mark(session_factory, task.id, "blocked", f"Depends on unknown task(s): {missing}")
            status_by_id[task.id] = "blocked"
            tasks_blocked += 1
            emit(
                conversation_id,
                "error",
                {
                    "agent": PM_AGENT_NAME,
                    "task_id": task.id,
                    "message": f"Task '{task.title}' depends on task(s) that do not exist: {missing}.",
                    "recoverable": True,
                },
                PM_AGENT_NAME,
            )
            continue
        unmet = [dep for dep in task.depends_on if status_by_id.get(dep) != "done"]
        if unmet:
            failed_deps = [d for d in unmet if status_by_id.get(d) == "blocked"]
            if failed_deps:
                # A dependency failed: this task cannot run either — mark it, so
                # the board shows why instead of leaving it "todo".
                _mark(session_factory, task.id, "blocked", f"Dependency blocked: {failed_deps}")
                status_by_id[task.id] = "blocked"
                tasks_blocked += 1
            else:
                tasks_skipped += 1
            emit(
                conversation_id,
                "decision",
                {
                    "agent": PM_AGENT_NAME,
                    "kind": "task_skipped",
                    "task_id": task.id,
                    "reason": f"unmet dependencies: {unmet}",
                    "blocked_dependencies": failed_deps,
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
        blocker = _unusable_reason(registry, provider_records, provider_name, budgets, spend_events)
        if blocker is not None:
            cause, reason_text = blocker
            fallback = _find_fallback(task_class, available, budgets, spend_events, provider_name)
            if fallback is None and cause == "health":
                # Not a budget problem: this provider cannot answer, nobody else
                # can stand in.  Block just this task, say why, keep going.
                _mark(session_factory, task.id, "blocked", f"Provider unavailable: {reason_text}")
                status_by_id[task.id] = "blocked"
                tasks_blocked += 1
                emit(
                    conversation_id,
                    "error",
                    {
                        "agent": agent.name,
                        "task_id": task.id,
                        "kind": "provider_unavailable",
                        "provider": provider_name,
                        "message": f"Provider '{provider_name}' cannot answer ({reason_text}) "
                        "and no other provider is available.",
                        "recoverable": True,
                    },
                    agent.name,
                )
                continue
            if fallback is not None:
                emit(
                    conversation_id,
                    "decision",
                    {
                        "agent": agent.name,
                        "kind": "provider_fallback",
                        "task_id": task.id,
                        "from": provider_name,
                        "to": fallback.provider,
                        "model": fallback.model,
                        "reason": reason_text,
                    },
                    agent.name,
                )
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
            {"role": "system", "content": agent.system_prompt + memory_block},
            {"role": "user", "content": prompt},
        ]

        try:
            full_text, usage = await _call_agent(
                provider,
                messages,
                model_id,
                stream,
                event_log,
                conversation_id,
                agent.name,
                session_factory,
            )
        except Exception as exc:  # noqa: BLE001 - any agent failure blocks only this task
            # (ProviderError is the usual case; an unexpected bug must not abort
            # the whole run or leave the task stuck "in_progress" either.)
            if not isinstance(exc, ProviderError):
                log.exception("agent %s crashed on task %s", agent.name, task.id)
            _mark(session_factory, task.id, "blocked", f"Provider error: {exc}")
            status_by_id[task.id] = "blocked"
            tasks_blocked += 1
            emit(
                conversation_id,
                "error",
                {
                    "agent": agent.name,
                    "task_id": task.id,
                    "message": str(exc) or type(exc).__name__,
                    "recoverable": True,
                },
                agent.name,
            )
            emit(conversation_id, "agent_status", {"agent": agent.name, "status": "idle"}, agent.name)
            continue

        if not full_text.strip():
            # An empty answer is an incomplete task, not a success.
            _mark(session_factory, task.id, "blocked", "The model returned an empty answer.")
            status_by_id[task.id] = "blocked"
            tasks_blocked += 1
            emit(
                conversation_id,
                "error",
                {
                    "agent": agent.name,
                    "task_id": task.id,
                    "message": "The model returned an empty answer; the task was not completed.",
                    "recoverable": True,
                },
                agent.name,
            )
            emit(conversation_id, "agent_status", {"agent": agent.name, "status": "idle"}, agent.name)
            continue

        figures = figures_for(provider_name, model_id, usage, quote)
        summary = summarize_result(full_text)
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
            "cache_read_tokens": usage["cache_read_tokens"],
            "cache_write_tokens": usage["cache_write_tokens"],
            "billing": figures.billing,
            "cost_kind": figures.kind,
            "cost_usd": figures.cost_usd,
            "fx_rate": figures.fx_rate,
            # Only per-token (API) spend counts against the EUR budgets: a CLI
            # subscription is bounded by its plan quota, and an unknown cost is
            # not zero.
            "cost_eur": figures.cost_eur if figures.billing == "api" else None,
        }
        spend_events.append({"payload": spend_payload})
        # Short-term memory of what this task concluded (idempotent per task).
        remember_task_result(session_factory, project_id, task.id, f"{task.title} ({agent.name})", summary)
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
