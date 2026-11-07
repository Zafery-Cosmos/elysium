"""Shared plumbing for providers that drive an official vendor CLI.

Elysium never touches OAuth tokens: ``claude`` (Claude Code) and ``codex``
run on the user's own machine, signed in with the user's own account, and we
only exchange text with them over stdin/stdout.  Each CLI is used as a
**chat-only** model: tools are disabled (Claude) or the sandbox is read-only
in an empty directory (Codex), so the CLI's own agent loop can never bypass
the permission broker (ARCHITECTURE.md ADR-003).

Processes are driven with ``subprocess.Popen`` + reader threads rather than
``asyncio.create_subprocess_exec`` so this works on every event loop (the
Windows selector loop has no subprocess support).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path

from elysium_engine.providers.base import ChatMessage, ProviderError

# Test seam: (argv, stdin_text, cwd) -> async iterator of stdout lines.
LineRunner = Callable[[Sequence[str], str, Path], AsyncIterator[str]]

# Seconds before a CLI call is abandoned (overridable via ai.request_timeout_s).
DEFAULT_CLI_TIMEOUT_S = 300.0

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def sandbox_dir() -> Path:
    """Empty, dedicated working directory: the CLI sees none of the user's files."""
    path = Path(tempfile.gettempdir()) / "elysium-cli-sandbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_binary(name: str) -> str | None:
    return shutil.which(name)


def render_prompt(messages: Sequence[ChatMessage]) -> tuple[str, str]:
    """Split ``messages`` into ``(system_text, prompt)`` for a stateless CLI.

    The CLIs take one prompt per invocation, so earlier turns are replayed as a
    transcript.  A lone user message is sent as-is.
    """
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] != "system"]
    if len(turns) == 1 and turns[0]["role"] == "user":
        return system, turns[0]["content"]
    lines = ["Conversation so far:", ""]
    for m in turns:
        who = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"[{who}]\n{m['content']}\n")
    lines.append("Reply as the assistant to the last user message. Output only the reply.")
    return system, "\n".join(lines)


def _clean_env() -> dict[str, str]:
    """Environment for the child: drop API keys so the *subscription* login is used."""
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        env.pop(key, None)
    return env


async def stream_lines(
    argv: Sequence[str],
    stdin_text: str,
    cwd: Path,
    *,
    label: str,
    timeout_s: float = DEFAULT_CLI_TIMEOUT_S,
) -> AsyncIterator[str]:
    """Run ``argv``, feed ``stdin_text``, yield stdout lines as they arrive.

    Raises :class:`ProviderError` if the binary cannot start, the call times
    out, or the process exits non-zero (stderr tail included).  The child is
    always killed if the consumer stops early (cancelled request).
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=_clean_env(),
            creationflags=_NO_WINDOW,
        )
    except OSError as exc:
        raise ProviderError(f"{label}: cannot start '{argv[0]}': {exc}") from exc

    stderr_chunks: list[bytes] = []

    def _put(item: str | None) -> None:
        # The loop may already be closed if the request was cancelled.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(queue.put_nowait, item)

    def _pump_stdout() -> None:
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                _put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        finally:
            _put(None)

    def _pump_stderr() -> None:
        assert proc.stderr is not None
        stderr_chunks.append(proc.stderr.read())

    def _feed_stdin() -> None:
        assert proc.stdin is not None
        with contextlib.suppress(OSError):
            proc.stdin.write(stdin_text.encode("utf-8"))
            proc.stdin.close()

    for target in (_pump_stdout, _pump_stderr, _feed_stdin):
        threading.Thread(target=target, daemon=True).start()

    deadline = loop.time() + timeout_s
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ProviderError(f"{label}: timed out after {timeout_s:.0f}s")
            try:
                line = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise ProviderError(f"{label}: timed out after {timeout_s:.0f}s") from exc
            if line is None:
                break
            yield line
        code = await asyncio.to_thread(proc.wait)
        if code != 0:
            tail = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()[-500:]
            raise ProviderError(f"{label}: CLI exited with code {code}: {tail or 'no output'}")
    finally:
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill()


def run_blocking(argv: Sequence[str], timeout_s: float = 20.0) -> tuple[int, str]:
    """Short synchronous call (auth status). Returns ``(exit_code, stdout+stderr)``."""
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell
            list(argv),
            capture_output=True,
            timeout=timeout_s,
            cwd=str(sandbox_dir()),
            env=_clean_env(),
            creationflags=_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    text = (done.stdout + done.stderr).decode("utf-8", errors="replace")
    return done.returncode, text


