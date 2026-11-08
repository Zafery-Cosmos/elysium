"""Live-preview supervisor: starts, watches and stops a project's dev server.

Design rules (see docs/ARCHITECTURE.md, "Live preview"):

* The frontend never sends a command.  The command is built here from a fixed
  per-framework table and the project's own ``package.json`` script name, as an
  argv list (no shell), with a minimal environment (no Elysium token, no API
  keys).
* Running a project's scripts is *code execution*: it needs an explicit
  ``trust`` decision from the user (stored per project), like an editor's
  "workspace trust".
* A server is "ready" only once it really answers HTTP on 127.0.0.1; the URL is
  never published before that.
* One session per project; several projects can run side by side on distinct
  ports.  The whole process tree is killed on stop / engine exit; leftovers of a
  crashed engine are reclaimed by :meth:`reconcile`.
"""

from __future__ import annotations

import http.client
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.models import PreviewRecord
from elysium_engine.mcp.client import safe_environment
from elysium_engine.parent_watch import pid_alive
from elysium_engine.preview.detect import (
    Detection,
    build_command,
    detect,
    install_command,
    manifest_digest,
)
from elysium_engine.preview.paths import PathRefused, resolve_root
from elysium_engine.proctree import kill_pid_tree
from elysium_engine.preview.static_server import StaticPreviewServer
from elysium_engine.providers.redaction import redact_secrets

log = logging.getLogger("elysium.preview")

ACTIVE_STATES = {"installing", "starting", "ready", "compiling", "compile_error", "unreachable", "stopping"}
READY_TIMEOUT_S = 90.0
INSTALL_TIMEOUT_S = 600.0
MAX_LOG_LINES = 400
MAX_LOG_LINE_CHARS = 2000
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_PORT_BUSY = re.compile(r"(?i)(EADDRINUSE|address already in use|port \d+ is (already )?in use|is already in use)")
_ERROR = re.compile(
    r"(?i)(failed to compile|compilation failed|build failed|syntaxerror|module not found|"
    r"cannot find module|\berror:|\[vite\][^\n]*error|\[error\]|\bts\d{4}:|internal server error|"
    r"unexpected token|✘)"
)
_OK = re.compile(
    r"(?i)(compiled successfully|compiled in|compiled client|ready in|hmr update|page reload|built in|"
    r"✓ ready|ready -|waiting for file changes|no errors found|local:\s+http|server running)"
)
_COMPILING = re.compile(r"(?i)\b(compiling|rebuilding|building|optimi[sz]ing|bundling)\b")


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def free_port(avoid: set[int] | None = None) -> int:
    """Ask the OS for a free loopback port that no other session is using."""
    avoid = avoid or set()
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in avoid:
            return port
    raise RuntimeError("No free port available.")


