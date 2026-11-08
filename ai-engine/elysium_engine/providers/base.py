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
import ipaddress
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict
from urllib.parse import urlsplit

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def is_private_url(url: str) -> bool:
    """Whether ``url`` points to this machine or the local network."""
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    if host == "localhost" or "." not in host and ":" not in host:
        return True  # a single-label name only resolves on the local network
    if host.endswith((".localhost", ".local", ".lan", ".internal", ".home.arpa")):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


async def guarded_stream(name: str, chunks: AsyncIterator[Chunk]) -> AsyncIterator[Chunk]:
    """Report transport failures and malformed answers as :class:`ProviderError`.

    Without this, "Ollama is not running" or a proxy's HTML page reached the user
    as an unexplained internal error.
    """
    try:
        async for chunk in chunks:
            yield chunk
    except httpx.HTTPError as exc:
        raise ProviderError(f"{name}: connection failed ({type(exc).__name__}).") from exc
    except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ProviderError(
            f"{name}: the server sent an invalid response ({type(exc).__name__})."
        ) from exc


def default_client(
    timeout_s: float | None = None,
    max_retries: int | None = None,
    *,
    trust_env: bool = True,
) -> httpx.AsyncClient:
    """Build the default outbound client, honouring AppSettings request knobs.

    ``timeout_s`` (``ai.request_timeout_s``) overrides the overall timeout;
    ``max_retries`` (``ai.max_retries``) sets httpx transport-level retries for
    transient connection errors. Both are best-effort: ``None`` keeps defaults.
    ``trust_env=False`` ignores proxy variables: a prompt for a local model must
    not be sent through a proxy.
    """
    timeout = (
        httpx.Timeout(float(timeout_s), connect=min(10.0, float(timeout_s)))
        if timeout_s is not None
        else DEFAULT_TIMEOUT
    )
    transport = (
        httpx.AsyncHTTPTransport(retries=max_retries)
        if max_retries is not None
        else None
    )
    return httpx.AsyncClient(timeout=timeout, transport=transport, trust_env=trust_env)


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
    # Optional: only CLI-backed providers report it (API-equivalent cost of the
    # call, USD). Subscription usage is not billed per token, so this is purely
    # informational for the usage dashboard.
    cost_usd: NotRequired[float | None]
    # Optional, present only when the provider reported cached tokens.
    cache_read_tokens: NotRequired[int]
    cache_write_tokens: NotRequired[int]


def cache_fields(read: int | None, write: int | None = None) -> dict[str, int]:
    """``cache_*_tokens`` entries for a done chunk — only the non-zero ones."""
    out: dict[str, int] = {}
    if read:
        out["cache_read_tokens"] = int(read)
    if write:
        out["cache_write_tokens"] = int(write)
    return out


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
    timeout_s: float | None = None,
    max_retries: int | None = None,
    *,
    trust_env: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    """Use the injected client (tests use a MockTransport) or a fresh one.

    ``timeout_s``/``max_retries`` configure the fresh client only; an injected
    client is returned unchanged so tests keep full control of the transport.
    """
    if injected is not None:
        yield injected
    else:
        async with default_client(timeout_s, max_retries, trust_env=trust_env) as client:
            yield client
