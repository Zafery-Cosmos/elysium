"""``python -m elysium_engine`` — run the engine as the Tauri sidecar does.

Binds 127.0.0.1 only, always (ARCHITECTURE.md §7): the engine must never be
reachable from the network in desktop mode.
"""

from __future__ import annotations

import uvicorn

from elysium_engine.api.app import create_app
from elysium_engine.config import Settings


def main() -> None:
    settings = Settings()  # fails fast with a clear error if ELYSIUM_TOKEN is missing
    app = create_app(settings)
    uvicorn.run(app, host="127.0.0.1", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
