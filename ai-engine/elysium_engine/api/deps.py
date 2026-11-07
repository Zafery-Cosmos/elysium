"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from elysium_engine.config import Settings
from elysium_engine.events import EventBus
from elysium_engine.providers.cli_login import CliLoginManager
from elysium_engine.providers.registry import ProviderRegistry


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus


def get_registry(request: Request) -> ProviderRegistry:
    return request.app.state.registry


def get_login_manager(request: Request) -> CliLoginManager:
    """Live CLI sign-in sessions (created on first use)."""
    manager = getattr(request.app.state, "login_manager", None)
    if manager is None:
        manager = CliLoginManager()
        request.app.state.login_manager = manager
    return manager
