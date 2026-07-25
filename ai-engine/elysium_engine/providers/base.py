"""``ModelProvider`` ABC and the normalized chunk/message types.

Every adapter yields the same chunk shapes regardless of upstream wire
format, so agents and routing never see provider-specific payloads:

- ``{"type": "token", "text": str}``
- ``{"type": "tool_call", "id": str, "name": str, "arguments": dict}``
- ``{"type": "done", "stop_reason": str | None, "input_tokens": int | None,
   "output_tokens": int | None}``
"""

from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class ChatMessage(TypedDict):
    role: str  # system | user | assistant
    content: str


class ToolSpec(TypedDict):
    """Provider-neutral tool definition (JSON Schema parameters)."""

    name: str
    description: str
    input_schema: dict[str, Any]


class TokenChunk(TypedDict):
    type: Literal["token"]
    text: str


class ToolCallChunk(TypedDict):
    type: Literal["tool_call"]
    id: str
    name: str
    arguments: dict[str, Any]


class DoneChunk(TypedDict):
    type: Literal["done"]
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None


Chunk = TokenChunk | ToolCallChunk | DoneChunk


Effort = Literal["low", "medium", "high"]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Metadata routing and cost display rely on. Costs are USD per Mtok."""

    id: str
    context_window: int
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    display_name: str = ""  # human label; empty -> fall back to ``id``
    release_date: str = ""  # ISO "yyyy-mm"; empty for local/custom models

    @property
    def cost_tier(self) -> int:
        """1 (cheapest, incl. local/free) .. 4 (premium), from input cost/Mtok."""
        if self.input_cost_per_mtok < 1.0:
            return 1
        if self.input_cost_per_mtok < 3.0:
            return 2
        if self.input_cost_per_mtok < 8.0:
            return 3
        return 4


class ProviderError(RuntimeError):
    """Raised for upstream API errors, with enough detail to explain to the user."""


class ModelProvider(ABC):
    """One configured upstream (Anthropic, OpenAI, a local Ollama, ...)."""

    name: str
    base_url: str
    default_model: str

    @abstractmethod
    def models(self) -> Sequence[ModelInfo]:
        """Known models with context/cost metadata."""

    @abstractmethod
    def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
        model: str | None = None,
        effort: Effort | None = None,
    ) -> AsyncIterator[Chunk]:
        """Run a chat completion, yielding normalized chunks.

        Non-streaming calls still yield chunks (one ``token`` with the full
        text, any ``tool_call``s, then ``done``) so callers have one code path.
        ``effort`` is best-effort: adapters pass it through only for models
        that support a reasoning-effort control and silently omit it otherwise.
        """

    async def is_reachable(self) -> bool:
        """Cheap liveness probe of the upstream base URL."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
                response = await client.get(self.base_url)
            return response.status_code < 500
        except httpx.HTTPError:
            return False


@contextlib.asynccontextmanager
async def client_or_default(
    injected: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Use the injected client (tests use a MockTransport) or a fresh one."""
    if injected is not None:
        yield injected
    else:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            yield client
