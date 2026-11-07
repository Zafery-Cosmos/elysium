"""Subscription-quota readings reported by CLI providers (persisted).

Claude Code emits a ``rate_limit_event`` on every call with the utilization of
the 5-hour and 7-day windows of the user's plan.  The latest reading per
(provider, window) is kept in memory and stored in ``quota_readings`` so it
survives a restart.

Absence of data is *unknown*, never "plenty left": :func:`assess` returns one of
``unknown`` (no reading), ``stale`` (old, or its window has since reset),
``exhausted`` or ``ok``.  API providers report no quota at all; they are shown
as ``unknown``/pay-as-you-go, never as available quota.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from elysium_engine.db.models import QuotaReading

log = logging.getLogger(__name__)

# A reading older than this no longer describes the present.
FRESH_FOR_S = 30 * 60

_latest: dict[str, dict[str, Any]] = {}
_store: sessionmaker[Session] | None = None


def configure(session_factory: sessionmaker[Session] | None) -> None:
    """Attach the database and reload the stored readings."""
    global _store
    _store = session_factory
    _latest.clear()
    if session_factory is None:
        return
    try:
        with session_factory() as session:
            for row in session.query(QuotaReading).all():
                reading = _latest.setdefault(row.provider, {"windows": {}, "updated_at": 0.0})
                reading["windows"][row.window] = {
                    "utilization": row.utilization,
                    "resets_at": row.resets_at,
                    "status": row.status,
                }
                observed = row.observed_at.replace(tzinfo=UTC).timestamp()
                reading["updated_at"] = max(reading["updated_at"], observed)
    except Exception:
        log.exception("could not load stored quota readings")


def record_quota(provider: str, windows: dict[str, Any]) -> None:
    clean: dict[str, dict[str, Any]] = {}
    for name, window in windows.items():
        if not isinstance(window, dict):
            continue
        used = window.get("utilization")
        if not isinstance(used, (int, float)):
            continue
        resets = window.get("resetsAt")
        clean[name] = {
            "utilization": float(used),
            "resets_at": float(resets) if isinstance(resets, (int, float)) else None,
            "status": window.get("status"),
        }
    if not clean:
        return
    _latest[provider] = {"windows": clean, "updated_at": time.time()}
    if _store is None:
        return
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        with _store() as session:
            for name, window in clean.items():
                row = session.get(QuotaReading, (provider, name)) or QuotaReading(
                    provider=provider, window=name
                )
                row.utilization = window["utilization"]
                row.resets_at = window["resets_at"]
                row.status = window["status"]
                row.observed_at = now
                session.add(row)
            session.commit()
    except Exception:
        log.exception("could not persist quota reading for %s", provider)


def latest_quotas() -> dict[str, dict[str, Any]]:
    return {name: dict(reading) for name, reading in _latest.items()}


def assess(reading: dict[str, Any] | None, now: float | None = None) -> dict[str, Any]:
    """``{state, observed_at, windows:[{name, utilization, resets_at, state}]}``."""
    now = time.time() if now is None else now
    if not reading:
        return {"state": "unknown", "observed_at": None, "windows": []}
    observed = float(reading["updated_at"])
    old = now - observed > FRESH_FOR_S
    windows = []
    for name, data in reading["windows"].items():
        resets = data.get("resets_at")
        reset_passed = isinstance(resets, (int, float)) and resets < now
        blocked = (data.get("utilization") or 0) >= 1.0 or str(data.get("status") or "").lower() in {
            "rejected",
            "exceeded",
            "blocked",
            "limit_reached",
        }
        if reset_passed or old:
            state = "stale"  # the figure belongs to a window that has moved on
        elif blocked:
            state = "exhausted"
        else:
            state = "ok"
        windows.append(
            {"name": name, "utilization": data.get("utilization"), "resets_at": resets, "state": state}
        )
    states = {w["state"] for w in windows}
    overall = "exhausted" if "exhausted" in states else "stale" if "stale" in states else "ok"
    return {"state": overall, "observed_at": observed, "windows": windows}


def is_exhausted(provider: str, now: float | None = None) -> bool:
    return assess(_latest.get(provider), now)["state"] == "exhausted"


def reset() -> None:
    global _store
    _store = None
    _latest.clear()
