"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ChatMode = Literal["discuss", "plan", "edit"]
ExecutionMode = Literal["simple", "expert"]
EffortLevel = Literal["low", "medium", "high"]


class HealthOut(BaseModel):
    status: str
    version: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=200)


class ConversationOut(BaseModel):
    id: str
    project_id: str
    title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)
    # Chat mode selects the PM system-prompt variant; model/effort override
    # routing for this turn only. Invalid values -> 422.
    mode: ChatMode = "discuss"
    # Execution mode: "simple" = one model working solo, "expert" = the PM
    # coordinates the full agent team. Invalid values -> 422.
    execution: ExecutionMode = "simple"
    model: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]+:.+$",
        description='Override as "provider:model_id" (e.g. "anthropic:claude-sonnet-5").',
    )
    effort: EffortLevel | None = None


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    agent_name: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageAccepted(BaseModel):
    id: str
    conversation_id: str
    status: str = "accepted"


class ModelOut(BaseModel):
    id: str
    display_name: str
    release_date: str  # ISO "yyyy-mm"; "" for local/custom models
    context_window: int
    input_cost_per_mtok: float
    output_cost_per_mtok: float
    cost_tier: int = Field(ge=1, le=4)
    tier: str


class ProviderOut(BaseModel):
    name: str
    kind: str
    base_url: str
    default_model: str
    is_local: bool
    configured: bool
    custom: bool = False  # True for user-registered OpenAI-compatible servers
    # None unless probed. Local configured providers are probed on every
    # GET /models (model discovery); remote ones only with ?probe=1.
    reachable: bool | None = None
    models: list[ModelOut]


class ModelsOut(BaseModel):
    providers: list[ProviderOut]


class ProviderConfigIn(BaseModel):
    base_url: str | None = None
    default_model: str | None = None
    is_local: bool | None = None
    # Write-only: stored in the OS keychain, never persisted to DB or echoed.
    api_key: str | None = None


class CustomProviderIn(BaseModel):
    """POST /models/providers — register a custom OpenAI-compatible server."""

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,49}$")
    base_url: str = Field(min_length=1, max_length=500)
    default_model: str = Field(default="", max_length=200)
    # Write-only: stored in the OS keychain, never persisted to DB or echoed.
    api_key: str | None = None


class ProviderTestOut(BaseModel):
    reachable: bool
    detail: str | None = None


FilesystemAccess = Literal["none", "read", "read_write"]


class PermissionProfile(BaseModel):
    """Least-privilege permission profile for an agent role (AI_SYSTEM.md §1)."""

    filesystem: FilesystemAccess
    shell: bool
    network: bool
    allowed_tools: list[str]


class AgentPermissionsUpdate(BaseModel):
    """Partial update of an agent role's permission profile."""

    filesystem: FilesystemAccess | None = None
    shell: bool | None = None
    network: bool | None = None
    allowed_tools: list[str] | None = None


class AgentOut(BaseModel):
    id: str | None = None
    name: str
    role: str
    model_ref: str
    allowed_tools: list[str]
    permissions: list[str]
    permission_profile: PermissionProfile


class EventOut(BaseModel):
    id: int
    type: str
    agent: str | None
    payload: dict[str, Any]


class McpCatalogEntryOut(BaseModel):
    catalog_id: str
    name: str
    description: str
    transport: str
    install_hint: str
    category: str
    permissions_note: str
    official: bool
    installed: bool = False


class McpServerCreate(BaseModel):
    """Install from the catalog ({catalog_id}) or register a custom server."""

    catalog_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url_or_command: str | None = Field(default=None, min_length=1)
    transport: Literal["stdio", "http"] | None = None

    @model_validator(mode="after")
    def _catalog_or_custom(self) -> "McpServerCreate":
        if self.catalog_id is None and not (
            self.name and self.url_or_command and self.transport
        ):
            raise ValueError(
                "Provide either catalog_id, or name + url_or_command + transport "
                "for a custom server."
            )
        return self


class McpServerUpdate(BaseModel):
    enabled: bool


class McpServerOut(BaseModel):
    id: str
    catalog_id: str | None
    name: str
    description: str
    url_or_command: str
    transport: str
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportFolderIn(BaseModel):
    """Body of ``POST /projects/{id}/import-folder``.

    ``path`` is trusted: in desktop mode the Rust broker only ever hands the
    engine a directory the user explicitly picked and the broker scoped.
    """

    path: str = Field(min_length=1)
    max_files: int = Field(default=2000, ge=1, le=20000)
    exclude_globs: list[str] = Field(default_factory=list)


class ImportFileOut(BaseModel):
    path: str  # relative to the imported root
    size: int
    language: str | None


class ImportStatsOut(BaseModel):
    total_files: int  # files included in the tree
    total_dirs: int
    total_size: int  # bytes of included files
    skipped_files: int  # binary / too large / excluded / over the cap
    truncated: bool  # True when the file cap was hit
    languages: dict[str, int]  # language -> file count histogram


class ImportSummaryOut(BaseModel):
    root: str
    stats: ImportStatsOut
    tree: list[ImportFileOut]
    readme_excerpt: str | None = None
