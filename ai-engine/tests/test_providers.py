"""Provider adapters: chunk normalization against mocked httpx transports.

No real LLM API is ever called — every response below is served by an
httpx.MockTransport.
"""

from __future__ import annotations

import json

import httpx
import pytest

from elysium_engine.providers.anthropic import AnthropicProvider
from elysium_engine.providers.base import ProviderError
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
