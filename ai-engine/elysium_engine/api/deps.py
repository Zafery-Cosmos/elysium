"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from elysium_engine.config import Settings
from elysium_engine.events import EventBus
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
