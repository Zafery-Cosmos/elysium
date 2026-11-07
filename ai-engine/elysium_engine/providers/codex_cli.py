"""Codex adapter: chat through the user's own ``codex`` CLI (ChatGPT login).

Same principle as :mod:`claude_code`: the official CLI runs on the user's
machine with *their* account; Elysium only exchanges text with it.  Codex has
no switch to disable its tools, so it runs with a **read-only sandbox, in an
empty directory, ephemeral session** — it cannot write anything and sees none
of the user's files.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from elysium_engine.providers.base import (
    ChatMessage,
    Chunk,
    Effort,
    ModelInfo,
    ModelProvider,
    ProviderError,
    ToolSpec,
)
from elysium_engine.providers.cli_common import (
    DEFAULT_CLI_TIMEOUT_S,
    LineRunner,
    find_binary,
    render_prompt,
    run_blocking,
    sandbox_dir,
    stream_lines,
)

BINARY = "codex"
# "default" = let Codex use its own configured model (no -m flag).
DEFAULT_MODEL = "default"

NOT_INSTALLED = (
    "codex: the 'codex' CLI was not found. Install Codex "
    "(npm i -g @openai/codex) and sign in with ChatGPT, then retry."
)


async def auth_status(binary: str | None = None) -> tuple[bool, str | None]:
    """``(logged_in, detail)`` from ``codex login status`` (exit 0 = signed in)."""
    exe = binary or find_binary(BINARY)
    if exe is None:
        return False, "Codex CLI not installed"
    code, text = await asyncio.to_thread(run_blocking, [exe, "login", "status"])
    if code == 0:
        return True, None
    return False, text.strip()[:200] or "Not signed in to Codex"


def login_argv(binary: str | None = None, mode: str = "browser") -> list[str]:
    """ChatGPT sign-in command.

    ``browser``: opens the browser and listens on a loopback port.
    ``device``: prints a link plus a one-time code to type there — works when
    the browser is on another machine (or belongs to someone else).
    """
    exe = binary or find_binary(BINARY)
    if exe is None:
        raise ProviderError(NOT_INSTALLED)
    return [exe, "login", "--device-auth"] if mode == "device" else [exe, "login"]


class CodexProvider(ModelProvider):
    def __init__(
        self,
        *,
        name: str = "codex",
        base_url: str = "cli://codex",
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

    def _argv(self, binary: str, model: str, effort: Effort | None) -> list[str]:
        argv = [
            binary,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "-s",
            "read-only",
            "-C",
            str(sandbox_dir()),
        ]
        if model and model != DEFAULT_MODEL:
            argv += ["-m", model]
        if effort is not None:
            argv += ["-c", f'model_reasoning_effort="{effort}"']
        argv.append("-")  # prompt from stdin
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
        if system:
            # Codex has no system-prompt flag: put the instructions up front.
            prompt = f"<instructions>\n{system}\n</instructions>\n\n{prompt}"
        argv = self._argv(binary, model or self.default_model, effort)
        lines = (
            self._runner(argv, prompt, sandbox_dir())
            if self._runner is not None
            else stream_lines(
                argv, prompt, sandbox_dir(), label=self.name, timeout_s=self._timeout_s
            )
        )
        async for chunk in self._parse(lines, stream):
            yield chunk

    async def _parse(self, lines: AsyncIterator[str], stream: bool) -> AsyncIterator[Chunk]:
        messages_out: list[str] = []
        done = False

        async for line in lines:
            if not line.strip():
                continue
            try:
                data: dict[str, Any] = json.loads(line)
            except ValueError:
                continue
            kind = data.get("type")

            if kind == "item.completed":
                item = data.get("item") or {}
                if item.get("type") == "agent_message":
                    text = str(item.get("text", ""))
                    # Codex emits whole messages (no token deltas).
                    if stream:
                        sep = "\n\n" if messages_out else ""
                        yield {"type": "token", "text": sep + text}
                    messages_out.append(text)
            elif kind == "turn.completed":
                if not stream and messages_out:
                    yield {"type": "token", "text": "\n\n".join(messages_out)}
                usage = data.get("usage") or {}
                input_tokens = int(usage.get("input_tokens") or 0)  # includes cached
                yield {
                    "type": "done",
                    "stop_reason": "end_turn",
                    "input_tokens": input_tokens,
                    "output_tokens": usage.get("output_tokens"),
                }
                done = True
            elif kind in ("turn.failed", "error"):
                err = data.get("error")
                message = err.get("message") if isinstance(err, dict) else data.get("message")
                raise ProviderError(f"{self.name}: {message or 'Codex reported an error'}")

        if not done:
            raise ProviderError(f"{self.name}: the CLI ended without a result")
