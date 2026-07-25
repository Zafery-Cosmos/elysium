"""Provider adapters: chunk normalization against mocked httpx transports.

No real LLM API is ever called — every response below is served by an
httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from elysium_engine.providers.anthropic import DEFAULT_MAX_TOKENS, AnthropicProvider
from elysium_engine.providers.base import DEFAULT_TIMEOUT, ProviderError, default_client
from elysium_engine.providers.openai_compat import OpenAICompatProvider
from tests.conftest import collect

MESSAGES = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "hi"},
]


def _sse(*events: str) -> bytes:
    return ("\n\n".join(events) + "\n\n").encode()


def _mock_client(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- anthropic


def _anthropic_stream_body() -> bytes:
    return _sse(
        'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":12}}}',
        'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text"}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel"}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"lo"}}',
        'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}',
        'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu_1","name":"create_task"}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"title\\": "}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\\"Spec\\"}"}}',
        'event: content_block_stop\ndata: {"type":"content_block_stop","index":1}',
        'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":25}}',
        'event: message_stop\ndata: {"type":"message_stop"}',
    )


async def test_anthropic_streaming_normalization() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200, content=_anthropic_stream_body(), headers={"content-type": "text/event-stream"}
        )

    provider = AnthropicProvider("k-test", client=_mock_client(handler))
    chunks = await collect(provider.chat(MESSAGES, stream=True))

    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "k-test"
    payload = seen["payload"]
    assert payload["system"] == "You are helpful."  # system extracted from messages
    assert payload["messages"] == [{"role": "user", "content": "hi"}]

    assert chunks == [
        {"type": "token", "text": "Hel"},
        {"type": "token", "text": "lo"},
        {"type": "tool_call", "id": "tu_1", "name": "create_task", "arguments": {"title": "Spec"}},
        {"type": "done", "stop_reason": "tool_use", "input_tokens": 12, "output_tokens": 25},
    ]


async def test_anthropic_non_streaming_normalization() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Hello there"},
                    {"type": "tool_use", "id": "tu_2", "name": "t", "input": {"x": 1}},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 4},
            },
        )

    provider = AnthropicProvider("k", client=_mock_client(handler))
    chunks = await collect(provider.chat(MESSAGES))
    assert chunks == [
        {"type": "token", "text": "Hello there"},
        {"type": "tool_call", "id": "tu_2", "name": "t", "arguments": {"x": 1}},
        {"type": "done", "stop_reason": "end_turn", "input_tokens": 3, "output_tokens": 4},
    ]


async def test_anthropic_http_error_raises_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    provider = AnthropicProvider("bad-key", client=_mock_client(handler))
    with pytest.raises(ProviderError, match="401"):
        await collect(provider.chat(MESSAGES))
    with pytest.raises(ProviderError, match="401"):
        await collect(provider.chat(MESSAGES, stream=True))


# ------------------------------------------------------------- openai-compat


def _openai_stream_body() -> bytes:
    return _sse(
        'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}',
        'data: {"choices":[{"index":0,"delta":{"content":" there"}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"plan","arguments":"{\\"steps\\":"}}]}}]}',
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"2}"}}]},"finish_reason":"tool_calls"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":9}}',
        "data: [DONE]",
    )


async def test_openai_compat_streaming_normalization() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, content=_openai_stream_body(), headers={"content-type": "text/event-stream"}
        )

    provider = OpenAICompatProvider(
        "sk-x",
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        client=_mock_client(handler),
    )
    chunks = await collect(provider.chat(MESSAGES, stream=True))

    assert seen["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-x"
    assert chunks == [
        {"type": "token", "text": "Hi"},
        {"type": "token", "text": " there"},
        {"type": "tool_call", "id": "call_1", "name": "plan", "arguments": {"steps": 2}},
        {"type": "done", "stop_reason": "tool_calls", "input_tokens": 7, "output_tokens": 9},
    ]


async def test_openai_compat_local_server_needs_no_key() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"index": 0, "message": {"content": "local hello"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3},
            },
        )

    provider = OpenAICompatProvider(
        None,
        name="ollama",
        base_url="http://localhost:11434/v1",
        default_model="llama3.1:8b",
        client=_mock_client(handler),
    )
    chunks = await collect(provider.chat(MESSAGES))
    assert seen["auth"] is None  # no Authorization header for keyless local servers
    assert chunks == [
        {"type": "token", "text": "local hello"},
        {"type": "done", "stop_reason": "stop", "input_tokens": 2, "output_tokens": 3},
    ]


async def test_openai_compat_invalid_tool_json_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {"name": "t", "arguments": "{not json"},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    provider = OpenAICompatProvider(
        "k", name="openai", base_url="https://api.openai.com/v1",
        default_model="gpt-4.1", client=_mock_client(handler),
    )
    with pytest.raises(ProviderError, match="invalid JSON arguments"):
        await collect(provider.chat(MESSAGES))


# ------------------------------------- AppSettings.ai request knobs (Task 3)


def _capture_payload_handler(seen: dict[str, object]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    return handler


async def test_anthropic_max_tokens_defaults_and_override() -> None:
    seen: dict[str, object] = {}
    provider = AnthropicProvider("k", client=_mock_client(_capture_payload_handler(seen)))
    await collect(provider.chat(MESSAGES))
    assert seen["payload"]["max_tokens"] == DEFAULT_MAX_TOKENS

    seen.clear()
    provider = AnthropicProvider(
        "k", client=_mock_client(_capture_payload_handler(seen)), max_tokens=4096
    )
    await collect(provider.chat(MESSAGES))
    assert seen["payload"]["max_tokens"] == 4096


async def test_openai_max_tokens_key_depends_on_model() -> None:
    def handler_for(seen: dict[str, object]):  # type: ignore[no-untyped-def]
        def handler(request: httpx.Request) -> httpx.Response:
            seen["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"index": 0, "message": {"content": "x"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        return handler

    # Classic model -> max_tokens.
    seen: dict[str, object] = {}
    provider = OpenAICompatProvider(
        "k", name="openai", base_url="https://api.openai.com/v1",
        default_model="gpt-4.1", client=_mock_client(handler_for(seen)), max_tokens=512,
    )
    await collect(provider.chat(MESSAGES))
    assert seen["payload"]["max_tokens"] == 512
    assert "max_completion_tokens" not in seen["payload"]

    # Reasoning model -> max_completion_tokens.
    seen = {}
    provider = OpenAICompatProvider(
        "k", name="openai", base_url="https://api.openai.com/v1",
        default_model="gpt-5", client=_mock_client(handler_for(seen)), max_tokens=512,
    )
    await collect(provider.chat(MESSAGES))
    assert seen["payload"]["max_completion_tokens"] == 512
    assert "max_tokens" not in seen["payload"]

    # No max_tokens configured -> neither key is sent (unchanged behaviour).
    seen = {}
    provider = OpenAICompatProvider(
        "k", name="openai", base_url="https://api.openai.com/v1",
        default_model="gpt-4.1", client=_mock_client(handler_for(seen)),
    )
    await collect(provider.chat(MESSAGES))
    assert "max_tokens" not in seen["payload"]
    assert "max_completion_tokens" not in seen["payload"]


async def test_default_client_honours_timeout_and_retries() -> None:
    # Defaults: unchanged timeout, no explicit retry transport.
    async with default_client() as client:
        assert client.timeout == DEFAULT_TIMEOUT

    # Configured timeout is applied to the outbound client.
    async with default_client(timeout_s=30, max_retries=3) as client:
        assert client.timeout.read == 30.0
        # connect is clamped to <= the overall timeout.
        assert client.timeout.connect == 10.0

    async with default_client(timeout_s=5) as client:
        assert client.timeout.connect == 5.0


class _FakeSecrets:
    def __init__(self, keys: dict[str, str]) -> None:
        self._keys = keys

    def get(self, name: str) -> str | None:
        return self._keys.get(name)

    def set(self, name: str, value: str) -> None:  # pragma: no cover - unused
        self._keys[name] = value

    def delete(self, name: str) -> None:  # pragma: no cover - unused
        self._keys.pop(name, None)


# ------------------------------------------------ model catalog (Task 1, 2026)


def test_known_providers_defaults_and_ids() -> None:
    from elysium_engine.providers.registry import KNOWN_PROVIDERS

    defaults = {name: spec.default_model for name, spec in KNOWN_PROVIDERS.items()}
    assert defaults["anthropic"] == "claude-sonnet-5"
    assert defaults["openai"] == "gpt-5.6-terra"
    assert defaults["xai"] == "grok-4.3"
    assert defaults["google"] == "gemini-3.5-flash"
    assert defaults["deepseek"] == "deepseek-v4-flash"
    assert defaults["mistral"] == "mistral-medium-latest"

    # xAI is a new, OpenAI-compatible remote provider.
    xai = KNOWN_PROVIDERS["xai"]
    assert xai.kind == "openai"
    assert xai.base_url == "https://api.x.ai/v1"
    assert xai.is_local is False

    def ids(name: str) -> set[str]:
        return {m.id for m in KNOWN_PROVIDERS[name].models}

    assert {"claude-fable-5", "claude-opus-4-8", "claude-haiku-4-5"} <= ids("anthropic")
    assert {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "o3"} <= ids("openai")
    assert {"grok-4.5", "grok-4.3", "grok-build-0.1"} == ids("xai")
    assert {"gemini-3-pro-preview", "gemini-3.5-flash", "gemini-2.5-pro"} <= ids("google")
    assert {"deepseek-v4-flash", "deepseek-v4-pro"} <= ids("deepseek")
    assert {"mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"} <= ids(
        "mistral"
    )

    # Every default model actually exists in its provider's catalog.
    for name, spec in KNOWN_PROVIDERS.items():
        assert spec.default_model in {m.id for m in spec.models}, name


def test_every_remote_model_has_display_name_release_date_and_cost_tier() -> None:
    from elysium_engine.providers.registry import KNOWN_PROVIDERS

    for name, spec in KNOWN_PROVIDERS.items():
        for model in spec.models:
            assert model.cost_tier in {1, 2, 3, 4}, (name, model.id)
            if spec.is_local:
                continue  # local models are live-probed; no static metadata
            assert model.display_name, (name, model.id)
            # openrouter/auto is a meta-router with no single release date.
            if name != "openrouter":
                assert model.release_date, (name, model.id)


def test_model_tier_known_for_every_remote_model() -> None:
    from elysium_engine.providers.registry import KNOWN_PROVIDERS, _MODEL_TIERS

    for name, spec in KNOWN_PROVIDERS.items():
        if spec.is_local or name == "openrouter":
            continue
        for model in spec.models:
            assert model.id in _MODEL_TIERS, (name, model.id)


def test_registry_build_threads_call_config_into_providers() -> None:
    from elysium_engine.db.models import ProviderRecord
    from elysium_engine.providers.registry import (
        ProviderCallConfig,
        ProviderRegistry,
        spec_for,
    )

    registry = ProviderRegistry(_FakeSecrets({"anthropic": "sk-x"}))
    call = ProviderCallConfig(max_tokens=2048, timeout_s=42.0, max_retries=4)

    anthropic = registry.build(
        spec_for(ProviderRecord(name="anthropic", base_url="")), call=call
    )
    assert anthropic is not None
    assert anthropic._max_tokens == 2048
    assert anthropic._timeout_s == 42.0
    assert anthropic._max_retries == 4

    openai = registry.build(
        spec_for(ProviderRecord(name="ollama", base_url="", is_local=True)), call=call
    )
    assert openai is not None
    assert openai._max_tokens == 2048
    assert openai._timeout_s == 42.0
    assert openai._max_retries == 4
