"""OpenAI-compatible Chat Completions adapter (ADR-004).

The lingua franca adapter: with the right ``base_url`` it covers OpenAI,
Ollama (http://localhost:11434/v1), LM Studio, OpenRouter, DeepSeek, Mistral,
vLLM and any other OpenAI-compatible server.  Local servers need no API key.
"""

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

_REASONING_MODEL_RE = re.compile(r"^(gpt-5|o\d)")


def supports_reasoning_effort(model: str) -> bool:
    """Whether an OpenAI-compatible model accepts ``reasoning_effort``.

    Only the o-series (o1, o3, ...) and the gpt-5 family take the parameter;
    other models reject or ignore it, so we omit it for them (best-effort).
    """
    return _REASONING_MODEL_RE.match(model) is not None


class OpenAICompatProvider(ModelProvider):
    def __init__(
        self,
        api_key: str | None,
        *,
        name: str,
        base_url: str,
        default_model: str,
        models: Sequence[ModelInfo] = (),
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._models = tuple(models)
        self._api_key = api_key
        self._client = client

    def models(self) -> Sequence[ModelInfo]:
        return self._models

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
        model: str | None = None,
        effort: Effort | None = None,
    ) -> AsyncIterator[Chunk]:
        resolved_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "stream": stream,
        }
        if effort is not None and supports_reasoning_effort(resolved_model):
            payload["reasoning_effort"] = effort
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
        url = f"{self.base_url}/chat/completions"
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"

        async with client_or_default(self._client) as client:
            if stream:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode(errors="replace")
                        raise ProviderError(f"{self.name}: HTTP {response.status_code}: {body[:500]}")
                    async for chunk in self._parse_sse(response):
                        yield chunk
            else:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    raise ProviderError(
                        f"{self.name}: HTTP {response.status_code}: {response.text[:500]}"
                    )
                for chunk in self._parse_full(response.json()):
                    yield chunk

    async def _parse_sse(self, response: httpx.Response) -> AsyncIterator[Chunk]:
        stop_reason: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        # tool-call index -> {"id": str, "name": str, "arguments": list[str]}
        open_tools: dict[int, dict[str, Any]] = {}

        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            data = json.loads(data_str)
            usage = data.get("usage")
            if usage:
                input_tokens = usage.get("prompt_tokens", input_tokens)
                output_tokens = usage.get("completion_tokens", output_tokens)
            choices = data.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                yield {"type": "token", "text": content}
            for tc in delta.get("tool_calls") or []:
                index = tc.get("index", 0)
                slot = open_tools.setdefault(index, {"id": "", "name": "", "arguments": []})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                function = tc.get("function") or {}
                if function.get("name"):
                    slot["name"] = function["name"]
                if function.get("arguments"):
                    slot["arguments"].append(function["arguments"])
            if choice.get("finish_reason"):
                stop_reason = choice["finish_reason"]

        for slot in (open_tools[i] for i in sorted(open_tools)):
            yield {
                "type": "tool_call",
                "id": slot["id"],
                "name": slot["name"],
                "arguments": _parse_arguments(self.name, slot["name"], "".join(slot["arguments"])),
            }
        yield {
            "type": "done",
            "stop_reason": stop_reason,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    def _parse_full(self, body: dict[str, Any]) -> list[Chunk]:
        chunks: list[Chunk] = []
        choices = body.get("choices") or []
        message: dict[str, Any] = choices[0].get("message", {}) if choices else {}
        if message.get("content"):
            chunks.append({"type": "token", "text": message["content"]})
        for tc in message.get("tool_calls") or []:
            function = tc.get("function") or {}
            chunks.append(
                {
                    "type": "tool_call",
                    "id": tc.get("id", ""),
                    "name": function.get("name", ""),
                    "arguments": _parse_arguments(
                        self.name, function.get("name", ""), function.get("arguments", "")
                    ),
                }
            )
        usage = body.get("usage") or {}
        chunks.append(
            {
                "type": "done",
                "stop_reason": choices[0].get("finish_reason") if choices else None,
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            }
        )
        return chunks


def _parse_arguments(provider: str, tool: str, raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(
            f"{provider}: model produced invalid JSON arguments for tool '{tool}': {exc}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderError(f"{provider}: tool '{tool}' arguments are not a JSON object: {raw!r}")
    return parsed
