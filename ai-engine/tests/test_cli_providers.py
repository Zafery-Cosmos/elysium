"""CLI-backed providers (Claude Code / Codex): parsing against canned JSONL.

No real CLI is ever launched — a fake ``runner`` replays recorded output lines.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from elysium_engine.providers.base import ProviderError
from elysium_engine.providers.claude_code import ClaudeCodeProvider
from elysium_engine.providers.cli_common import render_prompt
from elysium_engine.providers.codex_cli import CodexProvider
from tests.conftest import collect

MESSAGES = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "hi"},
]


def _runner(lines: list[str], seen: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
    async def run(argv: Sequence[str], stdin: str, cwd: Path) -> AsyncIterator[str]:
        if seen is not None:
            seen["argv"] = list(argv)
            seen["stdin"] = stdin
            seen["cwd"] = cwd
        for line in lines:
            yield line

    return run


def _j(**kw: object) -> str:
    return json.dumps(kw)


def _delta(text: str) -> str:
    return _j(
        type="stream_event",
        event={
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        },
    )


CLAUDE_LINES = [
    _j(type="system", subtype="init"),
    _delta("Hel"),
    _delta("lo"),
    _j(type="assistant", message={"content": [{"type": "text", "text": "Hello"}]}),
    _j(type="rate_limit_event"),
    _j(
        type="result",
        subtype="success",
        is_error=False,
        stop_reason="end_turn",
        total_cost_usd=0.0021,
        usage={
            "input_tokens": 2,
            "cache_creation_input_tokens": 600,
            "cache_read_input_tokens": 30,
            "output_tokens": 4,
        },
    ),
]


# ------------------------------------------------------------------ claude


async def test_claude_streaming_normalization() -> None:
    seen: dict[str, object] = {}
    provider = ClaudeCodeProvider(runner=_runner(CLAUDE_LINES, seen), binary="claude")
    chunks = await collect(provider.chat(MESSAGES, stream=True, model="claude-sonnet-5"))

    assert chunks == [
        {"type": "token", "text": "Hel"},
        {"type": "token", "text": "lo"},
        {
            "type": "done",
            "stop_reason": "end_turn",
            "input_tokens": 632,  # fresh + cache-written + cache-read
            "output_tokens": 4,
            "cost_usd": 0.0021,
            "cache_read_tokens": 30,
            "cache_write_tokens": 600,
        },
    ]
    argv = seen["argv"]
    assert argv[argv.index("--tools") + 1] == ""  # chat only: tools disabled
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    assert "--setting-sources" in argv and "--strict-mcp-config" in argv
    assert seen["stdin"] == "hi"  # prompt on stdin, not argv


async def test_claude_non_streaming_yields_one_token() -> None:
    provider = ClaudeCodeProvider(runner=_runner(CLAUDE_LINES), binary="claude")
    chunks = await collect(provider.chat(MESSAGES, stream=False))
    assert [c["type"] for c in chunks] == ["token", "done"]
    assert chunks[0] == {"type": "token", "text": "Hello"}


async def test_claude_default_model_and_effort_flags() -> None:
    seen: dict[str, object] = {}
    provider = ClaudeCodeProvider(runner=_runner(CLAUDE_LINES, seen), binary="claude")
    await collect(provider.chat(MESSAGES, effort="high"))
    argv = seen["argv"]
    assert "--model" not in argv  # "default" = the CLI's own default
    assert argv[argv.index("--effort") + 1] == "high"


async def test_claude_falls_back_to_full_message_without_deltas() -> None:
    lines = [CLAUDE_LINES[3], CLAUDE_LINES[5]]  # assistant + result, no deltas
    provider = ClaudeCodeProvider(runner=_runner(lines), binary="claude")
    chunks = await collect(provider.chat(MESSAGES, stream=True))
    assert chunks[0] == {"type": "token", "text": "Hello"}


async def test_claude_error_result_raises() -> None:
    lines = [_j(type="result", is_error=True, result="Overloaded, try again")]
    provider = ClaudeCodeProvider(runner=_runner(lines), binary="claude")
    with pytest.raises(ProviderError, match="Overloaded, try again"):
        await collect(provider.chat(MESSAGES))


async def test_claude_signed_out_error_points_to_elysium_not_the_terminal() -> None:
    lines = [_j(type="result", is_error=True, result="Not logged in · Please run /login")]
    provider = ClaudeCodeProvider(runner=_runner(lines), binary="claude")
    with pytest.raises(ProviderError, match="not signed in inside Elysium") as err:
        await collect(provider.chat(MESSAGES))
    assert "/login" not in str(err.value)


async def test_claude_missing_result_raises() -> None:
    provider = ClaudeCodeProvider(runner=_runner([_delta("x")]), binary="claude")
    with pytest.raises(ProviderError, match="without a result"):
        await collect(provider.chat(MESSAGES))


async def test_claude_missing_binary_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("elysium_engine.providers.claude_code.find_binary", lambda _n: None)
    provider = ClaudeCodeProvider(runner=_runner([]))
    with pytest.raises(ProviderError, match="not found"):
        await collect(provider.chat(MESSAGES))


# ------------------------------------------------------------------- codex

CODEX_LINES = [
    _j(type="thread.started", thread_id="t"),
    _j(type="turn.started"),
    _j(type="item.completed", item={"id": "i0", "type": "reasoning", "text": "thinking"}),
    _j(type="item.completed", item={"id": "i1", "type": "agent_message", "text": "ok"}),
    _j(
        type="turn.completed",
        usage={"input_tokens": 12779, "cached_input_tokens": 0, "output_tokens": 5},
    ),
]


async def test_codex_normalization_and_flags() -> None:
    seen: dict[str, object] = {}
    provider = CodexProvider(runner=_runner(CODEX_LINES, seen), binary="codex")
    chunks = await collect(
        provider.chat(MESSAGES, stream=True, model="gpt-5.5", effort="low")
    )

    assert chunks == [
        {"type": "token", "text": "ok"},
        {"type": "done", "stop_reason": "end_turn", "input_tokens": 12779, "output_tokens": 5},
    ]
    argv = seen["argv"]
    assert argv[:2] == ["codex", "exec"]
    assert argv[argv.index("-s") + 1] == "read-only"
    assert "--ephemeral" in argv and argv[-1] == "-"
    assert argv[argv.index("-m") + 1] == "gpt-5.5"
    assert 'model_reasoning_effort="low"' in argv
    # System prompt has no flag: it is prepended to the stdin prompt.
    assert str(seen["stdin"]).startswith("<instructions>\nYou are helpful.")
    assert str(seen["stdin"]).endswith("hi")


async def test_codex_non_streaming_joins_messages() -> None:
    lines = [
        _j(type="item.completed", item={"type": "agent_message", "text": "a"}),
        _j(type="item.completed", item={"type": "agent_message", "text": "b"}),
        _j(type="turn.completed", usage={"input_tokens": 1, "output_tokens": 2}),
    ]
    provider = CodexProvider(runner=_runner(lines), binary="codex")
    chunks = await collect(provider.chat(MESSAGES, stream=False))
    assert chunks[0] == {"type": "token", "text": "a\n\nb"}


async def test_codex_turn_failed_raises() -> None:
    lines = [_j(type="turn.failed", error={"message": "not signed in"})]
    provider = CodexProvider(runner=_runner(lines), binary="codex")
    with pytest.raises(ProviderError, match="not signed in"):
        await collect(provider.chat(MESSAGES))


# ------------------------------------------------------------------ shared


def test_render_prompt_single_user_message_is_verbatim() -> None:
    system, prompt = render_prompt(MESSAGES)
    assert system == "You are helpful."
    assert prompt == "hi"


def test_render_prompt_replays_history() -> None:
    _, prompt = render_prompt(
        [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ]
    )
    assert "[User]\none" in prompt and "[Assistant]\ntwo" in prompt
    assert prompt.index("one") < prompt.index("two") < prompt.index("three")


async def test_registry_exposes_cli_providers(auth_client) -> None:  # type: ignore[no-untyped-def]
    body = (await auth_client.get("/models")).json()
    by_name = {p["name"]: p for p in body["providers"]}
    for name in ("claude-code", "codex"):
        assert by_name[name]["kind"] == "cli"
        assert by_name[name]["models"][0]["id"] == "default"
        assert by_name[name]["models"][0]["input_cost_per_mtok"] == 0.0
