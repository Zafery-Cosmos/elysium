"""Agent definition + the runtime that executes one agent turn.

The runtime drives a provider chat loop and records everything on the
append-only event log (ADR-005): the UI renders those events, never raw
model output.  Tool calls are recorded as ``action_request`` events — actual
execution belongs to the Rust permission broker (ADR-003), never to Python.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.repository import EventRepository, MessageRepository
from elysium_engine.events import EventBus
from elysium_engine.providers.base import ChatMessage, Effort, ModelProvider, ProviderError

log = logging.getLogger(__name__)

# Inspects the final assistant text and returns extra (event_type, payload)
# events to append — e.g. the PM's understanding update.
Finalizer = Callable[[str], Sequence[tuple[str, dict[str, Any]]]]


@dataclass(frozen=True, slots=True)
class Agent:
    name: str
    role: str
    model_ref: str  # "auto" (routing decides) or "provider:model"
    system_prompt: str
    allowed_tools: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()  # capabilities requestable via the Rust broker
    # Least-privilege permission profile (AI_SYSTEM.md §1).
    filesystem: str = "none"  # none | read | read_write
    shell: bool = False
    network: bool = False


class EventLog:
    """Persist-then-publish: every event hits the DB before any subscriber."""

    def __init__(self, session_factory: sessionmaker[Session], bus: EventBus) -> None:
        self._session_factory = session_factory
        self._bus = bus

    def append(
        self,
        conversation_id: str,
        type_: str,
        payload: dict[str, Any],
        agent_name: str | None = None,
    ) -> int:
        with self._session_factory() as session:
            event = EventRepository(session).append(conversation_id, type_, payload, agent_name)
            event_id = event.id
        self._bus.publish(
            conversation_id,
            {"id": event_id, "type": type_, "payload": payload, "agent": agent_name},
        )
        return event_id


@dataclass(slots=True)
class AgentRuntime:
    """Runs one agent turn for a conversation.

    The caller resolves ``provider``/``model`` (via routing); ``provider=None``
    means nothing is configured and the run reports a recoverable error event
    instead of crashing the request.
    """

    agent: Agent
    provider: ModelProvider | None
    model: str | None
    event_log: EventLog
    session_factory: sessionmaker[Session]
    finalizer: Finalizer | None = None
    effort: Effort | None = None  # forwarded to providers that support it
    # AppSettings.ai.streaming default; non-streaming still yields one token
    # chunk with the full text, so the event flow is unchanged either way.
    stream: bool = True
    max_history: int = field(default=100)

    async def run(self, conversation_id: str) -> None:
        emit = self.event_log.append
        name = self.agent.name
        emit(conversation_id, "agent_status", {"agent": name, "status": "thinking"}, name)
        try:
            if self.provider is None:
                emit(
                    conversation_id,
                    "error",
                    {
                        "agent": name,
                        "message": (
                            "No AI model is configured yet. Add a provider in "
                            "Settings > Models (or configure a local one like Ollama) "
                            "and send your message again."
                        ),
                        "recoverable": True,
                    },
                    name,
                )
                return
            await self._run_chat(conversation_id)
        except ProviderError as exc:
            emit(
                conversation_id,
                "error",
                {"agent": name, "message": str(exc), "recoverable": True},
                name,
            )
        except Exception:
            log.exception("agent %s crashed for conversation %s", name, conversation_id)
            emit(
                conversation_id,
                "error",
                {
                    "agent": name,
                    "message": "The agent hit an internal error. The run was stopped; "
                    "you can retry your message.",
                    "recoverable": True,
                },
                name,
            )
        finally:
            emit(conversation_id, "agent_status", {"agent": name, "status": "idle"}, name)

    async def _run_chat(self, conversation_id: str) -> None:
        assert self.provider is not None
        emit = self.event_log.append
        name = self.agent.name
        messages = self._build_history(conversation_id)

        parts: list[str] = []
        usage: dict[str, Any] = {}
        async for chunk in self.provider.chat(
            messages, stream=self.stream, model=self.model, effort=self.effort
        ):
            if chunk["type"] == "token":
                parts.append(chunk["text"])
                emit(conversation_id, "token", {"text": chunk["text"]}, name)
            elif chunk["type"] == "tool_call":
                # Recorded for the permission broker; deny by default (ADR-003).
                emit(
                    conversation_id,
                    "action_request",
                    {
                        "agent": name,
                        "tool": chunk["name"],
                        "call_id": chunk["id"],
                        "arguments": chunk["arguments"],
                        "status": "pending_approval",
                    },
                    name,
                )
            elif chunk["type"] == "done":
                usage = {
                    "stop_reason": chunk["stop_reason"],
                    "input_tokens": chunk["input_tokens"],
                    "output_tokens": chunk["output_tokens"],
                }

        full_text = "".join(parts)
        with self.session_factory() as session:
            message = MessageRepository(session).add(
                conversation_id, role="assistant", content=full_text, agent_name=name
            )
            message_id = message.id
        if self.finalizer is not None:
            for event_type, payload in self.finalizer(full_text):
                emit(conversation_id, event_type, payload, name)
        emit(
            conversation_id,
            "done",
            {"agent": name, "message_id": message_id, "usage": usage},
            name,
        )

    def _build_history(self, conversation_id: str) -> list[ChatMessage]:
        with self.session_factory() as session:
            rows = MessageRepository(session).list_for_conversation(conversation_id)
        history: list[ChatMessage] = [{"role": "system", "content": self.agent.system_prompt}]
        for row in rows[-self.max_history :]:
            if row.role in ("user", "assistant"):
                history.append({"role": row.role, "content": row.content})
        return history
