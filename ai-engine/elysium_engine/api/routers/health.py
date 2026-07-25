"""``GET /health`` — the only unauthenticated route (sidecar liveness probe)."""

from __future__ import annotations

from fastapi import APIRouter

from elysium_engine import __version__
from elysium_engine.api.schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok", version=__version__)
