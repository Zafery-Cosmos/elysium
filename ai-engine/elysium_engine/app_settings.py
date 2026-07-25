"""Persisted application settings — the single-row user preferences store.

Distinct from :class:`elysium_engine.config.Settings` (process/runtime config
from ``ELYSIUM_*`` env vars): this is the user-editable, DB-persisted
preferences document surfaced in the Settings screen.  Stored as one JSON row
in ``app_settings`` (``id`` fixed to 1); :func:`GET /settings` always merges
stored values over these defaults, so new fields appear with sane defaults on
existing installs.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Theme = Literal["light", "dark", "system"]
Effort = Literal["low", "medium", "high"]
CacheTtl = Literal["5m", "1h"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class GeneralSettings(BaseModel):
    model_config = {"extra": "forbid"}

    language: str = "fr"
    theme: Theme = "light"
    telemetry: bool = False


class AiSettings(BaseModel):
    model_config = {"extra": "forbid"}

    default_provider: str | None = None
    default_model: str | None = None
    default_effort: Effort = "medium"
    auto_routing: bool = True
    # Soft budget guard in EUR; None disables the pre-operation cost prompt.
    cost_guard_eur: float | None = Field(default=None, ge=0.0)


class PromptCachingSettings(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = True
    ttl: CacheTtl = "5m"
    min_prefix_tokens: int = Field(default=1024, ge=0)


class DeveloperSettings(BaseModel):
    model_config = {"extra": "forbid"}

    show_advanced: bool = False
    log_level: LogLevel = "INFO"
    engine_port_hint: int | None = Field(default=None, ge=1, le=65535)
    expose_raw_events: bool = False


class PrivacySettings(BaseModel):
    model_config = {"extra": "forbid"}

    redact_secrets_before_send: bool = True
    local_only: bool = False


class AppSettings(BaseModel):
    """Full, validated application settings document (all sections present)."""

    model_config = {"extra": "forbid"}

    general: GeneralSettings = Field(default_factory=GeneralSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    prompt_caching: PromptCachingSettings = Field(default_factory=PromptCachingSettings)
    developer: DeveloperSettings = Field(default_factory=DeveloperSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)


def default_settings() -> AppSettings:
    return AppSettings()


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into ``base`` (returns a new dict).

    Nested dicts are merged key-by-key; any non-dict value in ``patch``
    replaces the value in ``base``.  ``None`` in ``patch`` is a real value
    (e.g. clearing ``cost_guard_eur``), not a "skip" marker.
    """
    merged = dict(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged
