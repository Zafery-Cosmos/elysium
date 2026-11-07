"""The engine must not outlive the desktop app that started it."""

from __future__ import annotations

import os
import subprocess
import sys
import threading

from elysium_engine.parent_watch import (
    parent_pid_from_env,
    pid_alive,
    start_parent_watch,
)


def test_pid_alive_for_self_and_for_a_dead_process() -> None:
    assert pid_alive(os.getpid())
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert not pid_alive(child.pid)
    assert not pid_alive(0)


def test_parent_pid_is_read_from_the_environment() -> None:
    assert parent_pid_from_env({"ELYSIUM_PARENT_PID": "1234"}) == 1234
    assert parent_pid_from_env({"ELYSIUM_PARENT_PID": "nope"}) is None
    assert parent_pid_from_env({}) is None


def test_callback_fires_once_the_parent_is_gone() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    fired = threading.Event()
    start_parent_watch(child.pid, on_gone=fired.set, poll_seconds=0.05)
    assert not fired.wait(0.3)  # still alive: nothing happens
    child.kill()
    child.wait()
    assert fired.wait(5)
