"""Minimal MCP client over the stdio transport (JSON-RPC 2.0, newline-delimited).

Implements what Elysium needs to *use* a server: ``initialize`` handshake,
``tools/list`` (with pagination) and ``tools/call``.  No SDK dependency (keeps
the PyInstaller sidecar small).  The server runs as a child process with a
dedicated environment; threads pump its pipes so this works on every event loop
(like :mod:`elysium_engine.providers.cli_common`).

Security: this module only speaks the protocol.  Deciding *whether* a tool may
run is the permission broker's job (ADR-003) — callers must gate ``call_tool``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elysium_engine.proctree import kill_pid_tree, spawn_flags, unsafe_shim_argument

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "elysium", "version": "1.0"}

# A third-party server must NOT inherit the user's whole environment (API keys,
# tokens...). Like the official MCP clients, pass only what a process needs to run.
_SAFE_ENV_KEYS = (
    ("APPDATA", "COMSPEC", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "PATH", "PATHEXT",
     "PROCESSOR_ARCHITECTURE", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
     "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERNAME", "USERPROFILE", "WINDIR")
    if sys.platform == "win32"
    else ("HOME", "LANG", "LOGNAME", "PATH", "SHELL", "TERM", "TMPDIR", "USER")
)


def safe_environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Minimal inherited environment + the server's own configuration."""
    base = {k: v for k, v in os.environ.items() if k.upper() in {s.upper() for s in _SAFE_ENV_KEYS}}
    base.update(extra or {})
    return base


class McpError(RuntimeError):
    """A server failed to start, answered with an error, or timed out."""


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]


class McpStdioClient:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        startup_timeout_s: float = 90.0,
        request_timeout_s: float = 60.0,
    ) -> None:
        self._argv = list(argv)
        self._env = safe_environment(env)
        self._cwd = str(cwd) if cwd else None
        self._startup_timeout = startup_timeout_s
        self._request_timeout = request_timeout_s
        self._proc: subprocess.Popen[bytes] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 0
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._write_lock = threading.Lock()
        self.server_info: dict[str, Any] = {}

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if unsafe_shim_argument(self._argv) is not None:
            raise McpError(
                "A configuration value contains characters the Windows command shell "
                'would interpret (& | < > ^ "). Remove them or launch the server directly.'
            )
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self._cwd,
                env=self._env,
                **spawn_flags(),  # npx/uvx start the real server as a child
            )
        except OSError as exc:
            raise McpError(f"cannot start '{self._argv[0]}': {exc}") from exc
        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
            timeout=self._startup_timeout,
        )
        info = result.get("serverInfo") if isinstance(result, dict) else None
        self.server_info = dict(info) if isinstance(info, dict) else {}
        self._notify("notifications/initialized")

    async def close(self) -> None:
        proc, self._proc = self._proc, None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpError("connection closed"))
        self._pending.clear()
        if proc is None:
            return
        # The tree first, before closing stdin: a server that exits on EOF would
        # orphan its children (npx/uvx wrappers run the real server as a child).
        if proc.poll() is None:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                await asyncio.to_thread(kill_pid_tree, proc.pid)
        with contextlib.suppress(OSError):
            if proc.stdin:
                proc.stdin.close()
        if proc.poll() is None:
            try:
                await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=3)
            except asyncio.TimeoutError:
                with contextlib.suppress(OSError):
                    proc.kill()

    # ------------------------------------------------------------- protocol

    async def list_tools(self) -> list[McpTool]:
        tools: list[McpTool] = []
        cursor: str | None = None
        for _ in range(50):  # pagination guard
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {})
            if not isinstance(result, dict) or not isinstance(result.get("tools", []), list):
                raise McpError("the server returned an invalid tool list")
            for raw in result.get("tools", []):
                if not isinstance(raw, dict):
                    raise McpError("the server returned an invalid tool list")
                tools.append(
                    McpTool(
                        name=str(raw.get("name", "")),
                        description=str(raw.get("description", "") or ""),
                        input_schema=dict(raw.get("inputSchema") or {}),
                    )
                )
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Run a tool. The caller is responsible for having obtained approval."""
        return await self._request("tools/call", {"name": name, "arguments": dict(arguments)})

    # ------------------------------------------------------------ internals

    async def _request(
        self, method: str, params: dict[str, Any], timeout: float | None = None
    ) -> dict[str, Any]:
        assert self._loop is not None
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[Any] = self._loop.create_future()
        self._pending[request_id] = future
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout or self._request_timeout)
        except asyncio.TimeoutError as exc:
            raise McpError(self._explain(f"timed out waiting for '{method}'")) from exc
        finally:
            self._pending.pop(request_id, None)

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise McpError(self._explain("the server is not running"))
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                proc.stdin.write(data)
                proc.stdin.flush()
        except OSError as exc:
            raise McpError(self._explain("the server closed its input")) from exc

    def _explain(self, what: str) -> str:
        tail = " | ".join(list(self._stderr_tail)[-4:]).strip()
        return f"{what}" + (f" — {tail[:400]}" if tail else "")

    def _deliver(self, message: dict[str, Any]) -> None:
        """Runs on the event loop: route a server message."""
        if "id" in message and ("result" in message or "error" in message):
            future = self._pending.get(message["id"])
            if future is None or future.done():
                return
            if "error" in message:
                err = message["error"] or {}
                text = err.get("message", "server error") if isinstance(err, dict) else err
                future.set_exception(McpError(str(text)))
            else:
                future.set_result(message.get("result") or {})
        elif "id" in message and "method" in message:
            # A request FROM the server: answer ping, refuse the rest.
            reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
            if message["method"] == "ping":
                reply["result"] = {}
            else:
                reply["error"] = {"code": -32601, "message": "Method not supported by Elysium"}
            with contextlib.suppress(McpError):
                self._send(reply)

    def _pump_stdout(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None and self._loop is not None
        loop = self._loop
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("{"):
                continue  # banner / log noise on stdout
            try:
                message = json.loads(line)
            except ValueError:
                continue
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._deliver, message)
        # stdout closed: fail whatever is still waiting
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(self._fail_pending)

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpError(self._explain("the server exited")))

    def _pump_stderr(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stderr is not None
        for raw in proc.stderr:
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr_tail.append(text)
