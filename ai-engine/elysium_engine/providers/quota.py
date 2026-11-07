"""Latest subscription-quota readings reported by CLI providers.

Claude Code emits a ``rate_limit_event`` on every call with the utilization of
the 5-hour and 7-day windows of the user's plan.  We keep the most recent
reading per provider (in memory: it is only meaningful while fresh) so the
admin page can show "how much of my plan is left".
"""

from __future__ import annotations

import time
from typing import Any

_latest: dict[str, dict[str, Any]] = {}


def record_quota(provider: str, windows: dict[str, Any]) -> None:
    clean: dict[str, dict[str, Any]] = {}
    for name, window in windows.items():
        if not isinstance(window, dict):
            continue
        used = window.get("utilization")
        if not isinstance(used, (int, float)):
            continue
        clean[name] = {
            "utilization": float(used),
            "resets_at": window.get("resetsAt"),
            "status": window.get("status"),
        }
    if clean:
        _latest[provider] = {"windows": clean, "updated_at": time.time()}


def latest_quotas() -> dict[str, dict[str, Any]]:
    return {name: dict(reading) for name, reading in _latest.items()}


def reset() -> None:
    _latest.clear()
