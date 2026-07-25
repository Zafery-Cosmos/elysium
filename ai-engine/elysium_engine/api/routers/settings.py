"""Persisted application settings routes.

``GET /settings`` returns the full document with defaults merged over the
stored JSON; ``PATCH /settings`` deep-merges a partial update, re-validates the
whole document and persists it; ``POST /settings/reset`` restores defaults.
The validated shape lives in :mod:`elysium_engine.app_settings`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from elysium_engine.app_settings import AppSettings, deep_merge, default_settings
from elysium_engine.api.deps import get_session
from elysium_engine.db.repository import AppSettingsRepository

router = APIRouter()


def _current(session: Session) -> AppSettings:
    """Stored JSON merged over defaults -> a validated document."""
    stored = AppSettingsRepository(session).get_data()
    merged = deep_merge(default_settings().model_dump(), stored)
    # Stored data is always something we wrote, so validation cannot fail here.
    return AppSettings.model_validate(merged)


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
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()
        ) from exc
    AppSettingsRepository(session).save(validated.model_dump())
    return validated


@router.post("/settings/reset", response_model=AppSettings)
def reset_settings(session: Session = Depends(get_session)) -> AppSettings:
    defaults = default_settings()
    AppSettingsRepository(session).save(defaults.model_dump())
    return defaults
