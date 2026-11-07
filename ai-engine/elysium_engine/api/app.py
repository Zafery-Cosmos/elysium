"""FastAPI application factory.

Every router except health is mounted behind the bearer-token dependency
(ARCHITECTURE.md §2/§7).  The schema is bootstrapped on startup so first run
is zero-setup on SQLite; Alembic owns upgrades from there.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from elysium_engine import __version__
from elysium_engine.api.routers import (
    admin,
    conversations,
    health,
    mcp,
    models,
    projects,
    settings as settings_router,
    tasks,
)
from elysium_engine.config import Settings
from elysium_engine.db.repository import AppSettingsRepository
from elysium_engine.db.session import create_db_engine, create_session_factory, init_db
from elysium_engine.events import EventBus
from elysium_engine.logging_setup import apply_log_level
from elysium_engine.providers.registry import ProviderRegistry
from elysium_engine.secrets import build_secret_store
from elysium_engine.security import require_token


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # reads ELYSIUM_* env vars
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    engine = create_db_engine(settings.db_url)
    init_db(engine)

    app = FastAPI(title="Elysium AI Engine", version=__version__, docs_url=None, redoc_url=None)
    # The Tauri webview runs on a different origin (tauri://localhost in
    # release, http://localhost:1420 in dev), so the browser-side CORS check
    # applies even though the engine only listens on loopback. Auth stays the
    # bearer token; CORS is scoped to the app's known origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:1420",
            "http://127.0.0.1:1420",
        ],
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.secret_store = build_secret_store()
    app.state.registry = ProviderRegistry(app.state.secret_store)
    app.state.event_bus = EventBus()
    app.state.active_runs = {}  # conversation_id -> asyncio.Task of the running agent
    app.state.started_at = time.time()

    # Honour the persisted log level from the very first request.
    with app.state.session_factory() as session:
        stored = AppSettingsRepository(session).get_data()
    apply_log_level(((stored or {}).get("developer") or {}).get("log_level", "info"))

    app.include_router(health.router)
    protected = APIRouter(dependencies=[Depends(require_token)])
    protected.include_router(projects.router)
    protected.include_router(conversations.router)
    protected.include_router(tasks.router)
    protected.include_router(models.router)
    protected.include_router(mcp.router)
    protected.include_router(settings_router.router)
    protected.include_router(admin.router)
    app.include_router(protected)
    return app
