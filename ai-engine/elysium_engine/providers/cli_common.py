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

from elysium_engine.mcp.client import safe_environment
from elysium_engine.proctree import kill_pid_tree, spawn_flags, unsafe_shim_argument
from elysium_engine.providers.base import ChatMessage, ProviderError
from elysium_engine.providers.cli_token import env_for as token_env_for
from elysium_engine.providers.redaction import redact_secrets

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


_cli_home: Path | None = None


def set_cli_home(path: Path | None) -> None:
    """Folder holding Elysium's OWN CLI sessions (``claude/`` and ``codex/``)."""
    global _cli_home
    _cli_home = path


def cli_session_home() -> Path | None:
    """Elysium's private folder for the CLI sessions (None when not configured)."""
    return _cli_home


def cli_session_env() -> dict[str, str]:
    """Point each CLI at an Elysium-private session folder.

    ``CLAUDE_CONFIG_DIR`` / ``CODEX_HOME`` relocate where the CLIs keep their
    login, so Elysium is a **separate instance**: it never uses, changes or signs
    out the session of the user's own terminal Claude Code / Codex, and vice
    versa.  Empty when no home is configured (tests, direct use).
    """
    if _cli_home is None:
        return {}
    env: dict[str, str] = {}
    for var, name in (("CLAUDE_CONFIG_DIR", "claude"), ("CODEX_HOME", "codex")):
        folder = _cli_home / name
        folder.mkdir(parents=True, exist_ok=True)
        env[var] = str(folder)
    return env


# What a vendor CLI legitimately needs beyond the OS basics: network proxies and
# custom certificate authorities (corporate networks) and the locale.
_PASSTHROUGH_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "LANG", "LC_ALL", "LC_CTYPE",
    "CLAUDE_CODE_GIT_BASH_PATH",  # Claude Code on Windows needs to find Git Bash
)  # fmt: skip

# Hard ceilings: a runaway CLI must not exhaust memory or hang the engine.
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024


def _clean_env(argv0: str | None = None) -> dict[str, str]:
    """Minimal environment for the child (allow-list, not "everything minus keys").

    A vendor CLI gets what it needs to run and reach the network — never the
    user's other tokens (GitHub, cloud, database...) and never an API key, so the
    *subscription* login is the one used.  Its session lives in Elysium's own
    folders (see :func:`cli_session_env`).
    """
    wanted = {k.upper() for k in _PASSTHROUGH_ENV}
    extra = {k: v for k, v in os.environ.items() if k.upper() in wanted}
    extra.update(cli_session_env())
    if argv0 is not None:
        extra.update(token_env_for(argv0))  # a pasted Claude token goes to `claude` only
    return safe_environment(extra)


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
    if unsafe_shim_argument(argv) is not None:
        raise ProviderError(f"{label}: refused an argument containing shell metacharacters.")
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=_clean_env(str(argv[0])),
            **spawn_flags(),  # own process tree: cancellation kills children too
        )
    except OSError as exc:
        raise ProviderError(f"{label}: cannot start '{argv[0]}': {exc}") from exc

    stderr_tail = bytearray()
    overflow = threading.Event()

    def _put(item: str | None) -> None:
        # The loop may already be closed if the request was cancelled.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(queue.put_nowait, item)

    def _pump_stdout() -> None:
        received = 0
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                received += len(raw)
                if received > MAX_OUTPUT_BYTES:
                    overflow.set()
                    kill_pid_tree(proc.pid)
                    return
                _put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        finally:
            _put(None)

    def _pump_stderr() -> None:
        # Always drained (a full pipe would block the CLI) but only the tail is kept.
        assert proc.stderr is not None
        while chunk := proc.stderr.read1(4096):  # type: ignore[attr-defined]
            stderr_tail.extend(chunk)
            if len(stderr_tail) > MAX_STDERR_BYTES:
                del stderr_tail[: len(stderr_tail) - MAX_STDERR_BYTES]

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
        if overflow.is_set():
            raise ProviderError(
                f"{label}: output exceeded {MAX_OUTPUT_BYTES // (1024 * 1024)} MB; the process was stopped"
            )
        if code != 0:
            tail = redact_secrets(bytes(stderr_tail).decode("utf-8", errors="replace").strip()[-500:])
            raise ProviderError(f"{label}: CLI exited with code {code}: {tail or 'no output'}")
    finally:
        # Timeout, cancellation, consumer gone: the whole tree must die, not
        # just the CLI's own PID (it may have started helpers).
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                kill_pid_tree(proc.pid)
                proc.kill()


def run_blocking(
    argv: Sequence[str],
    timeout_s: float = 20.0,
    env_override: dict[str, str] | None = None,
    stdin_text: str | None = None,
) -> tuple[int, str]:
    """Short synchronous call (auth status). Returns ``(exit_code, stdout+stderr)``."""
    env = _clean_env(str(argv[0]))
    env.update(env_override or {})
    try:
        done = subprocess.run(  # noqa: S603 - argv list, no shell
            list(argv),
            capture_output=True,
            timeout=timeout_s,
            cwd=str(sandbox_dir()),
            env=env,
            input=stdin_text.encode("utf-8") if stdin_text is not None else None,
            creationflags=_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    text = (done.stdout + done.stderr)[:MAX_STDERR_BYTES].decode("utf-8", errors="replace")
    return done.returncode, redact_secrets(text)


