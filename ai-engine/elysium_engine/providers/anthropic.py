"""Anthropic Messages API adapter — plain httpx, no vendor SDK (ADR-004)."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from elysium_engine.providers.base import (
    ChatMessage,
    Chunk,
    Effort,
    ModelInfo,
    ModelProvider,
    ProviderError,
    ToolSpec,
    client_or_default,
)

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MAX_TOKENS = 8192

_VERSIONED_MODEL_RE = re.compile(r"^claude-(opus|sonnet)-(\d+)(?:-(\d+))?")


def supports_effort(model: str) -> bool:
    """Whether an Anthropic model accepts ``output_config: {"effort": ...}``.

    Supported: the Fable family, Opus >= 4.6 and Sonnet >= 4.6 (which
    includes Sonnet 5 and any later major version). Older models reject the
    parameter, so we omit it for them (best-effort contract).
    """
    if model.startswith("claude-fable"):
        return True
    match = _VERSIONED_MODEL_RE.match(model)
    if match is None:
        return False
    version = (int(match.group(2)), int(match.group(3) or 0))
    return version >= (4, 6)


class AnthropicProvider(ModelProvider):
    def __init__(
        self,
        api_key: str,
        *,
        name: str = "anthropic",
        base_url: str = DEFAULT_BASE_URL,
        default_model: str = "claude-sonnet-5",
        models: Sequence[ModelInfo] = (),
        client: httpx.AsyncClient | None = None,
        cache_system_prompt: bool = False,
        cache_ttl: str = "5m",
        cache_min_tokens: int = 0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._models = tuple(models)
        self._api_key = api_key
        self._client = client
        # Prompt caching: mark the (stable) system prompt as an ephemeral cache
        # prefix so it is not re-billed at full rate on every turn. Volatile
        # content (the conversation) stays after the breakpoint and is not
        # cached. Gated by ``cache_min_tokens`` (rough len//4 estimate) so tiny
        # system prompts — never worth a cache write — are left uncached.
        self._cache_system_prompt = cache_system_prompt
        self._cache_ttl = cache_ttl
        self._cache_min_tokens = cache_min_tokens

    def models(self) -> Sequence[ModelInfo]:
        return self._models

    def _should_cache(self, system_text: str) -> bool:
        """Rough token estimate (len // 4) vs the configured minimum prefix."""
        return (len(system_text) // 4) >= self._cache_min_tokens

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
        model: str | None = None,
        effort: Effort | None = None,
    ) -> AsyncIterator[Chunk]:
        payload = self._build_payload(
            messages, tools, stream, model or self.default_model, effort
        )
        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        async with client_or_default(self._client) as client:
            if stream:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        raise ProviderError(await _stream_error(self.name, response))
                    async for chunk in self._parse_sse(response):
                        yield chunk
            else:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    raise ProviderError(_error_text(self.name, response))
                for chunk in self._parse_full(response.json()):
                    yield chunk

    def _build_payload(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None,
        stream: bool,
        model: str,
        effort: Effort | None = None,
    ) -> dict[str, Any]:
        # Anthropic takes system text as a top-level param, not a message role.
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        chat = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] != "system"
        ]
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "messages": chat,
            "stream": stream,
        }
        if system_parts:
            system_text = "\n\n".join(system_parts)
            if self._cache_system_prompt and self._should_cache(system_text):
                # System as a content-block list with an ephemeral cache prefix.
                payload["system"] = [
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral", "ttl": self._cache_ttl},
                    }
                ]
            else:
                payload["system"] = system_text
        if effort is not None and supports_effort(model):
            payload["output_config"] = {"effort": effort}
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["input_schema"],
                }
                for t in tools
            ]
        return payload

    async def _parse_sse(self, response: httpx.Response) -> AsyncIterator[Chunk]:
        input_tokens: int | None = None
        output_tokens: int | None = None
        stop_reason: str | None = None
        # index -> (id, name, accumulated partial_json) for open tool_use blocks
        open_tools: dict[int, tuple[str, str, list[str]]] = {}

        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = json.loads(line[5:].strip())
            kind = data.get("type")
            if kind == "message_start":
                usage = data.get("message", {}).get("usage", {})
                input_tokens = usage.get("input_tokens")
            elif kind == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "tool_use":
                    open_tools[data["index"]] = (block.get("id", ""), block.get("name", ""), [])
            elif kind == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield {"type": "token", "text": delta.get("text", "")}
                elif delta.get("type") == "input_json_delta":
                    tool = open_tools.get(data["index"])
                    if tool is not None:
                        tool[2].append(delta.get("partial_json", ""))
            elif kind == "content_block_stop":
                tool = open_tools.pop(data["index"], None)
                if tool is not None:
                    tool_id, tool_name, parts = tool
                    yield {
                        "type": "tool_call",
                        "id": tool_id,
                        "name": tool_name,
                        "arguments": _parse_tool_arguments(self.name, tool_name, "".join(parts)),
                    }
            elif kind == "message_delta":
                stop_reason = data.get("delta", {}).get("stop_reason", stop_reason)
                output_tokens = data.get("usage", {}).get("output_tokens", output_tokens)
            elif kind == "error":
                raise ProviderError(f"{self.name}: upstream stream error: {data.get('error')}")
            elif kind == "message_stop":
                yield {
                    "type": "done",
                    "stop_reason": stop_reason,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                }

    def _parse_full(self, body: dict[str, Any]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for block in body.get("content", []):
            if block.get("type") == "text":
                chunks.append({"type": "token", "text": block.get("text", "")})
            elif block.get("type") == "tool_use":
                chunks.append(
                    {
                        "type": "tool_call",
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": block.get("input") or {},
                    }
                )
        usage = body.get("usage", {})
        chunks.append(
            {
                "type": "done",
                "stop_reason": body.get("stop_reason"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
        )
        return chunks


def _parse_tool_arguments(provider: str, tool: str, raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            f"{provider}: model produced invalid JSON arguments for tool '{tool}': {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderError(
            f"{provider}: tool '{tool}' arguments are not a JSON object: {raw!r}"
        )
    return parsed


def _error_text(provider: str, response: httpx.Response) -> str:
    return f"{provider}: HTTP {response.status_code}: {response.text[:500]}"


async def _stream_error(provider: str, response: httpx.Response) -> str:
    body = (await response.aread()).decode(errors="replace")
    return f"{provider}: HTTP {response.status_code}: {body[:500]}"
