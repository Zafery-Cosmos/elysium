"""FastAPI application factory.

Every router except health is mounted behind the bearer-token dependency
(ARCHITECTURE.md §2/§7).  The schema is bootstrapped on startup so first run
is zero-setup on SQLite; Alembic owns upgrades from there.
"""

from __future__ import annotations

import atexit
import contextlib
import time

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from elysium_engine import __version__
from elysium_engine.api.routers import (
    admin,
    changes,
    conversations,
    database,
    health,
    mcp,
    memory,
    models,
    preview,
    projects,
    settings as settings_router,
    tasks,
)
from elysium_engine.config import Settings
from elysium_engine.db.external import resolve_db_url
from elysium_engine.db.repository import AppSettingsRepository, TaskRepository
from elysium_engine.db.session import create_db_engine, create_session_factory, init_db
from elysium_engine.events import EventBus
from elysium_engine.logging_setup import apply_log_level
from elysium_engine.mcp.toolbox import ActionGate
from elysium_engine.preview.manager import PreviewManager
from elysium_engine.providers import quota
from elysium_engine.providers.cli_token import set_token_lookup
from elysium_engine.providers.cli_common import set_cli_home
from elysium_engine.providers.registry import ProviderRegistry
from elysium_engine.secrets import build_secret_store
from elysium_engine.security import require_token


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # reads ELYSIUM_* env vars
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    secret_store = build_secret_store()
    db_url, db_fallback_error = resolve_db_url(settings, secret_store)
    engine = create_db_engine(db_url)
    init_db(engine)

    @contextlib.asynccontextmanager
    async def lifespan(application: FastAPI):  # type: ignore[no-untyped-def]
        # Dev servers started by the live preview never outlive the engine.
        application.state.previews.reconcile()
        # No run survives an engine restart: tasks it was working on go back in the queue.
        with application.state.session_factory() as session:
            TaskRepository(session).reset_interrupted()
        try:
            yield
        finally:
            application.state.previews.stop_all()

    app = FastAPI(
        title="Elysium AI Engine",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # the route inventory stays behind the token too
        lifespan=lifespan,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
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
    app.state.db_fallback_error = db_fallback_error
    app.state.secret_store = secret_store
    app.state.registry = ProviderRegistry(app.state.secret_store)
    app.state.event_bus = EventBus()
    app.state.active_runs = {}  # conversation_id -> asyncio.Task of the running agent
    app.state.starting_runs = set()  # conversation ids being set up, before their task exists
    app.state.expert_runs = {}  # project_id -> asyncio.Task of its task-graph run
    app.state.actions = ActionGate()  # tool calls waiting for a human decision
    app.state.started_at = time.time()
    app.state.previews = PreviewManager(
        app.state.session_factory, forbidden_dirs=(settings.data_dir,)
    )
    atexit.register(app.state.previews.stop_all)
    quota.configure(app.state.session_factory)  # plan-quota readings survive restarts

    # Elysium keeps its OWN Claude Code / Codex sessions, separate from the
    # user's terminal ones (see providers.cli_common.cli_session_env).
    set_cli_home(settings.data_dir / "cli")
    # A Claude token pasted by the user lives in the keychain and is handed to the
    # `claude` child process only (see providers/cli_token.py).
    set_token_lookup(app.state.secret_store.get)

    # Honour the persisted log level from the very first request.
    with app.state.session_factory() as session:
        stored = AppSettingsRepository(session).get_data()
    apply_log_level(((stored or {}).get("developer") or {}).get("log_level", "info"))

    app.include_router(health.router)
    protected = APIRouter(dependencies=[Depends(require_token)])
    protected.include_router(projects.router)
    protected.include_router(preview.router)
    protected.include_router(memory.router)
    protected.include_router(conversations.router)
    protected.include_router(changes.router)
    protected.include_router(tasks.router)
    protected.include_router(models.router)
    protected.include_router(mcp.router)
    protected.include_router(settings_router.router)
    protected.include_router(admin.router)
    protected.include_router(database.router)
    app.include_router(protected)
    return app
