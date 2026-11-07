"""Claude Code adapter: chat through the user's own ``claude`` CLI login.

No API key, no OAuth token handling: the official CLI is run as a subprocess
on the user's machine and signed in with *their* Claude account.  Used as a
plain chat model — built-in tools are disabled, user settings/MCP are not
loaded and the working directory is an empty sandbox — which also keeps the
prompt tiny (no 30k-token Claude Code system prompt).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from elysium_engine.providers.base import (
    ChatMessage,
    cache_fields,
    Chunk,
    Effort,
    ModelInfo,
    ModelProvider,
    ProviderError,
    ToolSpec,
)
from elysium_engine.providers.quota import record_quota
from elysium_engine.providers.cli_common import (
    DEFAULT_CLI_TIMEOUT_S,
    LineRunner,
    find_binary,
    render_prompt,
    run_blocking,
    sandbox_dir,
    stream_lines,
)

BINARY = "claude"
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."
# "default" = let the CLI pick its own default model (no --model flag).
DEFAULT_MODEL = "default"

NOT_SIGNED_IN = (
    "Claude Code is not signed in inside Elysium. Open Administration and sign in "
    "(Elysium keeps its own session, separate from Claude Code in your terminal)."
)

NOT_INSTALLED = (
    "claude-code: the 'claude' CLI was not found. Install Claude Code "
    "(https://claude.com/claude-code) and sign in, then retry."
)


async def auth_state(
    binary: str | None = None,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """``(logged_in, detail, account)`` from ``claude auth status`` (JSON on stdout).

    ``account`` (when signed in) says *whose* session this is, so the UI can show
    it instead of a bare "connected": email, plan, expiry and sign-in method.
    The CLI session is machine-wide — shared with the user's terminal.
    """
    exe = binary or find_binary(BINARY)
    if exe is None:
        return False, "Claude Code CLI not installed", None
    code, text = await asyncio.to_thread(run_blocking, [exe, "auth", "status"])
    try:
        data = json.loads(text)
    except ValueError:
        return False, f"unexpected output (exit {code}): {text.strip()[:200]}", None
    if data.get("loggedIn"):
        return (
            True,
            None,
            {
                "email": data.get("email"),
                "plan": data.get("subscriptionType") or data.get("planTier"),
                "expires_at": data.get("loginExpiresAt"),
                "method": data.get("authMethod"),
            },
        )
    return False, "Not signed in to Claude Code", None


async def auth_status(binary: str | None = None) -> tuple[bool, str | None]:
    """``(logged_in, detail)`` — see :func:`auth_state`."""
    signed_in, detail, _ = await auth_state(binary)
    return signed_in, detail


async def verify_token(token: str, binary: str | None = None) -> tuple[bool, str | None]:
    """Prove a pasted token works, in isolation from any other session.

    Runs one tiny call with ONLY this token and an empty throw-away config
    folder, so an existing browser sign-in cannot make a bad token look fine.
    It costs a handful of tokens of the user's own plan.
    """
    exe = binary or find_binary(BINARY)
    if exe is None:
        return False, "Claude Code CLI not installed"
    with tempfile.TemporaryDirectory(prefix="elysium-verify-") as scratch:
        argv = [
            exe, "-p", "Reply with the single word OK.",
            "--output-format", "json", "--tools", "", "--no-session-persistence",
            "--setting-sources", "", "--strict-mcp-config",
        ]  # fmt: skip
        code, text = await asyncio.to_thread(
            run_blocking,
            argv,
            90.0,
            {"CLAUDE_CODE_OAUTH_TOKEN": token, "CLAUDE_CONFIG_DIR": scratch},
        )
    if code == 0:
        try:
            data = json.loads(text[text.find("{") :])
        except ValueError:
            return True, None  # exited 0: accepted even if the output shape changes
        if isinstance(data, dict) and data.get("is_error"):
            return False, str(data.get("result") or "The token was rejected.")[:200]
        return True, None
    return False, (text.strip()[:200] or "The token was rejected.")


def logout_argv(binary: str | None = None) -> list[str]:
    exe = binary or find_binary(BINARY)
    if exe is None:
        raise ProviderError(NOT_INSTALLED)
    return [exe, "auth", "logout"]


def login_argv(binary: str | None = None, mode: str = "browser") -> list[str]:
    """Command for the Claude *subscription* sign-in (opens the browser, then
    waits for a pasted code). ``mode`` is ignored: Claude has one flow."""
    exe = binary or find_binary(BINARY)
    if exe is None:
        raise ProviderError(NOT_INSTALLED)
    return [exe, "auth", "login", "--claudeai"]


class ClaudeCodeProvider(ModelProvider):
    def __init__(
        self,
        *,
        name: str = "claude-code",
        base_url: str = "cli://claude",
        default_model: str = DEFAULT_MODEL,
        models: Sequence[ModelInfo] = (),
        runner: LineRunner | None = None,
        binary: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.default_model = default_model
        self._models = tuple(models)
        self._runner = runner
        self._binary = binary
        self._timeout_s = timeout_s or DEFAULT_CLI_TIMEOUT_S

    def models(self) -> Sequence[ModelInfo]:
        return self._models

    async def is_reachable(self) -> bool:
        return find_binary(BINARY) is not None

    def _argv(
        self, binary: str, model: str, effort: Effort | None, system_file: str
    ) -> list[str]:
        argv = [
            binary,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--no-session-persistence",
            "--tools",
            "",  # chat only: no Bash/Edit/Read/... (permission broker stays in charge)
            "--setting-sources",
            "",  # ignore the user's CLAUDE.md / hooks / settings
            "--strict-mcp-config",
            "--system-prompt-file",
            system_file,
        ]
        if model and model != DEFAULT_MODEL:
            argv += ["--model", model]
        if effort is not None:
            argv += ["--effort", effort]
        return argv

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        stream: bool = False,
        model: str | None = None,
        effort: Effort | None = None,
    ) -> AsyncIterator[Chunk]:
        # ``tools`` is ignored on purpose: the CLI is chat-only here.
        binary = self._binary or find_binary(BINARY)
        if binary is None:
            raise ProviderError(NOT_INSTALLED)
        system, prompt = render_prompt(messages)

        fd, system_file = tempfile.mkstemp(prefix="elysium-sys-", suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(system or DEFAULT_SYSTEM_PROMPT)
            argv = self._argv(binary, model or self.default_model, effort, system_file)
            lines = (
                self._runner(argv, prompt, sandbox_dir())
                if self._runner is not None
                else stream_lines(
                    argv, prompt, sandbox_dir(), label=self.name, timeout_s=self._timeout_s
                )
            )
            async for chunk in self._parse(lines, stream):
                yield chunk
        finally:
            Path(system_file).unlink(missing_ok=True)

    async def _parse(self, lines: AsyncIterator[str], stream: bool) -> AsyncIterator[Chunk]:
        buffered: list[str] = []
        saw_delta = False
        fallback_text: list[str] = []
        done = False

        async for line in lines:
            if not line.strip():
                continue
            try:
                data: dict[str, Any] = json.loads(line)
            except ValueError:
                continue  # stray non-JSON output (warnings)
            kind = data.get("type")

            if kind == "stream_event":
                event = data.get("event") or {}
                delta = event.get("delta") or {}
                if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    saw_delta = True
                    if stream:
                        yield {"type": "token", "text": text}
                    else:
                        buffered.append(text)
            elif kind == "assistant":
                # Complete message; only used if partial deltas never arrived.
                for block in (data.get("message") or {}).get("content", []):
                    if block.get("type") == "text":
                        fallback_text.append(block.get("text", ""))
            elif kind == "rate_limit_event":
                # Plan utilization (5-hour / 7-day windows) -> admin dashboard.
                info = data.get("rate_limit_info") or {}
                record_quota(self.name, info.get("unifiedWindows") or {})
            elif kind == "result":
                if data.get("is_error"):
                    message = str(data.get("result") or "Claude Code reported an error")
                    if "not logged in" in message.lower() or "/login" in message:
                        message = NOT_SIGNED_IN
                    raise ProviderError(f"{self.name}: {message}")
                if not saw_delta and fallback_text:
                    text = "".join(fallback_text)
                    yield {"type": "token", "text": text}
                elif buffered:
                    yield {"type": "token", "text": "".join(buffered)}
                usage = data.get("usage") or {}
                # Whole prompt size = fresh + cache-written + cache-read input.
                input_tokens = sum(
                    int(usage.get(k) or 0)
                    for k in (
                        "input_tokens",
                        "cache_creation_input_tokens",
                        "cache_read_input_tokens",
                    )
                )
                yield {
                    "type": "done",
                    "stop_reason": data.get("stop_reason"),
                    "input_tokens": input_tokens,
                    "output_tokens": usage.get("output_tokens"),
                    "cost_usd": data.get("total_cost_usd"),
                    **cache_fields(
                        usage.get("cache_read_input_tokens"), usage.get("cache_creation_input_tokens")
                    ),
                }
                done = True

        if not done:
            raise ProviderError(f"{self.name}: the CLI ended without a result")
