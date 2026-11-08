"""Persisted application settings routes.

``GET /settings`` returns the full document with defaults merged over the
stored JSON; ``PATCH /settings`` deep-merges a partial update, re-validates the
whole document and persists it; ``POST /settings/reset`` restores defaults.
The validated shape lives in :mod:`elysium_engine.app_settings`.
"""

from __future__ import annotations

import webbrowser
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from elysium_engine.app_settings import AppSettings, deep_merge, default_settings, load_settings
from elysium_engine.api.deps import get_session
from elysium_engine.db.repository import AppSettingsRepository
from elysium_engine.logging_setup import apply_log_level

router = APIRouter()


class OpenUrlIn(BaseModel):
    url: str = Field(max_length=2000, pattern=r"^https?://")


@router.post("/settings/open-url", status_code=status.HTTP_204_NO_CONTENT)
def open_url(body: OpenUrlIn) -> Response:
    """Open a link in the system browser (the webview cannot; http(s) only)."""
    webbrowser.open(body.url)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _current(session: Session) -> AppSettings:
    """Stored JSON merged over defaults -> a validated document."""
    return load_settings(AppSettingsRepository(session).get_data())


@router.get("/settings", response_model=AppSettings)
def get_settings(session: Session = Depends(get_session)) -> AppSettings:
    return _current(session)


@router.patch("/settings", response_model=AppSettings)
def patch_settings(
    patch: dict[str, Any] = Body(...),
    session: Session = Depends(get_session),
) -> AppSettings:
    merged = deep_merge(_current(session).model_dump(), patch)
    try:
        validated = AppSettings.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            # The context holds the raw exception, which JSON cannot encode (500).
            detail=exc.errors(include_url=False, include_context=False, include_input=False),
        ) from exc
    AppSettingsRepository(session).save(validated.model_dump())
    apply_log_level(validated.developer.log_level)
    return validated


@router.post("/settings/reset", response_model=AppSettings)
def reset_settings(session: Session = Depends(get_session)) -> AppSettings:
    defaults = default_settings()
    AppSettingsRepository(session).save(defaults.model_dump())
    apply_log_level(defaults.developer.log_level)
    return defaults
