"""``python -m elysium_engine`` — run the engine as the Tauri sidecar does.

Binds 127.0.0.1 only, always (ARCHITECTURE.md §7): the engine must never be
reachable from the network in desktop mode.
"""

from __future__ import annotations

import os

import uvicorn

from elysium_engine.api.app import create_app
from elysium_engine.config import Settings
from elysium_engine.parent_watch import parent_pid_from_env, start_parent_watch


def main() -> None:
    settings = Settings()  # fails fast with a clear error if ELYSIUM_TOKEN is missing
    app = create_app(settings)
    parent = parent_pid_from_env()
    if parent is not None:
        # Never outlive the desktop app — and take its dev servers down too
        # (os._exit would skip atexit handlers).
        def leave() -> None:
            app.state.previews.stop_all()
            os._exit(0)

        start_parent_watch(parent, on_gone=leave)
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
