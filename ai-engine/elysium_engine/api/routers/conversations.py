"""Messages + the SSE event stream.

Flow (ARCHITECTURE.md §4): POST a user message -> the Project Manager run is
started as a background task and every step lands on the append-only event
log; GET ``/conversations/{id}/stream`` replays persisted events (from the
``after`` cursor) and then relays live events until the run finishes.

SSE event types: ``token``, ``agent_status``, ``decision``, ``action_request``,
``done``, ``error``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from elysium_engine.agents.base import AgentRuntime, EventLog
from elysium_engine.agents.base import Finalizer
from elysium_engine.agents.project_manager import (
    PM_AGENT_NAME,
    build_plan_finalizer,
    build_project_manager,
    pm_finalizer,
    strip_tasks_block,
)
from elysium_engine.api.deps import get_session
from elysium_engine.api.schemas import MessageAccepted, MessageCreate, MessageOut
from elysium_engine.app_settings import AppSettings, deep_merge, default_settings
from elysium_engine.db.models import Conversation, Event, ProviderRecord
from elysium_engine.db.repository import (
    AgentRepository,
    AppSettingsRepository,
    ConversationRepository,
    EventRepository,
    MessageRepository,
    ProviderRepository,
)
from elysium_engine.events import BusEvent
from elysium_engine.providers.base import ModelProvider
from elysium_engine.providers.registry import (
    PromptCacheConfig,
    ProviderCallConfig,
    ProviderRegistry,
)
from elysium_engine.routing import NoModelAvailableError, select_model

router = APIRouter()

_LIVE_POLL_SECONDS = 0.5
_TERMINAL_EVENT_TYPES = ("done", "error")


def _get_or_404(session: Session, conversation_id: str) -> Conversation:
    conversation = ConversationRepository(session).get(conversation_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: str, session: Session = Depends(get_session)
) -> list[MessageOut]:
    _get_or_404(session, conversation_id)
    messages = MessageRepository(session).list_for_conversation(conversation_id)
    return [MessageOut.model_validate(m) for m in messages]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_message(
    conversation_id: str,
    body: MessageCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> MessageAccepted:
    conversation = _get_or_404(session, conversation_id)
    active_runs: dict[str, asyncio.Task[None]] = request.app.state.active_runs
    running = active_runs.get(conversation_id)
    if running is not None and not running.done():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="An agent is still working on this conversation. "
            "Wait for it to finish (watch the stream) before sending a new message.",
        )

    message = MessageRepository(session).add(conversation_id, role="user", content=body.content)

    registry: ProviderRegistry = request.app.state.registry
    provider_records = list(ProviderRepository(session).list())
    event_log = EventLog(request.app.state.session_factory, request.app.state.event_bus)
    app_settings = _load_app_settings(session)
    cache = _prompt_cache_config(app_settings)
    call = _provider_call_config(app_settings)

    if body.model is not None:
        # Per-turn override: "provider:model_id" (model ids may contain ':').
        provider_name, _, model = body.model.partition(":")
        provider = registry.resolve(provider_records, provider_name, cache, call)
        if provider is None:
            event_log.append(
                conversation_id,
                "error",
                {
                    "agent": PM_AGENT_NAME,
                    "message": f"The provider '{provider_name}' is not configured. "
                    "Configure it in Settings > Models or pick another model.",
                    "recoverable": True,
                },
                PM_AGENT_NAME,
            )
            return MessageAccepted(id=message.id, conversation_id=conversation_id)
    else:
        provider, model = _resolve_pm_model(
            registry, provider_records, body.content, cache, call
        )

    # Per-mode post-processing:
    # - discuss: parse the <checklist> block into an understanding decision.
    # - plan: parse the ```tasks block, persist the task graph, and strip the
    #   block from the stored/displayed plan message.
    # - edit: no machine block.
    finalizer: Finalizer | None = None
    text_transform = None
    if body.mode == "discuss":
        finalizer = pm_finalizer
    elif body.mode == "plan":
        valid_roles = AgentRepository(session).role_identifiers(conversation.project_id)
        finalizer = build_plan_finalizer(
            request.app.state.session_factory,
            conversation.project_id,
            conversation_id,
            valid_roles,
        )
        text_transform = strip_tasks_block

    runtime = AgentRuntime(
        agent=build_project_manager(mode=body.mode, execution=body.execution),
        provider=provider,
        model=model,
        event_log=event_log,
        session_factory=request.app.state.session_factory,
        finalizer=finalizer,
        text_transform=text_transform,
        effort=body.effort,
        stream=app_settings.ai.streaming,
    )
    task = asyncio.create_task(runtime.run(conversation_id))
    active_runs[conversation_id] = task
    task.add_done_callback(lambda t: _clear_run(active_runs, conversation_id, t))
    return MessageAccepted(id=message.id, conversation_id=conversation_id)


def _clear_run(
    active_runs: dict[str, asyncio.Task[None]], conversation_id: str, task: asyncio.Task[None]
) -> None:
    if active_runs.get(conversation_id) is task:
        active_runs.pop(conversation_id, None)


def _load_app_settings(session: Session) -> AppSettings:
    """Persisted AppSettings merged over defaults -> a validated document."""
    stored = AppSettingsRepository(session).get_data()
    return AppSettings.model_validate(
        deep_merge(default_settings().model_dump(), stored)
    )


def _prompt_cache_config(settings: AppSettings) -> PromptCacheConfig:
    """Effective prompt-caching config from persisted AppSettings."""
    pc = settings.prompt_caching
    return PromptCacheConfig(
        enabled=pc.enabled, ttl=pc.ttl, min_prefix_tokens=pc.min_prefix_tokens
    )


def _provider_call_config(settings: AppSettings) -> ProviderCallConfig:
    """Effective provider call knobs (max tokens, timeout, retries, streaming)."""
    ai = settings.ai
    return ProviderCallConfig(
        max_tokens=ai.max_response_tokens,
        timeout_s=float(ai.request_timeout_s),
        max_retries=ai.max_retries,
        streaming=ai.streaming,
    )


def _resolve_pm_model(
    registry: ProviderRegistry,
    records: list[ProviderRecord],
    user_content: str,
    cache: PromptCacheConfig | None = None,
    call: ProviderCallConfig | None = None,
) -> tuple[ModelProvider | None, str | None]:
    """Routing for the PM turn; (None, None) when nothing is configured."""
    options = registry.available_options(records)
    est_context_tokens = max(1, len(user_content) // 4) + 2000  # rough: prompt + history
    try:
        choice = select_model("general", est_context_tokens, None, options)
    except NoModelAvailableError:
        return None, None
    provider = registry.resolve(records, choice.provider, cache, call)
    if provider is None:
        return None, None
    return provider, choice.model


@router.get("/conversations/{conversation_id}/stream")
async def stream_events(
    conversation_id: str,
    request: Request,
    after: int = 0,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    _get_or_404(session, conversation_id)
    return StreamingResponse(
        _event_stream(request, conversation_id, after),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


def _format_sse(event_id: int, event_type: str, payload: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(payload)}\n\n"


async def _event_stream(
    request: Request, conversation_id: str, after: int
) -> AsyncIterator[str]:
    bus = request.app.state.event_bus
    active_runs: dict[str, asyncio.Task[None]] = request.app.state.active_runs
    # Subscribe BEFORE the replay snapshot so no event can fall in the gap;
    # duplicates are filtered with the id cursor.
    queue: asyncio.Queue[BusEvent] = bus.subscribe(conversation_id)
    last_id = after
    try:
        with request.app.state.session_factory() as session:
            replayed: list[Event] = list(
                EventRepository(session).list_for_conversation(conversation_id, after_id=after)
            )
        for event in replayed:
            yield _format_sse(event.id, event.type, event.payload)
            last_id = event.id

        while True:
            task = active_runs.get(conversation_id)
            run_active = task is not None and not task.done()
            try:
                bus_event = await asyncio.wait_for(queue.get(), timeout=_LIVE_POLL_SECONDS)
            except TimeoutError:
                if not run_active and queue.empty():
                    break
                continue
            if await request.is_disconnected():
                break
            if bus_event["id"] <= last_id:
                continue
            yield _format_sse(bus_event["id"], bus_event["type"], bus_event["payload"])
            last_id = bus_event["id"]
            if bus_event["type"] in _TERMINAL_EVENT_TYPES:
                break
    finally:
        bus.unsubscribe(conversation_id, queue)