def probe_http(port: int, timeout: float = 2.0) -> int | None:
    """HTTP status of ``GET /`` on 127.0.0.1:port, or None when nothing answers."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request("GET", "/", headers={"Accept": "text/html"})
            return int(conn.getresponse().status)
        finally:
            conn.close()
    except (OSError, http.client.HTTPException):
        return None


@dataclass(slots=True)
class PreviewSession:
    project_id: str
    root: Path
    subdir: str | None
    detection: Detection
    trusted: bool = False
    trust_digest: str | None = None
    framework_override: str | None = None
    state: str = "stopped"
    port: int | None = None
    url: str | None = None
    pid: int | None = None
    started_at: datetime | None = None
    error: str | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    stop_event: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[bytes] | None = None
    server: StaticPreviewServer | None = None
    thread: threading.Thread | None = None
    follow_lines: int = 0
    compile_error: bool = False
    pump: threading.Thread | None = None


class PreviewError(Exception):
    """A user-facing failure; ``code`` is a stable machine-readable string."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PreviewManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        forbidden_dirs: tuple[Path, ...] = (),
        ready_timeout: float = READY_TIMEOUT_S,
        opener: Callable[[str], object] = webbrowser.open,
    ) -> None:
        self._sf = session_factory
        self._forbidden = forbidden_dirs
        self._ready_timeout = ready_timeout
        self._opener = opener
        self._lock = threading.RLock()
        self._sessions: dict[str, PreviewSession] = {}

    # ------------------------------------------------------------ persistence

    def _persist(self, s: PreviewSession) -> None:
        try:
            with self._sf() as db:
                row = db.get(PreviewRecord, s.project_id) or PreviewRecord(
                    project_id=s.project_id, root_path=str(s.root)
                )
                row.root_path = str(s.root)
                row.subdir = s.subdir
                row.framework = s.detection.framework
                row.framework_override = s.framework_override
                row.trusted = s.trusted
                row.trust_digest = s.trust_digest
                row.state = s.state
                row.port = s.port
                row.url = s.url
                row.pid = s.pid
                row.started_at = s.started_at
                row.error = s.error
                db.add(row)
                db.commit()
        except Exception:  # persistence must never take the preview down
            log.exception("could not persist preview state for %s", s.project_id)

    def _set(self, s: PreviewSession, state: str, error: str | None = None, *, keep_error: bool = False) -> None:
        with self._lock:
            s.state = state
            if not keep_error:
                s.error = error
            elif error is not None:
                s.error = error
        self._persist(s)

    def _load(self, project_id: str) -> PreviewSession | None:
        with self._lock:
            if project_id in self._sessions:
                return self._sessions[project_id]
        with self._sf() as db:
            row = db.get(PreviewRecord, project_id)
        if row is None:
            return None
        try:
            root = resolve_root(row.root_path, forbidden=self._forbidden)
        except PathRefused:
            return None
        session = PreviewSession(
            project_id=project_id,
            root=root,
            subdir=row.subdir,
            detection=detect(root, subdir=row.subdir, framework=row.framework_override),
            trusted=row.trusted,
            trust_digest=row.trust_digest,
            framework_override=row.framework_override,
        )
        with self._lock:
            return self._sessions.setdefault(project_id, session)

    # ----------------------------------------------------------------- public

    def configure(
        self, project_id: str, root_raw: str, *, subdir: str | None = None, framework: str | None = None
    ) -> dict[str, Any]:
        """Validate a folder, detect the project and remember the choice."""
        try:
            root = resolve_root(root_raw, forbidden=self._forbidden)
        except PathRefused as exc:
            raise PreviewError("path_refused", str(exc)) from exc
        existing = self._load(project_id)
        if existing is not None and existing.state in ACTIVE_STATES:
            raise PreviewError("running", "Stop the preview before changing its folder.")
        same_folder = existing is not None and existing.root == root
        session = PreviewSession(
            project_id=project_id,
            root=root,
            subdir=subdir or None,
            detection=detect(root, subdir=subdir or None, framework=framework or None),
            trusted=existing.trusted if same_folder else False,
            trust_digest=existing.trust_digest if same_folder else None,
            framework_override=framework or None,
        )
        with self._lock:
            self._sessions[project_id] = session
        self._persist(session)
        return self.view(session)

    def status(self, project_id: str) -> dict[str, Any]:
        session = self._load(project_id)
        if session is None:
            return {"project_id": project_id, "configured": False, "state": "stopped"}
        if session.state == "stopped":
            # The folder may have changed since the last look: what is shown
            # (framework, whether trust is needed) must match what start() would do.
            self._refresh_detection(session)
        return self.view(session)

    def _refresh_detection(self, s: PreviewSession) -> None:
        s.detection = detect(s.root, subdir=s.subdir, framework=s.framework_override)

    @staticmethod
    def _is_trusted(s: PreviewSession) -> bool:
        """Consent covers one exact package.json: a changed manifest asks again."""
        return s.trusted and s.trust_digest is not None and s.trust_digest == manifest_digest(s.detection)

    def start(self, project_id: str, *, trust: bool = False, install_deps: bool = False) -> dict[str, Any]:
        session = self._load(project_id)
        if session is None:
            raise PreviewError("not_configured", "Choose the project folder first.")
        with self._lock:
            if session.state in ACTIVE_STATES:
                return self.view(session)  # never start the same project twice
            # Decide on the folder as it is now, not as it was last detected.
            self._refresh_detection(session)
            det = session.detection
            if not det.runnable:
                raise PreviewError("not_runnable", det.error or "This project cannot be previewed.")
            if not det.is_static:
                if not (self._is_trusted(session) or trust):
                    raise PreviewError(
                        "trust_required",
                        "Starting the preview runs this project's own scripts. Confirm you trust this folder.",
                    )
                session.trusted = True
                session.trust_digest = manifest_digest(det)
            session.stop_event = threading.Event()
            session.logs.clear()
            session.error = None
            session.compile_error = False
            session.state = "starting"
            session.port = session.url = session.pid = None
            session.started_at = _utcnow()
            thread = threading.Thread(
                target=self._run, args=(session, install_deps), name=f"preview-{project_id}", daemon=True
            )
            session.thread = thread
        self._persist(session)
        thread.start()
        return self.view(session)

    def stop(self, project_id: str) -> dict[str, Any]:
        session = self._load(project_id)
        if session is None:
            return {"project_id": project_id, "configured": False, "state": "stopped"}
        self._stop_session(session)
        return self.view(session)

    def restart(self, project_id: str) -> dict[str, Any]:
        self.stop(project_id)
        return self.start(project_id)

    def stop_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            self._stop_session(session)

    def open_external(self, project_id: str) -> str:
        session = self._load(project_id)
        if session is None or session.state not in {"ready", "compiling", "compile_error"} or not session.url:
            raise PreviewError("not_ready", "The preview server is not ready.")
        self._opener(session.url)
        return session.url

    def reconcile(self) -> int:
        """At engine start: reclaim dev servers a crashed engine left behind."""
        reclaimed = 0
        with self._sf() as db:
            rows = db.query(PreviewRecord).filter(PreviewRecord.state != "stopped").all()
            for row in rows:
                # A recorded pid is only trusted if it is alive AND its port still
                # answers: both must hold before we kill anything.
                if row.pid and pid_alive(row.pid) and row.port and probe_http(row.port, 0.5) is not None:
                    kill_pid_tree(row.pid)
                    reclaimed += 1
                row.state, row.pid, row.port, row.url = "stopped", None, None, None
                row.error = None
            db.commit()
        return reclaimed

    def summary(self) -> dict[str, Any]:
        with self._lock:
            sessions = list(self._sessions.values())
        items = [
            {
                "project_id": s.project_id,
                "framework": s.detection.label,
                "state": s.state,
                "port": s.port,
                "url": s.url,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "error": s.error,
            }
            for s in sessions
            if s.state != "stopped"
        ]
        return {"active": sum(1 for i in items if i["state"] in ACTIVE_STATES), "items": items}

    def view(self, s: PreviewSession) -> dict[str, Any]:
        det = s.detection
        return {
            "project_id": s.project_id,
            "configured": True,
            "root_path": str(s.root),
            "subdir": s.subdir,
            "app_root": str(det.app_root) if det.app_root else None,
            "framework": det.framework,
            "label": det.label,
            "package_manager": det.package_manager,
            "script": det.script,
            "deps_installed": det.deps_installed,
            "hot_update": det.hot_update,
            "candidates": det.candidates,
            "detection_error": det.error,
            "runnable": det.runnable,
            "needs_trust": (not det.is_static) and not self._is_trusted(s),
            "trusted": self._is_trusted(s),
            "state": s.state,
            "port": s.port,
            "url": s.url if s.state in {"ready", "compiling", "compile_error"} else None,
            "pid": s.pid,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "error": s.error,
            "logs": list(s.logs)[-80:],
        }

    # ---------------------------------------------------------------- internals

    def _stop_session(self, s: PreviewSession) -> None:
        thread = s.thread
        if s.state in ACTIVE_STATES and s.state != "stopping":
            self._set(s, "stopping")
        s.stop_event.set()
        self._terminate(s)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10)
        if s.state in ACTIVE_STATES or s.state == "stopping":  # thread gone or stuck
            self._finish(s)

    def _terminate(self, s: PreviewSession) -> None:
        proc, server = s.process, s.server
        if proc is not None and proc.poll() is None:
            kill_pid_tree(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning("preview process %s did not exit", proc.pid)
        if server is not None:
            try:
                server.stop()
            except Exception:
                log.exception("static preview server did not stop cleanly")

    def _finish(self, s: PreviewSession) -> None:
        """Release everything and record the final state."""
        self._terminate(s)
        failed = s.state in {"failed", "deps_missing"}  # keep the reason visible
        with self._lock:
            s.process = None
            s.server = None
            s.pid = None
            s.port = None
            s.url = None
            if not failed:
                s.state = "stopped"
                s.error = None
        self._persist(s)

    def _used_ports(self) -> set[int]:
        with self._lock:
            return {s.port for s in self._sessions.values() if s.port is not None}

    def _log_line(self, s: PreviewSession, raw: bytes) -> None:
        text = raw[: MAX_LOG_LINE_CHARS * 4].decode("utf-8", "replace")
        line = redact_secrets(_ANSI.sub("", text).rstrip())[:MAX_LOG_LINE_CHARS]
        if not line.strip():
            return
        s.logs.append(line)
        with self._lock:
            if s.follow_lines > 0:
                s.follow_lines -= 1
                s.error = ((s.error or "") + "\n" + line)[-1500:]
            if _ERROR.search(line):
                s.compile_error = True
                s.error = line[-600:]
                s.follow_lines = 3
                if s.state in {"ready", "compiling"}:
                    s.state = "compile_error"
            elif _OK.search(line):
                s.compile_error = False
                s.follow_lines = 0
                if s.state in {"compile_error", "compiling"}:
                    s.state = "ready"
                    s.error = None
            elif _COMPILING.search(line) and s.state == "ready":
                s.state = "compiling"

    def _run(self, s: PreviewSession, install_deps: bool) -> None:
        try:
            if s.detection.is_static:
                self._run_static(s)
            else:
                self._run_node(s, install_deps)
        except Exception as exc:
            log.exception("preview crashed for %s", s.project_id)
            self._set(s, "failed", f"Preview failed: {exc}")
        finally:
            self._finish(s)

    def _wait_ready(self, s: PreviewSession, port: int, proc: subprocess.Popen[bytes] | None) -> str | None:
        """None when the server answers, else a failure message."""
        deadline = time.monotonic() + self._ready_timeout
        while time.monotonic() < deadline:
            if s.stop_event.is_set():
                return "stopped"
            if proc is not None and proc.poll() is not None:
                return f"The server exited during startup (code {proc.returncode})."
            if probe_http(port, 1.5) is not None:
                return None
            time.sleep(0.3)
        return f"The server did not answer within {int(self._ready_timeout)}s."

    def _announce(self, s: PreviewSession, port: int) -> None:
        with self._lock:
            s.port = port
            s.url = f"http://127.0.0.1:{port}/"
            s.state = "compile_error" if s.compile_error else "ready"
        self._persist(s)

    def _run_static(self, s: PreviewSession) -> None:
        root = s.detection.app_root
        assert root is not None
        server = StaticPreviewServer(root)
        s.server = server
        server.start()
        s.port = server.port
        problem = self._wait_ready(s, server.port, None)
        if problem is not None:
            if problem != "stopped":
                self._set(s, "failed", problem)
            return
        self._announce(s, server.port)
        self._watch(s, server.port, None)

    def _run_node(self, s: PreviewSession, install_deps: bool) -> None:
        det = s.detection
        assert det.app_root is not None and det.package_manager and det.script and det.framework
        exe = shutil.which(det.package_manager)
        if exe is None:
            self._set(
                s, "failed", f"'{det.package_manager}' was not found. Install Node.js and {det.package_manager}."
            )
            return
        if not (det.app_root / "node_modules").is_dir():
            if not install_deps:
                self._set(s, "deps_missing", "Dependencies are not installed.")
                return
            if not self._install(s, exe):
                return
        for attempt in range(3):
            if s.stop_event.is_set():
                return
            port = free_port(self._used_ports())
            argv, extra = build_command(det.package_manager, det.script, det.framework, port)
            argv[0] = exe
            env = safe_environment(
                {
                    **extra,
                    "BROWSER": "none",
                    "FORCE_COLOR": "0",
                    "NO_COLOR": "1",
                    "NEXT_TELEMETRY_DISABLED": "1",
                    "ASTRO_TELEMETRY_DISABLED": "1",
                }
            )
            s.logs.append(f"$ {' '.join(argv[1:])}   (port {port})")
            with self._lock:
                s.port = port  # recorded with the pid, so a crashed engine can reclaim it
                s.compile_error = False  # install output says nothing about the server
                s.error = None
            proc = self._spawn(s, argv, det.app_root, env)
            problem = self._wait_ready(s, port, proc)
            if problem is None:
                self._announce(s, port)
                self._watch(s, port, proc)
                return
            if problem == "stopped":
                return
            self._terminate(s)
            with self._lock:
                # The process is gone: drop its pid BEFORE announcing "failed", so nobody
                # can observe a failed preview that still points at a dead (or stuck) pid.
                s.process = None
                s.pid = None
            if s.pump is not None:
                s.pump.join(timeout=2)  # let the last output lines land in the log
            busy = any(_PORT_BUSY.search(line) for line in s.logs)
            if busy and attempt < 2:
                s.logs.append("[elysium] port taken, trying another one")
                continue
            tail = " | ".join(list(s.logs)[-3:])
            self._set(s, "failed", f"{problem} {tail}".strip())
            return

    def _spawn(self, s: PreviewSession, argv: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = _NO_WINDOW | _NEW_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(  # noqa: S603 - argv list, fixed command table, no shell
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        s.process = proc
        s.pid = proc.pid
        self._persist(s)

        def pump() -> None:
            assert proc.stdout is not None
            for raw in proc.stdout:
                self._log_line(s, raw)

        s.pump = threading.Thread(target=pump, daemon=True, name=f"preview-log-{s.project_id}")
        s.pump.start()
        return proc

    def _install(self, s: PreviewSession, exe: str) -> bool:
        self._set(s, "installing")
        argv = install_command(s.detection.package_manager or "npm")
        argv[0] = exe
        proc = self._spawn(s, argv, s.detection.app_root or s.root, safe_environment({"NO_COLOR": "1"}))
        deadline = time.monotonic() + INSTALL_TIMEOUT_S
        while proc.poll() is None:
            if s.stop_event.is_set():
                return False
            if time.monotonic() > deadline:
                self._terminate(s)
                self._set(s, "failed", "Dependency installation timed out.")
                return False
            time.sleep(0.3)
        if proc.returncode != 0:
            tail = " | ".join(list(s.logs)[-3:])
            self._set(s, "failed", f"Dependency installation failed (code {proc.returncode}). {tail}")
            return False
        with self._lock:
            s.process = None
            s.pid = None
            s.state = "starting"
        s.detection.deps_installed = True
        return True

    def _watch(self, s: PreviewSession, port: int, proc: subprocess.Popen[bytes] | None) -> None:
        misses = 0
        last_probe = 0.0
        while not s.stop_event.is_set():
            if proc is not None and proc.poll() is not None:
                self._set(s, "failed", f"The server stopped unexpectedly (code {proc.returncode}).")
                return
            if proc is None and s.server is not None and not s.server._thread.is_alive():
                self._set(s, "failed", "The preview server stopped unexpectedly.")
                return
            now = time.monotonic()
            if now - last_probe >= 3.0:
                last_probe = now
                if probe_http(port, 1.5) is None:
                    misses += 1
                    if misses >= 3 and s.state != "unreachable":
                        self._set(s, "unreachable", "The server no longer answers.")
                else:
                    if misses >= 3:
                        self._set(s, "compile_error" if s.compile_error else "ready")
                    misses = 0
            s.stop_event.wait(0.4)
