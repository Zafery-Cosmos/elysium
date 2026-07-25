"""Persisted application settings — the single-row user preferences store.

Distinct from :class:`elysium_engine.config.Settings` (process/runtime config
from ``ELYSIUM_*`` env vars): this is the user-editable, DB-persisted
preferences document surfaced in the Settings screen.  Stored as one JSON row
in ``app_settings`` (``id`` fixed to 1); :func:`GET /settings` always merges
stored values over these defaults, so new fields appear with sane defaults on
existing installs.

The document is organised into coherent groups (Pydantic sub-models). Some
fields already drive engine behaviour today — ``prompt_caching.*`` and the
``ai`` request knobs (``max_response_tokens``, ``streaming``,
``request_timeout_s``, ``max_retries``) feed the provider call path — while
``agents.*`` and ``memory.*`` are persisted now and consumed by the
orchestrator in a later phase.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- enums
Language = Literal["fr", "en", "es"]
Theme = Literal["light", "dark", "auto"]
UiDensity = Literal["comfortable", "compact"]
Animations = Literal["full", "reduced", "off"]
FontSize = Literal["sm", "md", "lg"]
AiResponseLanguage = Literal["auto", "fr", "en", "es"]
Effort = Literal["low", "medium", "high"]
Execution = Literal["simple", "expert"]
ChatMode = Literal["discuss", "plan", "edit"]
CacheTtl = Literal["5m", "1h"]
LogLevel = Literal["debug", "info", "warning", "error"]
ApprovalAction = Literal["file_write", "shell", "deploy", "network"]


class GeneralSettings(BaseModel):
    model_config = {"extra": "forbid"}

    language: Language = "fr"
    theme: Theme = "light"
    ui_density: UiDensity = "comfortable"
    animations: Animations = "full"
    font_size: FontSize = "md"
    reduce_motion: bool = False
    restore_last_conversation: bool = True
    confirm_before_delete: bool = True
    ai_response_language: AiResponseLanguage = "auto"


class AiSettings(BaseModel):
    model_config = {"extra": "forbid"}

    default_provider: str | None = None
    default_model: str | None = None
    default_effort: Effort = "medium"
    default_execution: Execution = "simple"
    default_chat_mode: ChatMode = "discuss"
    auto_routing: bool = True
    # Soft budget guard in EUR; None disables the pre-operation cost prompt.
    cost_guard_eur: float | None = Field(default=None, ge=0.0)
    max_response_tokens: int = Field(default=8192, ge=1, le=200_000)
    streaming: bool = True
    request_timeout_s: int = Field(default=120, ge=1, le=3600)
    max_retries: int = Field(default=2, ge=0, le=10)
    multi_model_compare: bool = False
    auto_fallback: bool = True


class PromptCachingSettings(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = True
    ttl: CacheTtl = "5m"
    min_prefix_tokens: int = Field(default=1024, ge=0)
    prewarm_on_start: bool = False
    show_cache_stats: bool = False


class AgentsSettings(BaseModel):
    model_config = {"extra": "forbid"}

    allow_debate: bool = True
    max_parallel_agents: int = Field(default=3, ge=1, le=32)
    # Actions that always require an explicit human OK via the Rust broker.
    require_human_approval_for: list[ApprovalAction] = Field(
        default_factory=lambda: ["file_write", "shell", "deploy", "network"]
    )
    auto_snapshot_before_changes: bool = True


class MemorySettings(BaseModel):
    model_config = {"extra": "forbid"}

    vector_memory: bool = False
    context_window_tokens: int = Field(default=16_384, ge=0)
    auto_compaction: bool = True
    auto_summary: bool = True


class DeveloperSettings(BaseModel):
    model_config = {"extra": "forbid"}

    advanced_mode: bool = False
    log_level: LogLevel = "info"
    expose_raw_events: bool = False
    show_live_cost: bool = True
    engine_port_hint: int | None = Field(default=None, ge=1, le=65535)
    open_devtools: bool = False


class PrivacySettings(BaseModel):
    model_config = {"extra": "forbid"}

    redact_secrets_before_send: bool = True
    local_only: bool = False
    telemetry: bool = False
    clear_data_on_quit: bool = False
    encrypt_local_store: bool = False


class AppSettings(BaseModel):
    """Full, validated application settings document (all sections present)."""

    model_config = {"extra": "forbid"}

    general: GeneralSettings = Field(default_factory=GeneralSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    prompt_caching: PromptCachingSettings = Field(default_factory=PromptCachingSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
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
