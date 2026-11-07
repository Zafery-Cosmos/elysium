"""Kill a process together with everything it started (Windows and POSIX)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from elysium_engine.parent_watch import pid_alive

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def spawn_flags() -> dict[str, object]:
    """``Popen`` kwargs that make the child the root of its own killable tree."""
    if sys.platform == "win32":
        return {"creationflags": NO_WINDOW | NEW_GROUP}
    return {"start_new_session": True}


def kill_pid_tree(pid: int, grace: float = 3.0) -> None:
    """Kill ``pid`` and its descendants: ``taskkill /T`` / process-group signal."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=NO_WINDOW,
            check=False,
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    end = time.monotonic() + grace
    while time.monotonic() < end and pid_alive(pid):
        time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
