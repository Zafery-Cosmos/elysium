"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ChatMode = Literal["discuss", "plan", "edit"]
ExecutionMode = Literal["simple", "expert"]
ExpertSubmode = Literal["analyse", "complet"]
EffortLevel = Literal["low", "medium", "high"]

# Generous bounds: they only exist so one request cannot fill the database or
# send a paid model a prompt of unlimited size.
MAX_MESSAGE_CHARS = 2_000_000
MAX_LONG_TEXT = 200_000
MAX_TASK_DEPENDENCIES = 1_000


class HealthOut(BaseModel):
    status: str
    version: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=MAX_LONG_TEXT)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_LONG_TEXT)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    # Share of the project's tasks that are done, 0-1; None without any task.
    progress: float | None = None
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
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    # Chat mode selects the PM system-prompt variant; model/effort override
    # routing for this turn only. Invalid values -> 422.
    mode: ChatMode = "discuss"
    # Execution mode: "simple" = one model working solo, "expert" = the PM
    # coordinates the full agent team. Invalid values -> 422.
    execution: ExecutionMode = "simple"
    # Required (422 if missing/invalid) when execution == "expert"; ignored for
    # "simple". "analyse": the sequential orchestrator runs the project's task
    # graph read-only (no file writes) and produces a written summary per task.
    # "complet": full execution incl. writes — not yet available (501).
    expert_submode: ExpertSubmode | None = None
    model: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_-]+:.+$",
        description='Override as "provider:model_id" (e.g. "anthropic:claude-sonnet-5-5").',
    )
    effort: EffortLevel | None = None

    @model_validator(mode="after")
    def _expert_submode_required_for_expert(self) -> "MessageCreate":
        if self.execution == "expert" and self.expert_submode is None:
            raise ValueError(
                'expert_submode is required when execution is "expert" '
                '("analyse" or "complet").'
            )
        return self


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


class AccountOut(BaseModel):
    """Whose session a CLI provider is signed in with (shown so it can be verified)."""

    email: str | None = None
    plan: str | None = None  # e.g. "max", "pro"
    expires_at: str | None = None  # ISO timestamp of the stored login
    method: str | None = None  # "claude.ai", "ChatGPT", ...


class McpToolOut(BaseModel):
    name: str
    description: str = ""


class McpTestOut(BaseModel):
    """Result of really starting an MCP server and listing its tools."""

    ok: bool
    tools: list[McpToolOut] = Field(default_factory=list)
    server_name: str | None = None
    server_version: str | None = None
    error: str | None = None
    duration_ms: int = 0


class LoginIn(BaseModel):
    # "browser": the CLI opens the system browser (default).
    # "device": a link + one-time code to enter elsewhere (Codex only).
    mode: Literal["browser", "device"] = "browser"
    # Sign out the existing session first and start a fresh sign-in (another
    # account). The CLI session is machine-wide: this also signs the user out
    # of that CLI in their terminal.
    force: bool = False


class LoginCodeIn(BaseModel):
    # A sign-in code, or the redirect address (127.0.0.1:<port>/...?code=...).
    code: str = Field(min_length=1, max_length=2048)


class TokenIn(BaseModel):
    # Claude Code: the token printed by `claude setup-token`.
    # Codex: the whole content of the auth.json written by `codex login`.
    token: str = Field(min_length=1, max_length=65536, repr=False)


class LoginOut(BaseModel):
    """State of a CLI provider sign-in (the user's own account)."""

    state: Literal["not_installed", "signed_in", "signed_out", "pending", "failed"]
    reachable: bool  # == (state == "signed_in")
    # True when a session already existed before this request (nothing was started).
    already_signed_in: bool = False
    account: AccountOut | None = None
    detail: str | None = None
    auth_url: str | None = None  # link to open (here or on another device)
    device_code: str | None = None  # one-time code to type at ``auth_url``
    accepts_input: bool = False  # a pasted code / redirect address can finish it


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


class AgentUpdate(BaseModel):
    """Partial update of an agent (PATCH /agents/{role}): enable/disable + policy."""

    enabled: bool | None = None
    filesystem: FilesystemAccess | None = None
    shell: bool | None = None
    network: bool | None = None


class AgentCreate(BaseModel):
    """POST /agents — create a custom agent for a project."""

    name: str = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(default="", max_length=20_000)
    model_ref: str = Field(default="auto", max_length=200)
    filesystem: FilesystemAccess = "none"
    shell: bool = False
    network: bool = False


class AgentOut(BaseModel):
    id: str | None = None
    name: str
    role: str
    model_ref: str
    enabled: bool = True
    custom: bool = False
    allowed_tools: list[str]
    permissions: list[str]
    permission_profile: PermissionProfile


TaskStatus = Literal["todo", "in_progress", "done", "blocked"]


class TaskCreate(BaseModel):
    """POST /projects/{id}/tasks — add a node to the task graph."""

    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=MAX_LONG_TEXT)
    agent_role: str = Field(min_length=1, max_length=100)
    status: TaskStatus = "todo"
    # Task ids in the same project this task depends on (graph edges).
    depends_on: list[str] = Field(default_factory=list, max_length=MAX_TASK_DEPENDENCIES)


class TaskUpdate(BaseModel):
    """PATCH /tasks/{id} — partial update (drag-and-drop moves send ``status``
    and/or ``order_index``)."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=MAX_LONG_TEXT)
    agent_role: str | None = Field(default=None, min_length=1, max_length=100)
    status: TaskStatus | None = None
    order_index: int | None = Field(default=None, ge=0)
    result_summary: str | None = Field(default=None, max_length=MAX_LONG_TEXT)
    depends_on: list[str] | None = Field(default=None, max_length=MAX_TASK_DEPENDENCIES)


class TaskOut(BaseModel):
    id: str
    project_id: str
    conversation_id: str | None
    title: str
    description: str
    agent_role: str
    status: TaskStatus
    order_index: int
    depends_on: list[str]
    result_summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EventOut(BaseModel):
    id: int
    type: str
    agent: str | None
    payload: dict[str, Any]


class McpConfigFieldOut(BaseModel):
    key: str
    label: str
    type: Literal["string", "secret", "number"]
    required: bool
    # A value is stored in the keychain (the value itself is never sent back).
    secret_set: bool = False


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
    config_schema: list[McpConfigFieldOut] = Field(default_factory=list)


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
    """Partial update: toggle enabled and/or edit config, name, command."""

    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    url_or_command: str | None = Field(default=None, min_length=1)
    # Field-key -> value. ``secret`` fields (per config_schema) are routed to
    # the OS keychain and stripped from the persisted config JSON.
    config: dict[str, Any] | None = None
    # Extra keys of ``config`` to treat as secrets (fields added by hand).
    secret_keys: list[str] = Field(default_factory=list, max_length=100)


class McpServerOut(BaseModel):
    id: str
    catalog_id: str | None
    name: str
    description: str
    url_or_command: str
    transport: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)  # non-secret values only
    config_schema: list[McpConfigFieldOut] = Field(default_factory=list)
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
