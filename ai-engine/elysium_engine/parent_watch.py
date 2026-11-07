"""Exit when the desktop app that launched the engine is gone.

The Tauri app kills the engine on a clean exit, but not when it is killed,
crashes, or is closed by the installer.  An orphaned ``elysium-engine.exe``
then keeps running and locks its own file (the next install fails with
"Error opening file for writing").  The app therefore passes its PID in
``ELYSIUM_PARENT_PID`` and the engine shuts itself down once that process
no longer exists.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable

POLL_SECONDS = 2.0


def pid_alive(pid: int) -> bool:
    """True while process ``pid`` exists."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x102
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def parent_pid_from_env(env: dict[str, str] | None = None) -> int | None:
    raw = (env if env is not None else os.environ).get("ELYSIUM_PARENT_PID", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def start_parent_watch(
    pid: int,
    on_gone: Callable[[], None] | None = None,
    poll_seconds: float = POLL_SECONDS,
) -> threading.Thread:
    """Poll ``pid`` in a daemon thread; call ``on_gone`` (default: hard exit)."""

    def hard_exit() -> None:
        os._exit(0)

    callback = on_gone or hard_exit

    def run() -> None:
        while pid_alive(pid):
            time.sleep(poll_seconds)
        callback()

    thread = threading.Thread(target=run, name="parent-watch", daemon=True)
    thread.start()
    return thread
